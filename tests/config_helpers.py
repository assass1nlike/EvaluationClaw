"""Shared test helpers for building configured BenchmarkConfig instances."""
from __future__ import annotations

from evalclaw.types import TargetModelConfig


def dummy_config_kwargs() -> dict:
    """Return per-role dummy keys so every orchestration role reports configured.

    Tests that previously used ``orchestrator_api_key="dummy"`` to make every
    role configured through the catch-all fallback now spread the same key to
    each role explicitly, matching the no-orchestrator model where roles must
    be configured individually. Judge and task-agent roles expose a single dummy
    available model each so runner scoring paths stay exercised.
    """
    return {
        "planner_api_key": "dummy",
        "task_builder_api_key": "dummy",
        "qc_api_key": "dummy",
        "research_api_key": "dummy",
        "loop3_api_key": "dummy",
        "judge_models": [
            TargetModelConfig(provider="openai_compatible", model="dummy-judge", api_key="dummy")
        ],
        "task_agent_models": [
            TargetModelConfig(provider="openai_compatible", model="dummy-task-agent", api_key="dummy")
        ],
    }
