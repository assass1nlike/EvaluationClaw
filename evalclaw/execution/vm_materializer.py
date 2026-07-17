"""Task-level VM image materialization helpers.

The VM provider owns lifecycle, snapshots, and bridge startup. This module owns
per-item task state: files, public session metadata, and evaluator configuration
that should be available inside a freshly created VM.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_METADATA_KEY,
    public_agent_task_package,
)
from ..protocols.task_agent import TASK_AGENT_METADATA_KEY, public_task_agent_initial_content
from ..types import BenchmarkItem
from .installers import (
    apt_packages,
    package_list,
    render_install_commands,
    render_windows_install_commands,
)

VM_MATERIALIZATION_DIR_ENV_VAR = "EVALCLAW_VM_MATERIALIZATION_DIR"
_LINUX = "linux"
_WINDOWS = "windows"
_LINUX_PROVISIONING_FIELDS = {
    "apt_packages",
    "apk_packages",
    "dnf_packages",
    "yum_packages",
    "pacman_packages",
    "snap_packages",
    "cran_packages",
    "r_packages",
    "bioconductor_packages",
    "bioc_packages",
    "julia_packages",
    "conda_packages",
    "cargo_packages",
    "go_packages",
    "gem_packages",
    "ruby_gems",
    "composer_packages",
}
_WINDOWS_PROVISIONING_FIELDS = {
    "winget_packages",
    "choco_packages",
    "chocolatey_packages",
    "windows_features",
    "powershell_commands",
    "powershell_script",
    "interactive_powershell_commands",
    "restart_after_provisioning",
}


@dataclass(frozen=True)
class VmGuestFile:
    guest_path: str
    content: str
    source: str
    permissions: str = "0644"
    root_only: bool = False


@dataclass
class VmTaskMaterializationResult:
    item_id: str
    applied: bool
    seed_iso: str = ""
    work_dir: str = ""
    file_count: int = 0
    skipped_reason: str = ""
    guest_os: str = ""
    strategy: str = ""
    provisioning: dict[str, Any] = field(default_factory=dict)
    mappings: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class VmTaskMaterializationError(RuntimeError):
    """Raised when a VM task cannot be safely materialized."""


def _agent_env(item: BenchmarkItem) -> dict[str, Any]:
    env = item.metadata.get("agent_env")
    if isinstance(env, dict):
        return env
    return {}


def _set_agent_env(item: BenchmarkItem, env: dict[str, Any]) -> None:
    item.metadata["agent_env"] = env


def vm_task_requires_vm(item: BenchmarkItem) -> bool:
    env = _agent_env(item)
    return bool(env.get("requires_vm") or env.get("vm"))


def _task_agent(item: BenchmarkItem) -> dict[str, Any]:
    value = item.metadata.get(TASK_AGENT_METADATA_KEY)
    return value if isinstance(value, dict) else {}


def _initial_content(item: BenchmarkItem) -> dict[str, Any]:
    task_agent = _task_agent(item)
    initial = task_agent.get("initial_content")
    return initial if isinstance(initial, dict) else {}


def _agent_task_package(item: BenchmarkItem) -> dict[str, Any]:
    package = item.metadata.get(AGENT_TASK_PACKAGE_METADATA_KEY)
    return package if isinstance(package, dict) else {}


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return slug[:80] or "evalclaw-vm-task"


def _guest_os(env: dict[str, Any]) -> str:
    materialization = env.get("vm_materialization")
    vm = env.get("vm")
    candidates = []
    if isinstance(materialization, dict):
        candidates.extend((materialization.get("guest_os"), materialization.get("os")))
    if isinstance(vm, dict):
        candidates.extend((vm.get("guest_os"), vm.get("os"), vm.get("os_type"), vm.get("platform")))
    candidates.append(env.get("guest_os"))
    raw = next((str(value).strip().lower() for value in candidates if str(value or "").strip()), "")
    normalized = raw.replace("_", "-")
    if not normalized:
        return _LINUX
    if normalized == "win" or normalized.startswith("windows"):
        return _WINDOWS
    if normalized.startswith("linux") or normalized in {
        "ubuntu",
        "debian",
        "fedora",
        "rhel",
        "centos",
        "alpine",
        "arch",
    }:
        return _LINUX
    raise VmTaskMaterializationError(
        f"Unsupported VM guest OS {raw!r}; built-in materialization supports linux and windows."
    )


def _materialization_strategy(guest_os: str) -> str:
    return "cloudbase_init.nocloud.v1" if guest_os == _WINDOWS else "cloud_init.nocloud.v1"


def _add_required_vm_capabilities(
    vm_spec: dict[str, Any],
    env: dict[str, Any],
    *,
    guest_os: str,
    needs_config_drive: bool,
) -> None:
    required = vm_spec.get("required_capabilities")
    capabilities = [str(value) for value in required if str(value).strip()] if isinstance(required, list) else []
    if str(env.get("type") or "").lower() == "gui_desktop":
        capabilities.append("desktop_bridge")
    if needs_config_drive:
        if guest_os == _WINDOWS:
            capabilities.extend(("cloudbase_init_nocloud", "powershell"))
        else:
            capabilities.append("cloud_init_nocloud")
    if capabilities:
        vm_spec["required_capabilities"] = list(dict.fromkeys(capabilities))


def _guest_user(env: dict[str, Any], guest_os: str) -> str:
    materialization = env.get("vm_materialization")
    if isinstance(materialization, dict):
        value = materialization.get("guest_user")
        if isinstance(value, str) and value.strip():
            return value.strip()
    vm = env.get("vm")
    if isinstance(vm, dict):
        value = vm.get("guest_user") or vm.get("user")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Public" if guest_os == _WINDOWS else "ubuntu"


def _guest_root(env: dict[str, Any], guest_user: str, guest_os: str) -> str:
    materialization = env.get("vm_materialization")
    if isinstance(materialization, dict):
        value = materialization.get("guest_root") or materialization.get("file_root")
        if isinstance(value, str) and value.strip():
            root = _normalize_guest_path(value.strip(), guest_os)
            if guest_os == _WINDOWS and not PureWindowsPath(root).is_absolute():
                raise VmTaskMaterializationError("Windows vm_materialization.guest_root must be absolute.")
            return root
    if guest_os == _WINDOWS:
        if guest_user in {".", ".."} or any(separator in guest_user for separator in ("/", "\\")):
            raise VmTaskMaterializationError("Windows VM guest_user must be a local profile name.")
        return rf"C:\Users\{guest_user}"
    if guest_user == "root":
        return "/root"
    return f"/home/{guest_user}"


def _normalize_guest_path(raw_path: str, guest_os: str = _LINUX) -> str:
    if guest_os == _WINDOWS:
        path = raw_path.strip().replace("/", "\\")
        if not path or "\x00" in path:
            raise VmTaskMaterializationError("VM materialization received an empty or invalid guest path.")
        pure = PureWindowsPath(path)
        if any(part == ".." for part in pure.parts):
            raise VmTaskMaterializationError(f"Unsafe VM guest path with traversal component: {raw_path}")
        if pure.drive and not re.fullmatch(r"[A-Za-z]:", pure.drive):
            raise VmTaskMaterializationError(f"Unsupported Windows VM guest path: {raw_path}")
        if pure.drive and not pure.is_absolute():
            raise VmTaskMaterializationError(f"Windows VM guest path must not be drive-relative: {raw_path}")
        return str(pure)
    path = raw_path.strip().replace("\\", "/")
    if not path or "\x00" in path:
        raise VmTaskMaterializationError("VM materialization received an empty or invalid guest path.")
    pure = PurePosixPath(path)
    parts = [part for part in pure.parts if part not in {"", "/", "."}]
    if any(part == ".." for part in parts):
        raise VmTaskMaterializationError(f"Unsafe VM guest path with traversal component: {raw_path}")
    if pure.is_absolute():
        return "/" + "/".join(parts)
    return "/".join(parts)


def _map_guest_path(raw_path: str, *, guest_root: str, guest_os: str = _LINUX) -> str:
    normalized = _normalize_guest_path(raw_path, guest_os)
    if guest_os == _WINDOWS:
        path = PureWindowsPath(normalized)
        if path.is_absolute():
            return str(path)
        if not path.parts:
            raise VmTaskMaterializationError(f"Unsafe VM guest path: {raw_path}")
        return str(PureWindowsPath(guest_root, path))
    if normalized.startswith("/"):
        return normalized
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"", "."}]
    if not parts:
        raise VmTaskMaterializationError(f"Unsafe VM guest path: {raw_path}")
    return str(PurePosixPath(guest_root, *parts))


def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return json.dumps(value, ensure_ascii=False, indent=2)


def _vm_provisioning(env: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    vm = env.get("vm")
    if isinstance(vm, dict) and isinstance(vm.get("provisioning"), dict):
        merged.update(vm["provisioning"])
    if isinstance(env.get("vm_provisioning"), dict):
        merged.update(env["vm_provisioning"])
    return merged


def _vm_provisioning_requested(env: dict[str, Any]) -> bool:
    provisioning = _vm_provisioning(env)
    if not provisioning:
        return False
    if provisioning.get("enabled") is False:
        return False
    keys = (
        "apt_packages",
        "system_packages",
        "packages",
        "pip_packages",
        "python_packages",
        "snap_packages",
        "cran_packages",
        "r_packages",
        "bioconductor_packages",
        "bioc_packages",
        "julia_packages",
        "conda_packages",
        "conda_channels",
        "channels",
        "cargo_packages",
        "go_packages",
        "gem_packages",
        "ruby_gems",
        "composer_packages",
        "apk_packages",
        "dnf_packages",
        "yum_packages",
        "pacman_packages",
        "install_steps",
        "package_manager_steps",
        "software_install_steps",
        "commands",
        "run_commands",
        "bootstrap_commands",
        "runcmd",
        "desktop_bridge_install_command",
        "desktop_bridge_start_command",
        "winget_packages",
        "choco_packages",
        "chocolatey_packages",
        "windows_features",
        "powershell_commands",
        "powershell_script",
        "interactive_powershell_commands",
        "restart_after_provisioning",
    )
    return any(bool(provisioning.get(key)) for key in keys) or bool(provisioning.get("enabled"))


def _validate_provisioning_platform(provisioning: dict[str, Any], guest_os: str) -> None:
    unsupported_fields = (
        _LINUX_PROVISIONING_FIELDS if guest_os == _WINDOWS else _WINDOWS_PROVISIONING_FIELDS
    )
    used_fields = sorted(key for key in unsupported_fields if provisioning.get(key))
    raw_steps = (
        provisioning.get("install_steps")
        or provisioning.get("package_manager_steps")
        or provisioning.get("software_install_steps")
    )
    steps = [raw_steps] if isinstance(raw_steps, dict) else raw_steps
    managers = {
        str(step.get("manager") or step.get("type") or "").strip().lower().replace("_", "-")
        for step in steps or []
        if isinstance(step, dict)
    }
    unsupported_managers = (
        managers
        & {
            "apt",
            "apt-get",
            "apk",
            "dnf",
            "yum",
            "pacman",
            "snap",
            "cran",
            "bioconductor",
            "julia",
            "conda",
            "cargo",
            "go",
            "gem",
            "composer",
        }
        if guest_os == _WINDOWS
        else managers & {"winget", "choco", "chocolatey", "windows-feature", "windows-features"}
    )
    if used_fields or unsupported_managers:
        details = used_fields + sorted(unsupported_managers)
        raise VmTaskMaterializationError(
            f"VM provisioning for {guest_os} contains unsupported platform-specific fields or managers: "
            + ", ".join(details)
        )


def _provisioning_apt_packages(provisioning: dict[str, Any]) -> list[str]:
    return apt_packages(provisioning)


def _linux_provisioning_commands(provisioning: dict[str, Any]) -> list[str]:
    commands: list[str] = render_install_commands(provisioning)
    if commands:
        commands.append("mkdir -p /opt/evalclaw && touch /opt/evalclaw/vm-provisioned")
    return commands


def _windows_interactive_setup_commands(provisioning: dict[str, Any]) -> list[str]:
    raw_commands = provisioning.get("interactive_powershell_commands")
    commands = raw_commands if isinstance(raw_commands, list) else [raw_commands]
    commands = [str(command) for command in commands if str(command or "").strip()]
    if not commands:
        return []
    state_root = r"C:\ProgramData\EvalClaw\interactive-provisioning"
    script = "\r\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$stateRoot = '{state_root}'",
            "try {",
            *commands,
            "  Set-Content -LiteralPath (Join-Path $stateRoot 'ready') -Value 'ready' -Encoding ASCII",
            "  Remove-Item -LiteralPath $PSCommandPath -Force",
            "} catch {",
            "  $_ | Out-String | Set-Content -LiteralPath (Join-Path $stateRoot 'failed') -Encoding UTF8",
            "  exit 1",
            "}",
        ]
    ) + "\r\n"
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    setup_script = f"{state_root}\\setup.ps1"
    return [
        "; ".join(
            [
                f"$interactiveRoot = '{state_root}'",
                "New-Item -ItemType Directory -Force -Path $interactiveRoot | Out-Null",
                "& icacls.exe $interactiveRoot /inheritance:r "
                "/grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "
                "'*S-1-5-32-545:(OI)(CI)M' /T /C | Out-Null",
                "if ($LASTEXITCODE -ne 0) { throw 'Failed to protect interactive provisioning state' }",
                f"[IO.File]::WriteAllBytes('{setup_script}', [Convert]::FromBase64String('{encoded}'))",
                "Remove-Item -LiteralPath (Join-Path $interactiveRoot 'ready'),"
                "(Join-Path $interactiveRoot 'failed') -Force -ErrorAction SilentlyContinue",
                "Set-Content -LiteralPath (Join-Path $interactiveRoot 'required') "
                "-Value 'required' -Encoding ASCII",
            ]
        )
    ]


def _windows_provisioning_commands(provisioning: dict[str, Any]) -> list[str]:
    commands = render_windows_install_commands(provisioning)
    commands.extend(_windows_interactive_setup_commands(provisioning))
    if commands or provisioning.get("restart_after_provisioning"):
        commands.extend(
            [
                "$marker = 'C:\\ProgramData\\EvalClaw\\vm-provisioned'",
                "New-Item -ItemType Directory -Force -Path (Split-Path -Parent $marker) | Out-Null",
                "Set-Content -LiteralPath $marker -Value 'ready' -Encoding ASCII",
            ]
        )
    if provisioning.get("restart_after_provisioning"):
        commands.append(
            "Set-Content -LiteralPath 'C:\\ProgramData\\EvalClaw\\restart-after-provisioning' "
            "-Value 'required' -Encoding ASCII"
        )
    return commands


def _provisioning_summary(env: dict[str, Any], guest_os: str) -> dict[str, Any]:
    provisioning = _vm_provisioning(env)
    if not _vm_provisioning_requested(env):
        return {}
    commands = (
        _windows_provisioning_commands(provisioning)
        if guest_os == _WINDOWS
        else _linux_provisioning_commands(provisioning)
    )
    return {
        "enabled": True,
        "strategy": str(provisioning.get("strategy") or _materialization_strategy(guest_os)),
        "guest_os": guest_os,
        "apt_packages": _provisioning_apt_packages(provisioning) if guest_os == _LINUX else [],
        "winget_packages": package_list(provisioning.get("winget_packages")),
        "choco_packages": package_list(
            provisioning.get("choco_packages") or provisioning.get("chocolatey_packages")
        ),
        "windows_features": package_list(provisioning.get("windows_features")),
        "interactive_command_count": len(
            [
                command
                for command in (
                    provisioning.get("interactive_powershell_commands")
                    if isinstance(provisioning.get("interactive_powershell_commands"), list)
                    else [provisioning.get("interactive_powershell_commands")]
                )
                if str(command or "").strip()
            ]
        ),
        "restart_after_provisioning": bool(provisioning.get("restart_after_provisioning")),
        "pip_packages": package_list(provisioning.get("pip_packages") or provisioning.get("python_packages")),
        "snap_packages": package_list(provisioning.get("snap_packages")),
        "cran_packages": package_list(provisioning.get("cran_packages") or provisioning.get("r_packages")),
        "bioconductor_packages": package_list(
            provisioning.get("bioconductor_packages") or provisioning.get("bioc_packages")
        ),
        "julia_packages": package_list(provisioning.get("julia_packages")),
        "conda_packages": package_list(provisioning.get("conda_packages")),
        "cargo_packages": package_list(provisioning.get("cargo_packages")),
        "go_packages": package_list(provisioning.get("go_packages")),
        "gem_packages": package_list(provisioning.get("gem_packages") or provisioning.get("ruby_gems")),
        "composer_packages": package_list(provisioning.get("composer_packages")),
        "command_count": len(commands),
    }


def _add_file(
    files: dict[str, VmGuestFile],
    *,
    raw_path: str,
    content: Any,
    source: str,
    guest_root: str,
    guest_os: str,
    permissions: str = "0644",
    root_only: bool = False,
) -> None:
    guest_path = _map_guest_path(raw_path, guest_root=guest_root, guest_os=guest_os)
    files[guest_path] = VmGuestFile(
        guest_path=guest_path,
        content=_text_content(content),
        source=source,
        permissions=permissions,
        root_only=root_only,
    )


def _add_file_mapping(
    files: dict[str, VmGuestFile],
    mapping: Any,
    *,
    source: str,
    guest_root: str,
    guest_os: str,
) -> None:
    if not isinstance(mapping, dict):
        return
    for raw_path, content in mapping.items():
        if isinstance(raw_path, str) and raw_path.strip():
            _add_file(
                files,
                raw_path=raw_path,
                content=content,
                source=source,
                guest_root=guest_root,
                guest_os=guest_os,
            )


def _safe_private_suffix(raw_path: str, guest_os: str) -> str:
    normalized = _normalize_guest_path(raw_path, guest_os)
    path_type = PureWindowsPath if guest_os == _WINDOWS else PurePosixPath
    path = path_type(normalized)
    parts = [part for part in path.parts if part not in {"", "/", "\\", ".", path.anchor}]
    if not parts:
        raise VmTaskMaterializationError(f"Unsafe private guest path: {raw_path}")
    return str(path_type(*parts))


def _add_private_file_mapping(
    files: dict[str, VmGuestFile],
    mapping: Any,
    *,
    source: str,
    guest_os: str,
) -> None:
    if not isinstance(mapping, dict):
        return
    for raw_path, content in mapping.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        private_root = (
            PureWindowsPath(r"C:\ProgramData\EvalClaw\task\private\hidden_references")
            if guest_os == _WINDOWS
            else PurePosixPath("/opt/evalclaw/task/private/hidden_references")
        )
        private_path = str(private_root / _safe_private_suffix(raw_path, guest_os))
        files[private_path] = VmGuestFile(
            guest_path=private_path,
            content=_text_content(content),
            source=source,
            permissions="0600",
            root_only=True,
        )


def _session_asset_files(
    files: dict[str, VmGuestFile],
    session: Any,
    *,
    source: str,
    guest_root: str,
    guest_os: str,
) -> None:
    if not isinstance(session, dict):
        return
    for key in ("files", "input_files", "asset_files"):
        _add_file_mapping(
            files,
            session.get(key),
            source=f"{source}.{key}",
            guest_root=guest_root,
            guest_os=guest_os,
        )
    assets = session.get("assets")
    if isinstance(assets, dict):
        _add_file_mapping(
            files,
            assets,
            source=f"{source}.assets",
            guest_root=guest_root,
            guest_os=guest_os,
        )
    elif isinstance(assets, list):
        for index, asset in enumerate(assets):
            if not isinstance(asset, dict):
                continue
            raw_path = asset.get("path") or asset.get("guest_path") or asset.get("filename") or asset.get("name")
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            if "content" in asset:
                content = asset["content"]
            elif "text" in asset:
                content = asset["text"]
            else:
                continue
            _add_file(
                files,
                raw_path=raw_path,
                content=content,
                source=f"{source}.assets[{index}]",
                guest_root=guest_root,
                guest_os=guest_os,
            )


def _public_initial_content(initial: dict[str, Any]) -> dict[str, Any]:
    public = public_task_agent_initial_content(initial)
    public.pop("files", None)
    if isinstance(public.get("session"), dict):
        public["session"] = _public_session(public["session"])
    return public


def _public_session(session: dict[str, Any]) -> dict[str, Any]:
    public = copy.deepcopy(session)
    public.pop("baseline_checks", None)
    public.pop("initial_state_checks", None)
    return public


def _add_materialization_baseline_checks(
    env: dict[str, Any],
    *,
    guest_os: str,
    has_provisioning: bool,
) -> None:
    session = copy.deepcopy(env.get("session") if isinstance(env.get("session"), dict) else {})
    checks = list(session.get("baseline_checks") or []) if isinstance(session.get("baseline_checks"), list) else []
    materialized_marker = (
        r"C:\ProgramData\EvalClaw\vm-materialized"
        if guest_os == _WINDOWS
        else "/opt/evalclaw/vm-materialized"
    )
    marker_paths = {
        str(check.get("path"))
        for check in checks
        if isinstance(check, dict) and check.get("path")
    }
    if materialized_marker not in marker_paths:
        checks.append(
            {
                "id": "evalclaw_vm_materialized",
                "method": "file_exists",
                "path": materialized_marker,
            }
        )
    if has_provisioning:
        provisioned_marker = (
            r"C:\ProgramData\EvalClaw\vm-provisioned"
            if guest_os == _WINDOWS
            else "/opt/evalclaw/vm-provisioned"
        )
        if provisioned_marker not in marker_paths:
            checks.append(
                {
                    "id": "evalclaw_vm_provisioned",
                    "method": "file_exists",
                    "path": provisioned_marker,
                }
            )
    session["baseline_checks"] = checks
    env["session"] = session


def _collect_guest_files(item: BenchmarkItem, env: dict[str, Any]) -> list[VmGuestFile]:
    guest_os = _guest_os(env)
    guest_user = _guest_user(env, guest_os)
    guest_root = _guest_root(env, guest_user, guest_os)
    materialization = env.get("vm_materialization")
    files: dict[str, VmGuestFile] = {}
    initial = _initial_content(item)
    package = _agent_task_package(item)
    _add_file_mapping(
        files,
        env.get("visible_files"),
        source="metadata.agent_env.visible_files",
        guest_root=guest_root,
        guest_os=guest_os,
    )
    _add_file_mapping(
        files,
        env.get("files"),
        source="metadata.agent_env.files",
        guest_root=guest_root,
        guest_os=guest_os,
    )
    _add_file_mapping(
        files,
        initial.get("files"),
        source="metadata.task_agent.initial_content.files",
        guest_root=guest_root,
        guest_os=guest_os,
    )
    _session_asset_files(
        files,
        env.get("session"),
        source="metadata.agent_env.session",
        guest_root=guest_root,
        guest_os=guest_os,
    )
    _session_asset_files(
        files,
        initial.get("session"),
        source="metadata.task_agent.initial_content.session",
        guest_root=guest_root,
        guest_os=guest_os,
    )
    _add_private_file_mapping(
        files,
        env.get("hidden_files"),
        source="metadata.agent_env.hidden_files",
        guest_os=guest_os,
    )
    has_guest_files = bool(files)
    has_provisioning = _vm_provisioning_requested(env)
    force_metadata = bool(isinstance(materialization, dict) and materialization.get("force"))
    has_task_package = bool(package)
    include_manifest = has_guest_files or force_metadata or bool(
        isinstance(materialization, dict) and materialization.get("include_task_manifest")
    ) or has_task_package or has_provisioning
    if not include_manifest:
        return []

    public_manifest = {
        "item_id": item.id,
        "dimension_id": item.dimension_id,
        "prompt": item.prompt,
        "tags": item.tags,
        "task_agent_initial_content": _public_initial_content(initial),
        "session": _public_session(env["session"]) if isinstance(env.get("session"), dict) else {},
    }
    public_root = (
        PureWindowsPath(r"C:\ProgramData\EvalClaw\task\public")
        if guest_os == _WINDOWS
        else PurePosixPath("/opt/evalclaw/task/public")
    )
    private_root = (
        PureWindowsPath(r"C:\ProgramData\EvalClaw\task\private")
        if guest_os == _WINDOWS
        else PurePosixPath("/opt/evalclaw/task/private")
    )
    public_task_path = str(public_root / "task.json")
    files[public_task_path] = VmGuestFile(
        guest_path=public_task_path,
        content=json.dumps(public_manifest, ensure_ascii=False, indent=2),
        source="evalclaw.public_task_manifest",
        permissions="0644",
    )
    if package:
        public_package_path = str(public_root / "agent_task_package.json")
        files[public_package_path] = VmGuestFile(
            guest_path=public_package_path,
            content=json.dumps(public_agent_task_package(package), ensure_ascii=False, indent=2),
            source="metadata.agent_task_package.public",
            permissions="0644",
        )
        private_package_path = str(private_root / "agent_task_package_private.json")
        files[private_package_path] = VmGuestFile(
            guest_path=private_package_path,
            content=json.dumps(package, ensure_ascii=False, indent=2),
            source="metadata.agent_task_package.private",
            permissions="0600",
            root_only=True,
        )
    evaluation = env.get("evaluation")
    include_evaluation = has_guest_files or force_metadata or bool(
        isinstance(materialization, dict) and materialization.get("include_evaluation_manifest")
    )
    if include_evaluation and isinstance(evaluation, dict) and evaluation:
        evaluation_path = str(private_root / "evaluation.json")
        files[evaluation_path] = VmGuestFile(
            guest_path=evaluation_path,
            content=json.dumps(evaluation, ensure_ascii=False, indent=2),
            source="metadata.agent_env.evaluation",
            permissions="0600",
            root_only=True,
        )
    return list(files.values())


def _default_materialization_dir() -> Path:
    configured = str(os.environ.get(VM_MATERIALIZATION_DIR_ENV_VAR) or "").strip()
    if configured:
        root = Path(configured).expanduser()
    elif os.name == "nt" and Path(r"D:\localwork").exists():
        root = Path(r"D:\localwork\vm_backends\materialized")
    else:
        root = Path.home() / ".evalclaw" / "vm-materialized"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _files_digest(files: list[VmGuestFile]) -> str:
    hasher = hashlib.sha256()
    for file in sorted(files, key=lambda item: item.guest_path):
        hasher.update(file.guest_path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(file.content.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(file.source.encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()[:12]


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _cloud_init_user_data(files: list[VmGuestFile], *, guest_user: str, guest_root: str, env: dict[str, Any]) -> str:
    lines = ["#cloud-config"]
    provisioning = _vm_provisioning(env)
    apt_packages = _provisioning_apt_packages(provisioning)
    if apt_packages:
        lines.extend(["package_update: true", "packages:"])
        for package in apt_packages:
            lines.append(f"  - {_yaml_string(package)}")

    if files:
        lines.append("write_files:")
        for file in files:
            encoded = base64.b64encode(file.content.encode("utf-8")).decode("ascii")
            lines.extend(
                [
                    f"  - path: {_yaml_string(file.guest_path)}",
                    f"    permissions: {_yaml_string(file.permissions)}",
                    "    encoding: b64",
                    f"    content: {_yaml_string(encoded)}",
                ]
            )
    writable_dirs = sorted(
        {
            str(PurePosixPath(file.guest_path).parent)
            for file in files
            if not file.root_only
            and (file.guest_path.startswith(f"{guest_root.rstrip('/')}/") or file.guest_path.startswith("/opt/evalclaw/task/public/"))
        }
    )
    commands = []
    if writable_dirs:
        quoted_dirs = " ".join(shlex.quote(path) for path in writable_dirs)
        commands.append(f"mkdir -p {quoted_dirs}")
        commands.append(f"chown -R {shlex.quote(guest_user)}:{shlex.quote(guest_user)} {quoted_dirs} || true")
        commands.append(f"chmod -R u+rwX,go+rX {quoted_dirs} || true")
    commands.extend(_linux_provisioning_commands(provisioning))
    commands.append("mkdir -p /opt/evalclaw && touch /opt/evalclaw/vm-materialized")
    lines.append("runcmd:")
    if commands:
        for command in commands:
            lines.append("  - " + json.dumps(["sh", "-lc", command], ensure_ascii=False))
    else:
        lines.append("  - " + json.dumps(["sh", "-lc", "true"]))
    return "\n".join(lines) + "\n"


def _powershell_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _cloudbase_init_user_data(files: list[VmGuestFile], *, env: dict[str, Any]) -> str:
    lines = [
        "#ps1_sysnative",
        "$ErrorActionPreference = 'Stop'",
        "$ProgressPreference = 'SilentlyContinue'",
    ]
    for file in files:
        path = PureWindowsPath(file.guest_path)
        encoded = base64.b64encode(file.content.encode("utf-8")).decode("ascii")
        lines.extend(
            [
                f"$path = {_powershell_string(str(path))}",
                "New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path) | Out-Null",
                f"[IO.File]::WriteAllBytes($path, [Convert]::FromBase64String('{encoded}'))",
            ]
        )

    if any(file.root_only for file in files):
        private_root = r"C:\ProgramData\EvalClaw\task\private"
        lines.extend(
            [
                f"$privateRoot = {_powershell_string(private_root)}",
                "if (Test-Path -LiteralPath $privateRoot) {",
                "  & icacls.exe $privateRoot /inheritance:r "
                "/grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /T /C | Out-Null",
                "  if ($LASTEXITCODE -ne 0) { throw 'Failed to protect EvalClaw private task files' }",
                "}",
            ]
        )

    provisioning = _vm_provisioning(env)
    for index, command in enumerate(_windows_provisioning_commands(provisioning), 1):
        lines.extend(
            [
                "$global:LASTEXITCODE = 0",
                command,
                f"if ($LASTEXITCODE -ne 0) {{ throw 'VM provisioning command {index} failed' }}",
            ]
        )
    materialized_marker = r"C:\ProgramData\EvalClaw\vm-materialized"
    lines.extend(
        [
            f"$marker = {_powershell_string(materialized_marker)}",
            "New-Item -ItemType Directory -Force -Path (Split-Path -Parent $marker) | Out-Null",
            "Set-Content -LiteralPath $marker -Value 'ready' -Encoding ASCII",
        ]
    )
    return "\r\n".join(lines) + "\r\n"


def _windows_path_to_wsl(path: str | Path) -> str:
    absolute = str(Path(path).resolve())
    if len(absolute) >= 3 and absolute[1] == ":" and absolute[2] in {"\\", "/"}:
        drive = absolute[0].lower()
        rest = absolute[2:].replace("\\", "/").lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return absolute.replace("\\", "/")


def _run_command(command: list[str], *, timeout: int = 60) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode == 0:
        return True, output
    return False, output or f"exit code {proc.returncode}"


def _build_seed_iso(seed_dir: Path, iso_path: Path, *, timeout: int = 60) -> None:
    iso_path.parent.mkdir(parents=True, exist_ok=True)
    native_tool = shutil.which("genisoimage") or shutil.which("mkisofs")
    if native_tool:
        command = [
            native_tool,
            "-output",
            str(iso_path),
            "-volid",
            "cidata",
            "-joliet",
            "-rock",
            str(seed_dir / "user-data"),
            str(seed_dir / "meta-data"),
        ]
        ok, output = _run_command(command, timeout=timeout)
    else:
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if not wsl:
            raise VmTaskMaterializationError(
                "Cannot build VM NoCloud config-drive ISO: genisoimage/mkisofs was not found, and WSL is not available."
            )
        output_path = shlex.quote(_windows_path_to_wsl(iso_path))
        user_data_path = shlex.quote(_windows_path_to_wsl(seed_dir / "user-data"))
        meta_data_path = shlex.quote(_windows_path_to_wsl(seed_dir / "meta-data"))
        script = (
            "set -e; "
            "if command -v genisoimage >/dev/null 2>&1; then "
            f"genisoimage -output {output_path} -volid cidata -joliet -rock {user_data_path} {meta_data_path} >/dev/null; "
            "elif command -v mkisofs >/dev/null 2>&1; then "
            f"mkisofs -output {output_path} -volid cidata -joliet -rock {user_data_path} {meta_data_path} >/dev/null; "
            "else echo 'genisoimage or mkisofs is required inside WSL' >&2; exit 127; fi"
        )
        command = [wsl, "--", "bash", "-lc", script]
        ok, output = _run_command(command, timeout=timeout)
    if not ok:
        raise VmTaskMaterializationError(f"Failed to build VM NoCloud config-drive ISO: {output}")


def _existing_seed_iso(vm_spec: dict[str, Any]) -> str:
    for key in ("seed_iso", "cloud_init_iso", "config_drive_iso"):
        value = vm_spec.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def materialize_vm_task(
    item: BenchmarkItem,
    *,
    work_dir: str | Path | None = None,
    overwrite_seed_iso: bool = False,
) -> VmTaskMaterializationResult:
    env = copy.deepcopy(_agent_env(item))
    if not env or not vm_task_requires_vm(item):
        return VmTaskMaterializationResult(item_id=item.id, applied=False, skipped_reason="item does not require a VM")
    guest_os = _guest_os(env)
    strategy = _materialization_strategy(guest_os)
    vm_spec = copy.deepcopy(env.get("vm") if isinstance(env.get("vm"), dict) else {})
    session = env.get("session") if isinstance(env.get("session"), dict) else {}
    baseline_checks = session.get("baseline_checks")
    if not (
        isinstance(baseline_checks, list)
        and baseline_checks
        and all(isinstance(check, dict) and check for check in baseline_checks)
    ):
        raise VmTaskMaterializationError(
            "VM task materialization requires non-empty environment.session.baseline_checks "
            "so the bridge can prove the initial state before the target starts."
        )
    materialization = env.get("vm_materialization")
    if isinstance(materialization, dict) and materialization.get("enabled") is False:
        _add_required_vm_capabilities(
            vm_spec,
            env,
            guest_os=guest_os,
            needs_config_drive=False,
        )
        env["vm"] = vm_spec
        result = VmTaskMaterializationResult(
            item_id=item.id,
            applied=False,
            skipped_reason="metadata.agent_env.vm_materialization.enabled=false",
            guest_os=guest_os,
            strategy=strategy,
        )
        env["vm_materialization"] = {**materialization, **result.as_dict()}
        _set_agent_env(item, env)
        return result

    explicit_seed = _existing_seed_iso(vm_spec)
    overwrite = overwrite_seed_iso or bool(isinstance(materialization, dict) and materialization.get("overwrite_seed_iso"))
    if explicit_seed and not overwrite:
        _add_required_vm_capabilities(
            vm_spec,
            env,
            guest_os=guest_os,
            needs_config_drive=True,
        )
        env["vm"] = vm_spec
        result = VmTaskMaterializationResult(
            item_id=item.id,
            applied=False,
            seed_iso=explicit_seed,
            skipped_reason="existing VM config-drive ISO preserved",
            guest_os=guest_os,
            strategy=strategy,
        )
        env["vm_materialization"] = {**(materialization if isinstance(materialization, dict) else {}), **result.as_dict()}
        _set_agent_env(item, env)
        return result

    _validate_provisioning_platform(_vm_provisioning(env), guest_os)
    files = _collect_guest_files(item, env)
    provisioning_summary = _provisioning_summary(env, guest_os)
    if not files and not provisioning_summary:
        _add_required_vm_capabilities(
            vm_spec,
            env,
            guest_os=guest_os,
            needs_config_drive=False,
        )
        env["vm"] = vm_spec
        result = VmTaskMaterializationResult(
            item_id=item.id,
            applied=False,
            skipped_reason="no VM guest files to materialize",
            guest_os=guest_os,
            strategy=strategy,
        )
        env["vm_materialization"] = {**(materialization if isinstance(materialization, dict) else {}), **result.as_dict()}
        _set_agent_env(item, env)
        return result
    _add_materialization_baseline_checks(
        env,
        guest_os=guest_os,
        has_provisioning=bool(provisioning_summary.get("command_count")),
    )
    digest_payload = json.dumps(provisioning_summary, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(f"{_files_digest(files)}\0{digest_payload}".encode("utf-8")).hexdigest()[:12]
    slug = _safe_slug(item.id)
    root = Path(work_dir).expanduser() if work_dir is not None else _default_materialization_dir()
    task_dir = root / f"{slug}-{digest}"
    seed_dir = task_dir / "seed"
    seed_iso = task_dir / "seed.iso"
    seed_dir.mkdir(parents=True, exist_ok=True)
    guest_user = _guest_user(env, guest_os)
    guest_root = _guest_root(env, guest_user, guest_os)
    user_data = (
        _cloudbase_init_user_data(files, env=env)
        if guest_os == _WINDOWS
        else _cloud_init_user_data(files, guest_user=guest_user, guest_root=guest_root, env=env)
    )
    (seed_dir / "user-data").write_text(user_data, encoding="utf-8")
    (seed_dir / "meta-data").write_text(
        f"instance-id: evalclaw-{slug}-{digest}\nlocal-hostname: evalclaw-task\n",
        encoding="utf-8",
    )
    _build_seed_iso(seed_dir, seed_iso)

    _add_required_vm_capabilities(
        vm_spec,
        env,
        guest_os=guest_os,
        needs_config_drive=True,
    )
    vm_spec["seed_iso"] = str(seed_iso)
    vm_spec["config_drive_type"] = "nocloud"
    env["vm"] = vm_spec
    result = VmTaskMaterializationResult(
        item_id=item.id,
        applied=True,
        seed_iso=str(seed_iso),
        work_dir=str(task_dir),
        file_count=len(files),
        guest_os=guest_os,
        strategy=strategy,
        provisioning=provisioning_summary,
        mappings=[{"guest_path": file.guest_path, "source": file.source} for file in files],
    )
    env["vm_materialization"] = {**(materialization if isinstance(materialization, dict) else {}), **result.as_dict()}
    _set_agent_env(item, env)
    return result
