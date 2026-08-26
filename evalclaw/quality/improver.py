"""Loop 3 self-improvement: diagnose run outcomes and regenerate targeted items."""
from __future__ import annotations

import difflib
import json
import uuid
from collections import Counter, defaultdict
from queue import Empty, Queue
from threading import Thread
from typing import Callable

from ..construction.suite import build_task_suite
from ..execution.runner import run_eval
from ..models.llm import DEFAULT_MAX_OUTPUT_TOKENS, call_llm, extract_json
from ..models.roles import role_model_settings
from ..planning.task_planner import plan_blueprints_for_spec
from ..quality.qc import run_qc_gate
from ..types import (
    BenchmarkConfig,
    BenchmarkItem,
    EvalRun,
    ImprovementAction,
    ImprovementIteration,
    Message,
    QcReport,
    QcSeverity,
    TaskResource,
    TaskSuite,
    TaskTypeAllocation,
)

_SYSTEM = """\
You are the EvaluationClaw Loop 3 improver. You will see the eval spec, QC
issues, and model result summaries. Propose a small number of targeted
improvement actions. Do not give generic advice.

Use English for reasons, guidance, and notes unless you must quote non-English
benchmark content.

Return pure JSON only:
{
  "actions": [
    {
      "action_type": "regenerate_item",
      "dimension_id": "...",
      "item_id": "...",
      "reason": "...",
      "guidance": "..."
    }
  ],
  "notes": "..."
}

Allowed action_type values:
- regenerate_item: the item itself is flawed or scoring is unstable; rewrite an
  item in the same dimension.
- expand_weak_dimension: the model scored poorly in a dimension; add more
  fine-grained targeted items.
- keep: no change is needed.

scale_budget controls improvement depth:
- low: repair only blocking issues and use few actions; avoid expansion.
- mid: fix clear weak points and add key boundary items.
- high: dig into model weak points; prefer actions that confirm failure
  boundaries and distinguish random mistakes from systematic weaknesses. More
  fine-grained expansion is allowed.
"""


def _shorten(text: str | None, limit: int = 800) -> str:
    if not text:
        return ""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "..."


def _diagnose_locally(suite: TaskSuite, qc_report: QcReport, run: EvalRun) -> list[ImprovementAction]:
    actions: list[ImprovementAction] = []
    for issue in qc_report.issues:
        if issue.severity == QcSeverity.error and issue.item_id:
            item = next((candidate for candidate in suite.tasks if candidate.id == issue.item_id), None)
            actions.append(
                ImprovementAction(
                    action_type="regenerate_item",
                    dimension_id=item.dimension_id if item else None,
                    item_id=issue.item_id,
                    reason=issue.message,
                    guidance=issue.suggested_action or "Regenerate this item with a clearer prompt and rubric.",
                )
            )

    item_by_id = {item.id: item for item in suite.tasks}
    low_by_dimension: Counter[str] = Counter()
    for result in run.results:
        if result.error:
            continue
        if result.score < 0.4 and result.item_id in item_by_id:
            low_by_dimension[item_by_id[result.item_id].dimension_id] += 1
    for dimension_id, count in low_by_dimension.items():
        actions.append(
            ImprovementAction(
                action_type="expand_weak_dimension",
                dimension_id=dimension_id,
                reason=f"{count} executed item(s) scored below 0.4.",
                guidance="Generate one more targeted item exploring this weakness boundary.",
            )
        )
    return actions[:8]


def _loop3_budget_guidance(config: BenchmarkConfig) -> str:
    guidance = {
        "low": "LOW budget: repair only blocking QC/runtime issues and the clearest low-score failures.",
        "mid": "MID budget: repair issues and add targeted boundary items for clear weak dimensions.",
        "high": (
            "HIGH budget: dig deeper into weak dimensions. Prefer multiple targeted actions that isolate failure "
            "patterns, confirm persistent weaknesses, and increase task complexity without drifting from the user goal."
        ),
        "large": (
            "LARGE budget: prioritize systematic weak-slice expansion, source-backed replenishment, and targeted "
            "regression items across multiple dimensions."
        ),
        "xlarge": (
            "XLARGE budget: prioritize scalable slice-level repairs, source-backed expansion, deduplication, and "
            "sampling/QC strategy over hand-crafting many individual items."
        ),
    }
    return guidance.get(config.scale_budget.value, guidance["mid"])


def _loop3_action_limit(config: BenchmarkConfig) -> int:
    configured = max(0, int(config.loop3_max_actions))
    if config.scale_budget.value == "low":
        return min(configured, 2)
    if config.scale_budget.value == "high" and configured == 4:
        return 8
    if config.scale_budget.value == "large" and configured == 4:
        return 12
    if config.scale_budget.value == "xlarge" and configured == 4:
        return 16
    return configured


def _loop3_per_dimension_limit(config: BenchmarkConfig) -> int:
    if config.scale_budget.value == "low":
        return 1
    if config.scale_budget.value == "high":
        return 4
    if config.scale_budget.value == "large":
        return 6
    if config.scale_budget.value == "xlarge":
        return 8
    return 2


def _diagnosis_payload(
    suite: TaskSuite,
    qc_report: QcReport,
    run: EvalRun,
    config: BenchmarkConfig,
) -> dict:
    item_by_id = {item.id: item for item in suite.tasks}
    interesting_item_ids = {issue.item_id for issue in qc_report.issues if issue.item_id}
    low_or_error_results = []
    for result in run.results:
        if not result.error and result.score >= 0.4:
            continue
        item = item_by_id.get(result.item_id)
        interesting_item_ids.add(result.item_id)
        low_or_error_results.append(
            {
                "item_id": result.item_id,
                "target_id": result.target_id,
                "score": result.score,
                "error": result.error,
                "dimension_id": item.dimension_id if item else None,
                "task_type": item.task_type.value if item else None,
                "prompt_excerpt": _shorten(item.prompt if item else "", 700),
                "response_excerpt": _shorten(result.raw_response, 700),
                "judge_excerpt": _shorten(result.judge_reasoning, 500),
            }
        )

    candidate_items = []
    for item in suite.tasks:
        if item.id not in interesting_item_ids:
            continue
        candidate_items.append(
            {
                "id": item.id,
                "dimension_id": item.dimension_id,
                "task_type": item.task_type.value,
                "challenge_effort": item.challenge_effort.value,
                "prompt_excerpt": _shorten(item.prompt, 900),
                "assets": [asset.model_dump(mode="json") for asset in item.assets],
                "choices": [choice.model_dump(mode="json") for choice in item.choices],
                "correct_choice_ids": item.correct_choice_ids,
                "expected_text": item.expected_text,
                "rubric_excerpt": _shorten(item.rubric, 600),
                "judge_tools": [tool.model_dump(mode="json") for tool in item.judge_tools],
            }
        )

    return {
        "objective": suite.spec.objective,
        "scale_budget": suite.spec.scale_budget.value,
        "scale_budget_guidance": _loop3_budget_guidance(config),
        "task_types": [task_type.value for task_type in suite.spec.task_types],
        "dimensions": [
            {
                "id": dimension.id,
                "name": dimension.name,
                "description": _shorten(dimension.description, 500),
                "approach": _shorten(dimension.approach, 500),
                "challenge_effort": dimension.challenge_effort.value,
            }
            for dimension in suite.spec.dimensions
        ],
        "qc_issues": [issue.model_dump(mode="json") for issue in qc_report.issues[:30]],
        "summaries": [summary.model_dump(mode="json") for summary in run.summaries],
        "low_or_error_results": low_or_error_results[:20],
        "candidate_items": candidate_items[:30],
    }


def _call_loop3_llm_json(payload: dict, config: BenchmarkConfig) -> dict:
    result_queue: Queue[tuple[dict | None, BaseException | None]] = Queue(maxsize=1)
    settings = role_model_settings(config, "loop3")

    def _worker() -> None:
        try:
            raw = call_llm(
                [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
                system=_SYSTEM,
                **settings.call_kwargs(),
                backend=config.llm_backend,
                max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
                expect_json=True,
            )
            data = extract_json(raw)
            result_queue.put_nowait((data, None))
        except BaseException as exc:
            result_queue.put_nowait((None, exc))

    Thread(target=_worker, daemon=True).start()
    timeout_s = max(1, int(config.loop3_diagnosis_timeout_s))
    try:
        data, error = result_queue.get(timeout=timeout_s)
    except Empty as exc:
        raise TimeoutError(f"Loop 3 LLM diagnosis timed out after {timeout_s}s.") from exc
    if error is not None:
        raise error
    if data is None:
        raise ValueError("Loop 3 LLM diagnosis returned no JSON.")
    return data


def _diagnose_with_llm(
    suite: TaskSuite,
    qc_report: QcReport,
    run: EvalRun,
    config: BenchmarkConfig,
) -> tuple[list[ImprovementAction], str]:
    if config.loop3_diagnosis == "local" or not role_model_settings(config, "loop3").configured:
        return _diagnose_locally(suite, qc_report, run), "Local Loop 3 diagnosis."
    payload = _diagnosis_payload(suite, qc_report, run, config)
    try:
        data = _call_loop3_llm_json(payload, config)
    except Exception as exc:
        return _diagnose_locally(suite, qc_report, run), f"LLM Loop 3 diagnosis failed; used local fallback: {exc}"
    actions: list[ImprovementAction] = []
    for raw_action in data.get("actions", []):
        if not isinstance(raw_action, dict):
            continue
        action_type = str(raw_action.get("action_type", "keep"))
        if action_type == "keep":
            continue
        actions.append(
            ImprovementAction(
                action_type=action_type,
                dimension_id=raw_action.get("dimension_id"),
                item_id=raw_action.get("item_id"),
                reason=str(raw_action.get("reason", "")),
                guidance=str(raw_action.get("guidance", "")),
            )
        )
    if not actions:
        actions = _diagnose_locally(suite, qc_report, run)
    return actions[: max(8, _loop3_action_limit(config))], str(data.get("notes", ""))


def _replace_or_expand_items(
    suite: TaskSuite,
    actions: list[ImprovementAction],
    config: BenchmarkConfig,
    log: Callable[[str], None] | None = None,
) -> TaskSuite:
    by_dimension = {dimension.id: dimension for dimension in suite.spec.dimensions}
    replace_ids = {action.item_id for action in actions if action.action_type == "regenerate_item" and action.item_id}
    new_items: list[BenchmarkItem] = [item for item in suite.tasks if item.id not in replace_ids]
    item_by_id = {item.id: item for item in suite.tasks}
    merged_blueprints = list(suite.blueprints)
    merged_resources = list(suite.resources)
    generated_by_dimension: defaultdict[str, int] = defaultdict(int)
    per_dimension_limit = _loop3_per_dimension_limit(config)

    def is_duplicate(candidate: BenchmarkItem) -> bool:
        return any(
            difflib.SequenceMatcher(None, candidate.prompt.lower(), existing.prompt.lower()).ratio() >= 0.92
            for existing in new_items
        )

    for action in actions:
        if not action.dimension_id or action.dimension_id not in by_dimension:
            if log:
                log(f"  [Loop 3] Skipping action without known dimension: {action.action_type}")
            continue
        if action.action_type not in {"regenerate_item", "expand_weak_dimension"}:
            if log:
                log(f"  [Loop 3] Skipping unsupported action: {action.action_type}")
            continue
        if generated_by_dimension[action.dimension_id] >= per_dimension_limit:
            if log:
                log(f"  [Loop 3] Skipping {action.dimension_id}; per-dimension generation limit reached.")
            continue
        dimension = by_dimension[action.dimension_id]
        replaced_item = item_by_id.get(action.item_id or "")
        task_type = (
            replaced_item.task_type
            if replaced_item is not None
            else (dimension.task_types or suite.spec.task_types)[0]
        )
        scoped_dimension = dimension.model_copy(
            update={
                "task_types": [task_type],
                "task_type_allocation": [
                    TaskTypeAllocation(task_type=task_type, count=1)
                ],
                "target_item_count": 1,
            }
        )
        scoped_spec = suite.spec.model_copy(
            update={"dimensions": [scoped_dimension], "task_types": [task_type], "scale": 1}
        )
        if log:
            log(f"  [Loop 3] Generating 1 improved item for {dimension.id} ({action.action_type})...")
        accepted_item: BenchmarkItem | None = None
        accepted_blueprints: list | None = None
        accepted_resources: list[TaskResource] | None = None
        for _ in range(3):
            blueprints = plan_blueprints_for_spec(scoped_spec, config, log=log)
            blueprints = [
                blueprint.model_copy(
                    update={
                        "task_designs": [
                            design.model_copy(
                                update={
                                    "construction_requirements": [
                                        *design.construction_requirements,
                                        f"Loop 3 reason: {action.reason}",
                                        f"Loop 3 guidance: {action.guidance}",
                                    ]
                                }
                            )
                            for design in blueprint.task_designs
                        ]
                    }
                )
                for blueprint in blueprints
            ]
            partial_suite = build_task_suite(scoped_spec, blueprints, config, log=log)
            if not partial_suite.tasks:
                continue
            candidate = partial_suite.tasks[0]
            if is_duplicate(candidate):
                if log:
                    log(f"  [Loop 3] Discarding duplicate generated item for {dimension.id}.")
                continue
            new_id = f"{dimension.id}_loop3_{uuid.uuid4().hex[:8]}"
            metadata = {
                **candidate.metadata,
                "loop3_reason": action.reason,
                "loop3_guidance": action.guidance,
            }
            accepted_item = candidate.model_copy(update={"id": new_id, "metadata": metadata})
            accepted_blueprints = partial_suite.blueprints
            accepted_resources = partial_suite.resources
            if accepted_item:
                break
        if accepted_item is not None and accepted_blueprints is not None and accepted_resources is not None:
            new_items.append(accepted_item)
            merged_blueprints.extend(accepted_blueprints)
            merged_resources.extend(accepted_resources)
            generated_by_dimension[action.dimension_id] += 1

    def dedupe_resources(resources: list[TaskResource]) -> list[TaskResource]:
        deduped: list[TaskResource] = []
        seen: set[tuple[str, str, str]] = set()
        for resource in resources:
            key = (resource.kind, resource.uri, resource.title)
            if key not in seen:
                seen.add(key)
                deduped.append(resource)
        return deduped

    blueprint_by_id = {blueprint.id: blueprint for blueprint in merged_blueprints}
    materialized_types = list(
        dict.fromkeys(item.task_type for item in new_items)
    ) or suite.spec.task_types
    merged_spec = suite.spec.model_copy(update={"task_types": materialized_types})
    return suite.model_copy(
        update={
            "spec": merged_spec,
            "dimensions": suite.spec.dimensions,
            "blueprints": list(blueprint_by_id.values()),
            "resources": dedupe_resources(merged_resources),
            "tasks": new_items,
            "construction_notes": (
                suite.construction_notes.rstrip() + "\nLoop 3 improvement applied."
            ).strip(),
        }
    )


def run_loop3_improvement(
    suite: TaskSuite,
    qc_report: QcReport,
    run: EvalRun,
    config: BenchmarkConfig,
    *,
    iteration: int = 1,
    log: Callable[[str], None] | None = None,
) -> ImprovementIteration:
    """Diagnose and apply one self-improvement iteration."""
    if log:
        log(
            f"  [Loop 3] Diagnosing with mode={config.loop3_diagnosis}, "
            f"timeout={config.loop3_diagnosis_timeout_s}s..."
        )
    actions, notes = _diagnose_with_llm(suite, qc_report, run, config)
    max_actions = _loop3_action_limit(config)
    actions = actions[:max_actions]
    if log:
        log(f"  [Loop 3] Diagnosis produced {len(actions)} action(s).")
    if not actions:
        return ImprovementIteration(iteration=iteration, actions=[], notes=notes or "No improvements needed.")
    improved_suite = _replace_or_expand_items(suite, actions, config, log=log)
    if log:
        log(f"  [Loop 3] Improved suite has {len(improved_suite.tasks)} item(s).")
        log("  [Loop 3] Running improved QC...")
    improved_qc = run_qc_gate(improved_suite, config)
    if log:
        log("  [Loop 3] Rerunning targets on improved suite...")
    improved_run = run_eval(improved_suite, improved_qc, config)
    return ImprovementIteration(
        iteration=iteration,
        actions=actions,
        suite=improved_suite,
        qc_report=improved_qc,
        run=improved_run,
        notes=notes,
    )
