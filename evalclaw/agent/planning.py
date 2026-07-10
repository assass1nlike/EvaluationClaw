"""Agent benchmark dimension and blueprint planning."""
from __future__ import annotations

import json

from ..core.scaling import scale_budget_target_workload
from ..models.llm import call_llm, extract_json
from ..prompts.agent_benchmark import AGENT_BENCHMARK_PLANNER_PROMPT
from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_GENERATION_GUIDANCE,
    AGENT_TASK_PACKAGE_SCHEMA,
)
from ..protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE, TASK_AGENT_SCHEMA
from ..types import (
    AgentEnvironmentType,
    AgentTaskBlueprint,
    AgentTaskFamily,
    BenchmarkConfig,
    EvalSpec,
    Message,
    TaskType,
)
from .blueprints import _default_blueprint_for_dimension
from .common import (
    _safe_environment_type,
    _safe_optional_int,
    _safe_scale_budget,
    _safe_task_family,
    _slug,
)
from .dimensions import _fallback_dimensions, _parse_dimensions
from .goal_detection import _goal_mentions_code


def plan_agent_benchmark(goal: str, config: BenchmarkConfig) -> tuple[EvalSpec, list[AgentTaskBlueprint]]:
    scale_budget = _safe_scale_budget(config.scale_budget)
    builder_mode = str(config.agent_task_builder or "llm").lower()
    strict_llm = builder_mode == "llm"
    if config.orchestrator_api_key:
        payload = {
            "goal": goal,
            "scale_budget": scale_budget.value,
            "scale_budget_workload": scale_budget_target_workload(scale_budget),
            "reference_model": config.reference_model.model_dump(mode="json") if config.reference_model else None,
            "benchmark_mode": config.benchmark_mode.value,
            "task_agent_schema": TASK_AGENT_SCHEMA,
            "task_agent_generation_guidance": TASK_AGENT_GENERATION_GUIDANCE,
            "agent_task_package_schema": AGENT_TASK_PACKAGE_SCHEMA,
            "agent_task_package_generation_guidance": AGENT_TASK_PACKAGE_GENERATION_GUIDANCE,
        }
        try:
            raw = call_llm(
                [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
                system=AGENT_BENCHMARK_PLANNER_PROMPT,
                model=config.orchestrator_model,
                api_key=config.orchestrator_api_key,
                base_url=config.orchestrator_base_url,
                backend=config.llm_backend,
                max_tokens=8192,
            )
            parsed = extract_json(raw)
        except Exception as exc:
            if strict_llm:
                raise RuntimeError(
                    "Agent benchmark planner LLM generation failed "
                    f"using model '{config.orchestrator_model}': {type(exc).__name__}: {exc}. "
                    "Set BenchmarkConfig.agent_task_builder='local' only for offline smoke tests, "
                    "or 'auto' if fallback planning is intentionally acceptable."
                ) from exc
            parsed = None
        if isinstance(parsed, dict):
            spec = _parse_dimensions(parsed, goal, scale_budget)
            blueprints: list[AgentTaskBlueprint] = []
            for idx, raw_blueprint in enumerate(parsed.get("agent_task_blueprints", []) or [], 1):
                if not isinstance(raw_blueprint, dict):
                    continue
                blueprints.append(
                    AgentTaskBlueprint(
                        id=str(raw_blueprint.get("id") or f"blueprint_{idx}"),
                        dimension_id=str(raw_blueprint.get("dimension_id") or spec.dimensions[0].id),
                        title=str(raw_blueprint.get("title") or f"Blueprint {idx}"),
                        description=str(raw_blueprint.get("description") or ""),
                        task_family=_safe_task_family(raw_blueprint.get("task_family")),
                        environment_type=_safe_environment_type(raw_blueprint.get("environment_type")),
                        expected_task_count=_safe_optional_int(raw_blueprint.get("expected_task_count")) or 1,
                        resource_queries=[str(q) for q in raw_blueprint.get("resource_queries", []) if q],
                        source_strategy=str(raw_blueprint.get("source_strategy") or ""),
                        tool_requirements=[str(x) for x in raw_blueprint.get("tool_requirements", []) if x],
                        construction_requirements=[str(x) for x in raw_blueprint.get("construction_requirements", []) if x],
                        scoring_strategy=str(raw_blueprint.get("scoring_strategy") or ""),
                    )
                )
            blueprints_by_dimension = {blueprint.dimension_id for blueprint in blueprints}
            for dimension in spec.dimensions:
                if dimension.id not in blueprints_by_dimension:
                    blueprints.append(_default_blueprint_for_dimension(dimension))
            if blueprints:
                return spec, blueprints
        if strict_llm:
            raise RuntimeError(
                "Agent benchmark planner LLM generation failed "
                f"using model '{config.orchestrator_model}': response did not contain a usable "
                "agent benchmark plan. Set BenchmarkConfig.agent_task_builder='local' only for "
                "offline smoke tests, or 'auto' if fallback planning is intentionally acceptable."
            )
    elif strict_llm:
        raise RuntimeError(
            "Agent benchmark planner requires orchestrator_api_key in default 'llm' mode. "
            "Set BenchmarkConfig.agent_task_builder='local' only for offline smoke tests, "
            "or 'auto' if fallback planning is intentionally acceptable."
        )
    spec = EvalSpec(
        id=_slug(goal),
        objective=goal,
        subjects=["user_supplied_targets"],
        task_types=[TaskType.agent_interaction, TaskType.multi_turn],
        dimensions=_fallback_dimensions(goal),
        scale_budget=scale_budget,
        scale=scale_budget_target_workload(scale_budget),
        metrics=[],
        planner_notes="Local fallback agent benchmark planner output.",
    )
    blueprints = [_default_blueprint_for_dimension(dimension) for dimension in spec.dimensions]
    if _goal_mentions_code(goal):
        blueprints = [
            (
                blueprint.model_copy(
                    update={
                        "id": f"{blueprint.dimension_id}_code_blueprint",
                        "title": f"{blueprint.title} code repair",
                        "task_family": AgentTaskFamily.code_repair,
                        "environment_type": AgentEnvironmentType.code_sandbox,
                        "tool_requirements": ["read_file", "write_file", "run_tests"],
                        "construction_requirements": [
                            "Include complete visible source files and hidden tests.",
                            "Require the agent to inspect failures and revise code.",
                        ],
                        "scoring_strategy": "Deterministic hidden tests with partial credit for running tests.",
                    }
                )
                if blueprint.dimension_id == "agent_recovery"
                else blueprint
            )
            for blueprint in blueprints
        ]
    return spec, blueprints
