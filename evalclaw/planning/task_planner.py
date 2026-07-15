"""Create one EvalSpec and one common set of task blueprints."""
from __future__ import annotations

from collections.abc import Callable

from ..construction.blueprints import _default_blueprint_for_dimension
from ..models.roles import role_model_settings
from ..types import BenchmarkConfig, EvalSpec, TaskBlueprint, TaskType
from .planner import plan_eval_spec


def plan_benchmark(
    goal: str,
    config: BenchmarkConfig,
    *,
    feedback: str | None = None,
    previous_spec: EvalSpec | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[EvalSpec, list[TaskBlueprint]]:
    """Plan all task types through one blueprint model and construction route."""
    if log:
        log(f"  Planner: requesting one benchmark plan from {role_model_settings(config, 'planner').model}.")
    spec = plan_eval_spec(
        goal,
        config,
        feedback=feedback,
        previous_spec=previous_spec,
    )
    blueprints = blueprints_for_spec(spec, config)
    if log:
        environment_count = sum(blueprint.environment_type is not None for blueprint in blueprints)
        log(
            f"  Planner: {len(spec.dimensions)} dimension(s), {len(blueprints)} blueprint(s), "
            f"{sum(blueprint.expected_task_count for blueprint in blueprints)} task slot(s), "
            f"{environment_count} with execution environments."
        )
    return spec, blueprints


def blueprints_for_spec(
    spec: EvalSpec,
    config: BenchmarkConfig,
) -> list[TaskBlueprint]:
    """Convert an existing EvalSpec into homogeneous general task blueprints."""
    blueprints: list[TaskBlueprint] = []
    for dimension in spec.dimensions:
        task_types = list(dict.fromkeys(
            dimension.task_types or spec.task_types or [TaskType.open_generation]
        ))
        total = max(1, int(dimension.target_item_count or config.questions_per_dimension))
        represented_types = task_types[:total]
        quotient, remainder = divmod(total, len(represented_types))
        for index, task_type in enumerate(represented_types):
            task_count = quotient + (1 if index < remainder else 0)
            scoped_dimension = dimension.model_copy(
                update={"task_types": [task_type], "target_item_count": task_count}
            )
            blueprint = _default_blueprint_for_dimension(scoped_dimension)
            if len(represented_types) > 1:
                blueprint = blueprint.model_copy(
                    update={
                        "id": f"{blueprint.id}_{task_type.value}",
                        "title": f"{blueprint.title} ({task_type.value})",
                    }
                )
            blueprints.append(
                blueprint.model_copy(
                    update={
                        "task_types": [task_type],
                        "expected_task_count": task_count,
                    }
                )
            )
    return blueprints


__all__ = ["blueprints_for_spec", "plan_benchmark"]
