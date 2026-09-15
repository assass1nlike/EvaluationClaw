"""Runner-side event-triggered controls for Docker agent episodes."""
from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

CommandRunner = Callable[[str, int], subprocess.CompletedProcess[str]]


class InterventionController:
    """Observe episode events and execute one-shot actions outside the target runtime."""

    def __init__(
        self,
        specs: list[dict[str, Any]],
        run_command: CommandRunner,
        *,
        ready: Callable[[], bool] | None = None,
    ) -> None:
        self.specs = specs
        self.run_command = run_command
        self.ready = ready or (lambda: True)
        self.records: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._failure: RuntimeError | None = None
        self._episode_started = 0.0

    def start(self) -> None:
        if not self.specs:
            return
        coordinator = threading.Thread(target=self._wait_until_ready, daemon=True)
        self._threads.append(coordinator)
        coordinator.start()
        for spec in self.specs:
            worker = threading.Thread(target=self._run_spec, args=(spec,), daemon=True)
            self._threads.append(worker)
            worker.start()

    def _wait_until_ready(self) -> None:
        while not self._stop.is_set():
            try:
                if self.ready():
                    self._episode_started = time.monotonic()
                    self._ready.set()
                    return
            except (OSError, subprocess.SubprocessError):
                pass
            self._stop.wait(0.1)

    def _run_spec(self, spec: dict[str, Any]) -> None:
        while not self._ready.wait(0.1):
            if self._stop.is_set():
                self._record_not_triggered(spec)
                return
        trigger = spec["trigger"]
        trigger_type = trigger["type"]
        if trigger_type == "elapsed_time":
            remaining = float(trigger.get("after_seconds", 0))
            deadline = self._episode_started + remaining
            while not self._stop.is_set() and time.monotonic() < deadline:
                self._stop.wait(min(0.1, max(0, deadline - time.monotonic())))
            if self._stop.is_set():
                self._record_not_triggered(spec)
                return
        else:
            interval = float(trigger.get("poll_interval_seconds", 1))
            while not self._stop.is_set():
                try:
                    result = self.run_command(str(trigger["command"]), max(1, int(interval)))
                    if result.returncode == 0:
                        break
                except (OSError, subprocess.SubprocessError):
                    pass
                self._stop.wait(interval)
            if self._stop.is_set():
                self._record_not_triggered(spec)
                return
        self._execute(spec)

    def _execute(self, spec: dict[str, Any]) -> None:
        action = spec["action"]
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        try:
            result = self.run_command(
                str(action["command"]), int(action.get("timeout_seconds", 20))
            )
            record = {
                "id": spec["id"],
                "status": "completed" if result.returncode == 0 else "failed",
                "trigger": spec["trigger"],
                "action": spec["action"],
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except Exception as exc:
            record = {
                "id": spec["id"],
                "status": "failed",
                "trigger": spec["trigger"],
                "action": spec["action"],
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "returncode": None,
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
            }
        with self._lock:
            self.records.append(record)
            if record["status"] == "failed" and self._failure is None:
                self._failure = RuntimeError(
                    f"Environment intervention {spec['id']!r} failed: "
                    f"{record['stderr'] or record['stdout'] or record['returncode']}"
                )

    def _record_not_triggered(self, spec: dict[str, Any]) -> None:
        with self._lock:
            self.records.append(
                {
                    "id": spec["id"],
                    "status": "not_triggered",
                    "trigger": spec["trigger"],
                    "action": spec["action"],
                }
            )

    def stop(self) -> None:
        self._stop.set()
        max_action_timeout = max(
            (
                int(spec.get("action", {}).get("timeout_seconds", 20))
                for spec in self.specs
            ),
            default=0,
        )
        deadline = time.monotonic() + max_action_timeout + 6
        for thread in self._threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))

    def raise_if_failed(self) -> None:
        if self._failure is not None:
            raise self._failure
