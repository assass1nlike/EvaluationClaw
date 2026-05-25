"""Loop 3 self-improvement: diagnose run outcomes and regenerate targeted items."""
from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict

from .generator import generate_dimension_items
from .llm import call_llm, extract_json
from .qc import run_qc_gate
from .runner import run_eval
from .types import (
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
你是 EvaluationClaw 的 Loop 3 改进器。你会看到评测 spec、QC 问题、模型结果摘要。
请提出少量有针对性的改进行动，不要泛泛而谈。

只返回纯 JSON：
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

action_type 可选：
- regenerate_item: 题目本身有问题或评分不稳定，重写同维度题目
- expand_weak_dimension: 某维度模型低分，补充更细粒度题
- keep: 无需改动
"""


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


def _diagnose_with_llm(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    run: EvalRun,
    config: BenchmarkConfig,
) -> tuple[list[ImprovementAction], str]:
    if config.loop3_diagnosis == "local" or not config.orchestrator_api_key:
        return _diagnose_locally(dataset, qc_report, run), "Local Loop 3 diagnosis."
    payload = {
        "spec": dataset.spec.model_dump(mode="json"),
        "qc_report": qc_report.model_dump(mode="json"),
        "summaries": [summary.model_dump(mode="json") for summary in run.summaries],
        "results": [result.model_dump(mode="json") for result in run.results[:50]],
        "items": [item.model_dump(mode="json") for item in dataset.items[:80]],
    }
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
    return actions[:8], str(data.get("notes", ""))


def _replace_or_expand_items(
    dataset: BenchmarkDataset,
    actions: list[ImprovementAction],
    config: BenchmarkConfig,
) -> BenchmarkDataset:
    by_dimension = {dimension.id: dimension for dimension in dataset.spec.dimensions}
    replace_ids = {action.item_id for action in actions if action.action_type == "regenerate_item" and action.item_id}
    new_items: list[BenchmarkItem] = [item for item in dataset.items if item.id not in replace_ids]
    generated_by_dimension: defaultdict[str, int] = defaultdict(int)

    for action in actions:
        if not action.dimension_id or action.dimension_id not in by_dimension:
            continue
        if action.action_type not in {"regenerate_item", "expand_weak_dimension"}:
            continue
        if generated_by_dimension[action.dimension_id] >= 2:
            continue
        dimension = by_dimension[action.dimension_id]
        items, _, _ = generate_dimension_items(dataset.spec, dimension, 1, config)
        for item in items:
            item.id = f"{dimension.id}_loop3_{uuid.uuid4().hex[:8]}"
            item.metadata["loop3_reason"] = action.reason
            item.metadata["loop3_guidance"] = action.guidance
        new_items.extend(items)
        generated_by_dimension[action.dimension_id] += len(items)

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
) -> ImprovementIteration:
    """Diagnose and apply one self-improvement iteration."""
    actions, notes = _diagnose_with_llm(dataset, qc_report, run, config)
    if not actions:
        return ImprovementIteration(iteration=iteration, actions=[], notes=notes or "No improvements needed.")
    improved_dataset = _replace_or_expand_items(dataset, actions, config)
    improved_qc = run_qc_gate(improved_dataset, config)
    improved_run = run_eval(improved_dataset, improved_qc, config)
    return ImprovementIteration(
        iteration=iteration,
        actions=actions,
        dataset=improved_dataset,
        qc_report=improved_qc,
        run=improved_run,
        notes=notes,
    )
