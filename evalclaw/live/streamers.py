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


def get_streamer(
    trace_dir: str | Path | None,
    *,
    trace_name: str = "llm",
) -> Callable[[str], None] | None:
    """Return an on_token callback wired to the live bus for this trace, or None.

    Called by llm.py just before a streaming LLM call.  Returns None when
    the live server is not running or no run is registered for this trace_dir.
    """
    run_id = run_id_for_trace(trace_dir)
    if run_id is None:
        return None
    bus = global_bus().get(run_id)
    if bus is None:
        return None

    stage = stage_for_trace(trace_dir)
    call_id = f"{stage}:{trace_name}:{int(time.monotonic() * 1000)}"

    # Signal call start
    bus.publish({
        "type": "llm_start",
        "call_id": call_id,
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
