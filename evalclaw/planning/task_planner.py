"""Skill-driven benchmark content and Blueprint planning."""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from typing import Any

from ..models.llm import call_llm, extract_json
from ..models.roles import role_model_settings
from ..prompts.planner import BENCHMARK_PLANNER_SYSTEM_PROMPT
from ..protocols.multimodal import text_requests_multimodal
from ..protocols.science import text_requests_science
from ..research.deep_research import compact_brief_context
from ..types import (
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkPlan,
    BenchmarkPlanAudit,
    BenchmarkPlanDimension,
    EvalDimension,
    EvalSpec,
    Message,
    Metric,
    TaskBlueprint,
    TaskDesign,
    TaskType,
    TaskTypeAllocation,
)
from .planner import _fallback_outline, _safe_scale_budget, _scale_budget_guidance
from .skill_loader import benchmark_planner_system_prompt


def _unique_strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _instruction_resource(
    goal: str,
    config: BenchmarkConfig,
    *,
    feedback: str | None = None,
    previous_plan: BenchmarkPlan | None = None,
) -> str:
    scale_budget = _safe_scale_budget(config.scale_budget)
    constraints: dict[str, object] = {
        "target_models": [
            {"id": target.id, "provider": target.provider, "model": target.model}
            for target in config.targets
        ],
        "target_models_are_optional": True,
        "scale_budget": scale_budget.value,
        "scale_budget_guidance": _scale_budget_guidance(scale_budget),
        "default_questions_per_dimension_when_no_count_is_requested": (
            config.questions_per_dimension
        ),
        "count_policy": (
            "An explicit total task count in the user request overrides all defaults."
        ),
        "available_task_types": [task_type.value for task_type in TaskType],
        "available_metrics": [metric.value for metric in Metric],
        "available_environment_types": [environment.value for environment in AgentEnvironmentType],
        "reference_model": (
            config.reference_model.model_dump(mode="json") if config.reference_model else None
        ),
    }
    if config.reference_model is not None:
        constraints["pairwise_preference_policy"] = (
            "Use pairwise_preference only where target-versus-reference comparison directly "
            "measures the requested capability."
        )
    if text_requests_multimodal(goal):
        constraints["multimodal_policy"] = (
            "The request explicitly asks for multimodal evaluation. Include only modalities "
            "needed to measure the requested capability."
        )
    if text_requests_science(goal):
        constraints["science_policy"] = (
            "Make scientific evidence, assumptions, units, and scoring oracles explicit where relevant."
        )

    sections = [
        "# User Evaluation Request",
        "",
        goal.strip(),
        "",
        "# Framework-Supplied Task-Design Constraints",
        "",
        json.dumps(constraints, ensure_ascii=False, indent=2),
    ]
    if feedback:
        sections.extend(["", "# User Feedback on the Previous Plan", "", feedback.strip()])
    if previous_plan is not None:
        sections.extend(
            [
                "",
                "# Previous Plan to Revise",
                "",
                json.dumps({"plan": previous_plan.model_dump(mode="json")}, ensure_ascii=False, indent=2),
            ]
        )
    return "\n".join(sections).strip()


def _planner_resources(instruction: str, config: BenchmarkConfig) -> str:
    files = [
        '<FILE path="resources/instruction.md">\n'
        + instruction
        + "\n</FILE>"
    ]
    if config.research_brief is not None:
        files.append(
            '<FILE path="resources/deepresearch/brief.json">\n'
            + json.dumps(
                compact_brief_context(config.research_brief),
                ensure_ascii=False,
                indent=2,
            )
            + "\n</FILE>"
        )
    else:
        files.append('<DIRECTORY path="resources/deepresearch" empty="true" />')
    return (
        "The following read-only Planner resources are available by path.\n\n"
        "<PLANNER_RESOURCES>\n"
        + "\n\n".join(files)
        + "\n</PLANNER_RESOURCES>"
    )


def _environment_for_dimension(
    dimension: EvalDimension,
    task_type: TaskType,
) -> dict[str, Any]:
    if task_type not in {TaskType.agent_interaction, TaskType.multi_turn}:
        return {}
    text = " ".join(
        [dimension.name, dimension.description, dimension.approach, *dimension.item_requirements]
    ).lower()
    if task_type == TaskType.multi_turn:
        category = AgentEnvironmentType.dialogue.value
    elif any(token in text for token in ("browser", "desktop", "gui", "spreadsheet")):
        category = AgentEnvironmentType.gui_desktop.value
    elif any(token in text for token in ("docker", "container", "shell", "pipeline")):
        category = AgentEnvironmentType.docker_workspace.value
    elif any(token in text for token in ("code", "repository", "tests")):
        category = AgentEnvironmentType.code_sandbox.value
    else:
        category = AgentEnvironmentType.workspace.value
    return {
        "category": category,
        "purpose": "Provide the execution context required by this interactive task group.",
    }


def _allocations_for_dimension(dimension: EvalDimension) -> list[TaskTypeAllocation]:
    count = max(1, int(dimension.target_item_count or 1))
    if dimension.task_type_allocation:
        return dimension.task_type_allocation
    task_types = list(dict.fromkeys(dimension.task_types or [TaskType.open_generation]))[:count]
    quotient, remainder = divmod(count, len(task_types))
    return [
        TaskTypeAllocation(
            task_type=task_type,
            count=quotient + (1 if index < remainder else 0),
        )
        for index, task_type in enumerate(task_types)
    ]


def _local_plan_from_spec(spec: EvalSpec) -> BenchmarkPlan:
    dimensions: list[BenchmarkPlanDimension] = []
    for dimension in spec.dimensions:
        task_designs: list[TaskDesign] = []
        blueprints: list[TaskBlueprint] = []
        for index, allocation in enumerate(_allocations_for_dimension(dimension), 1):
            environment = _environment_for_dimension(dimension, allocation.task_type)
            design_id = f"{dimension.id}_{allocation.task_type.value}_{index}"
            task_designs.append(
                TaskDesign(
                    id=design_id,
                    task_type=allocation.task_type,
                    task_count=allocation.count,
                    challenge_effort=dimension.challenge_effort,
                    content_design={
                        "purpose": dimension.measurement_target or dimension.description,
                        "description": dimension.description,
                        "coverage_requirements": list(dimension.item_requirements),
                        "variation_requirements": [
                            "Make every concrete task materially distinct."
                        ],
                        "exclusions": [dimension.boundary] if dimension.boundary else [],
                    },
                    environment_requirements=environment,
                    scoring_contract={
                        "components": [
                            {
                                "method": "task-type-appropriate deterministic or rubric scoring",
                                "criteria": ["Measure the requested capability directly."],
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
            )
            blueprints.append(
                TaskBlueprint(
                    id=f"{design_id}_blueprint",
                    dimension_id=dimension.id,
                    title=f"{dimension.name} — {allocation.task_type.value}",
                    task_design_ids=[design_id],
                    grouping_rationale="This fallback work package contains one coherent task group.",
                    workload_reason="The task group is handled by one local Builder job.",
                    metadata={"planning_source": "local_fallback"},
                )
            )
        dimensions.append(
            BenchmarkPlanDimension(
                id=dimension.id,
                name=dimension.name,
                measurement_target=dimension.measurement_target or dimension.description,
                boundary=dimension.boundary or "Exclude capabilities outside this dimension.",
                approach=dimension.approach,
                content_requirements=list(dimension.item_requirements),
                exclusions=[dimension.boundary] if dimension.boundary else [],
                task_designs=task_designs,
                blueprints=blueprints,
            )
        )
    return BenchmarkPlan(
        id=spec.id,
        objective=spec.objective,
        metrics=spec.metrics,
        constraints=spec.constraints,
        planner_notes=spec.planner_notes,
        dimensions=dimensions,
        subjects=spec.subjects,
        scale_budget=spec.scale_budget,
        audit=BenchmarkPlanAudit(passed=True),
    )


def _audit_plan(plan: BenchmarkPlan) -> list[str]:
    issues: list[str] = []
    if not plan.dimensions:
        return ["plan.dimensions must contain at least one dimension."]
    dimension_ids = [dimension.id for dimension in plan.dimensions]
    if len(dimension_ids) != len(set(dimension_ids)):
        issues.append("Dimension ids must be unique.")

    all_design_ids: set[str] = set()
    all_blueprint_ids: set[str] = set()
    allowed_task_types = set(TaskType)
    allowed_environments = {environment.value for environment in AgentEnvironmentType}
    aliases = {
        "code sandbox": "code_sandbox",
        "container": "docker_workspace",
        "browser": "gui_desktop",
        "desktop": "gui_desktop",
    }
    for dimension in plan.dimensions:
        prefix = dimension.id or "unnamed_dimension"
        if not all(
            [dimension.id, dimension.name, dimension.measurement_target, dimension.boundary, dimension.approach]
        ):
            issues.append(f"{prefix}: id, name, measurement_target, boundary, and approach are required.")
        if not dimension.task_designs:
            issues.append(f"{prefix}: task_designs must not be empty.")
        local_design_ids = [design.id for design in dimension.task_designs]
        if len(local_design_ids) != len(set(local_design_ids)):
            issues.append(f"{prefix}: TaskDesign ids must be unique within the dimension.")
        repeated = all_design_ids.intersection(local_design_ids)
        if repeated:
            issues.append(f"{prefix}: TaskDesign ids must be globally unique: {sorted(repeated)}.")
        all_design_ids.update(local_design_ids)
        design_by_id = {design.id: design for design in dimension.task_designs}
        for design in dimension.task_designs:
            design_prefix = f"{prefix}/{design.id or 'unnamed_task_design'}"
            if design.task_type not in allowed_task_types:
                issues.append(f"{design_prefix}: unsupported task_type {design.task_type.value}.")
            if not design.description:
                issues.append(
                    f"{design_prefix}: content_design must include a concrete purpose or description."
                )
            category = str(design.environment_requirements.get("category") or "").strip().lower()
            normalized_category = aliases.get(category, category)
            if design.environment_requirements and not category:
                issues.append(
                    f"{design_prefix}: non-empty environment_requirements must define category."
                )
            if category and normalized_category not in allowed_environments:
                issues.append(
                    f"{design_prefix}: environment category {category!r} is not available at runtime."
                )
            if (
                design.task_type in {TaskType.agent_interaction, TaskType.multi_turn}
                and not category
            ):
                issues.append(f"{design_prefix}: interactive tasks require environment_requirements.")
            for url in _unique_strings(design.source_plan.get("suggested_urls")):
                if not url.lower().startswith(("https://", "http://")):
                    issues.append(f"{design_prefix}: suggested URL is invalid: {url!r}.")

        references: list[str] = []
        for blueprint in dimension.blueprints:
            blueprint_prefix = f"{prefix}/{blueprint.id or 'unnamed_blueprint'}"
            if blueprint.dimension_id or blueprint.task_designs:
                issues.append(
                    f"{blueprint_prefix}: Planner Blueprints must reference TaskDesign ids instead "
                    "of duplicating resolved task content."
                )
            if blueprint.id in all_blueprint_ids:
                issues.append(f"{blueprint_prefix}: Blueprint ids must be globally unique.")
            all_blueprint_ids.add(blueprint.id)
            if not all([blueprint.id, blueprint.title, blueprint.grouping_rationale, blueprint.workload_reason]):
                issues.append(
                    f"{blueprint_prefix}: id, title, grouping_rationale, and workload_reason are required."
                )
            if not blueprint.task_design_ids:
                issues.append(f"{blueprint_prefix}: task_design_ids must not be empty.")
            if len(blueprint.task_design_ids) != len(set(blueprint.task_design_ids)):
                issues.append(f"{blueprint_prefix}: task_design_ids contains duplicates.")
            unknown = set(blueprint.task_design_ids) - set(design_by_id)
            if unknown:
                issues.append(
                    f"{blueprint_prefix}: references TaskDesigns outside this dimension: {sorted(unknown)}."
                )
            references.extend(blueprint.task_design_ids)
        reference_counts = Counter(references)
        missing = [design_id for design_id in local_design_ids if reference_counts[design_id] == 0]
        duplicated = [design_id for design_id in local_design_ids if reference_counts[design_id] > 1]
        if missing:
            issues.append(f"{prefix}: TaskDesigns missing from Blueprints: {missing}.")
        if duplicated:
            issues.append(f"{prefix}: TaskDesigns assigned to multiple Blueprints: {duplicated}.")

    if not sum(design.task_count for dim in plan.dimensions for design in dim.task_designs):
        issues.append("The complete plan must contain at least one task.")
    return issues


def _parse_plan_response(
    data: object,
    config: BenchmarkConfig,
) -> tuple[BenchmarkPlan, list[str]]:
    if not isinstance(data, dict) or not isinstance(data.get("plan"), dict):
        raise ValueError("Planner response must be an object with a plan object at its root.")
    plan = BenchmarkPlan.model_validate(data["plan"]).model_copy(
        update={
            "subjects": [target.id for target in config.targets],
            "scale_budget": _safe_scale_budget(config.scale_budget),
        }
    )
    issues = _audit_plan(plan)
    return plan, issues


def _run_planner(
    instruction: str,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] | None,
) -> BenchmarkPlan:
    settings = role_model_settings(config, "planner")
    if not settings.configured:
        raise RuntimeError("Planner model is not configured.")
    system = benchmark_planner_system_prompt(BENCHMARK_PLANNER_SYSTEM_PROMPT)
    base_resources = _planner_resources(instruction, config)
    errors: list[str] = []
    previous_response: object | None = None
    max_attempts = max(1, config.max_planner_iterations)
    for attempt in range(1, max_attempts + 1):
        user_content = base_resources
        if errors:
            user_content += (
                "\n\n<FILE path=\"resources/repair.json\">\n"
                + json.dumps(
                    {
                        "attempt": attempt,
                        "issues": errors,
                        "previous_response": previous_response,
                        "instruction": (
                            "Return the complete planning JSON file again. Fix every listed issue "
                            "while changing sound parts as little as possible."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n</FILE>"
            )
        if log:
            log(f"  Planner: designing TaskDesigns and Blueprints ({attempt}/{max_attempts}).")
        try:
            raw = call_llm(
                [Message(role="user", content=user_content)],
                system=system,
                **settings.call_kwargs(),
                backend=config.llm_backend,
                max_tokens=16384,
            )
            previous_response = extract_json(raw)
            plan, errors = _parse_plan_response(previous_response, config)
        except Exception as exc:
            errors = [f"{type(exc).__name__}: {exc}"]
            if log:
                log(f"  Planner: attempt {attempt} failed: {errors[0][:500]}")
            continue
        if errors and log:
            log(
                f"  Planner: attempt {attempt} failed deterministic audit with "
                f"{len(errors)} issue(s)."
            )
            for issue in errors[:8]:
                log(f"    - {issue[:500]}")
        if not errors:
            completed = plan.model_copy(update={"audit": BenchmarkPlanAudit(passed=True)})
            if log:
                log(
                    f"  Planner: completed {len(completed.dimensions)} dimension(s), "
                    f"{len(completed.blueprints)} Blueprint(s), and "
                    f"{sum(blueprint.planned_task_count for blueprint in completed.blueprints)} task(s)."
                )
            return completed
    raise RuntimeError(
        "Planner could not produce a valid benchmark plan: " + "; ".join(errors[:12])
    )


def plan_benchmark(
    goal: str,
    config: BenchmarkConfig,
    *,
    feedback: str | None = None,
    previous_plan: BenchmarkPlan | None = None,
    log: Callable[[str], None] | None = None,
) -> BenchmarkPlan:
    """Turn one natural-language request into all TaskDesigns and Blueprints."""
    instruction = _instruction_resource(
        goal,
        config,
        feedback=feedback,
        previous_plan=previous_plan,
    )
    if role_model_settings(config, "planner").configured:
        return _run_planner(instruction, config, log=log)
    fallback = _fallback_outline(
        goal,
        [target.id for target in config.targets] or None,
        _safe_scale_budget(config.scale_budget),
    )
    return _local_plan_from_spec(fallback)


def plan_from_spec(
    spec: EvalSpec,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] | None = None,
) -> BenchmarkPlan:
    """Re-plan an explicitly supplied benchmark outline through the same Skill path."""
    if not role_model_settings(config, "planner").configured:
        return _local_plan_from_spec(spec)
    instruction = (
        "Design the complete benchmark plan represented by the following existing outline. "
        "Preserve its objective, dimensions, task counts, task types, metrics, and constraints, "
        "while supplying the TaskDesign detail and Blueprint allocation required by the Planner Skill.\n\n"
        + json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    return _run_planner(_instruction_resource(instruction, config), config, log=log)


def plan_blueprints_for_spec(
    spec: EvalSpec,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] | None = None,
) -> list[TaskBlueprint]:
    return plan_from_spec(spec, config, log=log).blueprints


__all__ = ["plan_benchmark", "plan_blueprints_for_spec", "plan_from_spec"]
