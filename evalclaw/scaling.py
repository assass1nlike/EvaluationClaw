"""Scale-budget and simple-equivalent workload helpers."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .types import BenchmarkItem, ScaleBudget, TaskType

SCALE_BUDGET_SIMPLE_EQUIVALENTS: dict[ScaleBudget, int] = {
    ScaleBudget.low: 100,
    ScaleBudget.mid: 500,
    ScaleBudget.high: 1000,
    ScaleBudget.large: 5000,
    ScaleBudget.xlarge: 20000,
}

LARGE_SCALE_BUDGETS = {ScaleBudget.large, ScaleBudget.xlarge}

TASK_TYPE_SIMPLE_EQUIVALENT_WEIGHTS: dict[TaskType, float] = {
    TaskType.yes_no: 1.0,
    TaskType.multiple_choice: 1.0,
    TaskType.short_answer: 1.0,
    TaskType.open_generation: 2.0,
    TaskType.code_execution: 3.0,
    TaskType.pairwise_preference: 3.0,
    TaskType.multi_turn: 5.0,
    TaskType.agent_interaction: 8.0,
}


def scale_budget_target_workload(scale_budget: ScaleBudget) -> int:
    return SCALE_BUDGET_SIMPLE_EQUIVALENTS.get(scale_budget, SCALE_BUDGET_SIMPLE_EQUIVALENTS[ScaleBudget.mid])


def is_large_scale_budget(scale_budget: ScaleBudget) -> bool:
    return scale_budget in LARGE_SCALE_BUDGETS


def task_type_workload_weight(task_type: TaskType) -> float:
    return TASK_TYPE_SIMPLE_EQUIVALENT_WEIGHTS.get(task_type, 2.0)


def _metadata_dict(item: BenchmarkItem, key: str) -> dict[str, Any]:
    value = item.metadata.get(key) if isinstance(item.metadata, dict) else None
    return value if isinstance(value, dict) else {}


def item_workload_weight(item: BenchmarkItem) -> float:
    weight = task_type_workload_weight(item.task_type)
    agent_env = _metadata_dict(item, "agent_env")
    env_type = str(agent_env.get("type") or "").lower()
    if env_type == "code_sandbox":
        weight = max(weight, 8.0)
    elif env_type == "docker_workspace":
        weight = max(weight, 15.0)

    task_agent = _metadata_dict(item, "task_agent")
    execution = task_agent.get("execution") if isinstance(task_agent.get("execution"), dict) else {}
    if isinstance(execution, dict):
        task_env = execution.get("agent_env") if isinstance(execution.get("agent_env"), dict) else {}
        env_type = str(execution.get("environment_type") or task_env.get("type") or "").lower()
        if env_type == "code_sandbox":
            weight = max(weight, 8.0)
        elif env_type == "docker_workspace":
            weight = max(weight, 15.0)

    swebench = item.metadata.get("swebench") if isinstance(item.metadata, dict) else None
    source_uri = (item.source.uri or "").lower() if item.source else ""
    tags = {tag.lower() for tag in item.tags}
    if isinstance(swebench, dict) or swebench is True or "swebench" in tags or source_uri.startswith("swebench:"):
        weight = max(weight, 30.0)
    return weight


def simple_equivalent_workload(items: Iterable[BenchmarkItem]) -> float:
    return sum(item_workload_weight(item) for item in items)
