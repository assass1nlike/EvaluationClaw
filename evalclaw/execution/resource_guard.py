"""Remove explicitly registered Docker resources when their owner exits."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


class DockerResourceGuard:
    def __init__(self, docker: str, env: dict[str, str]):
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), docker],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )

    def register(self, kind: str, name: str) -> None:
        self.process.stdin.write((json.dumps([kind, name]) + "\n").encode())
        self.process.stdin.flush()

    def close(self) -> None:
        self.process.stdin.close()
        self.process.wait(timeout=150)


def _watch(docker: str) -> None:
    resources = []
    for line in sys.stdin:
        resources.append(json.loads(line))
    # EOF also occurs on SIGKILL: no handler in the owner is required.
    for kind in ("container", "volume", "image", "network", "resume"):
        for registered_kind, name in reversed(resources):
            if registered_kind != kind:
                continue
            args = {
                "container": ["rm", "-f", "-v", name],
                "volume": ["volume", "rm", name],
                "image": ["image", "rm", name],
                "network": ["network", "rm", name],
                "resume": ["unpause", name],
            }[kind]
            try:
                subprocess.run(
                    [docker, *args],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass


if __name__ == "__main__":
    _watch(sys.argv[1])
