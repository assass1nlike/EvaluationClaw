"""Read-only accounting of registered process trees and labelled Docker containers."""
from __future__ import annotations

import errno
import json
import os
import subprocess
import time
from pathlib import Path

from .budget_docker import docker_env
from .memory_budget import MemoryBudgetError, _process_identity, _replace_file


class MemorySamplePending(Exception):
    """Docker state and cgroup teardown are not yet consistent; defer admission."""


def process_usage(owners, tracked, proc=Path("/proc")):
    records = {}
    page = os.sysconf("SC_PAGE_SIZE")
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            # Docker process memory is measured from its cgroup, not host RSS.
            if path.stat().st_uid != os.getuid():
                continue
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            records[int(path.name)] = (int(fields[1]), fields[19], int(fields[21]) * page)
        except (FileNotFoundError, ProcessLookupError):
            continue
    identities = dict(tracked)
    identities.update({str(v["pid"]): v["identity"] for v in owners.values()})
    selected = {pid for pid, (_, identity, _) in records.items()
                if identities.get(str(pid)) == identity}
    while True:
        children = {pid for pid, (parent, _, _) in records.items() if parent in selected}
        if children <= selected:
            break
        selected.update(children)
    # Local rootful Docker containers descend from the daemon, not these clients.
    total = sum(records[pid][2] for pid in selected)
    return total, {str(pid): records[pid][1] for pid in selected}


def container_usage(docker, endpoint=None):
    args = [docker]
    env = docker_env(endpoint) if endpoint else None
    ids = subprocess.check_output(
        [*args, "ps", "-q", "--no-trunc", "--filter", f"label=evalclaw.memory-owner={os.getuid()}"],
        text=True, timeout=30, env=env,
    ).split()
    total = 0
    for cid in ids:
        group = Path("/sys/fs/cgroup/system.slice") / f"docker-{cid}.scope"
        try:
            current = int((group / "memory.current").read_text())
            stats = dict(line.split() for line in (group / "memory.stat").read_text().splitlines())
        except OSError as exc:
            if exc.errno == errno.ENODEV:
                raise MemorySamplePending(f"Docker cgroup is being removed: {group}") from exc
            if not isinstance(exc, FileNotFoundError):
                raise
            # It may have exited between listing and sampling. A still-running
            # container with an unreadable cgroup must never silently count as zero.
            alive = subprocess.check_output(
                [*args, "ps", "-q", "--filter", f"id={cid}"], text=True, timeout=30, env=env,
            ).strip()
            if alive:
                raise MemorySamplePending(f"Docker container {cid} is transitioning at {group}.")
            continue
        total += max(0, current - int(stats.get("inactive_file", 0)))
    return total, len(ids)


def sample_usage(state, docker, endpoint=None):
    """Called under the shared admission lock; reuse samples for at most one second."""
    path = state / "usage.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    if 0 <= time.time() - previous.get("time", 0) < 1:
        return previous["bytes"], previous["available"]
    policy = state / "policy.json"
    owners = json.loads(policy.read_text()).get("owners", {}) if policy.exists() else {}
    owners = {k: v for k, v in owners.items() if _process_identity(v["pid"]) == v["identity"]}
    try:
        host, tracked = process_usage(owners, previous.get("tracked", {}))
        containers, count = container_usage(docker, endpoint)
        meminfo = dict((parts[0].rstrip(":"), int(parts[1]) * 1024)
                       for line in Path("/proc/meminfo").read_text().splitlines()
                       if len(parts := line.split()) >= 2)
        available = meminfo["MemAvailable"]
    except (MemorySamplePending, subprocess.TimeoutExpired):
        # Never estimate an unobserved container as zero. No new task fits this
        # sample; the next admission check retries without failing active work.
        return 2**63 - 1, 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise MemoryBudgetError(f"Shared memory measurement failed: {exc}") from exc
    sample = {"time": time.time(), "bytes": host + containers, "available": available,
              "host_rss": host, "container_bytes": containers, "containers": count,
              "tracked": tracked}
    _replace_file(path, json.dumps(sample))
    return sample["bytes"], available
