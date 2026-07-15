"""Single-route, blueprint-driven task-suite construction."""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock

from ..core.task_summary import compact_task_content_summary
from ..generation.generator import _source_context
from ..models.llm import LLMOutputTruncatedError, call_llm, extract_json
from ..models.roles import role_model_settings
from ..planning.planner import _fallback_dimensions
from ..prompts.task_builder import EXECUTION_CAPABILITY_PROMPT, TASK_BUILDER_PROMPT
from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_GENERATION_GUIDANCE,
    AGENT_TASK_PACKAGE_SCHEMA,
)
from ..protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE, TASK_AGENT_SCHEMA
from ..types import (
    BenchmarkConfig,
    EvalDimension,
    EvalSpec,
    Message,
    TaskBlueprint,
    TaskDefinition,
    TaskResource,
    TaskSuite,
    TaskType,
)
from .builders import _fallback_task_for_blueprint, _task_from_raw
from .research import TASK_BUILDER_E4_RESEARCH_PROMPT, run_task_builder_research
from .resources import (
    _dedupe_resources,
    _resource_from_raw,
    _resource_from_source,
    _select_blueprint_sources,
)
from .validation import (
    CHALLENGE_EFFORT_FIDELITY_METADATA_KEY,
    task_structure_issues,
)

_VALID_TASK_BUILDERS = {"llm", "local", "auto"}


@dataclass(frozen=True)
class _BlueprintBuildJob:
    order: int
    dimension: EvalDimension
    blueprint: TaskBlueprint
    task_type: TaskType
    fallback_start_index: int
    task_index: int
    total_task_count: int


@dataclass
class _BlueprintBuildResult:
    order: int
    resources: list[TaskResource]
    tasks: list[TaskDefinition]
    notes: list[str]


@dataclass
class _ParsedBuilderResponse:
    resources: list[TaskResource]
    tasks: list[TaskDefinition]
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
    blueprint: TaskBlueprint,
    resource_context: str,
    revision_context: dict[str, object] | None = None,
    *,
    task_index: int = 1,
    total_task_count: int = 1,
    task_type: TaskType,
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
    construction: dict[str, object] = {
        "id": blueprint.id,
        "title": blueprint.title,
        "description": blueprint.description,
        "task_type": task_type.value,
        "expected_task_count": 1,
        "task_index": task_index,
        "blueprint_task_count": total_task_count,
        "task_slot_instruction": (
            "Generate exactly one task for this slot. Make it materially distinct from "
            "the other slots in the same blueprint while preserving the capability target."
        ),
        "requirements": list(blueprint.construction_requirements),
        "scoring_strategy": blueprint.scoring_strategy,
    }
    if blueprint.environment_type is not None:
        construction["environment_type"] = blueprint.environment_type.value
        construction["tool_requirements"] = list(blueprint.tool_requirements)

    optional_fields = ["content_summary", "description", "resource_ids", "tags"]
    task_schema: dict[str, object] = {
        "required": ["id", "dimension_id", "task_type", "title", "prompt", "challenge_effort", "scoring", "metadata"],
        "optional": optional_fields,
        "task_type": task_type.value,
    }
    if task_type == TaskType.multiple_choice:
        optional_fields.extend(["choices", "answer", "rubric"])
        task_schema["type_requirements"] = ["Provide non-empty choices and the correct answer."]
    elif task_type in {TaskType.yes_no, TaskType.short_answer}:
        optional_fields.extend(["answer", "rubric"])
        task_schema["type_requirements"] = ["Provide the reference answer."]
    elif task_type == TaskType.code_execution:
        optional_fields.extend(["test_code", "rubric"])
        task_schema["type_requirements"] = ["Provide deterministic test_code or an equivalent scoring oracle."]
    else:
        optional_fields.append("rubric")
        task_schema["type_requirements"] = ["Provide a task-specific rubric or scoring criteria."]

    contract: dict[str, object] = {
        "task_schema": task_schema,
        "response_format": "Return one complete JSON object with construction_notes, resources, and tasks.",
    }
    if blueprint.environment_type is not None:
        optional_fields.extend(["environment", "system_prompt", "interaction"])
        contract["metadata_protocols"] = {
            "task_agent": {
                "schema": TASK_AGENT_SCHEMA,
                "guidance": TASK_AGENT_GENERATION_GUIDANCE,
            },
            "agent_task_package": {
                "schema": AGENT_TASK_PACKAGE_SCHEMA,
                "guidance": AGENT_TASK_PACKAGE_GENERATION_GUIDANCE,
            },
        }

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
            "construction": construction,
        },
        "resources": {
            "context": resource_context,
            "selection": {
                "queries": list(blueprint.resource_queries),
                "strategy": blueprint.source_strategy,
            },
        },
        "task_builder_contract": contract,
    }
    if revision_context:
        payload["revision"] = revision_context
    return payload


def _revision_context_for_job(
    revision_context: dict[str, object] | None,
    *,
    blueprint_id: str,
    task_index: int,
) -> dict[str, object] | None:
    if not revision_context:
        return None
    previous_tasks = (
        [
            task
            for task in revision_context.get("previous_tasks", [])
            if isinstance(task, dict)
        ]
        if isinstance(revision_context.get("previous_tasks"), list)
        else []
    )
    matched = [
        task
        for task in previous_tasks
        if isinstance(task.get("metadata"), dict)
        and task["metadata"].get("builder_blueprint_id") == blueprint_id
    ]
    candidates = matched or previous_tasks
    previous_task = candidates[task_index - 1] if task_index <= len(candidates) else None
    previous_id = str(previous_task.get("id") or "") if previous_task else ""
    raw_issues = revision_context.get("qc_issues")
    issues = (
        [issue for issue in raw_issues if isinstance(issue, dict)]
        if isinstance(raw_issues, list)
        else []
    )
    relevant_issues = [
        issue
        for issue in issues
        if issue.get("item_id") in {None, "", previous_id}
    ]
    return {
        **revision_context,
        "previous_tasks": [previous_task] if previous_task else [],
        "qc_issues": relevant_issues,
        "instruction": (
            "Return one complete replacement task for this slot. Fix every QC issue listed for "
            "this task, but do not redesign or extensively modify any prompt, fixture, file, "
            "environment, output contract, evaluator, or scoring behavior that QC did not identify "
            "as problematic. Preserve unaffected content byte-for-byte where practical."
        ),
    }


def build_task_suite(
    spec: EvalSpec,
    blueprints: list[TaskBlueprint],
    config: BenchmarkConfig,
    *,
    revision_context_by_dimension: dict[str, dict[str, object]] | None = None,
    log: Callable[[str], None] | None = None,
) -> TaskSuite:
    progress_lock = Lock()

    def emit(message: str) -> None:
        if log is None:
            return
        with progress_lock:
            log(message)

    builder_mode = str(config.task_builder or "llm").lower()
    if builder_mode not in _VALID_TASK_BUILDERS:
        raise ValueError(
            "BenchmarkConfig.task_builder must be one of: "
            f"{', '.join(sorted(_VALID_TASK_BUILDERS))}."
        )

    if not spec.dimensions:
        spec = EvalSpec(
            id=spec.id,
            objective=spec.objective,
            subjects=spec.subjects,
            task_types=spec.task_types or [TaskType.open_generation],
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
        task: TaskDefinition,
        blueprint: TaskBlueprint,
        candidate_resources: list[TaskResource],
    ) -> TaskDefinition:
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

    builder_settings = role_model_settings(config, "task_builder")

    def strict_error(blueprint: TaskBlueprint, message: str) -> RuntimeError:
        return RuntimeError(
            "Task builder LLM generation failed "
            f"for blueprint '{blueprint.id}' using model '{builder_settings.model}': {message} "
            "Set BenchmarkConfig.task_builder='local' only for offline smoke tests, "
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
            task_types = blueprint.task_types or dimension.task_types or spec.task_types
            task_types = task_types or [TaskType.open_generation]
            fallback_key = blueprint.environment_type.value if blueprint.environment_type else "no_environment"
            fallback_start_index = fallback_variant_counts[fallback_key] + 1
            fallback_variant_counts[fallback_key] += target_task_count
            for task_index in range(1, target_task_count + 1):
                jobs.append(
                    _BlueprintBuildJob(
                        order=order,
                        dimension=dimension,
                        blueprint=blueprint,
                        task_type=task_types[(task_index - 1) % len(task_types)],
                        fallback_start_index=fallback_start_index + task_index - 1,
                        task_index=task_index,
                        total_task_count=target_task_count,
                    )
                )
                order += 1

    if jobs:
        emit(
            f"  Task builder: {len(jobs)} one-task job(s) across "
            f"{len({job.dimension.id for job in jobs})} dimension(s)."
        )

    job_progress_index = {job.order: index for index, job in enumerate(jobs, 1)}

    def job_label(job: _BlueprintBuildJob) -> str:
        return (
            f"{job.dimension.id} {job.task_type.value} task "
            f"{job.task_index}/{job.total_task_count} ({job.blueprint.id})"
        )

    def build_blueprint_job(job: _BlueprintBuildJob) -> _BlueprintBuildResult:
        dimension = job.dimension
        blueprint = job.blueprint
        label = job_label(job)
        emit(
            f"  Task builder: starting {job_progress_index[job.order]}/{len(jobs)} - "
            f"{label}."
        )
        job_revision = _revision_context_for_job(
            (revision_context_by_dimension or {}).get(dimension.id),
            blueprint_id=blueprint.id,
            task_index=job.task_index,
        )
        if (
            job_revision
            and job_revision.get("previous_tasks")
            and not job_revision.get("qc_issues")
        ):
            previous = job_revision["previous_tasks"][0]
            return _BlueprintBuildResult(
                order=job.order,
                resources=[],
                tasks=[TaskDefinition.model_validate(previous)],
                notes=[f"{label}: preserved unchanged because QC reported no issue for this task."],
            )
        source_candidates = _select_blueprint_sources(dimension, blueprint, config)
        local_resources = [
            _resource_from_source(source, f"{blueprint.id}_resource_{idx}")
            for idx, source in enumerate(source_candidates, 1)
        ]
        result_resources: list[TaskResource] = list(local_resources)
        result_tasks: list[TaskDefinition] = []
        result_notes: list[str] = []
        target_task_count = 1
        effort_fidelity_uncertain = False

        def tag_task(task: TaskDefinition) -> TaskDefinition:
            task.metadata = {
                **task.metadata,
                "builder_blueprint_id": blueprint.id,
                "builder_task_index": job.task_index,
                "builder_blueprint_task_count": job.total_task_count,
            }
            if effort_fidelity_uncertain:
                task.metadata[CHALLENGE_EFFORT_FIDELITY_METADATA_KEY] = {
                    "status": "uncertain",
                    "requested_effort": dimension.challenge_effort.value,
                    "recovery_strategy": "reduced_effort_litellm_retry",
                    "reason": (
                        "The original task-builder completion exhausted its output budget; "
                        "the task was regenerated with reduced construction and reasoning effort."
                    ),
                }
            return task

        def add_local_tasks(*, reason: str) -> _BlueprintBuildResult:
            task = _fallback_task_for_blueprint(
                spec,
                dimension,
                blueprint,
                index=job.fallback_start_index,
                task_type=job.task_type,
            )
            result_tasks.append(
                ensure_task_content_summary(tag_task(task), blueprint, local_resources)
            )
            result_notes.append(
                f"{blueprint.id}: {reason} local task(s), "
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

        if not builder_settings.configured:
            if builder_mode == "auto":
                return add_local_tasks(reason="Missing task-builder API key; auto mode used")
            raise strict_error(
                blueprint,
                "missing task-builder API key. Default 'llm' mode requires a configured "
                "task-builder role for task materialization.",
            )

        payload = _task_builder_payload(
            spec,
            dimension,
            blueprint,
            _source_context(source_candidates),
            job_revision,
            task_index=job.task_index,
            total_task_count=job.total_task_count,
            task_type=job.task_type,
        )

        def call_task_builder(
            call_payload: dict[str, object],
            *,
            force_litellm: bool = False,
            reduce_effort: bool = False,
        ) -> str:
            research_enabled = (
                builder_mode == "llm"
                and dimension.challenge_effort.value == "E4"
                and config.use_web_research
                and str(config.search_backend).lower() != "none"
                and job_revision is None
                and not reduce_effort
            )
            system_prompt = TASK_BUILDER_PROMPT
            if blueprint.environment_type is not None:
                system_prompt += "\n\n" + EXECUTION_CAPABILITY_PROMPT
            if research_enabled:
                system_prompt += "\n\n" + TASK_BUILDER_E4_RESEARCH_PROMPT
                try:
                    raw_response, research_notes = run_task_builder_research(
                        call_payload,
                        system_prompt=system_prompt,
                        config=config,
                    )
                    result_notes.extend(research_notes)
                except LLMOutputTruncatedError:
                    raise
                except Exception as exc:
                    result_notes.append(
                        "E4 task-builder research tools were unavailable; continued with the regular "
                        f"task-builder call ({type(exc).__name__}: {str(exc)[:180]})."
                    )
                    raw_response = call_llm(
                        [Message(role="user", content=json.dumps(call_payload, ensure_ascii=False, indent=2))],
                        system=system_prompt,
                        **builder_settings.call_kwargs(),
                        backend="litellm" if force_litellm else config.llm_backend,
                        max_tokens=16384,
                        reduce_reasoning_effort=reduce_effort,
                        retry_on_truncation=False,
                    )
            else:
                raw_response = call_llm(
                    [Message(role="user", content=json.dumps(call_payload, ensure_ascii=False, indent=2))],
                    system=system_prompt,
                    **builder_settings.call_kwargs(),
                    backend="litellm" if force_litellm else config.llm_backend,
                    max_tokens=16384,
                    reduce_reasoning_effort=reduce_effort,
                    retry_on_truncation=False,
                )
            if not raw_response.strip():
                raise ValueError("empty response")
            return raw_response

        def parse_builder_response(parsed: dict[str, object]) -> _ParsedBuilderResponse:
            attempt_resources: list[TaskResource] = list(local_resources)
            attempt_tasks: list[TaskDefinition] = []
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
            parsed_task_resources: list[TaskResource] = []
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
                    task = _task_from_raw(
                        raw_task,
                        f"{blueprint.id}_task_{idx}",
                        default_dimension_id=dimension.id,
                        default_task_type=job.task_type,
                    )
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
                task = ensure_task_content_summary(
                    tag_task(task),
                    blueprint,
                    local_resources or parsed_task_resources[-1:],
                )
                task_issues = task_structure_issues(
                    task,
                    dimension=dimension,
                    blueprint=blueprint,
                    require_challenge_effort_self_assessment=builder_mode == "llm",
                )
                if task.task_type != job.task_type:
                    task_issues.append(
                        f"Task task_type must be {job.task_type.value}; got {task.task_type.value}."
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
                    task_type=job.task_type,
                )
                attempt_tasks.append(
                    ensure_task_content_summary(tag_task(task), blueprint, local_resources)
                )
                attempt_notes.append(f"{blueprint.id}: Filled missing task with local fallback.")
                added_for_blueprint += 1
            return _ParsedBuilderResponse(
                resources=attempt_resources,
                tasks=attempt_tasks,
                notes=attempt_notes,
                validation_issues=validation_issues,
            )

        active_payload = payload
        force_litellm = False

        def request_builder_response(call_payload: dict[str, object]) -> str:
            nonlocal active_payload, effort_fidelity_uncertain, force_litellm
            try:
                return call_task_builder(
                    call_payload,
                    force_litellm=force_litellm,
                    reduce_effort=effort_fidelity_uncertain,
                )
            except LLMOutputTruncatedError:
                if force_litellm:
                    raise
                effort_fidelity_uncertain = True
                force_litellm = True
                recovery = {
                    "reason": "task_builder_output_truncated",
                    "requested_effort": dimension.challenge_effort.value,
                    "reduce_construction_effort": True,
                    "instruction": (
                        "Regenerate this task from the beginning using less construction effort. "
                        "Prioritize a complete, compact, executable task and deterministic evaluator. "
                        "Remove nonessential scenario breadth, research, fixtures, files, and duplicated "
                        "explanation before removing anything required for execution or scoring. Keep "
                        "task.challenge_effort as the originally requested label for traceability, but "
                        "self-assess honestly whether the regenerated task meets it."
                    ),
                }
                active_payload = {**active_payload, "truncation_recovery": recovery}
                recovery_payload = {**call_payload, "truncation_recovery": recovery}
                emit(
                    f"  Task builder: output truncated for {label}; retrying once with "
                    "reduced effort through LiteLLM."
                )
                result_notes.append(
                    f"{blueprint.id}: regenerated after output truncation with reduced effort; "
                    "challenge-effort fidelity marked uncertain."
                )
                return call_task_builder(
                    recovery_payload,
                    force_litellm=True,
                    reduce_effort=True,
                )

        parsed: object | None = None
        raw = ""
        repair_attempts = max(0, int(getattr(config, "task_builder_repair_attempts", 2) or 0))
        last_validation_issues: list[str] = []
        repair_fields = (
            "missing or inconsistent choices, answer, rubric, tests, scoring, challenge_effort, and "
            "metadata.challenge_effort_self_assessment fields"
            if blueprint.environment_type is None
            else
            "missing or inconsistent execution fields, scoring, package, challenge_effort, and "
            "metadata.challenge_effort_self_assessment fields"
        )
        for attempt in range(repair_attempts + 1):
            call_payload = active_payload
            if attempt > 0:
                previous_response = parsed
                if previous_response is None and raw:
                    previous_response = {"raw_response_prefix": raw[:4000]}
                call_payload = {
                    **active_payload,
                    "repair": {
                        "reason": "task_structure_validation_failed",
                        "attempt": attempt,
                        "max_repair_attempts": repair_attempts,
                        "issues": last_validation_issues,
                        "instruction": (
                            "Return a complete replacement JSON object with resources and tasks. "
                            "Do not return a patch. Preserve the intended capability target, but repair "
                            "all malformed JSON, incorrect top-level response types, and "
                            f"{repair_fields} that the listed issues identify. "
                            "Do not redesign or extensively modify unaffected task content. Preserve sound "
                            "prompts, fixtures, files, environment behavior, evaluator checks, scoring, and "
                            "metadata byte-for-byte where practical. The tasks array length must equal "
                            "task_plan.construction.expected_task_count exactly."
                        ),
                        "previous_response": previous_response,
                    },
                }
            raw = ""
            parsed = None
            try:
                raw = request_builder_response(call_payload)
                parsed = extract_json(raw)
                if not isinstance(parsed, dict):
                    raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
                attempt_result = parse_builder_response(parsed)
            except LLMOutputTruncatedError as exc:
                last_validation_issues = [f"{type(exc).__name__}: {exc}"]
                emit(
                    f"  Task builder: reduced-effort LiteLLM retry also truncated for {label}."
                )
                break
            except Exception as exc:
                last_validation_issues = [f"{type(exc).__name__}: {exc}"]
                if attempt < repair_attempts:
                    emit(
                        f"  Task builder: retrying {label} "
                        f"({attempt + 1}/{repair_attempts}) after invalid response."
                    )
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
                emit(
                    f"  Task builder: retrying {label} "
                    f"({attempt + 1}/{repair_attempts}) for "
                    f"{len(last_validation_issues)} structural issue(s)."
                )
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

    max_workers = max(1, int(getattr(config, "task_builder_max_workers", 4) or 1))
    completed_jobs = 0
    if len(jobs) <= 1 or max_workers == 1:
        for job in jobs:
            build_results_by_order[job.order] = build_blueprint_job(job)
            completed_jobs += 1
            emit(f"  Task builder: completed {completed_jobs}/{len(jobs)} - {job_label(job)}.")
    else:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(jobs))) as executor:
            futures = {executor.submit(build_blueprint_job, job): job for job in jobs}
            try:
                for future in as_completed(futures):
                    result = future.result()
                    build_results_by_order[result.order] = result
                    completed_jobs += 1
                    emit(
                        f"  Task builder: completed {completed_jobs}/{len(jobs)} - "
                        f"{job_label(futures[future])}."
                    )
            except Exception:
                for future in futures:
                    future.cancel()
                raise

    resources: list[TaskResource] = []
    tasks: list[TaskDefinition] = []
    notes: list[str] = []
    for result_order in sorted(build_results_by_order):
        result = build_results_by_order[result_order]
        resources.extend(result.resources)
        tasks.extend(result.tasks)
        notes.extend(result.notes)

    if not resources and blueprints:
        for blueprint in blueprints:
            resources.append(
                TaskResource(
                    id=f"{blueprint.id}_resource",
                    kind="generated_fixture",
                    title=blueprint.title,
                    content_summary=blueprint.description,
                    notes=blueprint.source_strategy,
                )
            )

    return TaskSuite(
        objective=spec.objective,
        dimensions=spec.dimensions,
        blueprints=blueprints,
        resources=_dedupe_resources(resources),
        tasks=tasks,
        construction_notes="\n".join(notes),
    )
