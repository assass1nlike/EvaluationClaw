"""Run registration and trace_dir → run_id mapping for live visualisation."""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from .bus import RunBus, global_bus

_lock = threading.Lock()
# trace_dir_root (str) → run_id
_dir_to_run: dict[str, str] = {}


def register_run(
    run_id: str,
    *,
    goal: str = "",
    created_at: str = "",
    debug_dir: str | Path | None = None,
) -> RunBus:
    """Create a RunBus and record the debug_dir → run_id mapping."""
    bus = global_bus().create(run_id, goal=goal, created_at=created_at)
    if debug_dir is not None:
        root = str(Path(debug_dir).resolve())
        with _lock:
            _dir_to_run[root] = run_id
    return bus


def get_run(run_id: str) -> RunBus | None:
    return global_bus().get(run_id)


def run_id_for_trace(trace_dir: str | Path | None) -> str | None:
    """Resolve the run_id for a llm.py trace_dir path.

    llm.py passes trace_dir values like::

        <output_dir>/debug/planner/<invocation>/llm
        <output_dir>/debug/task-builder/<invocation>/llm
        <output_dir>/debug/runner/<target>/<item>/

    We walk up from the given path until we find a registered debug root.
    """
    if trace_dir is None:
        return None
    path = Path(trace_dir).resolve()
    with _lock:
        for candidate in [path, *path.parents]:
            run_id = _dir_to_run.get(str(candidate))
            if run_id:
                return run_id
    return None


_STAGE_SEGMENTS = {
    "planner": "planner",
    "task-builder": "construction",
    "construction": "construction",
    "qc": "qc",
    "research": "research",
    "runner": "runner",
    "loop3": "loop3",
    "judge": "runner",
    "human-review": "review",
    "environment": "construction",
    "synthesis": "research",
}


def stage_for_trace(trace_dir: str | Path | None) -> str:
    """Infer the pipeline stage label from the trace_dir path segments."""
    if trace_dir is None:
        return "unknown"
    parts = [p.lower() for p in Path(trace_dir).parts]
    for part in reversed(parts):
        label = _STAGE_SEGMENTS.get(part)
        if label:
            return label
        for key, val in _STAGE_SEGMENTS.items():
            if key in part:
                return val
    return "unknown"
