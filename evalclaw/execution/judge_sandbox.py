"""Filesystem snapshots for inspecting a completed Docker episode."""
from __future__ import annotations

import json
import shlex
import subprocess
import uuid

from .docker import docker_subprocess_env, resolve_docker_executable
from .errors import EvaluationExecutionError
from .image_acquisition import image_pull_options
from .process import run_bounded
from .resource_guard import DockerResourceGuard


class JudgeSandbox:
    """Clone rootfs and writable directory mounts; never reuse writable target data."""

    def __init__(self, docker: str, source: str, workdir: str):
        self.docker = resolve_docker_executable(docker)
        if not self.docker:
            raise RuntimeError("Docker is unavailable for judge exploration.")
        self.env = docker_subprocess_env(docker)
        self.source, self.workdir = source, workdir
        self.name = "evalclaw-judge-" + uuid.uuid4().hex[:12]
        self.image = self.name + ":snapshot"
        self.guard = None

    def docker_call(self, args, *, timeout=600, check=True):
        result = run_bounded([self.docker, *args], timeout=timeout, env=self.env)
        if check and result.returncode:
            raise RuntimeError(f"Judge sandbox Docker operation failed: {result.stderr or result.stdout}")
        return result

    def __enter__(self):
        resume = False
        try:
            self.guard = DockerResourceGuard(self.docker, self.env)
            self.guard.register("image", self.image)
            self.guard.register("container", self.name)
            info = json.loads(self.docker_call(["inspect", self.source]).stdout)[0]
            if info["State"]["Running"] and not info["State"]["Paused"]:
                self.guard.register("resume", self.source)
                self.docker_call(["pause", self.source])
                resume = True
            self.docker_call(["commit", "--pause=false", self.source, self.image])
            mounts = []
            for index, mount in enumerate(info["Mounts"]):
                destination = mount["Destination"]
                if mount["RW"]:
                    volume = f"{self.name}-{index}"
                    self.guard.register("volume", volume)
                    self.docker_call(["volume", "create", volume])
                    helper = f"{self.name}-copy-{index}"
                    self.guard.register("container", helper)
                    # Existing framework writable mounts are directories. Fail explicitly
                    # for other mount types rather than silently omitting episode state.
                    self.docker_call([
                        "run", *image_pull_options(), "--name", helper, "--rm", "--network", "none", "--user", "0:0",
                        "--entrypoint", "sh", "--volumes-from", self.source + ":ro",
                        "-v", volume + ":/evalclaw-copy", self.image, "-lc",
                        f"test -d {shlex.quote(destination)} && cp -a {shlex.quote(destination + '/.')} /evalclaw-copy/",
                    ])
                    mounts += ["-v", f"{volume}:{destination}"]
                else:
                    source = mount.get("Name") if mount["Type"] == "volume" else mount["Source"]
                    mounts += ["-v", f"{source}:{destination}:ro"]
            self.docker_call([
                "create", *image_pull_options(), "--name", self.name, "--network", "none", "--user", "0:0",
                "--workdir", self.workdir, "--entrypoint", "sh", *mounts,
                self.image, "-lc", "while :; do sleep 3600; done",
            ])
            self.docker_call(["start", self.name])
            if resume:
                self.docker_call(["unpause", self.source])
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def command(self, command: str, timeout: int = 120):
        token = uuid.uuid4().hex
        try:
            return self.docker_call([
                "exec", "--user", "0:0", "--workdir", self.workdir,
                "--env", f"EVALCLAW_JUDGE_COMMAND_ID={token}", self.name, "sh", "-lc", command,
            ], timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            # Killing the Docker client does not kill the guest command. Its unique
            # inherited environment marker identifies its descendants without touching
            # services started by review setup or another command.
            cleanup = r'''
pids=""
for entry in /proc/[0-9]*/environ; do
    if tr '\000' '\n' < "$entry" 2>/dev/null | grep -Fqx "EVALCLAW_JUDGE_COMMAND_ID=$1"; then
        pid=${entry#/proc/}; pid=${pid%/environ}
        if kill -STOP "$pid" 2>/dev/null; then pids="$pids $pid"; fi
    fi
done
for pid in $pids; do kill -KILL "$pid" 2>/dev/null || true; done
'''
            try:
                self.docker_call(["exec", "--user", "0:0", self.name,
                                  "sh", "-c", cleanup, "cleanup", token], timeout=30)
            except Exception as exc:
                raise EvaluationExecutionError("Failed to stop a timed-out judge command") from exc
            raise

    def __exit__(self, *_):
        if self.guard is not None:
            self.guard.close()
            self.guard = None
