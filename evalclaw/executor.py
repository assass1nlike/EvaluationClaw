"""Compatibility wrapper for the old Executor name.

New code should import :mod:`evalclaw.planner`.
"""
from __future__ import annotations

from typing import Optional

from .planner import plan_eval_spec
from .types import BenchmarkConfig, EvalDimension


def run_executor(
    goal: str,
    config: BenchmarkConfig,
    *,
    feedback: Optional[str] = None,
    previous_dimensions: Optional[list[EvalDimension]] = None,
) -> tuple[str, list[EvalDimension]]:
    """Return planner notes and dimensions for legacy callers."""
    previous_spec = None
    if previous_dimensions:
        from .types import EvalSpec

        previous_spec = EvalSpec(objective=goal, dimensions=previous_dimensions)
    spec = plan_eval_spec(goal, config, feedback=feedback, previous_spec=previous_spec)
    analysis = spec.planner_notes or spec.critique.notes
    return analysis, spec.dimensions
