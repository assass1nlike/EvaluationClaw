"""Container-isolated helpers for executable code evaluation."""
from __future__ import annotations

import json
import subprocess

from .docker import docker_status, docker_subprocess_env, resolve_docker_executable


def run_python_sandbox(
    code: str,
    *,
    timeout: int = 10,
    image: str = "python:3.11-slim",
    docker_executable: str = "docker",
) -> tuple[int, str, str]:
    """Run Python in a disposable container with no network or host secrets."""
    status = docker_status(executable=docker_executable, timeout_s=min(timeout, 15))
    if not status.available:
        raise RuntimeError(
            "Code execution requires a reachable Docker daemon; unsafe host execution is disabled. "
            f"Docker detail: {status.error}"
        )
    executable = resolve_docker_executable(docker_executable)
    if not executable:
        raise RuntimeError(f"Docker executable {docker_executable!r} could not be resolved.")
    proc = subprocess.run(
        [
            executable,
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--memory",
            "256m",
            "--cpus",
            "1",
            "--pids-limit",
            "128",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            image,
            "python",
            "-I",
            "-",
        ],
        input=code,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout + 10,
        env=docker_subprocess_env(docker_executable),
    )
    return proc.returncode, proc.stdout, proc.stderr


def build_code_harness(test_code: str, model_output: str) -> str:
    return test_code.replace("{model_output}", json.dumps(model_output))
