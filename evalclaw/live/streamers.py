"""Build on_token callbacks that publish events to the live event bus."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .bus import global_bus
from .registry import get_run, run_id_for_trace, stage_for_trace


def _publish(run_id: str, event: dict[str, Any]) -> None:
    bus = global_bus().get(run_id)
    if bus is not None:
        bus.publish(event)


def _stream_group(
    trace_dir: str | Path | None,
    stage: str,
    trace_name: str,
) -> tuple[str, str] | None:
    """Return a stable logical-call group and its display label.

    A TaskBuilder can make several model calls while handling tools or repairs.
    Those calls share the builder-job directory, so they should appear as one
    live card. Other stages do not use logical grouping.
    """
    if trace_dir is not None:
        parts = list(Path(trace_dir).resolve().parts)
        for index, part in enumerate(parts[:-1]):
            if part.lower() == "task-builder":
                builder_id = parts[index + 1]
                return (
                    f"{stage}:task-builder:{builder_id}",
                    f"TaskBuilder {builder_id}",
                )
    return None


def get_streamer(
    trace_dir: str | Path | None,
    *,
    trace_name: str = "llm",
) -> Callable[[str], None] | None:
    """Return an on_token callback wired to the live bus for this trace, or None.

    Called by llm.py just before a streaming LLM call.  Returns None when no
    run is registered for this trace_dir.
    """
    run_id = run_id_for_trace(trace_dir)
    if run_id is None:
        return None
    bus = global_bus().get(run_id)
    if bus is None:
        return None

    stage = stage_for_trace(trace_dir)
    call_id = f"{stage}:{trace_name}:{int(time.monotonic() * 1000)}"
    stream_group = _stream_group(trace_dir, stage, trace_name)
    group_id, group_label = stream_group or (call_id, trace_name)

    # Signal call start
    bus.publish({
        "type": "llm_start",
        "call_id": call_id,
        "group_id": group_id,
        "group_label": group_label,
        "stage": stage,
        "trace_name": trace_name,
        "t": time.time(),
    })

    def on_token(text: str) -> None:
        bus.publish({
            "type": "token",
            "call_id": call_id,
            "text": text,
            "t": time.time(),
        })

    return on_token


def notify_stage(run_id: str | None, stage: str, *, status: str = "active") -> None:
    """Publish a stage-change event (e.g. planner started, qc completed)."""
    if run_id is None:
        return
    _publish(run_id, {
        "type": "stage",
        "stage": stage,
        "status": status,
        "t": time.time(),
    })


def notify_log(run_id: str | None, message: str, *, level: str = "info") -> None:
    """Publish a log line as a live event."""
    if run_id is None:
        return
    _publish(run_id, {
        "type": "log",
        "message": message,
        "level": level,
        "t": time.time(),
    })
