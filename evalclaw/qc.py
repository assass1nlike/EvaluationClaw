"""Quality-control gate for generated benchmark datasets."""
from __future__ import annotations

import difflib
import json
from collections import Counter

from .llm import call_llm, extract_json
from .types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    Message,
    QcCategory,
    QcIssue,
    QcReport,
    QcSeverity,
    SourceKind,
    TaskType,
)

_SYSTEM = """\
你是 EvaluationClaw 的 QC Gate。你要审查 benchmark 是否能作为“对用户需求的好评估方案”。
你不仅要检查单题清晰度、答案可靠性、评分标准和覆盖面，也要做元评估：
- 这些维度是否真正对应 objective 和用户需求？
- 题型、source 策略、评分方式是否适合该需求？
- 是否有明显遗漏、偏题、过浅、过度依赖 judge、或为了难度/source 而引入偏差？
- 如果需要已有 benchmark/source，是否使用了适当且偏难的来源？
只返回纯 JSON，不要 markdown。格式：
{
  "issues": [
    {
      "item_id": "...",
      "severity": "warning",
      "category": "clarity",
      "message": "...",
      "suggested_action": "..."
    }
  ],
  "summary": "..."
}

severity 只能是 info/warning/error。
category 只能是 schema/duplicate/scoring/clarity/coverage/difficulty。
只有会导致题目不可执行或答案明显不可靠的问题才标 error。
"""


DIFFICULTY_RANK = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}


def _issue(
    item_id: str | None,
    severity: QcSeverity,
    category: QcCategory,
    message: str,
    suggested_action: str = "",
) -> QcIssue:
    return QcIssue(
        item_id=item_id,
        severity=severity,
        category=category,
        message=message,
        suggested_action=suggested_action,
    )


def _static_item_issues(item: BenchmarkItem) -> list[QcIssue]:
    issues: list[QcIssue] = []
    if not item.prompt.strip():
        issues.append(_issue(item.id, QcSeverity.error, QcCategory.schema, "Prompt is empty."))
    if len(item.prompt.strip()) < 20:
        issues.append(
            _issue(
                item.id,
                QcSeverity.warning,
                QcCategory.clarity,
                "Prompt is very short and may be under-specified.",
                "Add concrete context and expected behavior.",
            )
        )
    if item.task_type == TaskType.multiple_choice:
        if len(item.choices) < 2:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "Multiple-choice item has fewer than two choices.",
                )
            )
        if not item.answer:
            issues.append(
                _issue(item.id, QcSeverity.error, QcCategory.scoring, "Multiple-choice item lacks answer.")
            )
    if item.task_type == TaskType.yes_no and (item.answer or "").lower() not in {"yes", "no"}:
        issues.append(
            _issue(item.id, QcSeverity.error, QcCategory.scoring, "Yes/no item answer must be yes or no.")
        )
    if item.task_type in {TaskType.open_generation, TaskType.multi_turn, TaskType.agent_interaction} and not item.rubric:
        issues.append(
            _issue(
                item.id,
                QcSeverity.error,
                QcCategory.scoring,
                "Open, multi-turn, or agent item lacks a rubric.",
                "Add a concrete scoring rubric or deterministic environment scoring note.",
            )
        )
    if item.task_type == TaskType.short_answer and not item.answer and not item.rubric:
        issues.append(
            _issue(
                item.id,
                QcSeverity.error,
                QcCategory.scoring,
                "Short-answer item needs an exact answer or rubric.",
            )
        )
    if item.task_type == TaskType.code_execution and not item.test_code:
        issues.append(
            _issue(item.id, QcSeverity.error, QcCategory.scoring, "Code execution item lacks test_code.")
        )
    if item.task_type == TaskType.agent_interaction:
        env = item.metadata.get("agent_env")
        if env is not None and not isinstance(env, dict):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "Agent interaction item metadata.agent_env must be an object when provided.",
                )
            )
        if isinstance(env, dict) and env.get("type") == "code_sandbox":
            hidden_files = env.get("hidden_files")
            visible_files = env.get("visible_files") or env.get("files")
            if not isinstance(visible_files, dict):
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.schema,
                        "Code sandbox agent item needs metadata.agent_env.visible_files or files.",
                    )
                )
            if not isinstance(hidden_files, dict) and not env.get("test_command"):
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.warning,
                        QcCategory.scoring,
                        "Code sandbox item has no hidden_files and no explicit test_command.",
                        "Add hidden tests or a deterministic test command.",
                    )
                )
    return issues


def _duplicate_issues(items: list[BenchmarkItem]) -> list[QcIssue]:
    issues: list[QcIssue] = []
    for idx, item in enumerate(items):
        for other in items[idx + 1 :]:
            ratio = difflib.SequenceMatcher(None, item.prompt.lower(), other.prompt.lower()).ratio()
            if ratio >= 0.92:
                issues.append(
                    _issue(
                        other.id,
                        QcSeverity.warning,
                        QcCategory.duplicate,
                        f"Prompt is very similar to {item.id} (similarity {ratio:.2f}).",
                        "Rewrite one item to test a distinct behavior.",
                    )
                )
    return issues


def _coverage_issues(dataset: BenchmarkDataset) -> list[QcIssue]:
    issues: list[QcIssue] = []
    counts = Counter(item.dimension_id for item in dataset.items)
    task_counts = Counter(item.task_type for item in dataset.items)
    for dimension in dataset.spec.dimensions:
        dim_items = [item for item in dataset.items if item.dimension_id == dimension.id]
        if not dim_items:
            issues.append(
                _issue(
                    None,
                    QcSeverity.error,
                    QcCategory.coverage,
                    f"Dimension {dimension.id} has no generated items.",
                    "Generate at least one item for every planned dimension.",
                )
            )
            continue
        if dataset.spec.scale_budget.value == "high" and len(dim_items) < 2:
            issues.append(
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.coverage,
                    f"High-budget dimension {dimension.id} has only {len(dim_items)} item(s).",
                    "Add more targeted items or Loop 3 expansion before treating this as a deep evaluation.",
                )
            )
        target_rank = DIFFICULTY_RANK.get(dimension.target_difficulty.value, 4)
        low_items = [
            item.id
            for item in dim_items
            if DIFFICULTY_RANK.get(item.difficulty.value, 3) < target_rank
        ]
        if low_items:
            issues.append(
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.difficulty,
                    f"Dimension {dimension.id} has {len(low_items)} item(s) below target difficulty {dimension.target_difficulty.value}.",
                    "Increase item difficulty without drifting from the user's requested content.",
                )
            )
        if dimension.needs_research:
            backed = [
                item
                for item in dim_items
                if item.source.kind in {SourceKind.web, SourceKind.hf_dataset, SourceKind.lm_eval, SourceKind.imported}
            ]
            if not backed:
                issues.append(
                    _issue(
                        None,
                        QcSeverity.warning,
                        QcCategory.coverage,
                        f"Dimension {dimension.id} requested research but has no source-backed items.",
                        "Use high-quality external sources or explicitly document why generation is preferable.",
                    )
                )
    for task_type in dataset.spec.task_types:
        if task_counts[task_type] == 0:
            issues.append(
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.coverage,
                    f"Planned task type {task_type.value} has no generated items.",
                    "Generate at least one item for each planned task type or remove it from the spec.",
                )
            )
    return issues


def _llm_qc(dataset: BenchmarkDataset, config: BenchmarkConfig) -> list[QcIssue]:
    if not config.orchestrator_api_key:
        return []
    sample = [
        {
            "id": item.id,
            "dimension_id": item.dimension_id,
            "task_type": item.task_type.value,
            "difficulty": item.difficulty.value,
            "prompt": item.prompt[:1200],
            "choices": item.choices,
            "answer": item.answer,
            "rubric": item.rubric,
        }
        for item in dataset.items[:50]
    ]
    try:
        raw = call_llm(
            [
                Message(
                    role="user",
                    content=json.dumps(
                        {
                            "objective": dataset.spec.objective,
                            "scale_budget": dataset.spec.scale_budget.value,
                            "constraints": dataset.spec.constraints,
                            "planner_notes": dataset.spec.planner_notes,
                            "dimensions": [d.model_dump(mode="json") for d in dataset.spec.dimensions],
                            "items": sample,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            ],
            system=_SYSTEM,
            model=config.orchestrator_model,
            api_key=config.orchestrator_api_key,
            base_url=config.orchestrator_base_url,
            backend=config.llm_backend,
            max_tokens=4096,
        )
        data = extract_json(raw)
        if not isinstance(data, dict):
            return [
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.clarity,
                    f"LLM QC returned {type(data).__name__}; static QC was used as fallback.",
                    "Retry with a QC model that returns the requested object schema.",
                )
            ]
    except Exception as exc:
        return [
            _issue(
                None,
                QcSeverity.warning,
                QcCategory.clarity,
                f"LLM QC failed; static QC was used as fallback: {str(exc)[:240]}",
                "Retry with a smaller dataset, a different QC model, or local/static-only QC.",
            )
        ]
    issues: list[QcIssue] = []
    for raw_issue in data.get("issues", []):
        try:
            issues.append(
                QcIssue(
                    item_id=raw_issue.get("item_id"),
                    severity=QcSeverity(raw_issue.get("severity", "warning")),
                    category=QcCategory(raw_issue.get("category", "clarity")),
                    message=str(raw_issue.get("message", "")),
                    suggested_action=str(raw_issue.get("suggested_action", "")),
                )
            )
        except ValueError:
            continue
    return issues


def run_qc_gate(dataset: BenchmarkDataset, config: BenchmarkConfig) -> QcReport:
    """Run MVP static QC plus optional LLM review."""
    issues: list[QcIssue] = []
    for item in dataset.items:
        issues.extend(_static_item_issues(item))
    issues.extend(_duplicate_issues(dataset.items))
    issues.extend(_coverage_issues(dataset))
    issues.extend(_llm_qc(dataset, config))

    rejected_ids = {
        issue.item_id
        for issue in issues
        if issue.item_id and issue.severity == QcSeverity.error
    }
    passed_ids = [item.id for item in dataset.items if item.id not in rejected_ids]
    total = max(1, len(dataset.items))
    penalty = sum(0.2 if issue.severity == QcSeverity.error else 0.05 for issue in issues)
    quality_score = max(0.0, min(1.0, 1.0 - penalty / total))
    summary = (
        f"QC completed: {len(passed_ids)}/{len(dataset.items)} items passed, "
        f"{len(rejected_ids)} rejected, {len(issues)} issues."
    )
    return QcReport(
        issues=issues,
        passed_item_ids=passed_ids,
        rejected_item_ids=sorted(rejected_ids),
        quality_score=quality_score,
        summary=summary,
    )
