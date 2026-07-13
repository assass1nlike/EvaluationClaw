"""Docker availability helpers for containerized benchmark backends."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DockerStatus:
    available: bool
    executable: str = "docker"
    client_version: str = ""
    server_version: str = ""
    error: str = ""


def _windows_docker_cli_candidates() -> list[Path]:
    program_files = os.environ.get("ProgramFiles")
    if not program_files:
        return []
    return [Path(program_files) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"]


def resolve_docker_executable(executable: str = "docker") -> str | None:
    """Resolve Docker CLI from PATH or standard Windows install locations."""
    resolved = shutil.which(executable)
    if resolved:
        return resolved
    path = Path(executable)
    if path.is_file():
        return str(path)
    if executable == "docker":
        for candidate in _windows_docker_cli_candidates():
            if candidate.is_file():
                return str(candidate)
    return None


def docker_cli_search_paths(executable: str = "docker") -> list[str]:
    """Return directories that should be prepended to PATH for Docker subprocesses."""
    resolved = resolve_docker_executable(executable)
    if not resolved:
        return []
    return [str(Path(resolved).parent)]


def docker_subprocess_env(executable: str = "docker") -> dict[str, str]:
    """Build an environment where Docker and its credential helpers are discoverable."""
    env = os.environ.copy()
    paths = docker_cli_search_paths(executable)
    if paths:
        current_path = env.get("PATH", "")
        existing = [part for part in current_path.split(os.pathsep) if part]
        lowered = {part.lower() for part in existing}
        missing = [part for part in paths if part.lower() not in lowered]
        if missing:
            env["PATH"] = os.pathsep.join([*missing, current_path])
    return env


def docker_status(
    *,
    executable: str = "docker",
    timeout_s: int = 30,
) -> DockerStatus:
    """Return whether Docker CLI and daemon are reachable."""
    resolved = resolve_docker_executable(executable)
    if not resolved:
        return DockerStatus(
            available=False,
            executable=executable,
            error=f"Docker executable '{executable}' was not found on PATH.",
        )

    try:
        client = subprocess.run(
            [resolved, "version", "--format", "{{.Client.Version}}"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_s,
            check=False,
            env=docker_subprocess_env(executable),
        )
        server = subprocess.run(
            [resolved, "version", "--format", "{{.Server.Version}}"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_s,
            check=False,
            env=docker_subprocess_env(executable),
        )
    except Exception as exc:
        return DockerStatus(
            available=False,
            executable=resolved,
            error=f"Failed to execute Docker CLI: {exc}",
        )

    client_version = client.stdout.strip()
    server_version = server.stdout.strip()
    if client.returncode != 0 or server.returncode != 0 or not server_version:
        message = (server.stderr or client.stderr or "Docker daemon is not reachable.").strip()
        return DockerStatus(
            available=False,
            executable=resolved,
            client_version=client_version,
            server_version=server_version,
            error=message,
        )

    return DockerStatus(
        available=True,
        executable=resolved,
        client_version=client_version,
        server_version=server_version,
    )


def require_docker_available(*, executable: str = "docker", timeout_s: int = 30) -> DockerStatus:
    status = docker_status(executable=executable, timeout_s=timeout_s)
    if not status.available:
        raise RuntimeError(status.error)
    return status
