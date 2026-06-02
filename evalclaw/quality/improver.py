"""Loop 3 self-improvement: diagnose run outcomes and regenerate targeted items."""
from __future__ import annotations

import difflib
import json
import uuid
from collections import Counter, defaultdict
from queue import Empty, Queue
from threading import Thread
from typing import Callable

from ..execution.runner import run_eval
from ..generator import generate_dimension_items
from ..llm import call_llm, extract_json
from ..quality.qc import run_qc_gate
from ..types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    EvalRun,
    ImprovementAction,
    ImprovementIteration,
    Message,
    QcReport,
    QcSeverity,
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


def _diagnose_locally(dataset: BenchmarkDataset, qc_report: QcReport, run: EvalRun) -> list[ImprovementAction]:
    actions: list[ImprovementAction] = []
    for issue in qc_report.issues:
        if issue.severity == QcSeverity.error and issue.item_id:
            item = next((candidate for candidate in dataset.items if candidate.id == issue.item_id), None)
            actions.append(
                ImprovementAction(
                    action_type="regenerate_item",
                    dimension_id=item.dimension_id if item else None,
                    item_id=issue.item_id,
                    reason=issue.message,
                    guidance=issue.suggested_action or "Regenerate this item with a clearer prompt and rubric.",
                )
            )

    item_by_id = {item.id: item for item in dataset.items}
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
            "patterns, confirm persistent weaknesses, and increase difficulty without drifting from the user goal."
        ),
    }
    return guidance.get(config.scale_budget.value, guidance["mid"])


def _loop3_action_limit(config: BenchmarkConfig) -> int:
    configured = max(0, int(config.loop3_max_actions))
    if config.scale_budget.value == "low":
        return min(configured, 2)
    if config.scale_budget.value == "high" and configured == 4:
        return 8
    return configured


def _loop3_per_dimension_limit(config: BenchmarkConfig) -> int:
    if config.scale_budget.value == "low":
        return 1
    if config.scale_budget.value == "high":
        return 4
    return 2


def _diagnosis_payload(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    run: EvalRun,
    config: BenchmarkConfig,
) -> dict:
    item_by_id = {item.id: item for item in dataset.items}
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
    for item in dataset.items:
        if item.id not in interesting_item_ids:
            continue
        candidate_items.append(
            {
                "id": item.id,
                "dimension_id": item.dimension_id,
                "task_type": item.task_type.value,
                "difficulty": item.difficulty.value,
                "prompt_excerpt": _shorten(item.prompt, 900),
                "answer": item.answer,
                "rubric_excerpt": _shorten(item.rubric, 600),
            }
        )

    return {
        "objective": dataset.spec.objective,
        "scale_budget": dataset.spec.scale_budget.value,
        "scale_budget_guidance": _loop3_budget_guidance(config),
        "task_types": [task_type.value for task_type in dataset.spec.task_types],
        "dimensions": [
            {
                "id": dimension.id,
                "name": dimension.name,
                "description": _shorten(dimension.description, 500),
                "approach": _shorten(dimension.approach, 500),
                "target_difficulty": dimension.target_difficulty.value,
            }
            for dimension in dataset.spec.dimensions
        ],
        "qc_issues": [issue.model_dump(mode="json") for issue in qc_report.issues[:30]],
        "summaries": [summary.model_dump(mode="json") for summary in run.summaries],
        "low_or_error_results": low_or_error_results[:20],
        "candidate_items": candidate_items[:30],
    }


def _call_loop3_llm_json(payload: dict, config: BenchmarkConfig) -> dict:
    result_queue: Queue[tuple[dict | None, BaseException | None]] = Queue(maxsize=1)

    def _worker() -> None:
        try:
            raw = call_llm(
                [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
                system=_SYSTEM,
                model=config.orchestrator_model,
                api_key=config.orchestrator_api_key,
                base_url=config.orchestrator_base_url,
                backend=config.llm_backend,
                max_tokens=2048,
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
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    run: EvalRun,
    config: BenchmarkConfig,
) -> tuple[list[ImprovementAction], str]:
    if config.loop3_diagnosis == "local" or not config.orchestrator_api_key:
        return _diagnose_locally(dataset, qc_report, run), "Local Loop 3 diagnosis."
    payload = _diagnosis_payload(dataset, qc_report, run, config)
    try:
        data = _call_loop3_llm_json(payload, config)
    except Exception as exc:
        return _diagnose_locally(dataset, qc_report, run), f"LLM Loop 3 diagnosis failed; used local fallback: {exc}"
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
        actions = _diagnose_locally(dataset, qc_report, run)
    return actions[: max(8, _loop3_action_limit(config))], str(data.get("notes", ""))


def _replace_or_expand_items(
    dataset: BenchmarkDataset,
    actions: list[ImprovementAction],
    config: BenchmarkConfig,
    log: Callable[[str], None] | None = None,
) -> BenchmarkDataset:
    by_dimension = {dimension.id: dimension for dimension in dataset.spec.dimensions}
    replace_ids = {action.item_id for action in actions if action.action_type == "regenerate_item" and action.item_id}
    new_items: list[BenchmarkItem] = [item for item in dataset.items if item.id not in replace_ids]
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
        if log:
            log(f"  [Loop 3] Generating 1 improved item for {dimension.id} ({action.action_type})...")
        accepted: list[BenchmarkItem] = []
        for _ in range(3):
            items, _, _ = generate_dimension_items(dataset.spec, dimension, 1, config)
            for item in items:
                if is_duplicate(item):
                    if log:
                        log(f"  [Loop 3] Discarding duplicate generated item for {dimension.id}.")
                    continue
                item.id = f"{dimension.id}_loop3_{uuid.uuid4().hex[:8]}"
                item.metadata["loop3_reason"] = action.reason
                item.metadata["loop3_guidance"] = action.guidance
                accepted.append(item)
                break
            if accepted:
                break
        new_items.extend(accepted)
        generated_by_dimension[action.dimension_id] += len(accepted)

    return BenchmarkDataset(
        spec=dataset.spec,
        items=new_items,
        sources=dataset.sources,
        generation_notes=dataset.generation_notes + "\nLoop 3 improvement applied.",
    )


def run_loop3_improvement(
    dataset: BenchmarkDataset,
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
    actions, notes = _diagnose_with_llm(dataset, qc_report, run, config)
    max_actions = _loop3_action_limit(config)
    actions = actions[:max_actions]
    if log:
        log(f"  [Loop 3] Diagnosis produced {len(actions)} action(s).")
    if not actions:
        return ImprovementIteration(iteration=iteration, actions=[], notes=notes or "No improvements needed.")
    improved_dataset = _replace_or_expand_items(dataset, actions, config, log=log)
    if log:
        log(f"  [Loop 3] Improved dataset has {len(improved_dataset.items)} item(s).")
        log("  [Loop 3] Running improved QC...")
    improved_qc = run_qc_gate(improved_dataset, config)
    if log:
        log("  [Loop 3] Rerunning targets on improved dataset...")
    improved_run = run_eval(improved_dataset, improved_qc, config)
    return ImprovementIteration(
        iteration=iteration,
        actions=actions,
        dataset=improved_dataset,
        qc_report=improved_qc,
        run=improved_run,
        notes=notes,
    )
