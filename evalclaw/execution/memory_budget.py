"""Shared measured-memory admission, with an optional pre-provisioned hard cgroup.

Reservations are estimates, not per-task memory limits. The kernel slice is the
hard limit; an OOM invalidates active work rather than becoming a model score.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

GIB = 1024**3
SPEC_ENV = "EVALCLAW_MEMORY_SPEC"
_active = None
_activation_lock = threading.Lock()


class MemoryBudgetError(RuntimeError):
    """Infrastructure failure; never an assessment of target capability."""


def _process_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return None


def _oom_count(group):
    # Child task limits can be part of the benchmark. Only exhaustion of the
    # shared slice invalidates unrelated jobs.
    values = dict(line.split() for line in (group / "memory.events.local").read_text().splitlines())
    return int(values.get("oom", 0)) + int(values.get("oom_kill", 0))


def _own_group():
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            return Path("/sys/fs/cgroup") / line[3:].lstrip("/")
    raise MemoryBudgetError("A unified Linux cgroup v2 hierarchy is required.")


def _replace_file(path, text, mode=None):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text)
    if mode is not None:
        temporary.chmod(mode)
    temporary.replace(path)


class MemoryBudget:
    def __init__(self, group, budget, headroom, state, *, docker=None):
        self.group = Path(group) if group else None
        self.docker = docker
        self.budget, self.headroom = budget, headroom
        self.state = Path(state)
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.initial_oom = _oom_count(self.group) if self.group else None

    @contextmanager
    def locked(self):
        import fcntl

        with (self.state / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def check(self):
        if self.group and _oom_count(self.group) != self.initial_oom:
            raise MemoryBudgetError(
                "Shared memory cgroup reported OOM; active work is invalid infrastructure evidence."
            )

    def _claims(self):
        path = self.state / "claims.json"
        claims = json.loads(path.read_text()) if path.exists() else {}
        return {
            key: value
            for key, value in claims.items()
            if _process_identity(value["pid"]) == value["identity"]
        }

    def _save(self, claims):
        _replace_file(self.state / "claims.json", json.dumps(claims))

    def usage(self):
        if self.group is None:
            from .memory_usage import sample_usage

            return sample_usage(self.state, self.docker)
        current = int((self.group / "memory.current").read_text())
        stats = dict(line.split() for line in (self.group / "memory.stat").read_text().splitlines())
        return max(0, current - int(stats.get("inactive_file", 0))), None

    def join(self, policy):
        with self.locked():
            path = self.state / "policy.json"
            previous = json.loads(path.read_text()) if path.exists() else {}
            owners = {
                key: value
                for key, value in previous.get("owners", {}).items()
                if _process_identity(value["pid"]) == value["identity"]
            }
            if owners and previous["policy"] != policy:
                raise MemoryBudgetError(
                    "All active processes sharing this resource group must use the same memory policy."
                )
            token = uuid.uuid4().hex
            owners[token] = {"pid": os.getpid(), "identity": _process_identity(os.getpid())}
            _replace_file(path, json.dumps({"policy": policy, "owners": owners}))
            return token

    def leave(self, token):
        with self.locked():
            path = self.state / "policy.json"
            state = json.loads(path.read_text())
            state["owners"].pop(token, None)
            _replace_file(path, json.dumps(state))

    @contextmanager
    def reserve(self, amount, cancel=None):
        if amount > self.budget - self.headroom:
            raise MemoryBudgetError(
                "One job's memory reservation exceeds the entire admission budget."
            )
        token = uuid.uuid4().hex
        started = time.monotonic()
        announced = False
        while True:
            self.check()
            if cancel is not None and cancel.is_set():
                from concurrent.futures import CancelledError

                raise CancelledError()
            with self.locked():
                claims = self._claims()
                current, available = self.usage()
                reserved = sum(c["bytes"] for c in claims.values())
                if (max(current, reserved) + amount <= self.budget - self.headroom
                        and (available is None or available >= amount + self.headroom)):
                    claims[token] = {
                        "pid": os.getpid(),
                        "identity": _process_identity(os.getpid()),
                        "bytes": amount,
                    }
                    self._save(claims)
                    break
            if not announced:
                print(
                    f"[memory] Waiting for {amount / GIB:g} GiB of shared admission budget.",
                    flush=True,
                )
                announced = True
            time.sleep(1)
        if announced:
            print(f"[memory] Admitted after {time.monotonic() - started:.1f}s.", flush=True)
        try:
            yield
            self.check()
        finally:
            with self.locked():
                claims = self._claims()
                claims.pop(token, None)
                self._save(claims)


def worker_count(configured, jobs):
    return min(jobs, configured) if configured else jobs


def check_memory_budget():
    if _active is not None:
        _active.check()


@contextmanager
def memory_job(config, *, builder=False, item=None, cancel=None):
    if config.memory_budget_gib is None:
        yield
        return
    if _active is None:
        raise MemoryBudgetError(
            "Memory-budget work must run inside run_pipeline's resource context."
        )
    amount = config.memory_job_gib * GIB
    if builder and _active.group is not None:
        amount = max(amount, (config.builder_memory_mb * 1024**2) + 9 * GIB)
    if item is not None and _active.group is not None:
        env = item.metadata.get("agent_env", {})
        memory = (env.get("resource_limits") or {}).get("memory") or env.get("memory")
        if memory:
            match = re.fullmatch(
                r"(\d+(?:\.\d+)?)\s*([kmgtp]?)(?:i?b)?", str(memory).lower().strip()
            )
            if not match:
                raise MemoryBudgetError(f"Cannot reserve declared Docker memory: {memory!r}")
            amount = max(
                amount,
                int(
                    float(match[1])
                    * 1024 ** {"": 0, "k": 1, "m": 2, "g": 3, "t": 4, "p": 5}[match[2]]
                )
                + 9 * GIB,
            )
    with _active.reserve(amount, cancel):
        yield


def _verify_group(group, budget, own_group=None):
    root = Path("/sys/fs/cgroup")
    group = Path(group).resolve()
    if group == root or root not in group.parents:
        raise MemoryBudgetError(
            "memory_cgroup must identify a dedicated cgroup v2 slice, not the hierarchy root."
        )
    relative = group.relative_to(root)
    # Docker's systemd driver expands '-' into parent slice names.
    parts = group.name.removesuffix(".slice").split("-")
    expected = Path(*["-".join(parts[:i]) + ".slice" for i in range(1, len(parts) + 1)])
    if not group.name.endswith(".slice") or relative != expected:
        raise MemoryBudgetError(
            "System Docker requires a system-level slice, not a user-manager cgroup path."
        )
    own = Path(own_group) if own_group is not None else _own_group()
    if own != group and group not in own.parents:
        raise MemoryBudgetError(
            f"Launch the framework inside {group.name}; limiting Docker alone is insufficient."
        )
    try:
        hard = int((group / "memory.max").read_text())
        swap = (group / "memory.swap.max").read_text().strip()
    except (OSError, ValueError) as error:
        raise MemoryBudgetError(
            "The administrator must provision memory.max and memory.swap.max first."
        ) from error
    if hard != budget or swap != "0":
        raise MemoryBudgetError(
            "The slice memory.max must equal memory_budget_gib and memory.swap.max must be 0."
        )
    return group


@contextmanager
def memory_budget(config, artifact_dir=None):
    global _active
    if config.memory_budget_gib is None:
        yield
        return
    if not _activation_lock.acquire(blocking=False):
        raise MemoryBudgetError("Use separate processes for pipelines sharing a memory budget.")
    previous = os.environ.get(SPEC_ENV)
    manager = session = None
    try:
        group = (_verify_group(config.memory_cgroup, config.memory_budget_gib * GIB)
                 if config.memory_cgroup else None)
        docker = shutil.which(config.docker_executable)
        if not docker:
            raise MemoryBudgetError("Docker executable unavailable.")
        endpoint = json.loads(
            subprocess.check_output(
                [
                    docker,
                    "context",
                    "inspect",
                    "default",
                    "--format",
                    "{{json .Endpoints.docker.Host}}",
                ],
                text=True,
                timeout=30,
            )
        )
        if endpoint != "unix:///var/run/docker.sock":
            raise MemoryBudgetError(
                "Memory budgets require the local system Docker socket in the default context."
            )
        docker_args = [docker, "--context", "default"]
        info = json.loads(
            subprocess.check_output(
                [*docker_args, "info", "--format", "{{json .}}"], text=True, timeout=30
            )
        )
        if info.get("CgroupDriver") != "systemd" or info.get("CgroupVersion") != "2":
            raise MemoryBudgetError(
                "Memory budgets currently require Linux Docker with systemd/cgroup v2."
            )
        if "rootless" in str(info.get("SecurityOptions")):
            raise MemoryBudgetError("Memory budgets require the local system Docker daemon.")
        builders = subprocess.check_output(
            [*docker_args, "buildx", "ls", "--format", "{{json .}}"], text=True, timeout=30
        )
        if not any(
            b.get("Name") == "default" and b.get("Driver") == "docker"
            for b in (json.loads(line) for line in builders.splitlines() if line.strip())
        ):
            raise MemoryBudgetError(
                "Memory budgets require the default integrated Docker BuildKit driver."
            )
        key = hashlib.sha256(str(group or "measured").encode()).hexdigest()[:16]
        # TMPDIR can differ between experiment launchers; admission state cannot.
        state = Path("/tmp") / f"evalclaw-memory-{os.getuid()}" / key
        manager = MemoryBudget(
            group, config.memory_budget_gib * GIB, config.memory_headroom_gib * GIB, state,
            docker=docker,
        )
        policy = {"group": str(group) if group else None, "budget": manager.budget,
                  "headroom": manager.headroom, "mode": "hard" if group else "measured"}
        session = manager.join(policy)
        with manager.locked():
            # Integrated BuildKit preserves local FROM images and build cache.
            # Unlike Docker run, its parent option is a cgroup path, not a slice name.
            spec = {"docker": docker}
            if os.environ.get("EVALCLAW_DOCKER_NETWORK_POOL"):
                spec["network_pool"] = os.environ["EVALCLAW_DOCKER_NETWORK_POOL"]
            if group:
                spec.update(parent=group.name,
                            build_parent="/" + str(group.relative_to("/sys/fs/cgroup")))
            else:
                spec["label"] = f"evalclaw.memory-owner={os.getuid()}"
                manager.usage()  # Fail before model calls if measurement is unavailable.
            source = str(Path(__file__).with_name("budget_docker.py"))
            client_key = hashlib.sha256(f"{sys.executable}:{source}".encode()).hexdigest()[:16]
            client = state / "clients" / client_key
            client.mkdir(parents=True, exist_ok=True)
            spec_path = client / "docker.json"
            _replace_file(spec_path, json.dumps(spec))
            wrapper = client / "docker"
            _replace_file(
                wrapper,
                f'#!{sys.executable}\nimport runpy\nrunpy.run_path({source!r}, run_name="__main__")\n',
                0o700,
            )
        os.environ[SPEC_ENV] = str(spec_path)
        _active = manager
        if artifact_dir is not None:
            (Path(artifact_dir) / "memory-budget.json").write_text(
                json.dumps({**policy, "docker": spec, "initial_oom": manager.initial_oom}, indent=2)
            )
        yield
        manager.check()
    finally:
        try:
            if session is not None:
                manager.leave(session)
        finally:
            _active = None
            if previous is None:
                os.environ.pop(SPEC_ENV, None)
            else:
                os.environ[SPEC_ENV] = previous
            _activation_lock.release()
