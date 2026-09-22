"""Container-isolated helpers for executable code evaluation."""
from __future__ import annotations

import json
import subprocess
import uuid

from .docker import docker_status, docker_subprocess_env, resolve_docker_executable
from .image_acquisition import acquire_image, image_pull_options
from .resource_guard import DockerResourceGuard


_PYTHON_RUNNER = """import json, subprocess, sys
code = sys.stdin.read()
try:
    p = subprocess.run([sys.executable, '-I', '-'], input=code, text=True,
                       capture_output=True, timeout=float(sys.argv[1]))
    result = dict(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr, timed_out=False)
except subprocess.TimeoutExpired as exc:
    def text(value):
        return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
    result = dict(returncode=124, stdout=text(exc.stdout), stderr=text(exc.stderr), timed_out=True)
print(json.dumps(result))
"""


def run_python_sandbox(
    code: str,
    *,
    timeout: int = 10,
    image: str = "python:3.11-slim",
    docker_executable: str = "docker",
) -> tuple[int, str, str]:
    """Run Python in a disposable container with no network or host secrets."""
    status = docker_status(executable=docker_executable, timeout_s=120)
    if not status.available:
        raise RuntimeError(
            "Code execution requires a reachable Docker daemon; unsafe host execution is disabled. "
            f"Docker detail: {status.error}"
        )
    executable = resolve_docker_executable(docker_executable)
    if not executable:
        raise RuntimeError(f"Docker executable {docker_executable!r} could not be resolved.")
    image = acquire_image(image, docker_executable=docker_executable)
    name = "evalclaw-python-" + uuid.uuid4().hex[:12]
    env = docker_subprocess_env(docker_executable)
    guard = DockerResourceGuard(executable, env)
    guard.register("container", name)
    command = [
        executable, "run", *image_pull_options(), "--rm", "--name", name, "-i",
        "--network", "none", "--memory", "256m", "--cpus", "1", "--pids-limit", "128",
        "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--workdir", "/tmp",
        image, "python", "-I", "-c", _PYTHON_RUNNER, str(timeout),
    ]
    try:
        proc = subprocess.run(
            command, input=code, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout + 120, env=env,
        )
        if proc.returncode:
            raise RuntimeError(f"Python sandbox failed (exit {proc.returncode}): {proc.stderr}")
        result = json.loads(proc.stdout)
        if result["timed_out"]:
            raise subprocess.TimeoutExpired("sandboxed Python", timeout,
                                            output=result["stdout"], stderr=result["stderr"])
        return result["returncode"], result["stdout"], result["stderr"]
    finally:
        guard.close()


def build_code_harness(test_code: str, model_output: str) -> str:
    return test_code.replace("{model_output}", json.dumps(model_output))
