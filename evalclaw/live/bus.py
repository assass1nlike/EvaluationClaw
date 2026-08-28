"""Thread-safe per-run event bus for live pipeline visualisation."""
from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

_SENTINEL = None  # signals subscriber that the run ended
_REMOTE_TOKEN_BATCH_CHARS = 2048


class _RemotePublisher:
    """Best-effort HTTP publisher for a run owned by another process."""

    def __init__(self, url: str, run_id: str, goal: str, created_at: str) -> None:
        self.url = url.rstrip("/")
        self.run_id = run_id
        self.goal = goal
        self.created_at = created_at
        self._lock = threading.Lock()
        self._pending: list[dict[str, Any]] = []
        self._pending_chars = 0
        self._closed = False

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            if self._closed:
                return
            if event.get("type") == "token":
                text = str(event.get("text") or "")
                if not text:
                    return
                while text:
                    available = _REMOTE_TOKEN_BATCH_CHARS - self._pending_chars
                    if available == 0:
                        self._post(self._take_pending())
                        available = _REMOTE_TOKEN_BATCH_CHARS
                    part, text = text[:available], text[available:]
                    self._pending.append({**event, "text": part})
                    self._pending_chars += len(part)
                    if self._pending_chars == _REMOTE_TOKEN_BATCH_CHARS:
                        self._post(self._take_pending())
                return
            else:
                batch = self._take_pending()
                batch.append(event)
                self._post(batch)

    def end(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._post(self._take_pending(), end=True)

    def _take_pending(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        for event in self._pending:
            if (
                batch
                and event.get("type") == "token"
                and batch[-1].get("type") == "token"
                and event.get("call_id") == batch[-1].get("call_id")
            ):
                batch[-1] = {
                    **batch[-1],
                    "text": str(batch[-1].get("text") or "") + str(event.get("text") or ""),
                    "t": event.get("t", batch[-1].get("t")),
                }
            else:
                batch.append(event)
        self._pending = []
        self._pending_chars = 0
        return batch

    def _post(self, events: list[dict[str, Any]], *, end: bool = False) -> None:
        from .server import push_events

        push_events(
            self.run_id,
            events,
            url=self.url,
            goal=self.goal,
            created_at=self.created_at,
            end=end,
            timeout=1,
        )


@dataclass
class RunBus:
    run_id: str
    goal: str = ""
    created_at: str = ""
    remote_url: str | None = None
    ended: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _log: list[dict[str, Any]] = field(default_factory=list, repr=False, compare=False)
    _token_chunks: dict[str, list[tuple[int, str, Any]]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    _subscribers: list[queue.SimpleQueue] = field(default_factory=list, repr=False, compare=False)
    _last_seq: int = field(default=0, repr=False, compare=False)
    _remote: _RemotePublisher | None = field(init=False, repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self.remote_url:
            self._remote = _RemotePublisher(
                self.remote_url,
                self.run_id,
                self.goal,
                self.created_at,
            )

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._last_seq += 1
            event = {**event, "seq": self._last_seq}
            if event.get("type") == "token":
                call_id = str(event.get("call_id") or "")
                self._token_chunks.setdefault(call_id, []).append(
                    (self._last_seq, str(event.get("text") or ""), event.get("t"))
                )
            else:
                self._log.append(event)
            for q in self._subscribers:
                q.put_nowait(event)
        if self._remote is not None:
            self._remote.publish(event)

    def _events_after(self, after: int) -> list[dict[str, Any]]:
        events = [event for event in self._log if event["seq"] > after]
        for call_id, chunks in self._token_chunks.items():
            selected = [chunk for chunk in chunks if chunk[0] > after]
            if selected:
                seq, _, timestamp = selected[-1]
                events.append(
                    {
                        "type": "token",
                        "call_id": call_id,
                        "text": "".join(chunk[1] for chunk in selected),
                        "t": timestamp,
                        "seq": seq,
                    }
                )
        return sorted(events, key=lambda event: event["seq"])

    def subscribe(self, *, after: int = 0) -> queue.SimpleQueue:
        """Return compacted history after ``after`` followed by future events."""
        q: queue.SimpleQueue = queue.SimpleQueue()
        with self._lock:
            for past in self._events_after(after):
                q.put_nowait(past)
            if self.ended:
                q.put_nowait(_SENTINEL)
            else:
                self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.SimpleQueue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def end(self) -> None:
        with self._lock:
            self.ended = True
            for q in self._subscribers:
                q.put_nowait(_SENTINEL)
            self._subscribers.clear()
        if self._remote is not None:
            self._remote.end()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "run_id": self.run_id,
                "goal": self.goal,
                "created_at": self.created_at,
                "ended": self.ended,
                "last_seq": self._last_seq,
                "events": self._events_after(0),
            }


class EventBus:
    """Registry of per-run buses, thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buses: dict[str, RunBus] = {}

    def create(
        self,
        run_id: str,
        *,
        goal: str = "",
        created_at: str = "",
        remote_url: str | None = None,
    ) -> RunBus:
        with self._lock:
            existing = self._buses.get(run_id)
            if existing is not None:
                if goal and not existing.goal:
                    existing.goal = goal
                if created_at and not existing.created_at:
                    existing.created_at = created_at
                return existing
            bus = RunBus(
                run_id=run_id,
                goal=goal,
                created_at=created_at,
                remote_url=remote_url,
            )
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
