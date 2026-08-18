"""Shared test helpers for building configured BenchmarkConfig instances."""
from __future__ import annotations

from evalclaw.types import TargetModelConfig


def dummy_config_kwargs() -> dict:
    """Return per-role dummy keys so every orchestration role reports configured.

    Tests that previously used ``orchestrator_api_key="dummy"`` to make every
    role configured through the catch-all fallback now spread the same key to
    each role explicitly, matching the no-orchestrator model where roles must
    be configured individually. A single dummy task model is exposed so runner
    scoring and dialogue-simulator paths stay exercised.
    """
    return {
        "planner_api_key": "dummy",
        "task_builder_api_key": "dummy",
        "qc_api_key": "dummy",
        "research_api_key": "dummy",
        "loop3_api_key": "dummy",
        "task_models": [
            TargetModelConfig(provider="openai_compatible", model="dummy-task", api_key="dummy")
        ],
    }
