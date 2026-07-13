"""Agent task-suite construction."""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from ..core.task_summary import compact_task_content_summary
from ..generation.generator import _source_context
from ..models.llm import call_llm, extract_json
from ..prompts.agent_benchmark import AGENT_TASK_BUILDER_PROMPT
from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_GENERATION_GUIDANCE,
    AGENT_TASK_PACKAGE_SCHEMA,
)
from ..protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE, TASK_AGENT_SCHEMA
from ..types import (
    AgentResource,
    AgentTask,
    AgentTaskBlueprint,
    AgentTaskSuite,
    BenchmarkConfig,
    EvalDimension,
    EvalSpec,
    Message,
    TaskType,
)
from .builders import _fallback_task_for_blueprint, _task_from_raw
from .planning import _fallback_dimensions
from .research import TASK_BUILDER_E4_RESEARCH_PROMPT, run_task_builder_research
from .resources import (
    _agent_resource_from_source,
    _dedupe_agent_resources,
    _resource_from_raw,
    _select_blueprint_sources,
)
from .validation import agent_task_structure_issues

_VALID_AGENT_TASK_BUILDERS = {"llm", "local", "auto"}


@dataclass(frozen=True)
class _BlueprintBuildJob:
    order: int
    dimension: EvalDimension
    blueprint: AgentTaskBlueprint
    fallback_start_index: int


@dataclass
class _BlueprintBuildResult:
    order: int
    resources: list[AgentResource]
    tasks: list[AgentTask]
    notes: list[str]


@dataclass
class _ParsedBuilderResponse:
    resources: list[AgentResource]
    tasks: list[AgentTask]
    notes: list[str]
    validation_issues: list[str]


def _capability_payload(dimension: EvalDimension) -> dict[str, object]:
    return {
        "id": dimension.id,
        "name": dimension.name,
        "description": dimension.description,
        "approach": dimension.approach,
        "challenge_effort": dimension.challenge_effort.value,
        "task_types": [task_type.value for task_type in dimension.task_types],
        "requirements": list(dimension.item_requirements),
        "coverage": {
            "target_item_count": dimension.target_item_count,
            "target_source_backed_count": dimension.target_source_backed_count,
            "target_generated_count": dimension.target_generated_count,
        },
        "research_needed": dimension.needs_research,
    }


def _task_builder_payload(
    spec: EvalSpec,
    dimension: EvalDimension,
    blueprint: AgentTaskBlueprint,
    resource_context: str,
    revision_context: dict[str, object] | None = None,
) -> dict[str, object]:
    other_capabilities = [
        {
            "id": other.id,
            "name": other.name,
            "description": other.description,
            "task_types": [task_type.value for task_type in other.task_types],
            "requirements": list(other.item_requirements),
        }
        for other in spec.dimensions
        if other.id != dimension.id
    ]
    payload: dict[str, object] = {
        "benchmark_context": {
            "objective": spec.objective,
            "task_types": [task_type.value for task_type in spec.task_types],
            "scale": spec.scale,
            "metrics": [metric.value for metric in spec.metrics],
            "constraints": list(spec.constraints),
            "planner_notes": spec.planner_notes,
            "other_capabilities": other_capabilities,
        },
        "task_plan": {
            "capability": _capability_payload(dimension),
            "construction": {
                "id": blueprint.id,
                "title": blueprint.title,
                "description": blueprint.description,
                "environment_type": blueprint.environment_type.value,
                "expected_task_count": blueprint.expected_task_count,
                "tool_requirements": list(blueprint.tool_requirements),
                "requirements": list(blueprint.construction_requirements),
                "scoring_strategy": blueprint.scoring_strategy,
            },
        },
        "resources": {
            "context": resource_context,
            "selection": {
                "queries": list(blueprint.resource_queries),
                "strategy": blueprint.source_strategy,
            },
        },
        "task_builder_contract": {
            "metadata_protocols": {
                "task_agent": {
                    "schema": TASK_AGENT_SCHEMA,
                    "guidance": TASK_AGENT_GENERATION_GUIDANCE,
                },
                "agent_task_package": {
                    "schema": AGENT_TASK_PACKAGE_SCHEMA,
                    "guidance": AGENT_TASK_PACKAGE_GENERATION_GUIDANCE,
                },
            },
            "response_format": "Return one complete JSON object with construction_notes, resources, and tasks.",
        },
    }
    if revision_context:
        payload["revision"] = revision_context
    return payload


def build_agent_task_suite(
    spec: EvalSpec,
    blueprints: list[AgentTaskBlueprint],
    config: BenchmarkConfig,
    *,
    revision_context_by_dimension: dict[str, dict[str, object]] | None = None,
) -> AgentTaskSuite:
    builder_mode = str(config.agent_task_builder or "llm").lower()
    if builder_mode not in _VALID_AGENT_TASK_BUILDERS:
        raise ValueError(
            "BenchmarkConfig.agent_task_builder must be one of: "
            f"{', '.join(sorted(_VALID_AGENT_TASK_BUILDERS))}."
        )

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

    blueprint_by_dimension = defaultdict(list)
    for blueprint in blueprints:
        blueprint_by_dimension[blueprint.dimension_id].append(blueprint)

    def ensure_task_content_summary(
        task: AgentTask,
        blueprint: AgentTaskBlueprint,
        candidate_resources: list[AgentResource],
    ) -> AgentTask:
        if task.content_summary.strip():
            task.content_summary = compact_task_content_summary(task.content_summary)
            return task
        resource_summary = ""
        if candidate_resources:
            resource = candidate_resources[0]
            resource_summary = compact_task_content_summary(resource.title, resource.content_summary)
        task.content_summary = compact_task_content_summary(
            resource_summary,
            blueprint.title,
            task.title,
            task.prompt,
        )
        return task

    def strict_error(blueprint: AgentTaskBlueprint, message: str) -> RuntimeError:
        return RuntimeError(
            "Agent task builder LLM generation failed "
            f"for blueprint '{blueprint.id}' using model '{config.orchestrator_model}': {message} "
            "Set BenchmarkConfig.agent_task_builder='local' only for offline smoke tests, "
            "or 'auto' if fallback templates are intentionally acceptable."
        )

    jobs: list[_BlueprintBuildJob] = []
    build_results_by_order: dict[int, _BlueprintBuildResult] = {}
    fallback_variant_counts: defaultdict[str, int] = defaultdict(int)
    order = 0
    for dimension in spec.dimensions:
        dim_blueprints = blueprint_by_dimension.get(dimension.id, [])
        if not dim_blueprints:
            build_results_by_order[order] = _BlueprintBuildResult(
                order=order,
                resources=[],
                tasks=[],
                notes=[f"{dimension.id}: no blueprint supplied; skipping."],
            )
            order += 1
            continue
        for blueprint in dim_blueprints:
            target_task_count = max(1, int(blueprint.expected_task_count))
            fallback_key = blueprint.environment_type.value
            fallback_start_index = fallback_variant_counts[fallback_key] + 1
            fallback_variant_counts[fallback_key] += target_task_count
            jobs.append(
                _BlueprintBuildJob(
                    order=order,
                    dimension=dimension,
                    blueprint=blueprint,
                    fallback_start_index=fallback_start_index,
                )
            )
            order += 1

    def build_blueprint_job(job: _BlueprintBuildJob) -> _BlueprintBuildResult:
        dimension = job.dimension
        blueprint = job.blueprint
        source_candidates = _select_blueprint_sources(dimension, blueprint, config)
        local_resources = [
            _agent_resource_from_source(source, f"{blueprint.id}_resource_{idx}")
            for idx, source in enumerate(source_candidates, 1)
        ]
        result_resources: list[AgentResource] = list(local_resources)
        result_tasks: list[AgentTask] = []
        result_notes: list[str] = []
        target_task_count = max(1, int(blueprint.expected_task_count))

        def add_local_tasks(*, reason: str) -> _BlueprintBuildResult:
            for offset in range(target_task_count):
                task = _fallback_task_for_blueprint(
                    spec,
                    dimension,
                    blueprint,
                    index=job.fallback_start_index + offset,
                )
                result_tasks.append(ensure_task_content_summary(task, blueprint, local_resources))
            result_notes.append(
                f"{blueprint.id}: {reason} local executable agent task(s), "
                f"count={target_task_count}."
            )
            return _BlueprintBuildResult(
                order=job.order,
                resources=result_resources,
                tasks=result_tasks,
                notes=result_notes,
            )

        if builder_mode == "local":
            return add_local_tasks(reason="Explicit")

        if not config.orchestrator_api_key:
            if builder_mode == "auto":
                return add_local_tasks(reason="Missing orchestrator_api_key; auto mode used")
            raise strict_error(
                blueprint,
                "missing orchestrator_api_key. Default 'llm' mode requires a real "
                "orchestrator key for agent task materialization.",
            )

        payload = _task_builder_payload(
            spec,
            dimension,
            blueprint,
            _source_context(source_candidates),
            (revision_context_by_dimension or {}).get(dimension.id),
        )
        def call_task_builder(call_payload: dict[str, object]) -> str:
            research_enabled = (
                builder_mode == "llm"
                and dimension.challenge_effort.value == "E4"
                and config.use_web_research
                and str(config.search_backend).lower() != "none"
            )
            system_prompt = AGENT_TASK_BUILDER_PROMPT
            if research_enabled:
                system_prompt += "\n\n" + TASK_BUILDER_E4_RESEARCH_PROMPT
                try:
                    raw_response, research_notes = run_task_builder_research(
                        call_payload,
                        system_prompt=system_prompt,
                        config=config,
                    )
                    result_notes.extend(research_notes)
                except Exception as exc:
                    result_notes.append(
                        "E4 task-builder research tools were unavailable; continued with the regular "
                        f"task-builder call ({type(exc).__name__}: {str(exc)[:180]})."
                    )
                    raw_response = call_llm(
                        [Message(role="user", content=json.dumps(call_payload, ensure_ascii=False, indent=2))],
                        system=system_prompt,
                        model=config.orchestrator_model,
                        api_key=config.orchestrator_api_key,
                        base_url=config.orchestrator_base_url,
                        provider=config.orchestrator_provider,
                        backend=config.llm_backend,
                        max_tokens=16384,
                    )
            else:
                raw_response = call_llm(
                    [Message(role="user", content=json.dumps(call_payload, ensure_ascii=False, indent=2))],
                    system=system_prompt,
                    model=config.orchestrator_model,
                    api_key=config.orchestrator_api_key,
                    base_url=config.orchestrator_base_url,
                    provider=config.orchestrator_provider,
                    backend=config.llm_backend,
                    max_tokens=16384,
                )
            if not raw_response.strip():
                raise ValueError("empty response")
            return raw_response

        def parse_builder_response(parsed: dict[str, object]) -> _ParsedBuilderResponse:
            attempt_resources: list[AgentResource] = list(local_resources)
            attempt_tasks: list[AgentTask] = []
            attempt_notes: list[str] = []
            validation_issues: list[str] = []
            parsed_resources = parsed.get("resources", []) if isinstance(parsed.get("resources"), list) else []
            parsed_tasks = parsed.get("tasks", []) if isinstance(parsed.get("tasks"), list) else []
            if parsed.get("construction_notes"):
                attempt_notes.append(str(parsed["construction_notes"]))
            if not parsed_tasks:
                keys = ", ".join(sorted(str(key) for key in parsed.keys()))
                raise ValueError(f"LLM returned no tasks; parsed object keys were [{keys}].")
            if builder_mode != "auto" and len(parsed_tasks) > target_task_count:
                raise ValueError(
                    f"LLM returned {len(parsed_tasks)} task object(s), "
                    f"but blueprint.expected_task_count is {target_task_count}."
                )
            parsed_resource_ids: list[str] = []
            parsed_task_resources: list[AgentResource] = []
            seen_task_prompts: dict[str, str] = {}
            for idx, raw_resource in enumerate(parsed_resources, 1):
                if not isinstance(raw_resource, dict):
                    if builder_mode != "auto":
                        raise ValueError(f"resource #{idx} is not a JSON object.")
                    continue
                resource = _resource_from_raw(raw_resource, f"{blueprint.id}_resource_{idx}")
                attempt_resources.append(resource)
                parsed_task_resources.append(resource)
                parsed_resource_ids.append(resource.id)
            added_for_blueprint = 0
            for idx, raw_task in enumerate(parsed_tasks, 1):
                if not isinstance(raw_task, dict):
                    if builder_mode != "auto":
                        raise ValueError(f"task #{idx} is not a JSON object.")
                    continue
                try:
                    task = _task_from_raw(raw_task, f"{blueprint.id}_task_{idx}", default_dimension_id=dimension.id)
                except Exception as exc:
                    if builder_mode != "auto":
                        raise ValueError(
                            f"task #{idx} could not be normalized ({type(exc).__name__}: {exc})."
                        ) from exc
                    continue
                if not task.prompt.strip():
                    if builder_mode != "auto":
                        raise ValueError(f"task #{idx} has an empty prompt.")
                    continue
                if not task.resource_ids and local_resources:
                    task.resource_ids = [local_resources[0].id]
                elif not task.resource_ids and parsed_resource_ids:
                    task.resource_ids = [parsed_resource_ids[0]]
                task = ensure_task_content_summary(task, blueprint, local_resources or parsed_task_resources[-1:])
                task_issues = agent_task_structure_issues(
                    task,
                    dimension=dimension,
                    blueprint=blueprint,
                    require_challenge_effort_self_assessment=builder_mode == "llm",
                )
                normalized_prompt = " ".join(task.prompt.lower().split())
                if normalized_prompt in seen_task_prompts:
                    task_issues.append(
                        f"Task prompt duplicates {seen_task_prompts[normalized_prompt]} within the same blueprint."
                    )
                elif normalized_prompt:
                    seen_task_prompts[normalized_prompt] = task.id
                validation_issues.extend(f"task #{idx} ({task.id}): {issue}" for issue in task_issues)
                attempt_tasks.append(task)
                added_for_blueprint += 1
            while added_for_blueprint < target_task_count:
                if builder_mode != "auto":
                    raise ValueError(
                        f"LLM produced {added_for_blueprint} usable task(s), "
                        f"but blueprint.expected_task_count is {target_task_count}."
                    )
                task = _fallback_task_for_blueprint(
                    spec,
                    dimension,
                    blueprint,
                    index=job.fallback_start_index + added_for_blueprint,
                )
                attempt_tasks.append(ensure_task_content_summary(task, blueprint, local_resources))
                attempt_notes.append(f"{blueprint.id}: Filled missing agent task with local fallback.")
                added_for_blueprint += 1
            return _ParsedBuilderResponse(
                resources=attempt_resources,
                tasks=attempt_tasks,
                notes=attempt_notes,
                validation_issues=validation_issues,
            )

        parsed: object | None = None
        raw = ""
        repair_attempts = max(0, int(getattr(config, "agent_task_builder_repair_attempts", 2) or 0))
        last_validation_issues: list[str] = []
        for attempt in range(repair_attempts + 1):
            call_payload = payload
            if attempt > 0:
                previous_response = parsed
                if previous_response is None and raw:
                    previous_response = {"raw_response_prefix": raw[:4000]}
                call_payload = {
                    **payload,
                    "repair": {
                        "reason": "agent_task_structure_validation_failed",
                        "attempt": attempt,
                        "max_repair_attempts": repair_attempts,
                        "issues": last_validation_issues,
                        "instruction": (
                            "Return a complete replacement JSON object with resources and tasks. "
                            "Do not return a patch. Preserve the intended capability target, but repair "
                            "all malformed JSON, incorrect top-level response types, missing or inconsistent "
                            "executable environment, scoring, package, challenge_effort, and "
                            "metadata.challenge_effort_self_assessment fields. The tasks array length must "
                            "equal task_plan.construction.expected_task_count exactly."
                        ),
                        "previous_response": previous_response,
                    },
                }
            raw = ""
            parsed = None
            try:
                raw = call_task_builder(call_payload)
                parsed = extract_json(raw)
                if not isinstance(parsed, dict):
                    raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
                attempt_result = parse_builder_response(parsed)
            except Exception as exc:
                last_validation_issues = [f"{type(exc).__name__}: {exc}"]
                if attempt < repair_attempts:
                    result_notes.append(
                        f"{blueprint.id}: task-builder response could not be validated; requesting repair "
                        f"({last_validation_issues[0][:180]})."
                    )
                    continue
                break
            if not attempt_result.validation_issues:
                return _BlueprintBuildResult(
                    order=job.order,
                    resources=attempt_result.resources,
                    tasks=attempt_result.tasks,
                    notes=result_notes + attempt_result.notes,
                )
            last_validation_issues = attempt_result.validation_issues
            if attempt < repair_attempts:
                result_notes.append(
                    f"{blueprint.id}: structural validation failed; requesting builder repair "
                    f"({len(last_validation_issues)} issue(s))."
                )

        if builder_mode == "auto":
            result_notes.append(
                f"{blueprint.id}: structural validation failed after {repair_attempts} repair attempt(s); "
                "using local executable fallback."
            )
            return add_local_tasks(reason="Structural validation failure; auto mode used")
        raise strict_error(
            blueprint,
            "structural validation failed after "
            f"{repair_attempts} repair attempt(s): {'; '.join(last_validation_issues[:6])}",
        )

    max_workers = max(1, int(getattr(config, "agent_task_builder_max_workers", 4) or 1))
    if len(jobs) <= 1 or max_workers == 1:
        for job in jobs:
            build_results_by_order[job.order] = build_blueprint_job(job)
    else:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(jobs))) as executor:
            futures = [executor.submit(build_blueprint_job, job) for job in jobs]
            try:
                for future in as_completed(futures):
                    result = future.result()
                    build_results_by_order[result.order] = result
            except Exception:
                for future in futures:
                    future.cancel()
                raise

    resources: list[AgentResource] = []
    tasks: list[AgentTask] = []
    notes: list[str] = []
    for result_order in sorted(build_results_by_order):
        result = build_results_by_order[result_order]
        resources.extend(result.resources)
        tasks.extend(result.tasks)
        notes.extend(result.notes)

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
