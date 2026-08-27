"""Thread-safe per-run event bus for live pipeline visualisation."""
from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

_SENTINEL = None  # signals subscriber that the run ended


@dataclass
class RunBus:
    run_id: str
    goal: str = ""
    created_at: str = ""
    ended: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _log: list[dict[str, Any]] = field(default_factory=list, repr=False, compare=False)
    _subscribers: list[queue.SimpleQueue] = field(default_factory=list, repr=False, compare=False)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._log.append(event)
            for q in self._subscribers:
                q.put_nowait(event)

    def subscribe(self) -> queue.SimpleQueue:
        """Return a queue that receives all future events plus past log."""
        q: queue.SimpleQueue = queue.SimpleQueue()
        with self._lock:
            for past in self._log:
                q.put_nowait(past)
            if self.ended:
                q.put_nowait(_SENTINEL)
            else:
                self._subscribers.append(q)
        return q

    def end(self) -> None:
        with self._lock:
            self.ended = True
            for q in self._subscribers:
                q.put_nowait(_SENTINEL)
            self._subscribers.clear()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "run_id": self.run_id,
                "goal": self.goal,
                "created_at": self.created_at,
                "ended": self.ended,
                "events": list(self._log),
            }


class EventBus:
    """Registry of per-run buses, thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buses: dict[str, RunBus] = {}

    def create(self, run_id: str, *, goal: str = "", created_at: str = "") -> RunBus:
        bus = RunBus(run_id=run_id, goal=goal, created_at=created_at)
        with self._lock:
            self._buses[run_id] = bus
        return bus

    def get(self, run_id: str) -> RunBus | None:
        with self._lock:
            return self._buses.get(run_id)

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "run_id": b.run_id,
                    "goal": b.goal,
                    "created_at": b.created_at,
                    "ended": b.ended,
                }
                for b in reversed(list(self._buses.values()))
            ]


def event_json(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


_global_bus = EventBus()


def global_bus() -> EventBus:
    return _global_bus
