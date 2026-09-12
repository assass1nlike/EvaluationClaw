"""Quality-control gate for generated benchmark suites."""
from __future__ import annotations

import json
from pathlib import Path

from ..types import (
    BenchmarkConfig,
    QcCategory,
    QcIssue,
    QcReport,
    QcSeverity,
    TaskSuite,
    TaskType,
)
from .common import _issue
from .dataset_checks import (
    _coverage_issues,
    _duplicate_issues,
    _near_duplicate_limit,
)
from .llm_checks import _llm_qc
from .static_checks import _static_item_issues


def _persist_qc_trace(
    trace_dir: Path,
    suite: TaskSuite,
    llm_trace: dict[str, object],
    report: QcReport | None,
) -> None:
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "suite.json").write_text(
        json.dumps(suite.model_dump(mode="json"), ensure_ascii=False, indent=2),
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
    if report is not None:
        (trace_dir / "report.json").write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def run_qc_gate(
    suite: TaskSuite,
    config: BenchmarkConfig,
    *,
    trace_dir: str | Path | None = None,
) -> QcReport:
    """Run MVP static QC plus optional LLM review."""
    if config.ablation_simplified_contract:
        return QcReport(
            passed_item_ids=[item.id for item in suite.tasks],
            summary="QC skipped (ablation-simplified-contract).",
        )
    issues: list[QcIssue] = []
    for item in suite.tasks:
        issues.extend(_static_item_issues(item))
    issues.extend(_duplicate_issues(suite.tasks, near_duplicate_limit=_near_duplicate_limit(suite, config)))
    issues.extend(_coverage_issues(suite, config.large_scale_item_threshold))
    llm_trace: dict[str, object] = {}
    try:
        issues.extend(_llm_qc(suite, config, trace=llm_trace, trace_dir=trace_dir))
    except Exception:
        if trace_dir is not None:
            _persist_qc_trace(Path(trace_dir), suite, llm_trace, None)
        raise

    rejected_ids = {
        issue.item_id
        for issue in issues
        if issue.item_id and issue.severity == QcSeverity.error
    }
    passed_ids = [item.id for item in suite.tasks if item.id not in rejected_ids]
    total = max(1, len(suite.tasks))
    penalty = sum(0.2 if issue.severity == QcSeverity.error else 0.05 for issue in issues)
    quality_score = max(0.0, min(1.0, 1.0 - penalty / total))
    summary = (
        f"QC completed: {len(passed_ids)}/{len(suite.tasks)} items passed, "
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
        _persist_qc_trace(Path(trace_dir), suite, llm_trace, report)
    return report
