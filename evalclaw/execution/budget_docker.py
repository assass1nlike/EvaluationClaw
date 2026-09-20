"""Docker CLI used only inside a verified memory-budget runtime."""

from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path


def docker_env(endpoint):
    """Pin the selected local daemon, including BuildKit's default builder."""
    env = os.environ.copy()
    for key in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        env.pop(key, None)
    env["DOCKER_HOST"] = endpoint
    return env


def command(args, spec):
    if not args:
        return [spec["docker"]]
    operation = args[0]
    if operation in {"run", "create"}:
        # Framework-owned container creation never supplies a cgroup parent.
        # Docker takes the last option, so reject overrides instead of silently
        # permitting a container to escape the shared group.
        if any(a == "--cgroup-parent" or a.startswith("--cgroup-parent=") for a in args[1:]):
            raise ValueError("Explicit cgroup-parent conflicts with shared memory accounting.")
        options = (["--cgroup-parent", spec["parent"]] if "parent" in spec
                   else ["--label", spec["label"]])
        args = [operation, *options, *args[1:]]
    elif operation == "build":
        if any(a.split("=", 1)[0] in {"--builder", "--cgroup-parent"} for a in args[1:]):
            raise ValueError("Explicit builder conflicts with shared memory accounting.")
        args = [
            "buildx",
            "build",
            "--builder",
            "default",
            "--load",
            *(["--cgroup-parent", spec["build_parent"]] if "build_parent" in spec else []),
            *args[1:],
        ]
    elif operation not in {
        "version",
        "info",
        "inspect",
        "image",
        "images",
        "pull",
        "load",
        "save",
        "tag",
        "rm",
        "rmi",
        "ps",
        "exec",
        "cp",
        "start",
        "stop",
        "kill",
        "pause",
        "unpause",
        "commit",
        "logs",
        "wait",
        "network",
        "volume",
    }:
        raise ValueError(f"Docker operation {operation!r} is not supported in a memory-budget run.")
    return [spec["docker"], *args]


if __name__ == "__main__":
    spec = json.loads(Path(os.environ["EVALCLAW_MEMORY_SPEC"]).read_text())
    env = docker_env(spec["endpoint"])
    os.environ.clear()
    os.environ.update(env)
    try:
        argv = command(sys.argv[1:], spec)
        if argv[1:3] == ["network", "inspect"] and spec.get("network_pool"):
            inspect = runpy.run_path(str(Path(__file__).with_name("docker_networks.py")))["inspect_networks"]
            print(json.dumps(inspect(argv[:1], argv[3:])))
            raise SystemExit(0)
        if argv[1:3] == ["network", "create"] and spec.get("network_pool"):
            if not any(a.split("=", 1)[0] == "--subnet" for a in argv[3:]):
                create = runpy.run_path(str(Path(__file__).with_name("docker_networks.py")))["create_network"]
                result = create(argv[:1], argv[1:], spec["network_pool"])
                raise SystemExit(result.returncode)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
    os.execv(argv[0], argv)
