"""Single-route, TaskDesign-driven task-suite construction."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock

from ..core.task_summary import compact_task_content_summary
from ..diagnostics import _io_path, error_record, write_json
from ..execution.agent_envs import build_agent_environment
from ..execution.docker import require_docker_available
from ..models.llm import (
    LLMFinalContentMissingError,
    LLMOutputTruncatedError,
    extract_json,
)
from ..models.roles import role_model_settings
from ..prompts.task_builder import (
    build_task_builder_prompt,
    build_task_builder_tool_prompt,
    project_task_builder_document,
    task_builder_document_template,
)
from ..protocols.assets import replace_non_agent_asset_references
from ..types import (
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkItem,
    ChallengeEffort,
    EvalDimension,
    EvalSpec,
    TaskBlueprint,
    TaskDefinition,
    TaskResource,
    TaskSuite,
    TaskType,
)
from .packaging import pack_task_item
from .parsing import _task_from_raw
from .research import (
    TaskBuilderCallError,
    TaskBuilderTruncationSummaryError,
    run_task_builder_tools,
    task_builder_work_dir,
)
from .resources import (
    _dedupe_resources,
    _resource_from_raw,
    _resource_from_source,
    _select_blueprint_sources,
    _source_context,
)
from .skill_loader import environment_skill_payload, environment_skill_system_prompt
from .validation import resolve_builder_asset_path, task_structure_issues


def _ensure_unique_task_ids(tasks: list[TaskDefinition]) -> None:
    """Keep Builder IDs stable while preventing collisions across Builder jobs."""
    seen: set[str] = set()
    duplicate_counts: Counter[str] = Counter()
    for task in tasks:
        original_id = task.id
        if original_id not in seen:
            seen.add(original_id)
            continue
        blueprint_id = str(task.metadata.get("builder_job_id") or "").strip()
        prefix = blueprint_id or "task"
        duplicate_counts[original_id] += 1
        candidate = f"{prefix}__{original_id}"
        if duplicate_counts[original_id] > 1:
            candidate += f"__{duplicate_counts[original_id]}"
        while candidate in seen:
            duplicate_counts[original_id] += 1
            candidate = f"{prefix}__{original_id}__{duplicate_counts[original_id]}"
        task.id = candidate
        seen.add(candidate)


def _task_duplicate_key(task: TaskDefinition) -> str:
    content: dict[str, object] = {
        "prompt": task.prompt,
        "assets": [asset.path for asset in task.assets],
    }
    if task.task_type == TaskType.choice:
        content["choices"] = [choice.text for choice in task.choices]
    elif task.task_type == TaskType.multi_turn:
        content.update(
            {
                "system_prompt": task.system_prompt,
                "interaction": task.interaction,
            }
        )
    elif task.environment is not None:
        content["environment"] = task.environment.model_dump(mode="json")
    return " ".join(
        json.dumps(content, ensure_ascii=False, sort_keys=True).lower().split()
    )


def _normalize_builder_asset_paths(
    task: TaskDefinition,
    builder_work_dir: Path | None,
) -> TaskDefinition:
    if task.task_type != TaskType.agent:
        task.prompt = replace_non_agent_asset_references(task.prompt, task.assets)
        for choice in task.choices:
            choice.text = replace_non_agent_asset_references(choice.text, task.assets)
    if builder_work_dir is None:
        return task
    for asset in task.assets:
        raw_path = asset.path.strip()
        if not raw_path or Path(raw_path).is_absolute():
            continue
        try:
            resolved_path = resolve_builder_asset_path(raw_path, builder_work_dir)
        except ValueError:
            continue
        asset.path = str(resolved_path)
    return task


def _debug_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return slug[:100] or "unnamed"


def _debug_job_slug(dimension_id: str, blueprint_id: str) -> str:
    raw = f"{dimension_id}__{blueprint_id}"
    digest = uuid.uuid5(uuid.NAMESPACE_OID, raw).hex[:8]
    return f"{_debug_slug(raw)[:24]}-{digest}"


def _builder_checkpoint_digest(
    spec: EvalSpec,
    job: _BlueprintBuildJob,
    revision_context: dict[str, object] | None,
    namespace: str,
) -> str:
    revision = dict(revision_context or {})
    revision.pop("path", None)
    payload = {
        "namespace": namespace,
        "order": job.order,
        "dimension": job.dimension.model_dump(mode="json"),
        "blueprint": job.blueprint.model_dump(mode="json"),
        "spec": spec.model_dump(mode="json"),
        "revision": revision,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class _BlueprintBuildJob:
    order: int
    dimension: EvalDimension
    blueprint: TaskBlueprint


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
    valid_tasks: list[TaskDefinition]
    notes: list[str]
    validation_issues: list[str]


def _preflight_builder_environments(
    tasks: list[TaskDefinition],
    *,
    dimension: EvalDimension,
    blueprint: TaskBlueprint,
    resources: list[TaskResource],
    config: BenchmarkConfig,
    trace_dir: Path | None = None,
) -> tuple[list[str], set[str]]:
    if not config.environment_preflight:
        return [], set()
    resource_by_id = {resource.id: resource for resource in resources}
    issues: list[str] = []
    failed_ids: set[str] = set()
    for index, task in enumerate(tasks, 1):
        if task.environment is None or task.environment.type != AgentEnvironmentType.docker_workspace:
            continue
        task_design_id = str(task.metadata.get("task_design_id") or "")
        task_design = next(
            (design for design in blueprint.task_designs if design.id == task_design_id),
            None,
        )
        item = pack_task_item(
            task,
            dimension,
            resource_by_id=resource_by_id,
            blueprint=blueprint,
            task_design=task_design,
        )
        environment = None
        item_trace_dir = trace_dir / _debug_slug(task.id) if trace_dir is not None else None
        try:
            environment = build_agent_environment(item, config)
            preflight = getattr(environment, "preflight", None)
            if not callable(preflight):
                raise RuntimeError("environment does not implement evaluator preflight")
            outcome = preflight()
            if item_trace_dir is not None:
                write_json(item_trace_dir / "result.json", outcome.as_dict())
        except Exception as exc:
            failed_ids.add(task.id)
            issues.append(
                f"task #{index} ({task.id}): environment preflight failed: "
                f"{type(exc).__name__}: {exc}"
            )
            if item_trace_dir is not None:
                write_json(item_trace_dir / "failure.json", error_record(exc))
        finally:
            if item_trace_dir is not None and environment is not None:
                try:
                    write_json(item_trace_dir / "state.json", environment.state())
                    export = getattr(environment, "export_artifacts", None)
                    if callable(export):
                        write_json(
                            item_trace_dir / "artifacts.json",
                            export(item_trace_dir / "workspace"),
                        )
                except Exception as exc:
                    write_json(item_trace_dir / "artifact-error.json", error_record(exc))
            cleanup = getattr(environment, "cleanup", None)
            if callable(cleanup):
                cleanup()
    return issues, failed_ids


def _capability_payload(dimension: EvalDimension) -> dict[str, object]:
    return {
        "id": dimension.id,
        "name": dimension.name,
        "description": dimension.description,
        "measurement_target": dimension.measurement_target,
        "boundary": dimension.boundary,
        "approach": dimension.approach,
        "challenge_effort": dimension.challenge_effort.value,
        "task_types": [task_type.value for task_type in dimension.task_types],
        "task_type_allocation": [
            item.model_dump(mode="json") for item in dimension.task_type_allocation
        ],
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
    task_file_path: Path | None = None,
    config: BenchmarkConfig | None = None,
) -> dict[str, object]:
    if len(blueprint.task_designs) != 1:
        raise ValueError("Each Task Builder job must contain exactly one TaskDesign.")
    task_design = blueprint.task_designs[0]
    required_type_counts = {
        item.task_type.value: item.count for item in blueprint.task_type_allocation
    }
    required_task_design_counts = {
        design.id: design.task_count for design in blueprint.task_designs
    }
    required_return_count = blueprint.planned_task_count
    if revision_context:
        repair_types = Counter(
            str(task.get("task_type") or "")
            for task in revision_context.get("previous_tasks", [])
            if isinstance(task, dict) and str(task.get("task_type") or "")
        )
        required_type_counts = dict(repair_types)
        required_task_design_counts = dict(
            Counter(
                str(task.get("metadata", {}).get("task_design_id") or "")
                for task in revision_context.get("previous_tasks", [])
                if isinstance(task, dict)
                and isinstance(task.get("metadata"), dict)
                and str(task.get("metadata", {}).get("task_design_id") or "")
            )
        )
        required_return_count = int(
            revision_context.get("expected_replacement_count") or 0
        )
        if not required_task_design_counts and len(blueprint.task_designs) == 1:
            required_task_design_counts = {
                blueprint.task_designs[0].id: required_return_count
            }
    task_types = [_task_type for _task_type in TaskType if _task_type.value in required_type_counts]
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
        **task_design.model_dump(mode="json", exclude_defaults=True),
        "challenge_effort": task_design.challenge_effort.value,
        "required_return_task_count": required_return_count,
    }
    simplified = bool(config is not None and config.ablation_simplified_contract)
    optional_fields = [] if simplified else ["content_summary", "description", "assets", "tags"]
    if blueprint.source_strategy in {"adapted", "reused", "imported_dataset"}:
        optional_fields.append("resource_ids")
    task_schema: dict[str, object] = {
        "required": (
            ["title", "prompt"]
            if simplified
            else ["task_type", "title", "prompt", "challenge_effort", "metadata"]
        ),
        "optional": optional_fields,
        "allowed_task_types": [task_type.value for task_type in task_types],
        "required_task_type_counts": {
            **required_type_counts
        },
        "required_task_design_counts": required_task_design_counts,
        "framework_injected_fields": (
            ["id", "dimension_id", "task_type", "challenge_effort", "metadata.task_design_id"]
            if simplified
            else ["id", "dimension_id", "metadata.task_design_id"]
        ),
    }
    # These instructions must state the fields and runtime semantics required by
    # each selected task type.
    type_requirements: dict[str, list[str]] = {}
    if TaskType.choice in task_types:
        optional_fields.extend(["choices", "correct_choice_indices"])
        type_requirements[TaskType.choice.value] = [
            "Provide at least two choices as objects with text only, and provide a non-empty "
            "correct_choice_indices list using zero-based positions. One index means single-choice; multiple "
            "indices mean multi-select. The framework assigns canonical option ids. "
            "Do not put a multi-part answer object in a choice task. For choice tasks, you should put all "
            "answer options only in choices; do not include option labels or repeat option text in prompt."
        ]
    if TaskType.fill_blank in task_types:
        optional_fields.append("expected_texts")
        type_requirements[TaskType.fill_blank.value] = [
            "Provide expected_texts as a list of accepted answers; the runner scores a response correct "
            "when it exactly matches any listed answer apart from surrounding whitespace. State the "
            "constraints in the prompt or enumerate every correct answer, and ensure no correct answer "
            "outside the list is possible."
        ]
    if TaskType.generation in task_types:
        optional_fields.extend(["rubric", "judge_tools", "output_contract", "scoring"])
        type_requirements[TaskType.generation.value] = [
            "Provide a concrete rubric. Optional judge_tools may request registered external verification "
            "using python_tests. The Judge uses tool results as evidence; "
            "the tools do not directly assign the final score."
        ]
    if TaskType.multi_turn in task_types:
        optional_fields.extend(
            ["system_prompt", "interaction", "rubric", "judge_tools", "scoring"]
        )
        requested_followup_modes = sorted(
            {
                str(design.interaction_requirements.get("followup_mode") or "").strip().lower()
                for design in blueprint.task_designs
                if design.task_type == TaskType.multi_turn
                and str(design.interaction_requirements.get("followup_mode") or "").strip()
            }
        )
        if requested_followup_modes == ["adaptive"]:
            followup_contract = (
                "Use interaction.followup_instruction for response-conditioned follow-ups and omit "
                "interaction.user_turns."
            )
        elif requested_followup_modes == ["scripted"]:
            followup_contract = (
                "Use exactly interaction.user_turns as a list of 1 to 5 non-empty strings and omit "
                "interaction.followup_instruction."
            )
        else:
            followup_contract = (
                "Use exactly interaction.user_turns as a list of 1 to 5 non-empty strings for "
                "scripted follow-ups, or interaction.followup_instruction for adaptive follow-ups; "
                "aliases such as scripted_user_turns, turns, and follow_up_policy are invalid."
            )
        type_requirements[TaskType.multi_turn.value] = [
            "Provide a top-level interaction object. interaction.max_turns "
            f"must be between 1 and 5. {followup_contract}",
            "Provide task-specific transcript scoring criteria.",
            "The task prompt is the complete first content sent to the target and must include all "
            "target-visible role and scenario context. system_prompt is exclusively the separate "
            "dialogue-simulator prompt.",
        ]
        if requested_followup_modes:
            type_requirements[TaskType.multi_turn.value].append(
                "Implement each TaskDesign's interaction_requirements.followup_mode exactly. "
                "adaptive requires a task-specific simulator system_prompt and "
                "interaction.followup_instruction and forbids interaction.user_turns; scripted "
                "requires interaction.user_turns and forbids interaction.followup_instruction. "
                f"This TaskDesign requests: {', '.join(requested_followup_modes)}."
            )
    if TaskType.agent in task_types:
        optional_fields.extend(
            [
                "system_prompt",
                "interaction",
                "environment",
                "workflow",
                "output_contract",
                "rubric",
                "judge_tools",
                "scoring",
            ]
        )
        type_requirements[TaskType.agent.value] = [
            "Provide the executable environment, output contract, and deterministic checks or a "
            "task-specific rubric for the resulting state, artifacts, answer, or trajectory. "
            "For one task with ordered phases, provide workflow.stages with explicit stage ids, "
            "kind, prompts, context, environment lifecycle, file handoffs, and evaluation stages; "
            "reference only preceding stage outputs and define workflow.score_stage and metrics."
        ]
    if config is not None and config.task_models:
        task_model_hint = (
            "Select exactly one task model from available_models.models and record its id in "
            "metadata.task_model_id. This model is used at execution time for LLM scoring "
            "(generation/multi_turn/agent rubric judging) and as the dialogue simulator for "
            "adaptive multi_turn tasks. Choose the model whose capability matches the task's "
            "scoring or simulation complexity."
        )
        for model_task_type in (TaskType.generation, TaskType.multi_turn, TaskType.agent):
            if model_task_type in task_types:
                type_requirements[model_task_type.value].append(task_model_hint)
    task_schema["type_requirements"] = type_requirements

    contract: dict[str, object] = {
        "task_schema": task_schema,
        "response_format": (
            "Edit the complete JSON object at revision.path in place, then return a compact JSON "
            "confirmation."
            if revision_context
            else (
                "Edit the JSON working document at task_file.path in place, then return a compact "
                "JSON confirmation."
                if task_file_path is not None
                else "Return one complete JSON object with construction_notes, resources, and tasks."
            )
        ),
    }
    if blueprint.requires_environment:
        optional_fields.extend(["environment", "system_prompt", "interaction"])
        contract["environment_skill"] = environment_skill_payload(blueprint)

    payload: dict[str, object] = {
        "benchmark_context": {
            "objective": spec.objective,
            "task_types": [task_type.value for task_type in spec.task_types],
            "scale": spec.scale,
            "constraints": list(spec.constraints),
            "planner_notes": spec.planner_notes,
            "other_capabilities": other_capabilities,
        },
        "task_plan": {
            "capability": _capability_payload(dimension),
            "builder_job_id": blueprint.id,
            "task_design": construction,
        },
        "resources": {
            "context": resource_context,
            "selection": {
                "queries": list(blueprint.source_plan.search_queries),
                "suggested_urls": list(blueprint.source_plan.suggested_urls),
                "strategy": blueprint.source_plan.strategy,
                "requirements": list(blueprint.source_plan.requirements),
            },
        },
        "task_builder_contract": contract,
    }
    if config is not None and config.task_models:
        payload["available_models"] = {
            "models": [
                {"id": model.id, "model": model.model, "provider": model.provider or ""}
                for model in config.task_models
            ],
        }
    if revision_context:
        payload["revision"] = {
            key: revision_context[key]
            for key in ("path", "qc_issues", "instruction")
            if key in revision_context
        }
    elif task_file_path is not None:
        payload["task_file"] = {"path": str(task_file_path.resolve())}
    return payload


def _revision_context_for_job(
    revision_context: dict[str, object] | None,
    *,
    builder_job_id: str,
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
        and task["metadata"].get("builder_job_id") == builder_job_id
    ]
    raw_issues = revision_context.get("qc_issues")
    issues = (
        [issue for issue in raw_issues if isinstance(issue, dict)]
        if isinstance(raw_issues, list)
        else []
    )
    job_issues = [
        issue
        for issue in issues
        if issue.get("item_id") in {None, ""}
        or any(str(task.get("id") or "") == issue.get("item_id") for task in matched)
    ]
    affected_ids = {
        str(issue.get("item_id") or "")
        for issue in job_issues
        if str(issue.get("item_id") or "")
    }
    affected_tasks = [
        task for task in matched if str(task.get("id") or "") in affected_ids
    ]
    if job_issues and not affected_ids:
        affected_tasks = matched
    resource_ids = {
        resource_id
        for task in affected_tasks
        for resource_id in task.get("resource_ids", [])
        if isinstance(resource_id, str)
    }
    previous_resources = revision_context.get("previous_resources", [])
    return {
        **revision_context,
        "previous_tasks": affected_tasks,
        "previous_resources": [
            resource
            for resource in previous_resources
            if isinstance(resource, dict) and resource.get("id") in resource_ids
        ],
        "qc_issues": job_issues,
        "expected_replacement_count": len(affected_tasks),
        "instruction": (
            str(revision_context.get("instruction"))
            or (
                "Use read_candidate and update_candidate to inspect and edit the task-builder JSON at revision.path. "
                "Fix every listed QC issue, preserve the order and read-only ids of the tasks in "
                "that file, and do not add any other task from the TaskDesign."
            )
        ),
    }


def build_task_suite(
    spec: EvalSpec,
    blueprints: list[TaskBlueprint],
    config: BenchmarkConfig,
    *,
    revision_context_by_dimension: dict[str, dict[str, object]] | None = None,
    log: Callable[[str], None] | None = None,
    checkpoint_dir: str | Path | None = None,
    checkpoint_namespace: str = "initial",
) -> TaskSuite:
    progress_lock = Lock()

    def emit(message: str) -> None:
        if log is None:
            return
        with progress_lock:
            log(message)

    simplified = config.ablation_simplified_contract
    debug_root = (
        Path(config.task_builder_debug_dir).expanduser()
        if config.task_builder_debug_dir
        else None
    )
    checkpoint_root = Path(checkpoint_dir).expanduser() if checkpoint_dir is not None else None
    debug_invocation_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )

    if not spec.dimensions:
        raise ValueError("EvalSpec.dimensions must not be empty before task construction.")

    if config.environment_preflight and any(
        blueprint.environment_type == AgentEnvironmentType.docker_workspace
        for blueprint in blueprints
    ):
        require_docker_available(executable=config.docker_executable)

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
    stop_event = Event()

    def strict_error(blueprint: TaskBlueprint, message: str) -> RuntimeError:
        return RuntimeError(
            "Task builder LLM generation failed "
            f"for Builder job '{blueprint.id}' using model '{builder_settings.model}': {message}"
        )

    jobs: list[_BlueprintBuildJob] = []
    build_results_by_order: dict[int, _BlueprintBuildResult] = {}
    order = 0
    for dimension in spec.dimensions:
        dim_blueprints = blueprint_by_dimension.get(dimension.id, [])
        if not dim_blueprints:
            build_results_by_order[order] = _BlueprintBuildResult(
                order=order,
                resources=[],
                tasks=[],
                notes=[f"{dimension.id}: no TaskDesign Builder job supplied; skipping."],
            )
            order += 1
            continue
        for blueprint in dim_blueprints:
            jobs.append(
                _BlueprintBuildJob(
                    order=order,
                    dimension=dimension,
                    blueprint=blueprint,
                )
            )
            order += 1

    def checkpoint_path(job: _BlueprintBuildJob) -> Path | None:
        if checkpoint_root is None:
            return None
        return checkpoint_root / (
            f"{_debug_slug(checkpoint_namespace)}-{job.order:04d}-"
            f"{_debug_job_slug(job.dimension.id, job.blueprint.id)}.json"
        )

    def save_checkpoint(
        job: _BlueprintBuildJob,
        result: _BlueprintBuildResult,
        revision_context: dict[str, object] | None,
    ) -> None:
        path = checkpoint_path(job)
        if path is None:
            return
        write_json(
            path,
            {
                "schema_version": 1,
                "namespace": checkpoint_namespace,
                "order": job.order,
                "builder_job_id": job.blueprint.id,
                "dimension_id": job.dimension.id,
                "context_digest": _builder_checkpoint_digest(
                    spec, job, revision_context, checkpoint_namespace
                ),
                "resources": [resource.model_dump(mode="json") for resource in result.resources],
                "tasks": [task.model_dump(mode="json") for task in result.tasks],
                "notes": list(result.notes),
            },
        )

    def load_checkpoint(
        job: _BlueprintBuildJob,
        revision_context: dict[str, object] | None,
    ) -> _BlueprintBuildResult | None:
        path = checkpoint_path(job)
        if path is None:
            return None
        try:
            io_path = _io_path(path)
            if not io_path.is_file():
                return None
            payload = json.loads(io_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            if (
                payload.get("schema_version") != 1
                or payload.get("namespace") != checkpoint_namespace
                or payload.get("order") != job.order
                or payload.get("builder_job_id") != job.blueprint.id
                or payload.get("dimension_id") != job.dimension.id
                or payload.get("context_digest")
                != _builder_checkpoint_digest(spec, job, revision_context, checkpoint_namespace)
            ):
                return None
            resources = [TaskResource.model_validate(value) for value in payload.get("resources", [])]
            tasks = [TaskDefinition.model_validate(value) for value in payload.get("tasks", [])]
            notes = [str(value) for value in payload.get("notes", [])]
        except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            return None
        emit(f"  Task builder: resumed completed job {job.blueprint.id} from {path}.")
        return _BlueprintBuildResult(job.order, resources, tasks, notes)

    if jobs:
        emit(
            f"  Task builder: {len(jobs)} TaskDesign job(s) covering "
            f"{sum(job.blueprint.planned_task_count for job in jobs)} planned task(s) across "
            f"{len({job.dimension.id for job in jobs})} dimension(s)."
        )

    all_jobs = list(jobs)
    for job in all_jobs:
        revision = _revision_context_for_job(
            (revision_context_by_dimension or {}).get(job.dimension.id),
            builder_job_id=job.blueprint.id,
        )
        checkpoint = load_checkpoint(job, revision)
        if checkpoint is not None:
            build_results_by_order[job.order] = checkpoint
    jobs = [job for job in all_jobs if job.order not in build_results_by_order]
    if len(jobs) != len(all_jobs):
        emit(
            f"  Task builder: resumed {len(all_jobs) - len(jobs)} completed job(s); "
            f"{len(jobs)} job(s) remain."
        )
    job_progress_index = {job.order: index for index, job in enumerate(all_jobs, 1)}

    def job_label(job: _BlueprintBuildJob) -> str:
        allocation = ", ".join(
            f"{item.task_type.value}×{item.count}"
            for item in job.blueprint.task_type_allocation
        )
        return f"{job.dimension.id} {job.blueprint.planned_task_count} task(s) [{allocation}] ({job.blueprint.id})"

    def build_blueprint_job(job: _BlueprintBuildJob) -> _BlueprintBuildResult:
        dimension = job.dimension
        blueprint = job.blueprint
        label = job_label(job)
        debug_job_dir = (
            debug_root
            / _debug_job_slug(dimension.id, blueprint.id)
            / debug_invocation_id
            if debug_root is not None
            else None
        )

        def persist_builder_debug(
            *,
            attempt: int,
            status: str,
            raw_response: str | None = None,
            validation_issues: list[str] | None = None,
            error: Exception | None = None,
            parsed_keys: list[str] | None = None,
        ) -> None:
            if debug_job_dir is None:
                return
            phase = "initial" if attempt == 0 else "structural-repair"
            stem = f"attempt-{attempt + 1:02d}-{phase}"
            try:
                debug_job_dir.mkdir(parents=True, exist_ok=True)
                response_path = debug_job_dir / f"{stem}.response.txt"
                if raw_response is not None:
                    response_path.write_text(raw_response, encoding="utf-8")
                    emit(f"  Task builder: saved raw response debug: {response_path}.")
                diagnostics = {
                    "invocation_id": debug_invocation_id,
                    "dimension_id": dimension.id,
                    "builder_job_id": blueprint.id,
                    "model": builder_settings.model,
                    "backend": config.llm_backend,
                    "attempt": attempt + 1,
                    "phase": phase,
                    "status": status,
                    "response_file": response_path.name if response_path.exists() else None,
                    "response_bytes": response_path.stat().st_size if response_path.exists() else 0,
                    "parsed_top_level_keys": parsed_keys or [],
                    "validation_issues": validation_issues or [],
                    "error_type": type(error).__name__ if error is not None else None,
                    "error": str(error) if error is not None else None,
                }
                (debug_job_dir / f"{stem}.diagnostics.json").write_text(
                    json.dumps(diagnostics, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as exc:
                emit(f"  Task builder: could not save debug artifacts ({exc}).")

        emit(
            f"  Task builder: starting {job_progress_index[job.order]}/{len(all_jobs)} - "
            f"{label}."
        )
        job_revision = _revision_context_for_job(
            (revision_context_by_dimension or {}).get(dimension.id),
            builder_job_id=blueprint.id,
        )

        def finish_result(result: _BlueprintBuildResult) -> _BlueprintBuildResult:
            save_checkpoint(job, result, job_revision)
            return result

        if job_revision and not job_revision.get("qc_issues"):
            return _BlueprintBuildResult(
                order=job.order,
                resources=[],
                tasks=[],
                notes=[f"{label}: no task in this TaskDesign requires repair."],
            )
        source_candidates = _select_blueprint_sources(dimension, blueprint, config)
        local_resources = [
            _resource_from_source(source, f"{blueprint.id}_resource_{idx}")
            for idx, source in enumerate(source_candidates, 1)
        ]
        builder_work_dir = task_builder_work_dir(config, blueprint.id)
        initial_task_path: Path | None = None
        if job_revision:
            if builder_work_dir is None:
                raise strict_error(
                    blueprint,
                    "benchmark output_dir is required for file-based QC repair.",
                )
            revision_dir = builder_work_dir / "qc-repair" / debug_invocation_id
            revision_dir.mkdir(parents=True, exist_ok=True)
            best_path = revision_dir / "best.json"
            candidate_path = revision_dir / "candidate.json"
            best_path.write_text(
                json.dumps(
                    project_task_builder_document(
                        {
                            "construction_notes": "",
                            "resources": job_revision.get("previous_resources", []),
                            "tasks": job_revision.get("previous_tasks", []),
                        },
                        blueprint.task_designs[0].task_type,
                        source_backed=blueprint.source_strategy
                        in {"adapted", "reused", "imported_dataset"},
                        preserve_identity=True,
                        simplified=simplified,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            shutil.copyfile(best_path, candidate_path)
            job_revision = {**job_revision, "path": str(candidate_path.resolve())}
            emit(
                f"  Task builder: saved QC best and candidate JSON for {label}: {revision_dir}."
            )
        else:
            if builder_work_dir is None:
                raise strict_error(
                    blueprint,
                    "benchmark output_dir is required for file-based task construction.",
                )
            initial_dir = builder_work_dir / "initial" / debug_invocation_id
            initial_dir.mkdir(parents=True, exist_ok=True)
            initial_task_path = initial_dir / "candidate.json"
            initial_task_path.write_text(
                json.dumps(
                    task_builder_document_template(
                        blueprint.task_designs[0].task_type,
                        task_count=blueprint.planned_task_count,
                        challenge_effort=blueprint.task_designs[0].challenge_effort.value,
                        source_backed=blueprint.source_strategy
                        in {"adapted", "reused", "imported_dataset"},
                        simplified=simplified,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            emit(f"  Task builder: created working JSON for {label}: {initial_task_path}.")
        result_resources: list[TaskResource] = list(local_resources)
        result_tasks: list[TaskDefinition] = []
        result_notes: list[str] = []
        target_task_count = (
            int(job_revision.get("expected_replacement_count") or 0)
            if job_revision
            else blueprint.planned_task_count
        )
        planned_task_designs = [
            design
            for design in blueprint.task_designs
            for _ in range(design.task_count)
        ]
        planned_task_types = [design.task_type for design in planned_task_designs]
        if job_revision:
            planned_task_types = [
                TaskType(str(task.get("task_type")))
                for task in job_revision.get("previous_tasks", [])
                if isinstance(task, dict)
            ]
            design_by_id = {design.id: design for design in blueprint.task_designs}
            planned_task_designs = []
            for previous_task in job_revision.get("previous_tasks", []):
                if not isinstance(previous_task, dict):
                    continue
                metadata = previous_task.get("metadata")
                task_design_id = (
                    str(metadata.get("task_design_id") or "")
                    if isinstance(metadata, dict)
                    else ""
                )
                if task_design_id in design_by_id:
                    planned_task_designs.append(design_by_id[task_design_id])
                elif len(blueprint.task_designs) == 1:
                    planned_task_designs.append(blueprint.task_designs[0])
        def tag_task(task: TaskDefinition, task_design_id: str | None = None) -> TaskDefinition:
            if not task_design_id:
                matching_designs = [
                    design
                    for design in blueprint.task_designs
                    if design.task_type == task.task_type
                ]
                if len(matching_designs) == 1:
                    task_design_id = matching_designs[0].id
            task.metadata = {
                **task.metadata,
                "builder_job_id": blueprint.id,
                "builder_job_metadata": blueprint.metadata,
            }
            if task_design_id:
                task.metadata["task_design_id"] = task_design_id
            return task

        if not builder_settings.configured:
            raise strict_error(
                blueprint,
                "missing task-builder API key; configure the TaskBuilder role for task materialization.",
            )

        payload = _task_builder_payload(
            spec,
            dimension,
            blueprint,
            _source_context(
                source_candidates,
                config.research_brief if blueprint.source_strategy != "generated" else None,
            ),
            job_revision,
            task_file_path=initial_task_path,
            config=config,
        )
        payload["resources"]["available"] = [
            resource.model_dump(mode="json") for resource in local_resources
        ]

        def call_task_builder(
            call_payload: dict[str, object],
        ) -> str:
            task_type = blueprint.task_designs[0].task_type
            system_prompt = build_task_builder_prompt(
                task_type,
                source_strategy=blueprint.source_strategy,
                requires_environment=blueprint.requires_environment,
                simplified=simplified,
            )
            if blueprint.requires_environment:
                system_prompt += "\n\n" + environment_skill_system_prompt(blueprint)
            system_prompt += "\n\n" + build_task_builder_tool_prompt(
                task_type,
                source_backed=blueprint.source_strategy != "generated",
                include_image_tools=(
                    blueprint.environment_type == AgentEnvironmentType.docker_workspace
                ),
                include_vm_image_tools=(
                    blueprint.environment_type == AgentEnvironmentType.vm
                ),
            )
            debug_kwargs = (
                {"debug_dir": debug_job_dir / "tool-trace"}
                if debug_job_dir is not None
                else {}
            )
            tool_kwargs = {
                "include_source_tools": blueprint.source_strategy != "generated",
                "stop_event": stop_event,
                **debug_kwargs,
            }
            if blueprint.environment_type == AgentEnvironmentType.docker_workspace:
                tool_kwargs["include_image_tools"] = True
            if blueprint.environment_type == AgentEnvironmentType.vm:
                tool_kwargs["include_vm_image_tools"] = True
            raw_response, tool_notes = run_task_builder_tools(
                call_payload,
                system_prompt=system_prompt,
                config=config,
                **tool_kwargs,
            )
            result_notes.extend(tool_notes)
            revision = (
                call_payload.get("revision")
                if isinstance(call_payload.get("revision"), dict)
                else {}
            )
            task_file = (
                call_payload.get("task_file")
                if isinstance(call_payload.get("task_file"), dict)
                else {}
            )
            document_path = str(revision.get("path") or task_file.get("path") or "").strip()
            if document_path:
                raw_response = Path(document_path).read_text(encoding="utf-8")
            if document_path and not raw_response.strip():
                raise LLMFinalContentMissingError(
                    "TaskBuilder produced an empty task candidate file."
                )
            return raw_response

        def parse_builder_response(parsed: dict[str, object]) -> _ParsedBuilderResponse:
            attempt_resources: list[TaskResource] = list(local_resources)
            attempt_tasks: list[TaskDefinition] = []
            valid_tasks: list[TaskDefinition] = []
            attempt_notes: list[str] = []
            validation_issues: list[str] = []
            response_level_issues: list[str] = []
            parsed_resources = parsed.get("resources", []) if isinstance(parsed.get("resources"), list) else []
            parsed_tasks = parsed.get("tasks", []) if isinstance(parsed.get("tasks"), list) else []
            if parsed.get("construction_notes"):
                attempt_notes.append(str(parsed["construction_notes"]))
            if not parsed_tasks:
                keys = ", ".join(sorted(str(key) for key in parsed.keys()))
                raise ValueError(f"LLM returned no tasks; parsed object keys were [{keys}].")
            if job_revision and len(parsed_tasks) != target_task_count:
                raise ValueError(
                    f"LLM returned {len(parsed_tasks)} task object(s), "
                    f"but this repair requires exactly {target_task_count} for positional matching."
                )
            if len(parsed_tasks) > target_task_count:
                raise ValueError(
                    f"LLM returned {len(parsed_tasks)} task object(s), "
                    f"but this Builder job requires {target_task_count}."
                )
            parsed_task_resources: list[TaskResource] = []
            resource_aliases: dict[str, str] = {}
            seen_task_prompts: dict[str, str] = {}
            for idx, raw_resource in enumerate(parsed_resources, 1):
                if not isinstance(raw_resource, dict):
                    raise ValueError(f"resource #{idx} is not a JSON object.")
                resource = _resource_from_raw(raw_resource, f"{blueprint.id}_llm_resource_{idx}")
                raw_resource_id = str(raw_resource.get("id") or "").strip()
                existing_resource = next(
                    (
                        candidate
                        for candidate in attempt_resources
                        if (
                            candidate.kind,
                            candidate.uri,
                            candidate.title,
                        )
                        == (resource.kind, resource.uri, resource.title)
                    ),
                    None,
                )
                if existing_resource is not None:
                    resource = existing_resource
                else:
                    attempt_resources.append(resource)
                parsed_task_resources.append(resource)
                if raw_resource_id:
                    resource_aliases[raw_resource_id] = resource.id
                resource_aliases[f"resource_{idx}"] = resource.id
            duplicate_resource_ids = sorted(
                resource_id
                for resource_id, count in Counter(
                    resource.id for resource in attempt_resources
                ).items()
                if count > 1
            )
            if duplicate_resource_ids:
                issue = (
                    "Resource ids must be unique within this Builder job: "
                    + ", ".join(duplicate_resource_ids)
                )
                validation_issues.append(issue)
                response_level_issues.append(issue)
            known_resource_ids = {resource.id for resource in attempt_resources}
            if blueprint.source_strategy == "generated" and parsed_resources:
                issue = "generated source_plan.strategy requires an empty resources array."
                validation_issues.append(issue)
                response_level_issues.append(issue)
            expected_id_order = (
                [
                    str(task.get("id") or "")
                    for task in job_revision.get("previous_tasks", [])
                    if isinstance(task, dict) and str(task.get("id") or "")
                ]
                if job_revision
                else []
            )
            added_for_blueprint = 0
            for idx, raw_task in enumerate(parsed_tasks, 1):
                if not isinstance(raw_task, dict):
                    validation_issues.append(f"task #{idx} is not a JSON object.")
                    continue
                try:
                    task = _task_from_raw(
                        raw_task,
                        (
                            expected_id_order[idx - 1]
                            if idx <= len(expected_id_order)
                            else f"{blueprint.id}_task_{idx}"
                        ),
                        default_dimension_id=dimension.id,
                        default_task_type=planned_task_types[
                            min(idx - 1, len(planned_task_types) - 1)
                        ],
                    )
                except Exception as exc:
                    validation_issues.append(
                        f"task #{idx} could not be normalized ({type(exc).__name__}: {exc})."
                    )
                    continue
                task = _normalize_builder_asset_paths(task, builder_work_dir)
                task_issues: list[str] = []
                if not task.prompt.strip():
                    task_issues.append("Task prompt is required.")
                task.resource_ids = [
                    resource_aliases.get(resource_id, resource_id)
                    for resource_id in task.resource_ids
                ]
                planned_design = planned_task_designs[
                    min(idx - 1, len(planned_task_designs) - 1)
                ]
                task = tag_task(task, planned_design.id)
                planned_source_strategy = str(
                    planned_design.source_plan.get("strategy") or "generated"
                )
                if planned_source_strategy == "generated":
                    if task.resource_ids:
                        task_issues.append("generated tasks must not set resource_ids.")
                elif not task.resource_ids:
                    task_issues.append(
                        f"{planned_source_strategy} tasks must set "
                        "top-level resource_ids to the exact source ids they use. "
                        "metadata.source_ids does not bind task provenance."
                    )
                task = ensure_task_content_summary(
                    task,
                    blueprint,
                    local_resources or parsed_task_resources[-1:],
                )
                unknown_resource_ids = sorted(set(task.resource_ids) - known_resource_ids)
                if unknown_resource_ids:
                    task_issues.append(
                        "resource_ids reference unknown resources: "
                        + ", ".join(unknown_resource_ids)
                    )
                task_design_id = str(task.metadata.get("task_design_id") or "")
                task_design = next(
                    (
                        candidate
                        for candidate in blueprint.task_designs
                        if candidate.id == task_design_id
                    ),
                    None,
                )
                validation_blueprint = (
                    blueprint.model_copy(
                        update={
                            "task_design_ids": [task_design.id],
                            "task_designs": [task_design],
                        }
                    )
                    if task_design is not None
                    else blueprint
                )
                task_issues.extend(
                    task_structure_issues(
                        task,
                        dimension=dimension,
                        blueprint=validation_blueprint,
                        task_design=task_design,
                        require_challenge_effort_self_assessment=not simplified,
                        builder_work_dir=builder_work_dir,
                    )
                )
                if not task_design_id:
                    task_issues.append("Task metadata.task_design_id is required.")
                elif task_design is None:
                    task_issues.append(
                        f"Task metadata.task_design_id {task_design_id!r} is not in this Builder job."
                    )
                elif task.task_type != task_design.task_type:
                    task_issues.append(
                        f"Task task_type must match TaskDesign {task_design.id}: "
                        f"expected {task_design.task_type.value}, got {task.task_type.value}."
                    )
                if task.task_type not in set(planned_task_types):
                    task_issues.append(
                        f"Task task_type {task.task_type.value} is not allowed by this Builder job."
                    )
                duplicate_key = _task_duplicate_key(task)
                if duplicate_key in seen_task_prompts:
                    task_issues.append(
                        f"Task content duplicates {seen_task_prompts[duplicate_key]} within the same Builder job."
                    )
                elif duplicate_key:
                    seen_task_prompts[duplicate_key] = task.id
                validation_issues.extend(f"task #{idx} ({task.id}): {issue}" for issue in task_issues)
                attempt_tasks.append(task)
                if not task_issues:
                    valid_tasks.append(task)
                added_for_blueprint += 1
            if added_for_blueprint < target_task_count:
                validation_issues.append(
                    f"LLM produced {added_for_blueprint} usable task(s), "
                    f"but this Builder job requires {target_task_count} usable task(s)."
                )
            actual_type_counts = Counter(task.task_type for task in attempt_tasks)
            expected_type_counts = Counter(planned_task_types[:target_task_count])
            if actual_type_counts != expected_type_counts:
                validation_issues.append(
                    "Task type counts do not match this Builder job: "
                    f"expected {dict(expected_type_counts)}, got {dict(actual_type_counts)}."
                )
            actual_design_counts = Counter(
                str(task.metadata.get("task_design_id") or "") for task in attempt_tasks
            )
            expected_design_counts = Counter(
                design.id for design in planned_task_designs[:target_task_count]
            )
            if actual_design_counts != expected_design_counts:
                validation_issues.append(
                    "TaskDesign counts do not match this Builder job: "
                    f"expected {dict(expected_design_counts)}, got {dict(actual_design_counts)}."
                )
            if job_revision:
                expected_ids = set(expected_id_order)
                returned_ids = {task.id for task in attempt_tasks}
                if returned_ids != expected_ids:
                    validation_issues.append(
                        "Repair must preserve exactly the affected task ids: "
                        f"expected {sorted(expected_ids)}, got {sorted(returned_ids)}."
                    )
            return _ParsedBuilderResponse(
                resources=attempt_resources,
                tasks=attempt_tasks,
                valid_tasks=[] if response_level_issues else valid_tasks,
                notes=attempt_notes,
                validation_issues=validation_issues,
            )

        truncation_retries = max(
            0,
            int(getattr(config, "task_builder_truncation_retries", 3) or 0),
        )

        parsed: object | None = None
        raw = ""
        repair_attempts = max(0, int(getattr(config, "task_builder_repair_attempts", 2) or 0))
        last_validation_issues: list[str] = []
        last_failure_is_output = False
        last_truncation_error: LLMOutputTruncatedError | None = None
        best_partial_result: _ParsedBuilderResponse | None = None
        structural_repair_path: Path | None = None

        def prepare_structural_repair_file() -> Path:
            nonlocal structural_repair_path
            if structural_repair_path is not None:
                return structural_repair_path
            if builder_work_dir is None:
                raise strict_error(
                    blueprint,
                    "benchmark output_dir is required for file-based structural repair.",
                )
            revision_dir = builder_work_dir / "structural-repair" / debug_invocation_id
            revision_dir.mkdir(parents=True, exist_ok=True)
            best_path = revision_dir / "best.json"
            candidate_path = revision_dir / "candidate.json"
            source = raw
            if isinstance(parsed, dict):
                source = json.dumps(
                    project_task_builder_document(
                        parsed,
                        blueprint.task_designs[0].task_type,
                        source_backed=blueprint.source_strategy
                        in {"adapted", "reused", "imported_dataset"},
                        preserve_identity=bool(job_revision),
                        simplified=simplified,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            best_path.write_text(source, encoding="utf-8")
            shutil.copyfile(best_path, candidate_path)
            structural_repair_path = candidate_path
            emit(
                f"  Task builder: saved structural-repair candidate JSON for {label}: "
                f"{revision_dir}."
            )
            return candidate_path

        repair_fields = (
            "missing or inconsistent type-specific fields, rubric, Judge tools, challenge_effort, and "
            "metadata.challenge_effort_self_assessment fields"
            if not blueprint.requires_environment
            else
            "missing or inconsistent execution fields, scoring, package, challenge_effort, and "
            "metadata.challenge_effort_self_assessment fields"
        )
        for attempt in range(repair_attempts + 1):
            call_payload = payload
            if attempt > 0:
                repair_path = (
                    str(job_revision.get("path") or "")
                    if job_revision
                    else str(structural_repair_path or "")
                )
                repair_instruction = (
                    "Use read_candidate and update_candidate to inspect and edit the complete JSON object at revision.path. "
                    "Do not return a patch. Preserve the intended capability target and all unaffected "
                    "task content while fixing every listed structural issue. The tasks array in that "
                    f"file must contain exactly {target_task_count} complete task(s)."
                    if repair_path
                    else (
                        "Return a complete replacement JSON object with resources and tasks. "
                        "Do not return a patch. Preserve the intended capability target, but repair "
                        "all malformed JSON, incorrect top-level response types, and "
                        f"{repair_fields} that the listed issues identify. "
                        "Do not redesign or extensively modify unaffected task content. Preserve sound "
                        "prompts, fixtures, files, environment behavior, evaluator checks, scoring, and "
                        "metadata byte-for-byte where practical. The tasks array must contain "
                        f"exactly {target_task_count} complete task(s) with the required type counts."
                    )
                )
                call_payload = {
                    **payload,
                    "repair": {
                        "reason": "task_structure_validation_failed",
                        "attempt": attempt,
                        "max_repair_attempts": repair_attempts,
                        "issues": last_validation_issues,
                        "instruction": repair_instruction,
                    },
                }
                if repair_path:
                    call_payload.pop("task_file", None)
                    existing_revision = (
                        payload.get("revision")
                        if isinstance(payload.get("revision"), dict)
                        else {}
                    )
                    call_payload["revision"] = {
                        **existing_revision,
                        "path": repair_path,
                    }
                    contract = call_payload.get("task_builder_contract")
                    if isinstance(contract, dict):
                        call_payload["task_builder_contract"] = {
                            **contract,
                            "response_format": (
                                "Edit the complete JSON object at revision.path in place, then "
                                "return a compact JSON confirmation."
                            ),
                        }
            raw = ""
            parsed = None
            parsed_keys: list[str] = []
            response_received = False
            try:
                raw = call_task_builder(call_payload)
                response_received = True
                persist_builder_debug(
                    attempt=attempt,
                    status="response_received",
                    raw_response=raw,
                )
                parsed = extract_json(raw)
                if not isinstance(parsed, dict):
                    raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
                parsed_keys = sorted(str(key) for key in parsed)
                attempt_result = parse_builder_response(parsed)
            except LLMOutputTruncatedError as exc:
                last_failure_is_output = True
                last_truncation_error = exc
                last_validation_issues = [f"{type(exc).__name__}: {exc}"]
                persist_builder_debug(
                    attempt=attempt,
                    status="output_truncated",
                    validation_issues=last_validation_issues,
                    error=exc,
                )
                emit(
                    f"  Task builder: output still truncated after {truncation_retries} "
                    f"retry attempt(s) for {label}."
                )
                break
            except TaskBuilderCallError as exc:
                last_validation_issues = [f"{type(exc).__name__}: {exc}"]
                persist_builder_debug(
                    attempt=attempt,
                    status="call_failed",
                    validation_issues=last_validation_issues,
                    error=exc,
                )
                raise strict_error(blueprint, str(exc)) from exc
            except LLMFinalContentMissingError as exc:
                last_validation_issues = [f"{type(exc).__name__}: {exc}"]
                persist_builder_debug(
                    attempt=attempt,
                    status="final_content_missing",
                    validation_issues=last_validation_issues,
                    error=exc,
                )
                raise strict_error(blueprint, str(exc)) from exc
            except TaskBuilderTruncationSummaryError as exc:
                last_validation_issues = [f"{type(exc).__name__}: {exc}"]
                persist_builder_debug(
                    attempt=attempt,
                    status="truncation_summary_failed",
                    validation_issues=last_validation_issues,
                    error=exc,
                )
                raise strict_error(blueprint, str(exc)) from exc
            except CancelledError:
                raise
            except Exception as exc:
                last_failure_is_output = response_received
                last_validation_issues = [f"{type(exc).__name__}: {exc}"]
                persist_builder_debug(
                    attempt=attempt,
                    status="invalid_response",
                    validation_issues=last_validation_issues,
                    error=exc,
                    parsed_keys=parsed_keys,
                )
                if attempt < repair_attempts:
                    if not job_revision:
                        prepare_structural_repair_file()
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
            if attempt_result.valid_tasks:
                environment_issues, failed_task_ids = _preflight_builder_environments(
                    attempt_result.valid_tasks,
                    dimension=dimension,
                    blueprint=blueprint,
                    resources=attempt_result.resources,
                    config=config,
                    trace_dir=(
                        debug_job_dir
                        / "environment-preflight"
                        / f"attempt-{attempt + 1:02d}"
                        if debug_job_dir is not None
                        else None
                    ),
                )
                if environment_issues:
                    attempt_result.validation_issues.extend(environment_issues)
                    attempt_result.valid_tasks = [
                        task
                        for task in attempt_result.valid_tasks
                        if task.id not in failed_task_ids
                    ]
            if not attempt_result.validation_issues:
                persist_builder_debug(
                    attempt=attempt,
                    status="accepted",
                    parsed_keys=parsed_keys,
                )
                return finish_result(_BlueprintBuildResult(
                    order=job.order,
                    resources=attempt_result.resources,
                    tasks=attempt_result.tasks,
                    notes=result_notes + attempt_result.notes,
                ))
            if job_revision and attempt_result.valid_tasks and (
                best_partial_result is None
                or len(attempt_result.valid_tasks) > len(best_partial_result.valid_tasks)
            ):
                best_partial_result = attempt_result
            last_failure_is_output = True
            last_validation_issues = attempt_result.validation_issues
            persist_builder_debug(
                attempt=attempt,
                status="structural_validation_failed",
                validation_issues=last_validation_issues,
                parsed_keys=parsed_keys,
            )
            if attempt < repair_attempts:
                if not job_revision:
                    prepare_structural_repair_file()
                emit(
                    f"  Task builder: retrying {label} "
                    f"({attempt + 1}/{repair_attempts}) for "
                    f"{len(last_validation_issues)} structural issue(s)."
                )
                result_notes.append(
                    f"{blueprint.id}: structural validation failed; requesting builder repair "
                    f"({len(last_validation_issues)} issue(s))."
                )

        if last_truncation_error is not None:
            failure_message = (
                "output truncated after "
                f"{truncation_retries} retry attempt(s): "
                f"{type(last_truncation_error).__name__}: {last_truncation_error}"
            )
        else:
            failure_message = (
                "structural validation failed after "
                f"{repair_attempts} repair attempt(s): {'; '.join(last_validation_issues[:6])}"
            )
        if job_revision is not None and best_partial_result is not None:
            retained_resource_ids = {
                resource_id
                for task in best_partial_result.valid_tasks
                for resource_id in task.resource_ids
            }
            emit(
                f"  Task builder: keeping {len(best_partial_result.valid_tasks)} structurally valid "
                f"replacement(s) from {label}; its other previous tasks remain unchanged."
            )
            return finish_result(_BlueprintBuildResult(
                order=job.order,
                resources=[
                    resource
                    for resource in best_partial_result.resources
                    if resource.id in retained_resource_ids
                ],
                tasks=best_partial_result.valid_tasks,
                notes=result_notes + best_partial_result.notes,
            ))
        if job_revision is not None and last_failure_is_output:
            emit(
                f"  Task builder: no valid replacement produced for {label}; "
                "keeping its previous tasks."
            )
            result_notes.append(f"{blueprint.id}: {failure_message}")
            return _BlueprintBuildResult(
                order=job.order,
                resources=[],
                tasks=[],
                notes=result_notes,
            )
        raise strict_error(blueprint, failure_message)

    max_workers = max(1, int(getattr(config, "task_builder_max_workers", 4) or 1))
    completed_jobs = 0
    if len(jobs) <= 1 or max_workers == 1:
        for job in jobs:
            build_results_by_order[job.order] = build_blueprint_job(job)
            completed_jobs += 1
            emit(f"  Task builder: completed {completed_jobs}/{len(all_jobs)} - {job_label(job)}.")
    else:
        executor = ThreadPoolExecutor(max_workers=min(max_workers, len(jobs)))
        futures = {}
        try:
            futures = {executor.submit(build_blueprint_job, job): job for job in jobs}
            for future in as_completed(futures):
                result = future.result()
                build_results_by_order[result.order] = result
                completed_jobs += 1
                emit(
                    f"  Task builder: completed {completed_jobs}/{len(all_jobs)} - "
                    f"{job_label(futures[future])}."
                )
        except BaseException:
            stop_event.set()
            for future in futures:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown()

    resources: list[TaskResource] = []
    tasks: list[TaskDefinition] = []
    notes: list[str] = []
    for result_order in sorted(build_results_by_order):
        result = build_results_by_order[result_order]
        resources.extend(result.resources)
        tasks.extend(result.tasks)
        notes.extend(result.notes)

    _ensure_unique_task_ids(tasks)

    resources = _dedupe_resources(resources)
    canonical_resource_ids = {
        (resource.kind, resource.uri, resource.title): resource.id
        for resource in resources
    }
    for result in build_results_by_order.values():
        resource_id_map = {
            resource.id: canonical_resource_ids[(resource.kind, resource.uri, resource.title)]
            for resource in result.resources
        }
        for task in result.tasks:
            task.resource_ids = [
                resource_id_map.get(resource_id, resource_id)
                for resource_id in task.resource_ids
            ]
    blueprint_by_id = {blueprint.id: blueprint for blueprint in blueprints}
    resource_by_id = {resource.id: resource for resource in resources}
    items: list[BenchmarkItem] = []
    for task in tasks:
        blueprint = blueprint_by_id.get(str(task.metadata.get("builder_job_id") or ""))
        task_design = None
        if blueprint is not None:
            task_design_id = str(task.metadata.get("task_design_id") or "")
            task_design = next(
                (
                    candidate
                    for candidate in blueprint.task_designs
                    if candidate.id == task_design_id
                ),
                None,
            )
        dimension = next(
            (candidate for candidate in spec.dimensions if candidate.id == task.dimension_id),
            None,
        )
        items.append(
            pack_task_item(
                task,
                dimension,
                resource_by_id=resource_by_id,
                blueprint=blueprint,
                task_design=task_design,
            )
        )

    materialized_spec = spec.model_copy(
        update={
            "task_types": list(
                dict.fromkeys(item.task_type for item in items)
            ) or spec.task_types
        }
    )

    return TaskSuite(
        objective=materialized_spec.objective,
        spec=materialized_spec,
        dimensions=materialized_spec.dimensions,
        blueprints=blueprints,
        resources=resources,
        tasks=items,
        construction_notes="\n".join(notes),
    )
