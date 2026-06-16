"""Agent benchmark planning and construction helpers."""
from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from typing import Any

from .generation.fallback import fallback_items
from .generator import _safe_difficulty as _item_safe_difficulty
from .generator import _safe_task_type as _item_safe_task_type
from .generator import _source_context
from .llm import call_llm, extract_json
from .prompts.agent_benchmark import AGENT_BENCHMARK_PLANNER_PROMPT, AGENT_TASK_BUILDER_PROMPT
from .protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE, TASK_AGENT_SCHEMA
from .scaling import scale_budget_target_workload
from .search import format_search_result, web_search
from .types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    AgentResource,
    AgentScoringSpec,
    AgentTask,
    AgentTaskBlueprint,
    AgentTaskFamily,
    AgentTaskSuite,
    BenchmarkBatch,
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    BenchmarkSource,
    Difficulty,
    EvalDimension,
    EvalSpec,
    Message,
    ScaleBudget,
    SourceKind,
    TaskType,
)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug[:48] or "agent_benchmark"


def _safe_scale_budget(value: object, fallback: ScaleBudget = ScaleBudget.mid) -> ScaleBudget:
    if isinstance(value, ScaleBudget):
        return value
    try:
        return ScaleBudget(str(value).lower())
    except ValueError:
        return fallback


def _safe_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_task_family(value: object, fallback: AgentTaskFamily = AgentTaskFamily.custom) -> AgentTaskFamily:
    try:
        return AgentTaskFamily(str(value))
    except ValueError:
        return fallback


def _safe_environment_type(
    value: object,
    fallback: AgentEnvironmentType = AgentEnvironmentType.workspace,
) -> AgentEnvironmentType:
    try:
        return AgentEnvironmentType(str(value))
    except ValueError:
        return fallback


def _parse_dimensions(data: list[dict[str, Any]] | dict[str, Any], goal: str, scale_budget: ScaleBudget) -> EvalSpec:
    if isinstance(data, dict):
        spec_data = data.get("spec", data)
        dims = spec_data.get("dimensions", []) if isinstance(spec_data.get("dimensions"), list) else []
        task_types = spec_data.get("task_types", ["agent_interaction"])
        objective = str(spec_data.get("objective") or goal)
        scale = int(spec_data.get("scale") or scale_budget_target_workload(scale_budget))
        critique = spec_data.get("critique") if isinstance(spec_data.get("critique"), dict) else {}
        dimensions: list[EvalDimension] = []
        for idx, raw in enumerate(dims, 1):
            if not isinstance(raw, dict):
                continue
            dim_id = str(raw.get("id") or f"dimension_{idx}")
            dimensions.append(
                EvalDimension(
                    id=dim_id,
                    name=str(raw.get("name") or dim_id),
                    description=str(raw.get("description") or ""),
                    approach=str(raw.get("approach") or ""),
                    weight=float(raw.get("weight", 1.0) or 1.0),
                    target_difficulty=_item_safe_difficulty(raw.get("target_difficulty"), Difficulty.L4),
                    needs_research=bool(raw.get("needs_research", False)),
                    research_queries=[str(q) for q in raw.get("research_queries", []) if q],
                    target_item_count=_safe_optional_int(raw.get("target_item_count")),
                    target_source_backed_count=max(0, _safe_optional_int(raw.get("target_source_backed_count")) or 0),
                    target_generated_count=_safe_optional_int(raw.get("target_generated_count")),
                    task_types=[_item_safe_task_type(x, TaskType.agent_interaction) for x in raw.get("task_types", [])]
                    if isinstance(raw.get("task_types"), list)
                    else [TaskType.agent_interaction],
                    item_requirements=[str(x) for x in raw.get("item_requirements", []) if x],
                )
            )
        return EvalSpec(
            id=str(spec_data.get("id") or _slug(goal)),
            objective=objective,
            subjects=[str(x) for x in spec_data.get("subjects", ["user_supplied_targets"])],
            task_types=[_item_safe_task_type(x, TaskType.agent_interaction) for x in task_types],
            dimensions=dimensions,
            scale_budget=_safe_scale_budget(spec_data.get("scale_budget"), scale_budget),
            scale=scale,
            metrics=[],
            constraints=[str(x) for x in spec_data.get("constraints", [])],
            planner_notes=str(spec_data.get("planner_notes", "")),
        )
    raise TypeError("Expected dict agent benchmark planner output.")


def _goal_mentions_code(goal: str) -> bool:
    text = goal.lower()
    return any(keyword in text for keyword in ("code", "repo", "repository", "debug", "repair", "test", "python", "program"))


def _fallback_dimensions(goal: str) -> list[EvalDimension]:
    return [
        EvalDimension(
            id="agent_tool_use",
            name="Tool use and action selection",
            description=f"Measure whether the agent can use tools correctly for: {goal}",
            approach="Create realistic action-observation tasks with clear tool affordances.",
            target_difficulty=Difficulty.L4,
            task_types=[TaskType.agent_interaction],
            item_requirements=[
                "Test valid tool use, state tracking, and recovery from invalid actions.",
                "Prefer executable environments over static prompts.",
            ],
        ),
        EvalDimension(
            id="agent_recovery",
            name="Recovery and iteration",
            description="Measure whether the agent can inspect failures and revise its strategy.",
            approach="Use environments where the first attempt often fails and revision is required.",
            target_difficulty=Difficulty.L4,
            task_types=[TaskType.agent_interaction],
            item_requirements=[
                "Require the agent to inspect feedback and adapt.",
                "Make hidden tests or environment feedback part of the oracle.",
            ],
        ),
        EvalDimension(
            id="agent_resource_grounding",
            name="Grounding in resources",
            description="Measure whether the agent can exploit real resources or structured task context.",
            approach="Use docs, repositories, or issue-like materials as the basis for tasks.",
            target_difficulty=Difficulty.L4,
            needs_research=True,
            task_types=[TaskType.agent_interaction, TaskType.multi_turn],
            item_requirements=[
                "Build tasks from supplied resources rather than synthetic trivia.",
                "Keep the oracle tied to the provided materials.",
            ],
        ),
    ]


def _default_blueprint_for_dimension(dimension: EvalDimension) -> AgentTaskBlueprint:
    identity = " ".join([dimension.id, dimension.name]).lower()
    full_text = " ".join([dimension.id, dimension.name, dimension.description, dimension.approach]).lower()
    if any(keyword in identity for keyword in ("code", "repo", "debug", "repair", "test", "python")):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_code_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} code repair",
            description=f"Executable code-repair tasks for {dimension.name}.",
            task_family=AgentTaskFamily.code_repair,
            environment_type=AgentEnvironmentType.code_sandbox,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} bug report", f"{dimension.name} failing tests"],
            source_strategy="Use a compact repository or synthetic repair fixture.",
            tool_requirements=["read_file", "write_file", "run_tests"],
            construction_requirements=[
                "Include complete visible files and hidden tests.",
                "Make the failure mode discoverable from the visible state.",
            ],
            scoring_strategy="Deterministic hidden tests with partial credit for meaningful progress.",
        )
    if any(keyword in identity for keyword in ("dialogue", "conversation", "chat", "multi-turn", "multi turn")):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_dialogue_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} dialogue task",
            description=f"Multi-turn agent interaction tasks for {dimension.name}.",
            task_family=AgentTaskFamily.multi_turn_delegation,
            environment_type=AgentEnvironmentType.dialogue,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} dialogue benchmark"],
            source_strategy="Use a scripted dialogue or task-specific user simulator.",
            tool_requirements=["multi-turn conversation"],
            construction_requirements=[
                "Specify the initial user request and follow-up turns clearly.",
                "Define pass/fail/partial scoring for the transcript.",
            ],
            scoring_strategy="Transcript-based judge scoring.",
        )
    if any(keyword in full_text for keyword in ("browser", "web", "search", "research", "api", "tool")):
        return AgentTaskBlueprint(
            id=f"{dimension.id}_tool_blueprint",
            dimension_id=dimension.id,
            title=f"{dimension.name} tool use",
            description=f"Tool-using agent tasks for {dimension.name}.",
            task_family=AgentTaskFamily.api_tool_use,
            environment_type=AgentEnvironmentType.workspace,
            expected_task_count=1,
            resource_queries=[f"{dimension.name} tool use benchmark"],
            source_strategy="Use structured resources that require the agent to inspect, choose, and act.",
            tool_requirements=["look", "read_file", "write_file", "run_command"],
            construction_requirements=[
                "Make the task stateful and concrete.",
                "Ensure the oracle depends on the final state or command results.",
            ],
            scoring_strategy="Deterministic environment or judge scoring.",
        )
    return AgentTaskBlueprint(
        id=f"{dimension.id}_agent_blueprint",
        dimension_id=dimension.id,
        title=dimension.name,
        description=dimension.description,
        task_family=AgentTaskFamily.custom,
        environment_type=AgentEnvironmentType.workspace,
        expected_task_count=1,
        resource_queries=[f"{dimension.name} agent task"],
        source_strategy="Use the simplest executable environment that still reflects the requested capability.",
        tool_requirements=["look", "read_file", "write_file"],
        construction_requirements=[
            "Build one executable agent task for the dimension.",
            "Keep the oracle explicit and deterministic.",
        ],
        scoring_strategy="Deterministic environment or judge scoring.",
    )


def plan_agent_benchmark(goal: str, config: BenchmarkConfig) -> tuple[EvalSpec, list[AgentTaskBlueprint]]:
    scale_budget = _safe_scale_budget(config.scale_budget)
    if config.orchestrator_api_key:
        payload = {
            "goal": goal,
            "scale_budget": scale_budget.value,
            "scale_budget_workload": scale_budget_target_workload(scale_budget),
            "reference_model": config.reference_model.model_dump(mode="json") if config.reference_model else None,
            "benchmark_mode": config.benchmark_mode.value,
            "task_agent_schema": TASK_AGENT_SCHEMA,
            "task_agent_generation_guidance": TASK_AGENT_GENERATION_GUIDANCE,
        }
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


def _resource_from_raw(raw: dict[str, Any], fallback_id: str) -> AgentResource:
    return AgentResource(
        id=str(raw.get("id") or fallback_id),
        kind=str(raw.get("kind") or "web"),
        uri=str(raw.get("uri") or ""),
        title=str(raw.get("title") or ""),
        license=str(raw.get("license") or ""),
        content_summary=str(raw.get("content_summary") or ""),
        notes=str(raw.get("notes") or ""),
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def _agent_resource_from_source(source: BenchmarkSource, fallback_id: str) -> AgentResource:
    return AgentResource(
        id=_slug(fallback_id),
        kind=source.kind.value,
        uri=source.uri,
        title=source.title,
        content_summary=source.notes[:1000],
        notes="Discovered by agent benchmark resource search.",
    )


def _select_blueprint_sources(
    dimension: EvalDimension,
    blueprint: AgentTaskBlueprint,
    config: BenchmarkConfig,
) -> list[BenchmarkSource]:
    if not config.use_web_research or not config.orchestrator_api_key:
        return []
    queries = blueprint.resource_queries or dimension.research_queries
    if not queries:
        queries = [
            f"{dimension.name} {blueprint.title} agent benchmark task resources",
            f"{dimension.name} {blueprint.task_family.value} benchmark dataset",
        ]
    sources: list[BenchmarkSource] = []
    seen: set[str] = set()
    for query in queries[:2]:
        result = web_search(query, api_key=config.orchestrator_api_key, model=config.orchestrator_model)
        if not result:
            continue
        notes = format_search_result(result)[:1600]
        for citation in result.citations[: config.max_research_sources]:
            uri = str(citation.get("url") or "")
            if not uri or uri in seen:
                continue
            seen.add(uri)
            sources.append(
                BenchmarkSource(
                    kind=SourceKind.web,
                    uri=uri,
                    title=str(citation.get("title") or uri),
                    notes=notes,
                )
            )
            if len(sources) >= config.max_research_sources:
                return sources
    return sources


def _dedupe_agent_resources(resources: list[AgentResource]) -> list[AgentResource]:
    deduped: list[AgentResource] = []
    seen: set[tuple[str, str, str]] = set()
    used_ids: set[str] = set()
    for resource in resources:
        key = (resource.kind, resource.uri, resource.title)
        if key in seen:
            continue
        seen.add(key)
        resource_id = resource.id
        if resource_id in used_ids:
            resource_id = f"{resource_id}_{len(used_ids) + 1}"
            resource = resource.model_copy(update={"id": resource_id})
        used_ids.add(resource.id)
        deduped.append(resource)
    return deduped


def _task_from_raw(raw: dict[str, Any], fallback_id: str, *, default_dimension_id: str) -> AgentTask:
    environment = raw.get("environment") if isinstance(raw.get("environment"), dict) else {}
    scoring = raw.get("scoring") if isinstance(raw.get("scoring"), dict) else {}
    return AgentTask(
        id=str(raw.get("id") or fallback_id),
        dimension_id=str(raw.get("dimension_id") or default_dimension_id),
        title=str(raw.get("title") or fallback_id),
        description=str(raw.get("description") or ""),
        task_family=_safe_task_family(raw.get("task_family")),
        prompt=str(raw.get("prompt") or ""),
        system_prompt=str(raw.get("system_prompt") or ""),
        resource_ids=[str(x) for x in raw.get("resource_ids", []) if x],
        environment=AgentEnvironmentSpec(
            type=_safe_environment_type(environment.get("type")),
            tools=[tool for tool in environment.get("tools", []) if isinstance(tool, dict)],
            visible_files={str(path): str(content) for path, content in (environment.get("visible_files") or {}).items()}
            if isinstance(environment.get("visible_files"), dict)
            else {},
            hidden_files={str(path): str(content) for path, content in (environment.get("hidden_files") or {}).items()}
            if isinstance(environment.get("hidden_files"), dict)
            else {},
            image=str(environment.get("image") or ""),
            setup_commands=[str(cmd) for cmd in environment.get("setup_commands", []) if str(cmd).strip()]
            if isinstance(environment.get("setup_commands"), list)
            else [],
            test_command=str(environment.get("test_command") or ""),
            max_steps=max(1, int(environment.get("max_steps") or 8)),
            timeout=max(1, int(environment.get("timeout") or 20)),
            network=str(environment.get("network") or "none"),
            resource_limits=environment.get("resource_limits") if isinstance(environment.get("resource_limits"), dict) else {},
            workspace=environment.get("workspace") if isinstance(environment.get("workspace"), dict) else {},
            notes=str(environment.get("notes") or ""),
        ),
        interaction=raw.get("interaction") if isinstance(raw.get("interaction"), dict) else {},
        scoring=AgentScoringSpec(
            method=str(scoring.get("method") or "deterministic"),
            instructions=str(scoring.get("instructions") or ""),
            pass_criteria=str(scoring.get("pass_criteria") or scoring.get("pass_fail", {}).get("pass") or ""),
            partial_criteria=str(scoring.get("partial_criteria") or scoring.get("pass_fail", {}).get("partial") or ""),
            fail_criteria=str(scoring.get("fail_criteria") or scoring.get("pass_fail", {}).get("fail") or ""),
            score_levels={
                str(key): str(value)
                for key, value in (scoring.get("score_levels") or scoring.get("levels") or {}).items()
            }
            if isinstance(scoring.get("score_levels") or scoring.get("levels"), dict)
            else {},
            oracle_notes=str(scoring.get("oracle_notes") or ""),
        ),
        difficulty=_item_safe_difficulty(raw.get("difficulty"), Difficulty.L4),
        tags=[str(tag) for tag in raw.get("tags", []) if tag],
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def _task_from_legacy_item(item: BenchmarkItem, *, title: str, family: AgentTaskFamily) -> AgentTask:
    env = item.metadata.get("agent_env") if isinstance(item.metadata.get("agent_env"), dict) else {}
    task_agent = item.metadata.get("task_agent") if isinstance(item.metadata.get("task_agent"), dict) else {}
    scoring = task_agent.get("scoring") if isinstance(task_agent.get("scoring"), dict) else {}
    pass_fail = scoring.get("pass_fail") if isinstance(scoring.get("pass_fail"), dict) else {}
    env_type = _safe_environment_type(env.get("type"))
    workspace = {
        key: env[key]
        for key in ("start_room", "rooms", "item_descriptions", "goal")
        if key in env
    }
    return AgentTask(
        id=item.id,
        dimension_id=item.dimension_id,
        title=title,
        description=item.prompt,
        task_family=family,
        prompt=item.prompt,
        system_prompt=str(task_agent.get("system_prompt") or "You are the target agent. Return JSON only."),
        resource_ids=[],
        environment=AgentEnvironmentSpec(
            type=env_type,
            visible_files={str(k): str(v) for k, v in (env.get("visible_files") or env.get("files") or {}).items()}
            if isinstance(env.get("visible_files") or env.get("files"), dict)
            else {},
            hidden_files={str(k): str(v) for k, v in (env.get("hidden_files") or {}).items()}
            if isinstance(env.get("hidden_files"), dict)
            else {},
            image=str(env.get("image") or ""),
            setup_commands=[str(cmd) for cmd in env.get("setup_commands", [])]
            if isinstance(env.get("setup_commands"), list)
            else [],
            test_command=str(env.get("test_command") or ""),
            max_steps=max(1, int(env.get("max_steps") or 8)),
            timeout=max(1, int(env.get("timeout") or 20)),
            network=str(env.get("network") or "none"),
            resource_limits=env.get("resource_limits") if isinstance(env.get("resource_limits"), dict) else {},
            workspace=workspace,
            notes="Converted from EvaluationClaw fallback agent item.",
        ),
        interaction=task_agent.get("interaction") if isinstance(task_agent.get("interaction"), dict) else {},
        scoring=AgentScoringSpec(
            method=str(scoring.get("method") or "deterministic"),
            instructions=item.rubric or str(scoring.get("instructions") or ""),
            pass_criteria=str(pass_fail.get("pass") or ""),
            partial_criteria=str(pass_fail.get("partial") or ""),
            fail_criteria=str(pass_fail.get("fail") or ""),
            score_levels={str(k): str(v) for k, v in (scoring.get("levels") or {}).items()}
            if isinstance(scoring.get("levels"), dict)
            else {},
        ),
        difficulty=item.difficulty,
        tags=item.tags,
        metadata=dict(item.metadata),
    )


def _fallback_task_for_blueprint(
    spec: EvalSpec,
    dimension: EvalDimension,
    blueprint: AgentTaskBlueprint,
    *,
    index: int = 1,
) -> AgentTask:
    if blueprint.environment_type == AgentEnvironmentType.workspace:
        variants = [
            {
                "prompt": (
                    "Use the simulated workspace tools to place the blue_notebook and charged_tablet "
                    "in the outgoing bin. Inspect ambiguous items when needed, avoid distractors, and finish "
                    "within the step limit."
                ),
                "rooms": {
                    "office": ["blue_notebook", "red_notebook"],
                    "lab": ["charged_tablet", "dead_tablet"],
                    "mailroom": [],
                },
                "descriptions": {
                    "blue_notebook": "A blue notebook labeled project plan.",
                    "red_notebook": "A red notebook labeled old draft.",
                    "charged_tablet": "A tablet showing 100% battery.",
                    "dead_tablet": "A tablet with an empty battery icon.",
                },
                "goal": {"outgoing_bin": ["blue_notebook", "charged_tablet"]},
            },
            {
                "prompt": (
                    "Use the simulated workspace tools to find the signed_contract and priority_badge, "
                    "then place only those required items in the outgoing bin. Inspect similar-looking "
                    "items before moving them."
                ),
                "rooms": {
                    "office": ["draft_contract", "signed_contract"],
                    "security": ["priority_badge", "visitor_badge"],
                    "mailroom": [],
                },
                "descriptions": {
                    "draft_contract": "A contract marked draft, not ready to send.",
                    "signed_contract": "A contract with all signatures complete.",
                    "priority_badge": "A badge labeled priority access.",
                    "visitor_badge": "A temporary visitor badge.",
                },
                "goal": {"outgoing_bin": ["signed_contract", "priority_badge"]},
            },
            {
                "prompt": (
                    "Use the simulated workspace tools to identify the production_config and qa_report, "
                    "then place both in the outgoing bin without selecting stale or personal files."
                ),
                "rooms": {
                    "office": ["personal_notes", "qa_report"],
                    "server_room": ["production_config", "staging_config"],
                    "mailroom": [],
                },
                "descriptions": {
                    "personal_notes": "Private notes unrelated to the task.",
                    "qa_report": "The latest QA report approved this morning.",
                    "production_config": "Configuration labeled production.",
                    "staging_config": "Configuration labeled staging.",
                },
                "goal": {"outgoing_bin": ["production_config", "qa_report"]},
            },
        ]
        variant_offset = sum(ord(char) for char in dimension.id) % len(variants)
        variant = variants[(variant_offset + index - 1) % len(variants)]
        return AgentTask(
            id=f"{dimension.id}_workspace_{index}_{uuid.uuid4().hex[:8]}",
            dimension_id=dimension.id,
            title=blueprint.title if index == 1 else f"{blueprint.title} {index}",
            description=(
                "A deterministic stateful workspace task with distractors. The target agent must inspect "
                "observations, choose valid actions, and complete the requested final state."
            ),
            task_family=blueprint.task_family,
            prompt=str(variant["prompt"]),
            system_prompt=(
                "You are the target model acting as an agent in an EvaluationClaw simulated workspace. "
                "Use exactly one JSON action per turn. Read observations carefully, inspect ambiguous "
                "items before taking them, and finish only after the goal is complete."
            ),
            environment=AgentEnvironmentSpec(
                type=AgentEnvironmentType.workspace,
                workspace={
                    "start_room": "office",
                    "rooms": variant["rooms"],
                    "item_descriptions": variant["descriptions"],
                    "goal": variant["goal"],
                },
                max_steps=8,
            ),
            interaction={
                "max_turns": 8,
                "stop_condition": "Stop when required items are in the outgoing bin or the step limit is reached.",
            },
            scoring=AgentScoringSpec(
                method="deterministic",
                instructions=(
                    "Use deterministic environment scoring: full credit for placing all required items and no wrong "
                    "items in the outgoing bin; partial credit for required items placed; penalties for invalid actions."
                ),
                pass_criteria="All required items and no wrong items are placed in the outgoing bin.",
                partial_criteria="Some required items are placed, with penalties for wrong or invalid actions.",
                fail_criteria="No required item is correctly placed.",
            ),
            difficulty=dimension.target_difficulty,
            tags=[dimension.id, blueprint.task_family.value, "workspace"],
        )
    item_spec = spec.model_copy(update={"task_types": [TaskType.agent_interaction]})
    item_dimension = dimension.model_copy(update={"task_types": [TaskType.agent_interaction]})
    legacy_items = fallback_items(item_spec, item_dimension, 1)
    if legacy_items:
        task = _task_from_legacy_item(
            legacy_items[0],
            title=blueprint.title,
            family=blueprint.task_family,
        )
        if index > 1:
            task.id = f"{task.id}_{index}"
            task.title = f"{task.title} {index}"
        return task
    return AgentTask(
        id=f"{blueprint.id}_{index}_{uuid.uuid4().hex[:8]}",
        dimension_id=dimension.id,
        title=blueprint.title,
        description=blueprint.description,
        task_family=blueprint.task_family,
        prompt=f"Use the simulated workspace tools to complete this task: {dimension.description}",
        system_prompt="You are the target agent. Return exactly one JSON tool action per turn.",
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.workspace,
            workspace={
                "start_room": "office",
                "rooms": {"office": ["blue_notebook"], "mailroom": []},
                "goal": {"outgoing_bin": ["blue_notebook"]},
            },
            max_steps=6,
        ),
        interaction={"max_turns": 6, "stop_condition": "Stop when the workspace goal is complete."},
        scoring=AgentScoringSpec(
            method="deterministic",
            instructions="Score from the final environment state.",
            pass_criteria="The required item is placed in the outgoing bin.",
            partial_criteria="The agent takes a useful intermediate action.",
            fail_criteria="The agent does not make progress toward the goal.",
        ),
        difficulty=dimension.target_difficulty,
        tags=[dimension.id, blueprint.task_family.value],
    )


def build_agent_task_suite(
    spec: EvalSpec,
    blueprints: list[AgentTaskBlueprint],
    config: BenchmarkConfig,
) -> AgentTaskSuite:
    if not spec.dimensions:
        spec = EvalSpec(
            id=spec.id,
            objective=spec.objective,
            subjects=spec.subjects,
            task_types=spec.task_types or [TaskType.agent_interaction],
            dimensions=_fallback_dimensions(spec.objective),
            scale_budget=spec.scale_budget,
            scale=spec.scale,
            metrics=spec.metrics,
            constraints=spec.constraints,
            planner_notes=spec.planner_notes,
            critique=spec.critique,
        )

    resources: list[AgentResource] = []
    tasks: list[AgentTask] = []
    notes: list[str] = []
    blueprint_by_dimension = defaultdict(list)
    for blueprint in blueprints:
        blueprint_by_dimension[blueprint.dimension_id].append(blueprint)

    for dimension in spec.dimensions:
        dim_blueprints = blueprint_by_dimension.get(dimension.id, [])
        if not dim_blueprints:
            notes.append(f"{dimension.id}: no blueprint supplied; skipping.")
            continue
        for blueprint in dim_blueprints:
            source_candidates = _select_blueprint_sources(dimension, blueprint, config)
            local_resources = [
                _agent_resource_from_source(source, f"{blueprint.id}_resource_{idx}")
                for idx, source in enumerate(source_candidates, 1)
            ]
            resources.extend(local_resources)
            payload = {
                "spec": spec.model_dump(mode="json"),
                "dimension": dimension.model_dump(mode="json"),
                "blueprint": blueprint.model_dump(mode="json"),
                "resource_context": _source_context(source_candidates),
                "task_agent_schema": TASK_AGENT_SCHEMA,
                "task_agent_generation_guidance": TASK_AGENT_GENERATION_GUIDANCE,
            }
            if config.orchestrator_api_key:
                raw = call_llm(
                    [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
                    system=AGENT_TASK_BUILDER_PROMPT,
                    model=config.orchestrator_model,
                    api_key=config.orchestrator_api_key,
                    base_url=config.orchestrator_base_url,
                    backend=config.llm_backend,
                    max_tokens=8192,
                )
                parsed = extract_json(raw)
            else:
                parsed = None
            parsed_resources = []
            parsed_tasks = []
            if isinstance(parsed, dict):
                parsed_resources = parsed.get("resources", []) if isinstance(parsed.get("resources"), list) else []
                parsed_tasks = parsed.get("tasks", []) if isinstance(parsed.get("tasks"), list) else []
                if parsed.get("construction_notes"):
                    notes.append(str(parsed["construction_notes"]))
            target_task_count = max(1, int(blueprint.expected_task_count))
            if not parsed_tasks:
                for task_index in range(1, target_task_count + 1):
                    tasks.append(_fallback_task_for_blueprint(spec, dimension, blueprint, index=task_index))
                notes.append(
                    f"{blueprint.id}: Local fallback executable agent task(s), count={target_task_count}."
                )
                continue
            added_for_blueprint = 0
            for idx, raw_resource in enumerate(parsed_resources, 1):
                if not isinstance(raw_resource, dict):
                    continue
                resources.append(_resource_from_raw(raw_resource, f"{blueprint.id}_resource_{idx}"))
            for idx, raw_task in enumerate(parsed_tasks, 1):
                if not isinstance(raw_task, dict):
                    continue
                task = _task_from_raw(raw_task, f"{blueprint.id}_task_{idx}", default_dimension_id=dimension.id)
                if not task.prompt.strip():
                    continue
                if not task.resource_ids and local_resources:
                    task.resource_ids = [local_resources[0].id]
                elif not task.resource_ids and resources:
                    task.resource_ids = [resources[-1].id]
                tasks.append(task)
                added_for_blueprint += 1
            while added_for_blueprint < target_task_count:
                added_for_blueprint += 1
                tasks.append(_fallback_task_for_blueprint(spec, dimension, blueprint, index=added_for_blueprint))
                notes.append(f"{blueprint.id}: Filled missing agent task with local fallback.")

    if not resources and blueprints:
        for blueprint in blueprints:
            resources.append(
                AgentResource(
                    id=f"{blueprint.id}_resource",
                    kind="generated_fixture",
                    title=blueprint.title,
                    content_summary=blueprint.description,
                    notes=blueprint.source_strategy,
                )
            )

    return AgentTaskSuite(
        objective=spec.objective,
        dimensions=spec.dimensions,
        blueprints=blueprints,
        resources=_dedupe_agent_resources(resources),
        tasks=tasks,
        construction_notes="\n".join(notes),
    )


def _agent_env_for_runner(task: AgentTask) -> dict[str, Any]:
    env = task.environment.model_dump(mode="json")
    env_type = str(env.get("type") or "workspace")
    env["type"] = env_type
    if env_type == "workspace":
        workspace = env.get("workspace") if isinstance(env.get("workspace"), dict) else {}
        for key in ("start_room", "rooms", "item_descriptions", "goal", "max_steps"):
            if key in workspace and key not in env:
                env[key] = workspace[key]
        if "rooms" not in env:
            env["start_room"] = "office"
            env["rooms"] = {"office": ["blue_notebook"], "mailroom": []}
            env["goal"] = {"outgoing_bin": ["blue_notebook"]}
            env["max_steps"] = env.get("max_steps") or 6
    if env_type == "code_sandbox":
        if not env.get("test_command"):
            env["test_command"] = "python3 tests.py"
        env.pop("workspace", None)
    if env_type == "docker_workspace":
        if not env.get("image"):
            env["image"] = "python:3.11-slim"
        if not env.get("test_command"):
            env["test_command"] = "pytest -q"
        env.pop("workspace", None)
    return env


def _task_agent_metadata_for_task(task: AgentTask, agent_env: dict[str, Any]) -> dict[str, Any]:
    existing = task.metadata.get("task_agent") if isinstance(task.metadata.get("task_agent"), dict) else {}
    initial_content: dict[str, Any] = {}
    if isinstance(existing.get("initial_content"), dict):
        initial_content.update(existing["initial_content"])
    if task.description and "scenario" not in initial_content:
        initial_content["scenario"] = task.description
    if agent_env.get("workspace") and "workspace" not in initial_content:
        initial_content["workspace"] = agent_env["workspace"]
    if agent_env.get("visible_files") and "files" not in initial_content:
        initial_content["files"] = agent_env["visible_files"]
    if agent_env.get("hidden_files") and "hidden_file_names" not in initial_content:
        initial_content["hidden_file_names"] = sorted(agent_env["hidden_files"].keys())
    if agent_env.get("image") and "image" not in initial_content:
        initial_content["image"] = agent_env["image"]
    if agent_env.get("notes") and "notes" not in initial_content:
        initial_content["notes"] = agent_env["notes"]

    scoring = task.scoring.model_dump(mode="json")
    scoring.update(
        {
            "method": scoring.get("method") or "deterministic",
            "instructions": scoring.get("instructions") or task.scoring.oracle_notes or task.description,
            "pass_fail": {
                "pass": scoring.get("pass_criteria") or task.scoring.pass_criteria,
                "partial": scoring.get("partial_criteria") or task.scoring.partial_criteria,
                "fail": scoring.get("fail_criteria") or task.scoring.fail_criteria,
            },
            "levels": scoring.get("score_levels") or task.scoring.score_levels,
        }
    )
    metadata = {
        "schema_version": existing.get("schema_version") or "evalclaw.task_agent.v1",
        "agent_role": existing.get("agent_role") or "target_agent_executor",
        "system_prompt": task.system_prompt or existing.get("system_prompt") or "You are the target agent. Return JSON only.",
        "initial_content": initial_content,
        "interaction": existing.get("interaction") if isinstance(existing.get("interaction"), dict) else task.interaction,
        "scoring": scoring,
        "execution": {
            "environment_type": agent_env.get("type", task.environment.type.value),
            "agent_env": agent_env,
        },
    }
    for key, value in existing.items():
        if key not in metadata:
            metadata[key] = value
    return metadata


def task_suite_to_dataset(suite: AgentTaskSuite, spec: EvalSpec, config: BenchmarkConfig) -> BenchmarkDataset:
    items: list[BenchmarkItem] = []
    def _source_kind(kind: str) -> SourceKind:
        if kind == "web":
            return SourceKind.web
        if kind == "hf_dataset":
            return SourceKind.hf_dataset
        if kind == "lm_eval":
            return SourceKind.lm_eval
        return SourceKind.imported

    sources: list[BenchmarkSource] = [
        BenchmarkSource(
            kind=_source_kind(resource.kind),
            uri=resource.uri or resource.id,
            title=resource.title or resource.id,
            notes=resource.content_summary or resource.notes,
        )
        for resource in suite.resources
    ]
    batches: list[BenchmarkBatch] = []
    for index, task in enumerate(suite.tasks, 1):
        agent_env = _agent_env_for_runner(task)
        metadata = dict(task.metadata)
        metadata["task_agent"] = _task_agent_metadata_for_task(task, agent_env)
        metadata["agent_env"] = agent_env
        item = BenchmarkItem(
            id=task.id,
            dimension_id=task.dimension_id,
            task_type=(
                TaskType.multi_turn
                if task.task_family == AgentTaskFamily.multi_turn_delegation or agent_env.get("type") == "dialogue"
                else TaskType.agent_interaction
            ),
            prompt=task.prompt,
            rubric=(
                task.scoring.instructions
                or f"{task.scoring.pass_criteria} {task.scoring.partial_criteria} {task.scoring.fail_criteria}".strip()
            ),
            difficulty=task.difficulty,
            source=BenchmarkSource(kind=SourceKind.imported, uri=task.id, title=task.title, notes=task.description),
            tags=task.tags,
            metadata=metadata,
        )
        items.append(item)
        sources.append(BenchmarkSource(kind=SourceKind.imported, uri=task.id, title=task.title, notes=task.description))

    if spec.dimensions:
        for dimension in spec.dimensions:
            dim_count = sum(1 for item in items if item.dimension_id == dimension.id)
            batches.append(
                BenchmarkBatch(
                    id=f"{dimension.id}_agent_batch",
                    dimension_id=dimension.id,
                    description=f"Agent benchmark batch for {dimension.name}.",
                    planned_item_count=dimension.target_item_count or dim_count,
                    materialized_item_count=dim_count,
                    source_backed_target=dimension.target_source_backed_count,
                    generated_target=dimension.target_generated_count or 0,
                    task_types=[TaskType.agent_interaction],
                    source_strategy="Resource-backed executable agent tasks.",
                    qc_sample_size=max(1, min(dim_count, 8)),
                    notes="Agent-mode benchmark batch.",
                )
            )

    return BenchmarkDataset(
        spec=spec.model_copy(update={"task_types": [TaskType.agent_interaction]}),
        items=items,
        sources=sources,
        batches=batches,
        agent_task_suite=suite,
        generation_notes=suite.construction_notes,
    )


def build_agent_dataset(goal: str, config: BenchmarkConfig) -> BenchmarkDataset:
    spec, blueprints = plan_agent_benchmark(goal, config)
    suite = build_agent_task_suite(spec, blueprints, config)
    return task_suite_to_dataset(suite, spec, config)
