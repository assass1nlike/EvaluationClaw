from __future__ import annotations

from typing import Any

from evalclaw.types import (
    AgentEnvironmentType,
    BenchmarkPlan,
    BenchmarkPlanAudit,
    BenchmarkPlanDimension,
    ChallengeEffort,
    EvalSpec,
    TaskBlueprint,
    TaskDesign,
    TaskType,
)


def make_task_design(
    design_id: str,
    task_type: TaskType,
    *,
    count: int = 1,
    content: str = "Test the requested capability.",
    challenge_effort: ChallengeEffort = ChallengeEffort.E3,
    environment_type: AgentEnvironmentType | None = None,
    source_plan: dict[str, Any] | None = None,
    construction_requirements: list[str] | None = None,
    allowed_tools: list[str] | None = None,
) -> TaskDesign:
    interaction_requirements: dict[str, Any] = {}
    if allowed_tools:
        interaction_requirements["allowed_action_or_tool_categories"] = allowed_tools
    if task_type == TaskType.multi_turn:
        interaction_requirements["followup_mode"] = "scripted"
    return TaskDesign(
        id=design_id,
        task_type=task_type,
        task_count=count,
        challenge_effort=challenge_effort,
        content_design={"purpose": content, "description": content},
        environment_requirements=(
            {"category": environment_type.value, "purpose": "Execute the task."}
            if environment_type is not None
            else {}
        ),
        interaction_requirements=interaction_requirements,
        scoring_contract={
            "components": [{"method": "task-appropriate", "criteria": ["Correctness"]}]
        },
        source_plan=source_plan or {"strategy": "self_contained"},
        construction_requirements=construction_requirements or [],
    )


def make_blueprint(
    blueprint_id: str,
    dimension_id: str,
    title: str,
    *,
    task_type: TaskType | None = None,
    count: int = 1,
    content: str = "Test the requested capability.",
    challenge_effort: ChallengeEffort = ChallengeEffort.E3,
    environment_type: AgentEnvironmentType | None = None,
    source_plan: dict[str, Any] | None = None,
    construction_requirements: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    task_designs: list[TaskDesign] | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskBlueprint:
    designs = task_designs or [
        make_task_design(
            f"{blueprint_id}_design",
            task_type or TaskType.generation,
            count=count,
            content=content,
            challenge_effort=challenge_effort,
            environment_type=environment_type,
            source_plan=source_plan,
            construction_requirements=construction_requirements,
            allowed_tools=allowed_tools,
        )
    ]
    return TaskBlueprint(
        id=blueprint_id,
        dimension_id=dimension_id,
        title=title,
        task_design_ids=[design.id for design in designs],
        task_designs=designs,
        grouping_rationale="These task groups form one coherent Builder job.",
        workload_reason="One Builder call can implement this workload at sufficient quality.",
        metadata=metadata or {},
    )


def make_plan(spec: EvalSpec, blueprints: list[TaskBlueprint]) -> BenchmarkPlan:
    dimensions: list[BenchmarkPlanDimension] = []
    for dimension in spec.dimensions:
        dimension_blueprints = [
            blueprint for blueprint in blueprints if blueprint.dimension_id == dimension.id
        ]
        dimensions.append(
            BenchmarkPlanDimension(
                id=dimension.id,
                name=dimension.name,
                measurement_target=dimension.measurement_target or dimension.description,
                boundary=dimension.boundary or "Exclude unrelated capabilities.",
                approach=dimension.approach,
                task_designs=[
                    design
                    for blueprint in dimension_blueprints
                    for design in blueprint.task_designs
                ],
            )
        )
    return BenchmarkPlan(
        id=spec.id,
        objective=spec.objective,
        constraints=spec.constraints,
        planner_notes=spec.planner_notes,
        dimensions=dimensions,
        subjects=spec.subjects,
        scale_budget=spec.scale_budget,
        audit=BenchmarkPlanAudit(passed=True),
    )
