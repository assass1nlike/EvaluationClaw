"""Quality-control gate for generated benchmark datasets."""
from __future__ import annotations

from ..types import (
    BenchmarkConfig,
    BenchmarkDataset,
    QcCategory,
    QcIssue,
    QcReport,
    QcSeverity,
    TaskType,
)
from .common import _issue
from .dataset_checks import (
    _batch_issues,
    _coverage_issues,
    _duplicate_issues,
    _near_duplicate_limit,
)
from .llm_checks import _llm_qc
from .static_checks import _static_item_issues


def run_qc_gate(dataset: BenchmarkDataset, config: BenchmarkConfig) -> QcReport:
    """Run MVP static QC plus optional LLM review."""
    issues: list[QcIssue] = []
    for item in dataset.items:
        issues.extend(_static_item_issues(item))
        if item.task_type == TaskType.pairwise_preference and config.reference_model is None:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "Pairwise preference item requires BenchmarkConfig.reference_model.",
                    "Pass --reference-model or regenerate without pairwise_preference items.",
                )
            )
    issues.extend(_duplicate_issues(dataset.items, near_duplicate_limit=_near_duplicate_limit(dataset, config)))
    issues.extend(_coverage_issues(dataset))
    issues.extend(_batch_issues(dataset))
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
