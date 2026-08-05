"""Quality-control gate for generated benchmark datasets."""
from __future__ import annotations

import json
from pathlib import Path

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


def _persist_qc_trace(
    trace_dir: Path,
    dataset: BenchmarkDataset,
    llm_trace: dict[str, object],
    report: QcReport,
) -> None:
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "dataset.json").write_text(
        json.dumps(dataset.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    request = {
        key: llm_trace[key]
        for key in ("system_prompt", "request", "model", "provider", "base_url", "max_tokens")
        if key in llm_trace
    }
    (trace_dir / "llm-request.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (trace_dir / "llm-response.txt").write_text(
        str(llm_trace.get("raw_response") or ""),
        encoding="utf-8",
    )
    (trace_dir / "llm-parsed-response.json").write_text(
        json.dumps(llm_trace.get("parsed_response"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    diagnostics = {
        key: value
        for key, value in llm_trace.items()
        if key not in {"system_prompt", "request", "raw_response", "parsed_response"}
    }
    (trace_dir / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (trace_dir / "report.json").write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_qc_gate(
    dataset: BenchmarkDataset,
    config: BenchmarkConfig,
    *,
    trace_dir: str | Path | None = None,
) -> QcReport:
    """Run MVP static QC plus optional LLM review."""
    issues: list[QcIssue] = []
    for item in dataset.items:
        issues.extend(_static_item_issues(item))
        if (
            item.task_type == TaskType.generation
            and any(tool.tool == "reference_model_response" for tool in item.judge_tools)
            and config.run_targets
            and config.reference_model is None
        ):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "The reference_model_response judge tool requires BenchmarkConfig.reference_model.",
                    "Configure a reference model or remove that judge tool from the task design.",
                )
            )
    issues.extend(_duplicate_issues(dataset.items, near_duplicate_limit=_near_duplicate_limit(dataset, config)))
    issues.extend(_coverage_issues(dataset))
    issues.extend(_batch_issues(dataset))
    llm_trace: dict[str, object] = {}
    issues.extend(_llm_qc(dataset, config, trace=llm_trace))

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
    report = QcReport(
        issues=issues,
        passed_item_ids=passed_ids,
        rejected_item_ids=sorted(rejected_ids),
        quality_score=quality_score,
        summary=summary,
    )
    if trace_dir is not None:
        _persist_qc_trace(Path(trace_dir), dataset, llm_trace, report)
    return report
