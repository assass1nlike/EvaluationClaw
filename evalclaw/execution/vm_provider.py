"""VM provider lifecycle helpers for GUI/desktop evaluations."""
from __future__ import annotations

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
from urllib.parse import urlparse

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
        "A GUI desktop task requires an isolated VM, but no reachable VM provider or usable local VM backend is configured.\n\n"
        "Configure one of:\n"
        f"1. Set {VM_PROVIDER_URL_ENV_VAR}=http://127.0.0.1:<port>\n"
        "2. Pass --vm-provider-url http://127.0.0.1:<port>\n"
        "3. Use the built-in local provider with --vm-provider-url local://virtualbox/local://qemu and a prepared template VM\n"
        "4. Put vm_provider_url in metadata.agent_env for this item.\n\n"
        "Expected VM provider contract:\n"
        "- GET /health\n"
        "- POST /vms\n"
        "- DELETE /vms/{vm_id}\n\n"
        "POST /vms receives {vm, session} and should create or reset an isolated VM, start the "
        "desktop/CUA bridge for that VM, mount any vm.seed_iso/config_drive_iso before boot, and "
        "return vm_id plus bridge_url. The provider can wrap "
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
) -> list[list[str]]:
    paths = _vm_cdrom_paths(vm_spec)
    if not paths:
        return []
    configured_controller = str(vm_spec.get("config_drive_controller") or "").strip()
    controller = configured_controller or "EvalClawConfigDrive"
    commands: list[list[str]] = []
    if not configured_controller:
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
    for port, path in enumerate(paths):
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
        with httpx.Client(
            base_url=url,
            timeout=max(1, timeout),
            headers=_headers(_resolve_provider_api_key(api_key)),
            trust_env=trust_env_for_url(url),
        ) as client:
            response = client.get("/health")
            response.raise_for_status()
            data = response.json() if response.content else {}
    except Exception as exc:
        return VmProviderStatus(False, provider_url=url, detail=str(exc))
    return VmProviderStatus(True, provider_url=url, detail="VM provider is reachable.", data=data if isinstance(data, dict) else {})


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

    commands = [
        [executable, "clonevm", template, "--name", vm_id, "--register", "--mode", "machine"],
    ]
    if snapshot:
        commands.append([executable, "snapshot", vm_id, "restore", snapshot])
    commands.extend(_virtualbox_config_drive_commands(executable, vm_id, vm_spec))
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

    executed: list[list[str]] = []
    try:
        for command in commands:
            ok, output = _run_command(command, timeout=timeout)
            executed.append(command)
            if not ok:
                raise RuntimeError(f"VirtualBox command failed: {' '.join(command)}\n{output}")
        wait_timeout = int(vm_spec.get("bridge_wait_timeout") or min(max(30, timeout), 180))
        ok, detail = _wait_for_bridge(bridge_url, timeout=wait_timeout)
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
        f"file={overlay_path},if=virtio,format=qcow2",
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
    payload = {
        "vm": vm_spec or {},
        "session": session_spec or {},
    }
    with httpx.Client(
        base_url=url,
        timeout=max(1, timeout),
        headers=_headers(_resolve_provider_api_key(api_key)),
        trust_env=trust_env_for_url(url),
    ) as client:
        response = client.post("/vms", json=payload)
        response.raise_for_status()
        data = response.json() if response.content else {}
    if not isinstance(data, dict):
        data = {"result": data}
    data.setdefault("provider_url", url)
    vm_id = _payload_vm_id(data)
    if not vm_id:
        raise RuntimeError("VM provider did not return vm_id from POST /vms.")
    return VmSession(
        vm_id=vm_id,
        bridge_url=_payload_bridge_url(data),
        bridge_api_key=_payload_bridge_api_key(data),
        data=data,
    )


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
    with httpx.Client(
        base_url=url,
        timeout=max(1, timeout),
        headers=_headers(_resolve_provider_api_key(api_key)),
        trust_env=trust_env_for_url(url),
    ) as client:
        response = client.delete(f"/vms/{vm_id}")
        response.raise_for_status()
