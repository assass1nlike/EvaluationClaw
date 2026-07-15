"""Reporter: produce human-readable benchmark reports."""
from __future__ import annotations

from collections import Counter, defaultdict

from ..types import (
    BenchmarkDataset,
    EvalReport,
    EvalRun,
    ItemResult,
    QcReport,
    ResearchBrief,
    SourceKind,
)
from .markdown import _markdown_table, _pct
from .run_sections import (
    _dedupe_sources,
    _detailed_item_lines,
    _failure_mode_rows,
    _is_source_backed,
    _item_result_table,
    _judge_audit_lines,
    _qc_summary_lines,
    _recommendations,
    _research_brief_lines,
    _run_provenance_lines,
    _score_semantics_lines,
    _source_mapping_lines,
    _task_suite_lines,
    _used_items,
    artifact_index_markdown,
)
from .safety import _is_safety_eval, _risk_labels, _risk_severity, _safety_audit_lines


def build_report(run: EvalRun, *, research_brief: ResearchBrief | None = None) -> EvalReport:
    """Build a Markdown report from an eval run."""
    dataset: BenchmarkDataset = run.dataset
    qc: QcReport = run.qc_report
    lines: list[str] = [
        f"# EvaluationClaw Report: {dataset.spec.id}",
        "",
        "## Objective",
        "",
        dataset.spec.objective,
        "",
        "## Planner Spec",
        "",
        f"- Subjects: {', '.join(dataset.spec.subjects)}",
        f"- Task types: {', '.join(t.value for t in dataset.spec.task_types)}",
        f"- Metrics: {', '.join(m.value for m in dataset.spec.metrics)}",
        f"- Scale budget: {dataset.spec.scale_budget.value}",
        f"- Planned item count: {dataset.spec.scale:g}",
        f"- Planner critique score: {dataset.spec.critique.score:.1f}/5",
        "",
        *_research_brief_lines(research_brief),
        *_score_semantics_lines(),
        *_run_provenance_lines(run),
        "## Dimensions",
        "",
    ]
    dimension_rows = [
        [
            dimension.id,
            dimension.name,
            f"{dimension.weight:.2f}",
            dimension.challenge_effort.value,
            "yes" if dimension.needs_research else "no",
            dimension.description.replace("\n", " ")[:140],
        ]
        for dimension in dataset.spec.dimensions
    ]
    lines.append(_markdown_table(["ID", "Name", "Weight", "Challenge Effort", "Research", "Description"], dimension_rows))
    used_items = _used_items(dataset, qc)
    rejected_count = len(dataset.items) - len(used_items)
    lines.extend(
        [
            "",
            "## Dataset",
            "",
            f"- Items generated: {len(dataset.items)}",
            f"- Items accepted for run: {len(used_items)}",
            f"- Items rejected by QC: {rejected_count}",
            f"- Batches: {len(dataset.batches)}",
            f"- External source candidates: {len(_dedupe_sources(dataset.sources))}",
            f"- Source-backed used items: {sum(1 for item in used_items if _is_source_backed(item))}/{len(used_items)}",
            f"- Self-generated used items: {sum(1 for item in used_items if item.source.kind == SourceKind.self_generated)}",
            "",
        ]
    )
    lines.extend(_task_suite_lines(dataset))
    task_counts: dict[str, int] = defaultdict(int)
    challenge_effort_counts: dict[str, int] = defaultdict(int)
    item_source_counts: Counter[str] = Counter()
    for item in used_items:
        task_counts[item.task_type.value] += 1
        challenge_effort_counts[item.challenge_effort.value] += 1
        item_source_counts[item.source.kind.value] += 1
    deduped_sources = _dedupe_sources(dataset.sources)
    lines.append(
        _markdown_table(
            ["Bucket", "Count"],
            [[f"task:{key}", str(value)] for key, value in sorted(task_counts.items())]
            + [[f"challenge_effort:{key}", str(value)] for key, value in sorted(challenge_effort_counts.items())],
        )
    )
    lines.extend(["", "### Source Coverage", ""])
    if dataset.batches:
        lines.extend(
            [
                "### Batch Plan",
                "",
                _markdown_table(
                    ["Batch", "Dimension", "Planned", "Materialized", "Source Target", "Generated Target", "QC Sample"],
                    [
                        [
                            batch.id,
                            batch.dimension_id,
                            str(batch.planned_item_count),
                            str(batch.materialized_item_count),
                            str(batch.source_backed_target),
                            str(batch.generated_target),
                            str(batch.qc_sample_size),
                        ]
                        for batch in dataset.batches
                    ],
                ),
                "",
            ]
        )
    source_rows = [[f"item_source:{key}", str(value)] for key, value in sorted(item_source_counts.items())]
    if source_rows:
        lines.append(_markdown_table(["Bucket", "Count"], source_rows))
        lines.append("")
    if deduped_sources:
        source_preview_rows = [
            [source.kind.value, source.title or "-", source.uri[:140]]
            for source in deduped_sources[:10]
        ]
        lines.append(_markdown_table(["Kind", "Title", "URI"], source_preview_rows))
        lines.append("")
    lines.extend(_source_mapping_lines(used_items))
    average_qc_issues = len(qc.issues) / max(1, len(dataset.items))
    lines.extend(
        [
            "",
            "## QC Gate",
            "",
            f"- Passed items: {len(qc.passed_item_ids)}",
            f"- Rejected items: {len(qc.rejected_item_ids)}",
            f"- Average QC issues: {average_qc_issues:.2f}",
            "",
        ]
    )
    issue_rows = [
        [
            issue.severity.value,
            issue.category.value,
            issue.item_id or "-",
            issue.message.replace("\n", " ")[:160],
        ]
        for issue in qc.issues[:25]
    ]
    if issue_rows:
        lines.append(_markdown_table(["Severity", "Category", "Item", "Message"], issue_rows))
        lines.append("")
    lines.extend(_qc_summary_lines(qc))

    lines.extend(["## Results", ""])
    summary_rows = [
        [
            summary.target_id,
            summary.model,
            _pct(summary.average_score),
            str(summary.total_items),
            str(summary.errors),
        ]
        for summary in run.summaries
    ]
    if summary_rows:
        lines.append(_markdown_table(["Target", "Model", "Average", "Items", "Errors"], summary_rows))
        lines.append("")
    else:
        lines.append("No target results were executed.")
        lines.append("")

    if run.results:
        lines.extend(_judge_audit_lines(run))

    if run.runner_artifacts:
        lines.extend(["## Runner Artifacts", ""])
        lm_eval = run.runner_artifacts.get("lm_eval")
        if isinstance(lm_eval, dict):
            rows = []
            for target_id, payload in lm_eval.items():
                if isinstance(payload, dict) and payload.get("error"):
                    rows.append([str(target_id), "failed", str(payload.get("error", ""))[:180]])
                elif isinstance(payload, dict):
                    rows.append([str(target_id), "completed", str(payload.get("results_dir", ""))])
            if rows:
                lines.append(_markdown_table(["Target", "Status", "Detail"], rows))
                lines.append("")

    if run.results:
        lines.extend(["## Item Results", ""])
        item_result_table = _item_result_table(run)
        if item_result_table:
            lines.append(item_result_table)
            lines.append("")

    if run.results and run.summaries:
        lines.extend(["## Scores By Dimension", ""])
        headers = ["Target"] + [dimension.id for dimension in dataset.spec.dimensions]
        rows: list[list[str]] = []
        for summary in run.summaries:
            rows.append(
                [summary.target_id]
                + [
                    _pct(summary.score_by_dimension[dimension.id])
                    if dimension.id in summary.score_by_dimension
                    else "-"
                    for dimension in dataset.spec.dimensions
                ]
            )
        lines.append(_markdown_table(headers, rows))
        lines.append("")

    if run.results:
        lines.extend(["## Failure Mode Summary", ""])
        failure_rows = _failure_mode_rows(run)
        if failure_rows:
            lines.append(_markdown_table(["Target", "Dimension", "Items", "Average", "Representative Evidence"], failure_rows))
        else:
            lines.append("No low-score or errored item clusters.")
        lines.append("")

    lines.extend(["## Example Failures", ""])
    item_by_id = {item.id: item for item in dataset.items}
    failures: list[ItemResult] = sorted(
        [result for result in run.results if result.error or result.score < 1.0],
        key=lambda result: (result.error is None, result.score),
    )[:8]
    if failures:
        for result in failures:
            item = item_by_id.get(result.item_id)
            prompt = item.prompt.replace("\n", " ")[:220] if item else result.item_id
            suffix = f" Error: {result.error}" if result.error else ""
            lines.append(
                f"- `{result.target_id}` score {_pct(result.score)} on `{result.item_id}`: {prompt}{suffix}"
            )
    else:
        lines.append("No failures to display.")
    lines.append("")

    lines.extend(_detailed_item_lines(run))

    lines.extend(_safety_audit_lines(run))

    recommendations = _recommendations(run)
    lines.extend(["## Recommendations", ""])
    if recommendations:
        for rec in recommendations:
            lines.append(f"- {rec}")
    else:
        lines.append("- Benchmark is ready for a larger run or deeper dynamic QC.")
    lines.append("")

    return EvalReport(
        title=f"EvaluationClaw Report: {dataset.spec.id}",
        markdown="\n".join(lines),
        summaries=run.summaries,
        recommendations=recommendations,
    )
