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
from pathlib import Path, PurePosixPath
from typing import Any

from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_METADATA_KEY,
    public_agent_task_package,
)
from ..protocols.task_agent import TASK_AGENT_METADATA_KEY
from ..types import BenchmarkItem
from .installers import apt_packages, package_list, render_install_commands

VM_MATERIALIZATION_DIR_ENV_VAR = "EVALCLAW_VM_MATERIALIZATION_DIR"


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
    task_agent = item.metadata.get(TASK_AGENT_METADATA_KEY)
    if isinstance(task_agent, dict):
        execution = task_agent.get("execution")
        if isinstance(execution, dict):
            task_env = execution.get("agent_env")
            if isinstance(task_env, dict):
                return task_env
    return {}


def _set_agent_env(item: BenchmarkItem, env: dict[str, Any]) -> None:
    item.metadata["agent_env"] = env
    task_agent = item.metadata.get(TASK_AGENT_METADATA_KEY)
    if isinstance(task_agent, dict):
        execution = task_agent.get("execution")
        if isinstance(execution, dict):
            execution["agent_env"] = env
            task_agent["execution"] = execution
            item.metadata[TASK_AGENT_METADATA_KEY] = task_agent


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


def _guest_user(env: dict[str, Any]) -> str:
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
    return "ubuntu"


def _guest_root(env: dict[str, Any], guest_user: str) -> str:
    materialization = env.get("vm_materialization")
    if isinstance(materialization, dict):
        value = materialization.get("guest_root") or materialization.get("file_root")
        if isinstance(value, str) and value.strip():
            return _normalize_guest_path(value.strip())
    if guest_user == "root":
        return "/root"
    return f"/home/{guest_user}"


def _normalize_guest_path(raw_path: str) -> str:
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


def _map_guest_path(raw_path: str, *, guest_root: str) -> str:
    normalized = _normalize_guest_path(raw_path)
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
    )
    return any(bool(provisioning.get(key)) for key in keys) or bool(provisioning.get("enabled"))


def _provisioning_apt_packages(provisioning: dict[str, Any]) -> list[str]:
    return apt_packages(provisioning)


def _provisioning_commands(provisioning: dict[str, Any]) -> list[str]:
    commands: list[str] = render_install_commands(provisioning)
    if commands:
        commands.append("mkdir -p /opt/evalclaw && touch /opt/evalclaw/vm-provisioned")
    return commands


def _provisioning_summary(env: dict[str, Any]) -> dict[str, Any]:
    provisioning = _vm_provisioning(env)
    if not _vm_provisioning_requested(env):
        return {}
    return {
        "enabled": True,
        "strategy": str(provisioning.get("strategy") or "cloud_init.v1"),
        "apt_packages": _provisioning_apt_packages(provisioning),
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
        "command_count": len(_provisioning_commands(provisioning)),
    }


def _add_file(
    files: dict[str, VmGuestFile],
    *,
    raw_path: str,
    content: Any,
    source: str,
    guest_root: str,
    permissions: str = "0644",
    root_only: bool = False,
) -> None:
    guest_path = _map_guest_path(raw_path, guest_root=guest_root)
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
) -> None:
    if not isinstance(mapping, dict):
        return
    for raw_path, content in mapping.items():
        if isinstance(raw_path, str) and raw_path.strip():
            _add_file(files, raw_path=raw_path, content=content, source=source, guest_root=guest_root)


def _safe_private_suffix(raw_path: str) -> str:
    normalized = _normalize_guest_path(raw_path)
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"", "/", "."}]
    if not parts:
        raise VmTaskMaterializationError(f"Unsafe private guest path: {raw_path}")
    return str(PurePosixPath(*parts))


def _add_private_file_mapping(
    files: dict[str, VmGuestFile],
    mapping: Any,
    *,
    source: str,
) -> None:
    if not isinstance(mapping, dict):
        return
    for raw_path, content in mapping.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        private_path = str(PurePosixPath("/opt/evalclaw/task/private/hidden_references", _safe_private_suffix(raw_path)))
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
) -> None:
    if not isinstance(session, dict):
        return
    for key in ("files", "input_files", "asset_files"):
        _add_file_mapping(files, session.get(key), source=f"{source}.{key}", guest_root=guest_root)
    assets = session.get("assets")
    if isinstance(assets, dict):
        _add_file_mapping(files, assets, source=f"{source}.assets", guest_root=guest_root)
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
            )


def _public_initial_content(initial: dict[str, Any]) -> dict[str, Any]:
    public = copy.deepcopy(initial)
    public.pop("files", None)
    public.pop("hidden_files", None)
    public.pop("hidden_file_names", None)
    return public


def _collect_guest_files(item: BenchmarkItem, env: dict[str, Any]) -> list[VmGuestFile]:
    guest_user = _guest_user(env)
    guest_root = _guest_root(env, guest_user)
    materialization = env.get("vm_materialization")
    files: dict[str, VmGuestFile] = {}
    initial = _initial_content(item)
    package = _agent_task_package(item)
    visible_package = package.get("visible_inputs") if isinstance(package.get("visible_inputs"), dict) else {}
    hidden_package = package.get("hidden_references") if isinstance(package.get("hidden_references"), dict) else {}
    _add_file_mapping(files, env.get("visible_files"), source="metadata.agent_env.visible_files", guest_root=guest_root)
    _add_file_mapping(files, env.get("files"), source="metadata.agent_env.files", guest_root=guest_root)
    _add_file_mapping(files, initial.get("files"), source="metadata.task_agent.initial_content.files", guest_root=guest_root)
    _add_file_mapping(files, visible_package.get("files"), source="metadata.agent_task_package.visible_inputs.files", guest_root=guest_root)
    _session_asset_files(files, env.get("session"), source="metadata.agent_env.session", guest_root=guest_root)
    _session_asset_files(files, initial.get("session"), source="metadata.task_agent.initial_content.session", guest_root=guest_root)
    _session_asset_files(files, visible_package, source="metadata.agent_task_package.visible_inputs", guest_root=guest_root)
    _add_private_file_mapping(
        files,
        hidden_package.get("files"),
        source="metadata.agent_task_package.hidden_references.files",
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
        "rubric": item.rubric,
        "tags": item.tags,
        "task_agent_initial_content": _public_initial_content(initial),
        "session": copy.deepcopy(env.get("session") if isinstance(env.get("session"), dict) else {}),
    }
    files["/opt/evalclaw/task/public/task.json"] = VmGuestFile(
        guest_path="/opt/evalclaw/task/public/task.json",
        content=json.dumps(public_manifest, ensure_ascii=False, indent=2),
        source="evalclaw.public_task_manifest",
        permissions="0644",
    )
    if package:
        files["/opt/evalclaw/task/public/agent_task_package.json"] = VmGuestFile(
            guest_path="/opt/evalclaw/task/public/agent_task_package.json",
            content=json.dumps(public_agent_task_package(package), ensure_ascii=False, indent=2),
            source="metadata.agent_task_package.public",
            permissions="0644",
        )
        files["/opt/evalclaw/task/private/agent_task_package_private.json"] = VmGuestFile(
            guest_path="/opt/evalclaw/task/private/agent_task_package_private.json",
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
        files["/opt/evalclaw/task/private/evaluation.json"] = VmGuestFile(
            guest_path="/opt/evalclaw/task/private/evaluation.json",
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
    commands.extend(_provisioning_commands(provisioning))
    lines.append("runcmd:")
    if commands:
        for command in commands:
            lines.append("  - " + json.dumps(["sh", "-lc", command], ensure_ascii=False))
    else:
        lines.append("  - " + json.dumps(["sh", "-lc", "true"]))
    return "\n".join(lines) + "\n"


def _windows_path_to_wsl(path: str | Path) -> str:
    absolute = str(Path(path).resolve())
    if len(absolute) >= 3 and absolute[1] == ":" and absolute[2] in {"\\", "/"}:
        drive = absolute[0].lower()
        rest = absolute[2:].replace("\\", "/").lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return absolute.replace("\\", "/")


def _run_command(command: list[str], *, timeout: int = 60) -> tuple[bool, str]:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
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
                "Cannot build VM cloud-init seed ISO: genisoimage/mkisofs was not found, and WSL is not available."
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
        raise VmTaskMaterializationError(f"Failed to build VM cloud-init seed ISO: {output}")


def _existing_seed_iso(vm_spec: dict[str, Any]) -> str:
    for key in ("seed_iso", "cloud_init_iso"):
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
    materialization = env.get("vm_materialization")
    if isinstance(materialization, dict) and materialization.get("enabled") is False:
        result = VmTaskMaterializationResult(
            item_id=item.id,
            applied=False,
            skipped_reason="metadata.agent_env.vm_materialization.enabled=false",
        )
        env["vm_materialization"] = {**materialization, **result.as_dict()}
        _set_agent_env(item, env)
        return result

    vm_spec = copy.deepcopy(env.get("vm") if isinstance(env.get("vm"), dict) else {})
    explicit_seed = _existing_seed_iso(vm_spec)
    overwrite = overwrite_seed_iso or bool(isinstance(materialization, dict) and materialization.get("overwrite_seed_iso"))
    if explicit_seed and not overwrite:
        result = VmTaskMaterializationResult(
            item_id=item.id,
            applied=False,
            seed_iso=explicit_seed,
            skipped_reason="existing vm.seed_iso/cloud_init_iso preserved",
        )
        env["vm_materialization"] = {**(materialization if isinstance(materialization, dict) else {}), **result.as_dict()}
        _set_agent_env(item, env)
        return result

    files = _collect_guest_files(item, env)
    provisioning_summary = _provisioning_summary(env)
    if not files and not provisioning_summary:
        result = VmTaskMaterializationResult(
            item_id=item.id,
            applied=False,
            skipped_reason="no VM guest files to materialize",
        )
        env["vm_materialization"] = {**(materialization if isinstance(materialization, dict) else {}), **result.as_dict()}
        _set_agent_env(item, env)
        return result
    digest_payload = json.dumps(provisioning_summary, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(f"{_files_digest(files)}\0{digest_payload}".encode("utf-8")).hexdigest()[:12]
    slug = _safe_slug(item.id)
    root = Path(work_dir).expanduser() if work_dir is not None else _default_materialization_dir()
    task_dir = root / f"{slug}-{digest}"
    seed_dir = task_dir / "seed"
    seed_iso = task_dir / "seed.iso"
    seed_dir.mkdir(parents=True, exist_ok=True)
    guest_user = _guest_user(env)
    guest_root = _guest_root(env, guest_user)
    (seed_dir / "user-data").write_text(
        _cloud_init_user_data(files, guest_user=guest_user, guest_root=guest_root, env=env),
        encoding="utf-8",
    )
    (seed_dir / "meta-data").write_text(
        f"instance-id: evalclaw-{slug}-{digest}\nlocal-hostname: evalclaw-task\n",
        encoding="utf-8",
    )
    _build_seed_iso(seed_dir, seed_iso)

    vm_spec["seed_iso"] = str(seed_iso)
    env["vm"] = vm_spec
    result = VmTaskMaterializationResult(
        item_id=item.id,
        applied=True,
        seed_iso=str(seed_iso),
        work_dir=str(task_dir),
        file_count=len(files),
        provisioning=provisioning_summary,
        mappings=[{"guest_path": file.guest_path, "source": file.source} for file in files],
    )
    env["vm_materialization"] = {**(materialization if isinstance(materialization, dict) else {}), **result.as_dict()}
    _set_agent_env(item, env)
    return result
