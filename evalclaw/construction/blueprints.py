"""Generic local Blueprint fallback used when no Planner model is configured."""
from __future__ import annotations

from ..types import EvalDimension, TaskBlueprint, TaskDesign, TaskType


def _default_blueprint_for_dimension(dimension: EvalDimension) -> TaskBlueprint:
    """Create one conservative work package for offline/local smoke tests."""
    task_type = (dimension.task_types or [TaskType.generation])[0]
    count = max(1, int(dimension.target_item_count or 1))
    design = TaskDesign(
        id=f"{dimension.id}_{task_type.value}_tasks",
        task_type=task_type,
        task_count=count,
        challenge_effort=dimension.challenge_effort,
        content_design={
            "purpose": dimension.measurement_target or dimension.description,
            "description": dimension.description,
            "coverage_requirements": list(dimension.item_requirements),
            "variation_requirements": ["Make every generated task materially distinct."],
            "exclusions": [dimension.boundary] if dimension.boundary else [],
        },
        scoring_contract={
            "components": [
                {
                    "method": "task-type-appropriate deterministic or rubric scoring",
                    "criteria": ["Measure the dimension directly."],
                }
            ]
        },
        source_plan={
            "strategy": "source_backed" if dimension.needs_research else "self_contained",
            "search_queries": list(dimension.research_queries),
        },
        construction_requirements=list(dimension.item_requirements),
        metadata={"planning_source": "local_fallback"},
    )
    return TaskBlueprint(
        id=f"{dimension.id}_blueprint",
        dimension_id=dimension.id,
        title=dimension.name,
        task_design_ids=[design.id],
        task_designs=[design],
        grouping_rationale="The fallback contains one coherent task group.",
        workload_reason="The group is handled by one local Builder job.",
        metadata={"planning_source": "local_fallback"},
    )


__all__ = ["_default_blueprint_for_dimension"]
