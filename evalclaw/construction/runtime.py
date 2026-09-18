"""A persistent, resource-limited workspace for Builder-generated Python."""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from ..execution.docker import docker_subprocess_env, resolve_docker_executable
from ..execution.image_acquisition import acquire_image, image_pull_options
from ..execution.process import run_bounded
from ..execution.resource_guard import DockerResourceGuard
from ..types import BenchmarkConfig


class BuilderRuntime:
    def __init__(self, work_dir: Path, config: BenchmarkConfig):
        self.docker = resolve_docker_executable(config.docker_executable)
        if not self.docker:
            raise RuntimeError("Builder Python requires Docker for resource and process isolation.")
        self.env = docker_subprocess_env(config.docker_executable)
        self.name = "evalclaw-builder-" + uuid.uuid4().hex[:12]
        self.guard = DockerResourceGuard(self.docker, self.env)
        self.guard.register("network", self.name)
        self.guard.register("container", self.name)
        directory = str(work_dir.resolve())
        try:
            image = acquire_image(config.builder_sandbox_image, docker_executable=config.docker_executable,
                                  timeout_s=config.docker_pull_timeout_s)
            self._docker(["network", "create", self.name])
            self._docker(
                [
                    "run",
                    *image_pull_options(),
                    "-d",
                    "--name",
                    self.name,
                    "--init",
                    "--network",
                    self.name,
                    "--memory",
                    f"{config.builder_memory_mb}m",
                    "--memory-swap",
                    f"{config.builder_memory_mb}m",
                    "--pids-limit",
                    str(config.builder_pids_limit),
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "--tmpfs",
                    "/tmp:rw,nosuid,size=1073741824",
                    "-e",
                    "HOME=/tmp",
                    "-e",
                    "PYTHONUSERBASE=/tmp/python",
                    "-e",
                    "PATH=/tmp/python/bin:/usr/local/bin:/usr/bin:/bin",
                    "--mount",
                    f"type=bind,source={directory},target={directory}",
                    "--workdir",
                    directory,
                    image,
                    "sleep",
                    "infinity",
                ],
                timeout=config.docker_pull_timeout_s,
            )
        except BaseException:
            self.close()
            raise

    def _docker(self, args, timeout=120):
        result = run_bounded([self.docker, *args], timeout=timeout, env=self.env)
        result.check_returncode()
        return result

    def run(self, code: str, *, timeout: int, max_chars: int):
        with tempfile.TemporaryFile() as source:
            source.write(code.encode("utf-8"))
            source.seek(0)
            try:
                return run_bounded(
                    [self.docker, "exec", "-i", self.name, "python", "-B", "-"],
                    stdin=source,
                    timeout=timeout,
                    env=self.env,
                    output_limit=max_chars,
                )
            except BaseException:
                self.close()
                raise

    def close(self):
        if self.guard is not None:
            guard, self.guard = self.guard, None
            guard.close()
