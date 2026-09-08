"""VM provider lifecycle helpers for GUI/desktop evaluations."""
from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

VM_PROVIDER_URL_ENV_VAR = "EVALCLAW_VM_PROVIDER_URL"
VM_PROVIDER_API_KEY_ENV_VAR = "EVALCLAW_VM_PROVIDER_API_KEY"
VM_BACKEND_ENV_VAR = "EVALCLAW_VM_BACKEND"
VM_TEMPLATE_ENV_VAR = "EVALCLAW_VM_TEMPLATE"
VM_SNAPSHOT_ENV_VAR = "EVALCLAW_VM_SNAPSHOT"
VM_BRIDGE_GUEST_PORT_ENV_VAR = "EVALCLAW_VM_BRIDGE_GUEST_PORT"
VM_BRIDGE_HOST_ENV_VAR = "EVALCLAW_VM_BRIDGE_HOST"
VM_WORK_DIR_ENV_VAR = "EVALCLAW_VM_WORK_DIR"
VIRTUALBOX_EXECUTABLE_ENV_VAR = "EVALCLAW_VBOXMANAGE"
QEMU_EXECUTABLE_ENV_VAR = "EVALCLAW_QEMU_EXECUTABLE"
QEMU_IMG_EXECUTABLE_ENV_VAR = "EVALCLAW_QEMU_IMG_EXECUTABLE"
QEMU_ACCEL_ENV_VAR = "EVALCLAW_QEMU_ACCEL"

VM_PROVIDER_PROTOCOL_V2 = "evalclaw.vm_provider.v2"
VM_PROVIDER_CAPABILITIES_PATH = "/capabilities"
VM_PROVIDER_CONFIG_DRIVE_UPLOAD_PATH = "/artifacts/config-drives"
VM_PROVIDER_IMAGE_BUILD_PATH = "/images/builds"

LOCAL_VM_PROVIDER_PREFIX = "local://"
_LOCAL_QEMU_PROCESSES: dict[str, subprocess.Popen] = {}
_LOCAL_QEMU_OVERLAYS: dict[str, Path] = {}


@dataclass
class VmProviderStatus:
    available: bool
    provider_url: str = ""
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class VmSession:
    vm_id: str
    bridge_url: str = ""
    bridge_api_key: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class LocalVmBackendStatus:
    backend: str = ""
    available: bool = False
    executable: str = ""
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def vm_provider_setup_message() -> str:
    return (
        "A VM-backed GUI task requires an isolated VM, but no reachable VM provider or usable local VM backend is configured.\n\n"
        "Configure one of:\n"
        f"1. Set {VM_PROVIDER_URL_ENV_VAR}=http://127.0.0.1:<port>\n"
        "2. Pass --vm-provider-url http://127.0.0.1:<port>\n"
        "3. Use the built-in local provider with --vm-provider-url local://virtualbox/local://qemu and a prepared template VM\n"
        "4. Put vm_provider_url in metadata.agent_env for this item.\n\n"
        "Expected VM provider contract:\n"
        "- GET /health\n"
        "- GET /capabilities (v2; image inventory and supported features)\n"
        "- POST /artifacts/config-drives (v2; multipart ISO upload with SHA-256)\n"
        "- POST /images/builds (v2; declarative image build plan; requires image_build capability)\n"
        "- POST /vms\n"
        "- GET /operations/{operation_id} (v2 async create status)\n"
        "- DELETE /vms/{vm_id}\n\n"
        "Legacy POST /vms receives {vm, session}. Protocol v2 receives the same fields plus a "
        "request id, resolved image metadata, and an uploaded config-drive reference. The provider "
        "should create or reset an isolated VM, mount the config-drive before boot, start the "
        "desktop/CUA bridge, and return vm_id plus bridge_url. The provider can wrap "
        "VirtualBox, Hyper-V, VMware, QEMU, cloud VMs, or an internal VM farm.\n\n"
        "Built-in local provider supports VirtualBox when VBoxManage is installed and a GUI template VM exists. "
        "It also supports QEMU when qemu-system-x86_64 and qemu-img are installed and vm.disk_image points to a "
        f"prepared disk image. Set {VM_TEMPLATE_ENV_VAR}=<template-name-or-disk-path> or use vm.image/template/disk_image."
    )


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def trust_env_for_url(url: str) -> bool:
    """Return False for local bridge/provider URLs so proxy env vars cannot intercept them."""
    hostname = (urlparse(url).hostname or "").strip().lower().strip("[]")
    if hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return False
    return True


def _provider_client(
    provider_url: str,
    *,
    api_key: str | None,
    timeout: int,
) -> httpx.Client:
    return httpx.Client(
        base_url=provider_url,
        timeout=max(1, timeout),
        headers=_headers(_resolve_provider_api_key(api_key)),
        trust_env=trust_env_for_url(provider_url),
    )


def _normalized_capability(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _capability_names(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {_normalized_capability(item) for item in value if _normalized_capability(item)}


def _fetch_provider_capabilities(
    client: httpx.Client,
) -> tuple[dict[str, Any], bool]:
    response = client.get(VM_PROVIDER_CAPABILITIES_PATH)
    if response.status_code in {404, 405}:
        return {}, False
    response.raise_for_status()
    parsed = response.json() if response.content else {}
    if not isinstance(parsed, dict):
        raise RuntimeError("VM provider /capabilities must return a JSON object.")
    return parsed, True


def _vm_image_requirements(vm_spec: dict[str, Any]) -> tuple[str, str, set[str]]:
    requirements = vm_spec.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    guest_os = _normalized_capability(
        requirements.get("guest_os")
        or requirements.get("os")
        or vm_spec.get("guest_os")
        or vm_spec.get("os")
        or vm_spec.get("platform")
    )
    if guest_os == "win" or guest_os.startswith("windows"):
        guest_os = "windows"
    elif guest_os.startswith("linux"):
        guest_os = "linux"
    architecture = _normalized_capability(
        requirements.get("architecture")
        or requirements.get("arch")
        or vm_spec.get("architecture")
        or vm_spec.get("arch")
    )
    capabilities = _capability_names(requirements.get("capabilities"))
    capabilities.update(_capability_names(requirements.get("required_capabilities")))
    capabilities.update(_capability_names(vm_spec.get("required_capabilities")))
    return guest_os, architecture, capabilities


def _image_identifiers(image: dict[str, Any]) -> set[str]:
    identifiers = {
        str(image.get(key) or "").strip()
        for key in ("id", "name", "image", "template")
        if str(image.get(key) or "").strip()
    }
    aliases = image.get("aliases")
    if isinstance(aliases, list):
        identifiers.update(str(value).strip() for value in aliases if str(value).strip())
    return identifiers


def _image_matches_requirements(
    image: dict[str, Any],
    *,
    guest_os: str,
    architecture: str,
    required_capabilities: set[str],
) -> bool:
    image_os = _normalized_capability(image.get("guest_os") or image.get("os"))
    if image_os == "win" or image_os.startswith("windows"):
        image_os = "windows"
    elif image_os.startswith("linux"):
        image_os = "linux"
    image_arch = _normalized_capability(image.get("architecture") or image.get("arch"))
    image_capabilities = _capability_names(image.get("capabilities"))
    return bool(
        image.get("enabled", True)
        and (not guest_os or image_os == guest_os)
        and (not architecture or image_arch == architecture)
        and required_capabilities.issubset(image_capabilities)
    )


def _image_priority(image: dict[str, Any]) -> int:
    try:
        return int(image.get("priority") or 0)
    except (TypeError, ValueError):
        return 0


def resolve_vm_image_spec(
    vm_spec: dict[str, Any],
    capabilities: dict[str, Any],
    *,
    capabilities_discovered: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve a provider image without embedding provider-specific ids in tasks."""
    resolved = copy.deepcopy(vm_spec)
    images = capabilities.get("images")
    images = [image for image in images if isinstance(image, dict)] if isinstance(images, list) else []
    features = _capability_names(capabilities.get("features"))
    inventory_supported = bool(images or "image_inventory" in features)
    pinned = next(
        (
            str(resolved.get(key) or "").strip()
            for key in ("template", "template_name", "image", "disk_image")
            if str(resolved.get(key) or "").strip()
        ),
        "",
    )
    guest_os, architecture, required_capabilities = _vm_image_requirements(resolved)
    if not inventory_supported:
        if not pinned and capabilities_discovered and "server_side_image_resolution" not in features:
            raise RuntimeError(
                "VM provider does not expose an image inventory or server-side image resolution, "
                "and the task does not pin a concrete image."
            )
        return resolved, None

    matching = [
        image
        for image in images
        if _image_matches_requirements(
            image,
            guest_os=guest_os,
            architecture=architecture,
            required_capabilities=required_capabilities,
        )
    ]
    if pinned:
        matching = [image for image in matching if pinned in _image_identifiers(image)]
        if not matching:
            raise RuntimeError(
                f"VM provider cannot resolve pinned image {pinned!r} with the required OS/capabilities."
            )
    if not matching:
        requirements = ", ".join(sorted(required_capabilities)) or "none"
        raise RuntimeError(
            "VM provider has no enabled image satisfying "
            f"guest_os={guest_os or 'any'}, architecture={architecture or 'any'}, "
            f"capabilities={requirements}."
        )
    matching.sort(
        key=lambda image: (
            not bool(image.get("default", False)),
            -_image_priority(image),
            str(image.get("id") or image.get("name") or ""),
        )
    )
    selected = matching[0]
    image_id = str(selected.get("id") or selected.get("name") or "").strip()
    if not image_id:
        raise RuntimeError("VM provider image inventory entry is missing id/name.")
    resolved["image"] = image_id
    resolved["resolved_image"] = {
        key: selected[key]
        for key in ("id", "name", "digest", "guest_os", "os", "architecture", "arch", "capabilities")
        if key in selected
    }
    return resolved, copy.deepcopy(selected)


def _resolve_provider_url(provider_url: str | None) -> str:
    return (provider_url or os.environ.get(VM_PROVIDER_URL_ENV_VAR) or "").strip().rstrip("/")


def _resolve_provider_api_key(api_key: str | None) -> str | None:
    return (api_key or os.environ.get(VM_PROVIDER_API_KEY_ENV_VAR) or "").strip() or None


def _is_local_provider(provider_url: str | None) -> bool:
    return str(provider_url or "").strip().lower().startswith(LOCAL_VM_PROVIDER_PREFIX)


def _local_provider_backend(provider_url: str | None) -> str:
    raw = str(provider_url or "").strip().lower()
    if raw.startswith(LOCAL_VM_PROVIDER_PREFIX):
        backend = raw[len(LOCAL_VM_PROVIDER_PREFIX) :].strip("/")
        return backend or "auto"
    return str(os.environ.get(VM_BACKEND_ENV_VAR) or "auto").strip().lower() or "auto"


def _run_command(command: list[str], *, timeout: int = 30) -> tuple[bool, str]:
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


def _virtualbox_executable() -> str:
    return _first_existing_executable(
        [
            os.environ.get(VIRTUALBOX_EXECUTABLE_ENV_VAR, ""),
            "VBoxManage",
            "VBoxManage.exe",
            r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
            r"C:\Program Files (x86)\Oracle\VirtualBox\VBoxManage.exe",
            r"D:\localwork\vm_backends\VirtualBox\VBoxManage.exe",
        ]
    )


def _hyperv_available() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "Hyper-V PowerShell cmdlets are only available on Windows."
    ok, output = _run_command(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "if (Get-Command New-VM -ErrorAction SilentlyContinue) { 'available' } else { 'missing' }",
        ],
        timeout=15,
    )
    return bool(ok and "available" in output.lower()), output


def _first_existing_executable(candidates: list[str]) -> str:
    for candidate in candidates:
        value = str(candidate or "").strip().strip('"')
        if not value:
            continue
        resolved = shutil.which(value)
        if resolved:
            return resolved
        path = Path(value)
        if path.is_file():
            return str(path)
    return ""


def _qemu_executable() -> str:
    return _first_existing_executable(
        [
            os.environ.get(QEMU_EXECUTABLE_ENV_VAR, ""),
            "qemu-system-x86_64",
            "qemu-system-x86_64.exe",
            r"D:\localwork\vm_backends\QEMU\qemu-system-x86_64.exe",
            r"D:\localwork\vm_backends\qemu\qemu-system-x86_64.exe",
            r"C:\Program Files\qemu\qemu-system-x86_64.exe",
            r"C:\Program Files (x86)\qemu\qemu-system-x86_64.exe",
        ]
    )


def _qemu_img_executable() -> str:
    qemu_exe = _qemu_executable()
    sibling = str(Path(qemu_exe).with_name("qemu-img.exe")) if qemu_exe else ""
    return _first_existing_executable(
        [
            os.environ.get(QEMU_IMG_EXECUTABLE_ENV_VAR, ""),
            "qemu-img",
            "qemu-img.exe",
            sibling,
            r"D:\localwork\vm_backends\QEMU\qemu-img.exe",
            r"D:\localwork\vm_backends\qemu\qemu-img.exe",
            r"C:\Program Files\qemu\qemu-img.exe",
            r"C:\Program Files (x86)\qemu\qemu-img.exe",
        ]
    )


def probe_local_vm_backend(provider_url: str | None = None) -> LocalVmBackendStatus:
    requested = _local_provider_backend(provider_url)
    candidates = [requested] if requested != "auto" else ["virtualbox", "hyperv", "qemu"]
    details: list[str] = []
    for backend in candidates:
        if backend == "virtualbox":
            executable = _virtualbox_executable()
            if executable:
                ok, output = _run_command([executable, "--version"], timeout=15)
                if ok:
                    return LocalVmBackendStatus(
                        backend="virtualbox",
                        available=True,
                        executable=executable,
                        detail=output or "VirtualBox VBoxManage is available.",
                        data={"provider_url": "local://virtualbox"},
                    )
                details.append(f"virtualbox: {output}")
            else:
                details.append("virtualbox: VBoxManage not found")
        elif backend == "hyperv":
            ok, output = _hyperv_available()
            if ok:
                return LocalVmBackendStatus(
                    backend="hyperv",
                    available=False,
                    detail="Hyper-V was detected, but the built-in provider does not yet automate Hyper-V VM lifecycle.",
                    data={"provider_url": "local://hyperv", "probe": output},
                )
            details.append(f"hyperv: {output or 'New-VM not found'}")
        elif backend == "qemu":
            executable = _qemu_executable()
            if executable:
                img_executable = _qemu_img_executable()
                return LocalVmBackendStatus(
                    backend="qemu",
                    available=bool(img_executable),
                    executable=executable,
                    detail=(
                        "QEMU executable and qemu-img are available. A prepared GUI disk image with "
                        "evalclaw-desktop-bridge is still required at VM creation time."
                        if img_executable
                        else "QEMU executable was detected, but qemu-img was not found."
                    ),
                    data={"provider_url": "local://qemu", "qemu_img": img_executable},
                )
            details.append("qemu: qemu-system-x86_64 not found")
        else:
            details.append(f"{backend}: unsupported local VM backend")
    return LocalVmBackendStatus(
        backend=requested,
        available=False,
        detail="; ".join(details) or "No local VM backend detected.",
        data={"provider_url": f"local://{requested}"},
    )


def local_vm_setup_message() -> str:
    return (
        "Built-in local VM provider could not start because no supported local VM backend/template is ready.\n\n"
        "Supported built-in backends: VirtualBox and QEMU.\n"
        "VirtualBox setup:\n"
        "1. Install VirtualBox so VBoxManage is on PATH.\n"
        f"2. Create a GUI template VM, e.g. {VM_TEMPLATE_ENV_VAR}=evalclaw-gui-ubuntu-22.04.\n"
        "3. Install a desktop session and evalclaw-desktop-bridge inside the VM.\n"
        "4. Install cloud-init for Linux templates or Cloudbase-Init with the NoCloud service for Windows templates.\n"
        "5. Make the bridge listen inside the guest, default port 7766.\n"
        "6. Run EvalClaw with --vm-provider-url local://virtualbox, or leave provider URL empty to allow local auto-detect.\n\n"
        "QEMU setup:\n"
        "1. Install qemu-system-x86_64 and qemu-img.\n"
        "2. Prepare a qcow2/raw GUI disk image with evalclaw-desktop-bridge and cloud-init (Linux) "
        "or Cloudbase-Init NoCloud (Windows) installed.\n"
        "3. Set vm.disk_image, vm.template, vm.image, or "
        f"{VM_TEMPLATE_ENV_VAR}=<disk-image-path>.\n"
        "4. Run EvalClaw with --vm-provider-url local://qemu.\n\n"
        "The local provider creates an isolated clone/overlay, creates a NAT port-forward to the guest bridge, "
        "starts the VM headless, waits for /health, and deletes the clone/overlay on cleanup."
    )


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _safe_vm_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return name[:80] or f"evalclaw-vm-{uuid.uuid4().hex[:8]}"


def _vm_template_name(vm_spec: dict[str, Any]) -> str:
    for key in ("template", "template_name", "image"):
        value = vm_spec.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(os.environ.get(VM_TEMPLATE_ENV_VAR) or "").strip()


def _vm_snapshot_name(vm_spec: dict[str, Any]) -> str:
    value = vm_spec.get("snapshot")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(os.environ.get(VM_SNAPSHOT_ENV_VAR) or "").strip()


def _bridge_guest_port(vm_spec: dict[str, Any]) -> int:
    bridge = vm_spec.get("bridge")
    if isinstance(bridge, dict):
        value = bridge.get("guest_port") or bridge.get("port")
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            pass
    try:
        return max(1, int(os.environ.get(VM_BRIDGE_GUEST_PORT_ENV_VAR) or 7766))
    except ValueError:
        return 7766


def _vm_disk_image_path(vm_spec: dict[str, Any]) -> Path:
    for key in ("disk_image", "disk_path", "template_path", "template", "image"):
        value = vm_spec.get(key)
        if isinstance(value, str) and value.strip():
            candidate = Path(value.strip()).expanduser()
            if candidate.is_file():
                return candidate.resolve()
    env_template = str(os.environ.get(VM_TEMPLATE_ENV_VAR) or "").strip()
    if env_template:
        candidate = Path(env_template).expanduser()
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(
        local_vm_setup_message()
        + "\n\nMissing QEMU disk image. Set vm.disk_image/template/image or "
        + f"{VM_TEMPLATE_ENV_VAR}=<qcow2-or-raw-disk-path>."
    )


def _qemu_backing_format(vm_spec: dict[str, Any], disk_image: Path) -> str:
    value = vm_spec.get("disk_format") or vm_spec.get("backing_format")
    if isinstance(value, str) and value.strip():
        return value.strip()
    suffix = disk_image.suffix.lower()
    if suffix in {".img", ".raw"}:
        return "raw"
    return "qcow2"


def _qemu_work_dir() -> Path:
    configured = str(os.environ.get(VM_WORK_DIR_ENV_VAR) or "").strip()
    if configured:
        path = Path(configured).expanduser()
    elif os.name == "nt" and Path(r"D:\localwork").exists():
        path = Path(r"D:\localwork\vm_backends\runtime")
    else:
        path = Path.home() / ".evalclaw" / "vms"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _qemu_memory(vm_spec: dict[str, Any]) -> str:
    value = vm_spec.get("memory") or vm_spec.get("memory_mb") or os.environ.get("EVALCLAW_QEMU_MEMORY")
    if isinstance(value, int | float):
        return str(int(value))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "2048"


def _qemu_cpus(vm_spec: dict[str, Any]) -> str:
    value = vm_spec.get("cpus") or vm_spec.get("cpu_count") or os.environ.get("EVALCLAW_QEMU_CPUS")
    try:
        return str(max(1, int(value)))
    except (TypeError, ValueError):
        return "2"


def _qemu_accel(vm_spec: dict[str, Any]) -> str:
    value = vm_spec.get("accel") or os.environ.get(QEMU_ACCEL_ENV_VAR)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "tcg"


def _vm_cdrom_paths(vm_spec: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for key in ("seed_iso", "cloud_init_iso", "config_drive_iso", "cdrom", "iso"):
        value = vm_spec.get(key)
        if isinstance(value, str) and value.strip():
            candidate = Path(value.strip()).expanduser()
            if candidate.is_file():
                paths.append(candidate.resolve())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    candidate = Path(item.strip()).expanduser()
                    if candidate.is_file():
                        paths.append(candidate.resolve())
    return list(dict.fromkeys(paths))


def _virtualbox_config_drive_commands(
    executable: str,
    vm_id: str,
    vm_spec: dict[str, Any],
    *,
    timeout: int,
) -> list[list[str]]:
    paths = _vm_cdrom_paths(vm_spec)
    if not paths:
        return []
    configured_controller = str(vm_spec.get("config_drive_controller") or "").strip()
    ok, machine_info = _run_command(
        [executable, "showvminfo", vm_id, "--machinereadable"],
        timeout=timeout,
    )
    if not ok:
        raise RuntimeError(f"Could not inspect VirtualBox VM storage controllers: {machine_info}")

    names: dict[str, str] = {}
    types: dict[str, str] = {}
    port_counts: dict[str, int] = {}
    for line in machine_info.splitlines():
        match = re.match(r'^storagecontrollername(\d+)="(.*)"$', line)
        if match:
            names[match.group(1)] = match.group(2)
            continue
        match = re.match(r'^storagecontrollertype(\d+)="(.*)"$', line)
        if match:
            types[match.group(1)] = match.group(2)
            continue
        match = re.match(r'^storagecontrollerportcount(\d+)="?(\d+)"?$', line)
        if match:
            port_counts[match.group(1)] = int(match.group(2))

    controller = configured_controller
    ports: list[int] = []
    candidates = [
        (index, name)
        for index, name in names.items()
        if (configured_controller and name == configured_controller)
        or (not configured_controller and types.get(index) == "IntelAhci")
    ]
    for index, name in candidates:
        occupied: set[int] = set()
        attachment_pattern = re.compile(rf'^"{re.escape(name)}-(\d+)-(\d+)"="(.*)"$')
        for line in machine_info.splitlines():
            attachment = attachment_pattern.match(line)
            if attachment and attachment.group(3).lower() != "none":
                occupied.add(int(attachment.group(1)))
        free = [port for port in range(port_counts.get(index, 0)) if port not in occupied]
        if len(free) >= len(paths):
            controller = name
            ports = free[: len(paths)]
            break

    commands: list[list[str]] = []
    if not controller:
        if candidates:
            raise RuntimeError("Existing VirtualBox SATA controller has no free config-drive ports.")
        controller = "EvalClawConfigDrive"
        ports = list(range(len(paths)))
        commands.append(
            [
                executable,
                "storagectl",
                vm_id,
                "--name",
                controller,
                "--add",
                "sata",
                "--controller",
                "IntelAhci",
            ]
        )
    elif not ports:
        ports = list(range(len(paths)))
    for port, path in zip(ports, paths, strict=True):
        commands.append(
            [
                executable,
                "storageattach",
                vm_id,
                "--storagectl",
                controller,
                "--port",
                str(port),
                "--device",
                "0",
                "--type",
                "dvddrive",
                "--medium",
                str(path),
            ]
        )
    return commands


def _wait_for_bridge(url: str, *, timeout: int, api_key: str | None = None) -> tuple[bool, str]:
    deadline = time.monotonic() + max(1, timeout)
    headers = _headers(api_key)
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(
                f"{url.rstrip('/')}/health",
                timeout=3,
                headers=headers,
                trust_env=trust_env_for_url(url),
            )
            response.raise_for_status()
            return True, "bridge is reachable"
        except Exception as exc:
            last_error = str(exc)
            time.sleep(2)
    return False, last_error or "timed out waiting for bridge"


def _virtualbox_restart_requested(executable: str, vm_id: str) -> bool:
    ok, output = _run_command(
        [
            executable,
            "guestproperty",
            "get",
            vm_id,
            "/EvalClaw/RestartAfterProvisioning",
        ],
        timeout=10,
    )
    return bool(ok and re.search(r"(?im)^Value:\s*pending\s*$", output))


def _wait_for_virtualbox_bridge(
    executable: str,
    vm_id: str,
    url: str,
    *,
    timeout: int,
    restart_grace: int = 90,
) -> tuple[bool, str]:
    deadline = time.monotonic() + max(1, timeout)
    restart_seen_at: float | None = None
    reset_issued = False
    last_detail = ""
    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        ok, last_detail = _wait_for_bridge(url, timeout=min(5, remaining))
        if ok:
            return True, last_detail
        requested = _virtualbox_restart_requested(executable, vm_id)
        if requested and restart_seen_at is None:
            restart_seen_at = time.monotonic()
        elif not requested:
            restart_seen_at = None
        if (
            requested
            and restart_seen_at is not None
            and not reset_issued
            and time.monotonic() - restart_seen_at >= max(0, restart_grace)
        ):
            reset_ok, reset_detail = _run_command(
                [executable, "controlvm", vm_id, "reset"],
                timeout=30,
            )
            if not reset_ok:
                return False, f"VirtualBox provisioning restart recovery failed: {reset_detail}"
            reset_issued = True
    return False, last_detail or "timed out waiting for bridge"


def probe_vm_provider(
    provider_url: str | None,
    *,
    api_key: str | None = None,
    timeout: int = 10,
) -> VmProviderStatus:
    url = _resolve_provider_url(provider_url)
    if not url:
        local_status = probe_local_vm_backend("local://auto")
        return VmProviderStatus(
            local_status.available,
            provider_url=local_status.data.get("provider_url", "local://auto"),
            detail=local_status.detail
            if local_status.available
            else f"{VM_PROVIDER_URL_ENV_VAR} is not set; local auto-detect failed: {local_status.detail}",
            data={
                "local_backend": local_status.backend,
                "executable": local_status.executable,
                **local_status.data,
            },
        )
    if _is_local_provider(url):
        local_status = probe_local_vm_backend(url)
        return VmProviderStatus(
            local_status.available,
            provider_url=local_status.data.get("provider_url", url),
            detail=local_status.detail,
            data={
                "local_backend": local_status.backend,
                "executable": local_status.executable,
                **local_status.data,
            },
        )
    try:
        with _provider_client(url, api_key=api_key, timeout=timeout) as client:
            response = client.get("/health")
            response.raise_for_status()
            data = response.json() if response.content else {}
            data = data if isinstance(data, dict) else {"result": data}
            capabilities, discovered = _fetch_provider_capabilities(client)
            if discovered:
                data["capabilities"] = capabilities
            data["capabilities_discovered"] = discovered
            data["protocol_v2"] = _provider_protocol_is_v2(capabilities, discovered)
    except Exception as exc:
        return VmProviderStatus(False, provider_url=url, detail=str(exc))
    return VmProviderStatus(True, provider_url=url, detail="VM provider is reachable.", data=data)


def _virtualbox_clone_and_start(
    *,
    provider_url: str,
    vm_spec: dict[str, Any],
    session_spec: dict[str, Any],
    timeout: int,
) -> VmSession:
    executable = _virtualbox_executable()
    if not executable:
        raise RuntimeError(local_vm_setup_message())
    template = _vm_template_name(vm_spec)
    if not template:
        raise RuntimeError(
            local_vm_setup_message()
            + "\n\nMissing template VM. Set vm.template/image or "
            + f"{VM_TEMPLATE_ENV_VAR}=<template-name>."
        )
    vm_id = _safe_vm_name(f"evalclaw-{template}-{uuid.uuid4().hex[:8]}")
    snapshot = _vm_snapshot_name(vm_spec)
    guest_port = _bridge_guest_port(vm_spec)
    host_port = _free_local_port()
    bridge_host = str(os.environ.get(VM_BRIDGE_HOST_ENV_VAR) or "127.0.0.1").strip() or "127.0.0.1"
    bridge_url = f"http://{bridge_host}:{host_port}"

    clone_command = [executable, "clonevm", template]
    if snapshot:
        clone_command.extend(["--snapshot", snapshot])
    clone_command.extend(["--name", vm_id, "--register", "--mode", "machine"])
    initial_commands = [clone_command]

    executed: list[list[str]] = []
    try:
        for command in initial_commands:
            ok, output = _run_command(command, timeout=timeout)
            executed.append(command)
            if not ok:
                raise RuntimeError(f"VirtualBox command failed: {' '.join(command)}\n{output}")
        commands = _virtualbox_config_drive_commands(
            executable,
            vm_id,
            vm_spec,
            timeout=timeout,
        )
        commands.extend(
            [
                [
                    executable,
                    "modifyvm",
                    vm_id,
                    "--natpf1",
                    f"evalclaw-bridge,tcp,127.0.0.1,{host_port},,{guest_port}",
                ],
                [executable, "startvm", vm_id, "--type", "headless"],
            ]
        )
        for command in commands:
            ok, output = _run_command(command, timeout=timeout)
            executed.append(command)
            if not ok:
                raise RuntimeError(f"VirtualBox command failed: {' '.join(command)}\n{output}")
        wait_timeout = int(vm_spec.get("bridge_wait_timeout") or min(max(30, timeout), 600))
        ok, detail = _wait_for_virtualbox_bridge(
            executable,
            vm_id,
            bridge_url,
            timeout=wait_timeout,
            restart_grace=int(vm_spec.get("restart_grace_timeout") or 90),
        )
        if not ok:
            raise RuntimeError(f"Started VM {vm_id}, but desktop bridge did not become reachable at {bridge_url}: {detail}")
    except Exception:
        try:
            destroy_local_vm_session(provider_url, vm_id, timeout=30)
        finally:
            raise

    return VmSession(
        vm_id=vm_id,
        bridge_url=bridge_url,
        data={
            "provider": "local",
            "provider_url": provider_url,
            "backend": "virtualbox",
            "template": template,
            "snapshot": snapshot,
            "guest_bridge_port": guest_port,
            "host_bridge_port": host_port,
            "session": session_spec,
            "commands": executed,
        },
    )


def _qemu_clone_and_start(
    *,
    provider_url: str,
    vm_spec: dict[str, Any],
    session_spec: dict[str, Any],
    timeout: int,
) -> VmSession:
    executable = _qemu_executable()
    img_executable = _qemu_img_executable()
    if not executable or not img_executable:
        raise RuntimeError(local_vm_setup_message())
    disk_image = _vm_disk_image_path(vm_spec)
    backing_format = _qemu_backing_format(vm_spec, disk_image)
    vm_id = _safe_vm_name(f"evalclaw-qemu-{disk_image.stem}-{uuid.uuid4().hex[:8]}")
    overlay_path = _qemu_work_dir() / f"{vm_id}.qcow2"
    guest_port = _bridge_guest_port(vm_spec)
    host_port = _free_local_port()
    bridge_host = str(os.environ.get(VM_BRIDGE_HOST_ENV_VAR) or "127.0.0.1").strip() or "127.0.0.1"
    bridge_url = f"http://{bridge_host}:{host_port}"
    create_overlay_command = [
        img_executable,
        "create",
        "-f",
        "qcow2",
        "-F",
        backing_format,
        "-b",
        str(disk_image),
        str(overlay_path),
    ]
    accel = _qemu_accel(vm_spec)
    qemu_command = [
        executable,
        "-name",
        vm_id,
        "-machine",
        str(vm_spec.get("machine") or "q35"),
        "-accel",
        accel,
        "-m",
        _qemu_memory(vm_spec),
        "-smp",
        _qemu_cpus(vm_spec),
        "-drive",
        f"file={overlay_path},if=virtio,format=qcow2,cache=writethrough",
        "-nic",
        f"user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:{host_port}-:{guest_port}",
    ]
    for cdrom_path in _vm_cdrom_paths(vm_spec):
        qemu_command.extend(["-drive", f"file={cdrom_path},if=ide,media=cdrom,readonly=on"])
    vnc = vm_spec.get("vnc")
    if isinstance(vnc, str) and vnc.strip():
        qemu_command.extend(["-vnc", vnc.strip()])
    else:
        qemu_command.extend(["-display", "none"])
    serial_log = vm_spec.get("serial_log")
    if isinstance(serial_log, str) and serial_log.strip():
        serial_path = Path(serial_log.strip()).expanduser()
        serial_path.parent.mkdir(parents=True, exist_ok=True)
        qemu_command.extend(["-serial", f"file:{serial_path}"])
    if bool(vm_spec.get("no_reboot", True)):
        qemu_command.append("-no-reboot")

    commands = [create_overlay_command, qemu_command]
    process: subprocess.Popen | None = None
    try:
        ok, output = _run_command(create_overlay_command, timeout=max(30, timeout))
        if not ok:
            raise RuntimeError(f"QEMU image command failed: {' '.join(create_overlay_command)}\n{output}")
        _LOCAL_QEMU_OVERLAYS[vm_id] = overlay_path
        process = subprocess.Popen(qemu_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _LOCAL_QEMU_PROCESSES[vm_id] = process
        wait_timeout = int(vm_spec.get("bridge_wait_timeout") or min(max(30, timeout), 240))
        ok, detail = _wait_for_bridge(bridge_url, timeout=wait_timeout)
        if not ok:
            raise RuntimeError(f"Started QEMU VM {vm_id}, but desktop bridge did not become reachable at {bridge_url}: {detail}")
    except Exception:
        try:
            destroy_local_vm_session(provider_url, vm_id, timeout=30)
        finally:
            if process and process.poll() is None:
                process.kill()
            raise

    return VmSession(
        vm_id=vm_id,
        bridge_url=bridge_url,
        data={
            "provider": "local",
            "provider_url": provider_url,
            "backend": "qemu",
            "disk_image": str(disk_image),
            "overlay_path": str(overlay_path),
            "guest_bridge_port": guest_port,
            "host_bridge_port": host_port,
            "session": session_spec,
            "commands": commands,
        },
    )


def create_local_vm_session(
    provider_url: str | None,
    *,
    vm_spec: dict[str, Any] | None = None,
    session_spec: dict[str, Any] | None = None,
    timeout: int = 120,
) -> VmSession:
    url = _resolve_provider_url(provider_url) or "local://auto"
    status = probe_local_vm_backend(url)
    if not status.available or status.backend not in {"virtualbox", "qemu"}:
        raise RuntimeError(local_vm_setup_message() + f"\n\nProbe detail: {status.detail}")
    if status.backend == "qemu":
        return _qemu_clone_and_start(
            provider_url=status.data.get("provider_url", "local://qemu"),
            vm_spec=vm_spec or {},
            session_spec=session_spec or {},
            timeout=timeout,
        )
    return _virtualbox_clone_and_start(
        provider_url=status.data.get("provider_url", "local://virtualbox"),
        vm_spec=vm_spec or {},
        session_spec=session_spec or {},
        timeout=timeout,
    )


def destroy_local_vm_session(provider_url: str | None, vm_id: str, *, timeout: int = 30) -> None:
    if not vm_id:
        return
    backend = _local_provider_backend(provider_url)
    if backend == "auto" and vm_id in _LOCAL_QEMU_PROCESSES:
        backend = "qemu"
    elif backend == "auto":
        backend = "virtualbox"
    if backend == "qemu":
        process = _LOCAL_QEMU_PROCESSES.pop(vm_id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=max(1, timeout))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        overlay_path = _LOCAL_QEMU_OVERLAYS.pop(vm_id, None)
        if overlay_path and overlay_path.exists():
            try:
                overlay_path.unlink()
            except OSError:
                pass
        return
    if backend != "virtualbox":
        return
    executable = _virtualbox_executable()
    if not executable:
        return
    _run_command([executable, "controlvm", vm_id, "poweroff"], timeout=timeout)
    _run_command([executable, "unregistervm", vm_id, "--delete"], timeout=max(timeout, 60))


def _payload_bridge_url(payload: dict[str, Any]) -> str:
    for key in ("bridge_url", "gui_bridge_url", "desktop_bridge_url"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    bridge = payload.get("bridge")
    if isinstance(bridge, dict):
        value = bridge.get("url") or bridge.get("bridge_url")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _payload_bridge_api_key(payload: dict[str, Any]) -> str | None:
    for key in ("bridge_api_key", "gui_bridge_api_key", "desktop_bridge_api_key"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    bridge = payload.get("bridge")
    if isinstance(bridge, dict):
        value = bridge.get("api_key") or bridge.get("bridge_api_key")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _payload_vm_id(payload: dict[str, Any]) -> str:
    for key in ("vm_id", "id", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    vm = payload.get("vm")
    if isinstance(vm, dict):
        value = vm.get("id") or vm.get("vm_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _provider_protocol_is_v2(capabilities: dict[str, Any], discovered: bool) -> bool:
    version = _normalized_capability(capabilities.get("protocol_version"))
    return bool(
        discovered
        and version in {"2", "v2", _normalized_capability(VM_PROVIDER_PROTOCOL_V2)}
    )


def _local_config_drive_path(vm_spec: dict[str, Any]) -> tuple[str, Path] | None:
    for key in ("seed_iso", "cloud_init_iso", "config_drive_iso"):
        value = vm_spec.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        return key, Path(value.strip()).expanduser().resolve()
    return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upload_remote_config_drive(
    client: httpx.Client,
    vm_spec: dict[str, Any],
    capabilities: dict[str, Any],
    *,
    capabilities_discovered: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    prepared = copy.deepcopy(vm_spec)
    local_drive = _local_config_drive_path(prepared)
    if local_drive is None:
        return prepared, None
    source_key, path = local_drive
    if not _provider_protocol_is_v2(capabilities, capabilities_discovered):
        return prepared, None
    if not path.is_file():
        raise RuntimeError(
            f"VM config-drive {source_key} does not point to a readable local file: {path}"
        )
    features = _capability_names(capabilities.get("features"))
    if "config_drive_upload" not in features:
        raise RuntimeError(
            "VM provider v2 must advertise config_drive_upload before EvalClaw can transfer "
            "a task-specific local config-drive."
        )

    digest = _file_sha256(path)
    size = path.stat().st_size
    with path.open("rb") as handle:
        response = client.post(
            VM_PROVIDER_CONFIG_DRIVE_UPLOAD_PATH,
            data={
                "sha256": digest,
                "size": str(size),
                "lifecycle": "vm_scoped",
            },
            files={"file": (path.name, handle, "application/x-iso9660-image")},
            headers={"Idempotency-Key": f"config-drive-{digest}"},
        )
    response.raise_for_status()
    uploaded = response.json() if response.content else {}
    if not isinstance(uploaded, dict):
        raise RuntimeError("VM provider config-drive upload must return a JSON object.")
    artifact_id = str(uploaded.get("artifact_id") or uploaded.get("id") or "").strip()
    returned_digest = str(uploaded.get("sha256") or "").strip().lower()
    if returned_digest and returned_digest != digest:
        _delete_remote_artifact(client, artifact_id)
        raise RuntimeError("VM provider returned a config-drive SHA-256 that does not match the upload.")
    artifact_url = str(uploaded.get("url") or uploaded.get("download_url") or "").strip()
    if not artifact_id and not artifact_url:
        raise RuntimeError("VM provider config-drive upload returned neither artifact_id nor URL.")
    drive = {
        "artifact_id": artifact_id,
        "url": artifact_url,
        "sha256": digest,
        "size": size,
        "media_type": "application/x-iso9660-image",
        "lifecycle": "vm_scoped",
    }
    for alias in ("seed_iso", "cloud_init_iso", "config_drive_iso"):
        prepared.pop(alias, None)
    prepared["config_drive"] = {key: value for key, value in drive.items() if value not in {"", None}}
    return prepared, prepared["config_drive"]


def _delete_remote_artifact(client: httpx.Client, artifact_id: str) -> None:
    if not artifact_id:
        return
    try:
        response = client.delete(f"/artifacts/{artifact_id}")
        response.raise_for_status()
    except Exception:
        pass


def _same_provider_url(provider_url: str, value: str) -> str:
    resolved = urljoin(provider_url.rstrip("/") + "/", value)
    provider = urlparse(provider_url)
    target = urlparse(resolved)
    if (provider.scheme, provider.netloc) != (target.scheme, target.netloc):
        raise RuntimeError("VM provider operation URL must use the same origin as the provider.")
    return resolved


def _poll_vm_operation(
    client: httpx.Client,
    provider_url: str,
    response: httpx.Response,
    data: dict[str, Any],
    *,
    timeout: int,
) -> dict[str, Any]:
    if response.status_code != 202:
        return data
    operation_url = str(
        data.get("status_url")
        or data.get("operation_url")
        or response.headers.get("Location")
        or ""
    ).strip()
    operation_id = str(data.get("operation_id") or data.get("id") or "").strip()
    if not operation_url and operation_id:
        operation_url = f"/operations/{operation_id}"
    if not operation_url:
        raise RuntimeError("Async VM provider response must include status_url or operation_id.")
    operation_url = _same_provider_url(provider_url, operation_url)
    deadline = time.monotonic() + max(1, timeout)
    latest = data
    while time.monotonic() < deadline:
        poll = client.get(operation_url)
        poll.raise_for_status()
        latest = poll.json() if poll.content else {}
        if not isinstance(latest, dict):
            raise RuntimeError("VM provider operation status must return a JSON object.")
        status = _normalized_capability(latest.get("status") or latest.get("state"))
        if status in {"failed", "error", "cancelled", "canceled"}:
            detail = latest.get("error") or latest.get("detail") or status
            raise RuntimeError(f"VM provider operation failed: {detail}")
        if status in {"ready", "succeeded", "completed"} or (
            status == "running" and _payload_vm_id(latest) and _payload_bridge_url(latest)
        ):
            return latest
        time.sleep(1)
    raise RuntimeError(f"Timed out after {timeout}s waiting for VM provider operation.")


def _poll_image_build_operation(
    client: httpx.Client,
    provider_url: str,
    response: httpx.Response,
    data: dict[str, Any],
    *,
    timeout: int,
) -> dict[str, Any]:
    """Poll a provider image-build operation until it returns its image record."""
    if response.status_code != 202:
        return data
    operation_url = str(
        data.get("status_url")
        or data.get("operation_url")
        or response.headers.get("Location")
        or ""
    ).strip()
    operation_id = str(data.get("operation_id") or data.get("id") or "").strip()
    if not operation_url and operation_id:
        operation_url = f"/operations/{operation_id}"
    if not operation_url:
        raise RuntimeError("Async VM image build response must include status_url or operation_id.")
    operation_url = _same_provider_url(provider_url, operation_url)
    deadline = time.monotonic() + max(1, timeout)
    latest = data
    while time.monotonic() < deadline:
        poll = client.get(operation_url)
        poll.raise_for_status()
        latest = poll.json() if poll.content else {}
        if not isinstance(latest, dict):
            raise RuntimeError("VM image build operation status must return a JSON object.")
        status = _normalized_capability(latest.get("status") or latest.get("state"))
        if status in {"failed", "error", "cancelled", "canceled"}:
            detail = latest.get("error") or latest.get("detail") or status
            raise RuntimeError(f"VM image build failed: {detail}")
        image = latest.get("image")
        image_id = (
            image.get("id") if isinstance(image, dict) else image
        )
        if status in {"ready", "succeeded", "completed"} and str(image_id or "").strip():
            return latest
        time.sleep(1)
    raise RuntimeError(f"Timed out after {timeout}s waiting for VM image build operation.")


def build_vm_image(
    provider_url: str | None,
    *,
    api_key: str | None = None,
    build_plan: dict[str, Any],
    timeout: int = 600,
) -> dict[str, Any]:
    """Build and publish a reusable VM image through a capable remote provider.

    The plan is declarative: the provider executes it inside an isolated temporary
    guest and must return an image identifier only after its checks pass.
    """
    url = _resolve_provider_url(provider_url)
    if not url or _is_local_provider(url):
        raise RuntimeError(
            "VM image construction requires a remote provider advertising the image_build capability."
        )
    if not isinstance(build_plan, dict) or not build_plan:
        raise ValueError("build_plan must be a non-empty JSON object.")
    request_id = f"vm-image-{uuid.uuid4().hex}"
    with _provider_client(url, api_key=api_key, timeout=timeout) as client:
        capabilities, discovered = _fetch_provider_capabilities(client)
        if not discovered:
            raise RuntimeError(
                "VM provider does not expose /capabilities; image construction cannot be verified."
            )
        features = _capability_names(capabilities.get("features"))
        if not _provider_protocol_is_v2(capabilities, discovered):
            raise RuntimeError("VM image construction requires VM provider protocol v2.")
        if "image_build" not in features:
            raise RuntimeError(
                "VM provider does not advertise the image_build capability."
            )
        payload = {
            "protocol_version": VM_PROVIDER_PROTOCOL_V2,
            "request_id": request_id,
            "build": copy.deepcopy(build_plan),
        }
        response = client.post(
            VM_PROVIDER_IMAGE_BUILD_PATH,
            json=payload,
            headers={"Idempotency-Key": request_id},
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        if not isinstance(data, dict):
            raise RuntimeError("VM image build response must return a JSON object.")
        initial = data
        data = _poll_image_build_operation(
            client,
            url,
            response,
            data,
            timeout=timeout,
        )
        result = {**initial, **data}
        image = result.get("image")
        if isinstance(image, str):
            image = {"id": image}
        if not isinstance(image, dict) or not str(image.get("id") or "").strip():
            raise RuntimeError("VM image build did not return a concrete image id.")
        result["image"] = image
        result["image_id"] = str(image["id"]).strip()
        result.setdefault("provider_url", url)
        result.setdefault("request_id", request_id)
        return _public_vm_session_data(result)


def _public_vm_session_data(data: dict[str, Any]) -> dict[str, Any]:
    def sanitized(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: sanitized(child)
                for key, child in value.items()
                if not (
                    str(key).lower() in {"api_key", "authorization", "token", "secret"}
                    or str(key).lower().endswith(("_api_key", "_token", "_secret"))
                )
            }
        if isinstance(value, list):
            return [sanitized(child) for child in value]
        return copy.deepcopy(value)

    return sanitized(data)


def create_vm_session(
    provider_url: str | None,
    *,
    api_key: str | None = None,
    vm_spec: dict[str, Any] | None = None,
    session_spec: dict[str, Any] | None = None,
    timeout: int = 120,
) -> VmSession:
    url = _resolve_provider_url(provider_url)
    if not url:
        url = "local://auto"
    if _is_local_provider(url):
        return create_local_vm_session(
            url,
            vm_spec=vm_spec,
            session_spec=session_spec,
            timeout=timeout,
        )
    request_id = f"vm-{uuid.uuid4().hex}"
    uploaded_drive: dict[str, Any] | None = None
    selected_image: dict[str, Any] | None = None
    prepared_vm = copy.deepcopy(vm_spec or {})
    with _provider_client(url, api_key=api_key, timeout=timeout) as client:
        capabilities, discovered = _fetch_provider_capabilities(client)
        protocol_v2 = _provider_protocol_is_v2(capabilities, discovered)
        prepared_vm, selected_image = resolve_vm_image_spec(
            prepared_vm,
            capabilities if protocol_v2 else {},
            capabilities_discovered=protocol_v2,
        )
        prepared_vm, uploaded_drive = _upload_remote_config_drive(
            client,
            prepared_vm,
            capabilities,
            capabilities_discovered=discovered,
        )
        payload: dict[str, Any] = {
            "vm": prepared_vm,
            "session": session_spec or {},
        }
        if protocol_v2:
            payload.update(
                {
                    "protocol_version": VM_PROVIDER_PROTOCOL_V2,
                    "request_id": request_id,
                }
            )
        data: dict[str, Any] = {}
        try:
            request: dict[str, Any] = {"json": payload}
            if protocol_v2:
                request["headers"] = {"Idempotency-Key": request_id}
            response = client.post("/vms", **request)
            response.raise_for_status()
            data = response.json() if response.content else {}
            if not isinstance(data, dict):
                data = {"result": data}
            initial_data = data
            if protocol_v2:
                data = _poll_vm_operation(
                    client,
                    url,
                    response,
                    data,
                    timeout=timeout,
                )
                data = {**initial_data, **data}
            data.setdefault("provider_url", url)
            if protocol_v2:
                data.setdefault("request_id", request_id)
            data.setdefault("vm", prepared_vm)
            if selected_image is not None:
                data.setdefault("resolved_image", selected_image)
            if uploaded_drive is not None:
                data.setdefault("config_drive", uploaded_drive)
            vm_id = _payload_vm_id(data)
            if not vm_id:
                raise RuntimeError("VM provider did not return vm_id from POST /vms.")
            bridge_url = _payload_bridge_url(data)
            if not bridge_url:
                raise RuntimeError("VM provider did not return bridge_url from POST /vms.")
            return VmSession(
                vm_id=vm_id,
                bridge_url=bridge_url,
                bridge_api_key=_payload_bridge_api_key(data),
                data=_public_vm_session_data(data),
            )
        except Exception:
            created_vm_id = _payload_vm_id(data) if isinstance(data, dict) else ""
            if created_vm_id:
                try:
                    client.delete(f"/vms/{created_vm_id}")
                except Exception:
                    pass
            _delete_remote_artifact(
                client,
                str((uploaded_drive or {}).get("artifact_id") or "").strip(),
            )
            raise


def destroy_vm_session(
    provider_url: str | None,
    vm_id: str,
    *,
    api_key: str | None = None,
    timeout: int = 30,
) -> None:
    url = _resolve_provider_url(provider_url)
    if not url or not vm_id:
        return
    if _is_local_provider(url):
        destroy_local_vm_session(url, vm_id, timeout=timeout)
        return
    with _provider_client(url, api_key=api_key, timeout=timeout) as client:
        response = client.delete(f"/vms/{vm_id}")
        response.raise_for_status()


@dataclass
class VmCommandSession:
    vm_id: str
    provider_url: str | None
    bridge_url: str
    bridge_api_key: str | None
    bridge_session_id: str
    vm_data: dict[str, Any] = field(default_factory=dict)


def start_vm_command_session(
    provider_url: str | None,
    image: str = "",
    *,
    api_key: str | None = None,
    vm_spec_extra: dict[str, Any] | None = None,
    timeout: int = 120,
) -> VmCommandSession:
    """Create a VM from an image and open a desktop-bridge session for multi-round commands.

    When ``image`` is empty the provider falls back to its default base image
    (e.g. ``EVALCLAW_VM_TEMPLATE`` for the local QEMU provider).
    """
    vm_spec = dict(vm_spec_extra or {})
    image_id = str(image or "").strip()
    if image_id:
        vm_spec["image"] = image_id
    session = create_vm_session(
        provider_url,
        api_key=api_key,
        vm_spec=vm_spec,
        timeout=timeout,
    )
    try:
        bridge_session_id = _bridge_open_session(
            session.bridge_url,
            session.bridge_api_key,
            timeout=timeout,
        )
    except Exception:
        destroy_vm_session(provider_url, session.vm_id, api_key=api_key)
        raise
    return VmCommandSession(
        vm_id=session.vm_id,
        provider_url=provider_url,
        bridge_url=session.bridge_url,
        bridge_api_key=session.bridge_api_key,
        bridge_session_id=bridge_session_id,
        vm_data=session.data,
    )


def run_vm_session_command(
    session: VmCommandSession,
    command: str,
    *,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run one shell command in the VM's live bridge session."""
    return _bridge_run_action(
        session.bridge_url,
        session.bridge_api_key,
        session.bridge_session_id,
        command,
        timeout=timeout,
    )


def close_vm_command_session(
    session: VmCommandSession,
    *,
    api_key: str | None = None,
) -> None:
    """Close the bridge session and destroy the VM."""
    try:
        _bridge_close_session(session.bridge_url, session.bridge_api_key, session.bridge_session_id)
    finally:
        destroy_vm_session(session.provider_url, session.vm_id, api_key=api_key)


def commit_vm_command_session(
    session: VmCommandSession,
    *,
    name: str = "",
    api_key: str | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    """Solidify the probed VM into a reusable image and return its identifier.

    The returned dict carries an ``image`` key the caller can copy into
    ``environment.vm.image``; the probed VM itself may be destroyed afterwards.
    """
    url = _resolve_provider_url(session.provider_url)
    if _is_local_provider(url):
        backend = _local_provider_backend(url)
        if backend == "qemu":
            return _commit_qemu_overlay(session, name, timeout)
        return _commit_virtualbox_template(session, name, timeout)
    return _commit_remote_vm(session, name, api_key, timeout)


def _commit_qemu_overlay(
    session: VmCommandSession,
    name: str,
    timeout: int,
) -> dict[str, Any]:
    img_executable = _qemu_img_executable()
    if not img_executable:
        raise RuntimeError(local_vm_setup_message())
    overlay_path = _LOCAL_QEMU_OVERLAYS.get(session.vm_id) or session.vm_data.get("overlay_path")
    if not overlay_path or not Path(str(overlay_path)).exists():
        raise RuntimeError("QEMU overlay for the VM session is unavailable.")
    # Flush guest filesystem buffers so the overlay captures the latest writes
    # before the VM is stopped for commit.
    try:
        run_vm_session_command(session, "sync", timeout=30)
    except Exception:
        pass
    process = _LOCAL_QEMU_PROCESSES.get(session.vm_id)
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    committed_name = _safe_vm_name(name or "evalclaw-committed")
    new_image = _qemu_work_dir() / f"{committed_name}-{uuid.uuid4().hex[:8]}.qcow2"
    ok, output = _run_command(
        [img_executable, "convert", "-O", "qcow2", str(overlay_path), str(new_image)],
        timeout=max(1, timeout),
    )
    if not ok:
        raise RuntimeError(f"QEMU overlay commit failed: {output}")
    return {"image": str(new_image), "backend": "qemu"}


def _commit_virtualbox_template(
    session: VmCommandSession,
    name: str,
    timeout: int,
) -> dict[str, Any]:
    executable = _virtualbox_executable()
    if not executable:
        raise RuntimeError(local_vm_setup_message())
    template_name = _safe_vm_name(name or "evalclaw-committed")
    commands = [
        [executable, "controlvm", session.vm_id, "poweroff"],
        [executable, "clonevm", session.vm_id, "--name", template_name, "--register", "--mode", "machine"],
    ]
    for command in commands:
        ok, output = _run_command(command, timeout=max(1, timeout))
        if not ok:
            raise RuntimeError(f"VirtualBox commit failed: {' '.join(command)}: {output}")
    return {"image": template_name, "backend": "virtualbox"}


def _commit_remote_vm(
    session: VmCommandSession,
    name: str,
    api_key: str | None,
    timeout: int,
) -> dict[str, Any]:
    url = _resolve_provider_url(session.provider_url)
    if not url:
        raise RuntimeError("Remote VM commit requires a provider URL.")
    with _provider_client(url, api_key=api_key, timeout=timeout) as client:
        body: dict[str, Any] = {"name": name} if name.strip() else {}
        response = client.post(f"/vms/{session.vm_id}/commit", json=body)
        response.raise_for_status()
        data = response.json() if response.content else {}
        if not isinstance(data, dict):
            data = {"result": data}
        image = data.get("image") or data.get("image_id") or data.get("snapshot")
        if not image:
            raise RuntimeError("Remote VM commit did not return an image identifier.")
        return {"image": str(image), "backend": "remote"}


def run_command_in_vm(
    provider_url: str | None,
    image: str,
    command: str,
    *,
    api_key: str | None = None,
    vm_spec_extra: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Create a VM from an image, run one shell command via its desktop bridge, and destroy it.

    Returns ``{"command", "observation", "error"}``. The VM is destroyed after the
    command regardless of outcome.
    """
    if not str(command or "").strip():
        raise ValueError("VM command requires a command.")
    session = start_vm_command_session(
        provider_url,
        image,
        api_key=api_key,
        vm_spec_extra=vm_spec_extra,
        timeout=timeout,
    )
    try:
        return run_vm_session_command(session, command, timeout=timeout)
    finally:
        close_vm_command_session(session, api_key=api_key)


def _bridge_open_session(
    bridge_url: str,
    bridge_api_key: str | None,
    *,
    timeout: int = 120,
) -> str:
    url = bridge_url.rstrip("/")
    with httpx.Client(
        base_url=url,
        timeout=max(1, timeout),
        headers=_headers(bridge_api_key),
        trust_env=trust_env_for_url(url),
    ) as client:
        response = client.post("/sessions", json={"session": {}})
        response.raise_for_status()
        payload = response.json() if response.content else {}
        session_id = str(payload.get("session_id") or payload.get("id") or "")
        if not session_id:
            raise RuntimeError("Desktop bridge did not return session_id from POST /sessions.")
        return session_id


def _bridge_run_action(
    bridge_url: str,
    bridge_api_key: str | None,
    session_id: str,
    command: str,
    *,
    timeout: int = 120,
    step: int = 1,
) -> dict[str, Any]:
    url = bridge_url.rstrip("/")
    with httpx.Client(
        base_url=url,
        timeout=max(1, timeout),
        headers=_headers(bridge_api_key),
        trust_env=trust_env_for_url(url),
    ) as client:
        response = client.post(
            f"/sessions/{session_id}/actions",
            json={
                "action": "run_command",
                "args": {"command": command, "timeout": timeout},
                "step": step,
            },
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            payload = {"result": payload}
        return {
            "command": command,
            "observation": _bridge_observation(payload),
            "error": str(payload.get("error") or "") or None,
        }


def _bridge_close_session(
    bridge_url: str,
    bridge_api_key: str | None,
    session_id: str,
) -> None:
    url = bridge_url.rstrip("/")
    with httpx.Client(
        base_url=url,
        timeout=max(1, 30),
        headers=_headers(bridge_api_key),
        trust_env=trust_env_for_url(url),
    ) as client:
        try:
            client.delete(f"/sessions/{session_id}")
        except Exception:
            pass


def _bridge_observation(payload: dict[str, Any]) -> str:
    for key in ("observation", "text", "summary", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    parts = []
    for key in ("stdout", "stderr"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts) if parts else "Action run_command completed."
