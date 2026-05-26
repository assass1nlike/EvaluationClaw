"""Reporter: produce human-readable benchmark reports."""
from __future__ import annotations

from collections import Counter, defaultdict

from .types import BenchmarkDataset, EvalReport, EvalRun, ItemResult, QcReport, SourceKind, TargetSummary


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def _judge_instability_count(run: EvalRun) -> int:
    return sum(
        1
        for result in run.results
        if result.judge_reasoning and "judge_instability=true" in result.judge_reasoning
    )


def _is_source_backed(item: object) -> bool:
    source = getattr(item, "source", None)
    if source is None:
        return False
    return source.kind in {SourceKind.web, SourceKind.hf_dataset, SourceKind.lm_eval, SourceKind.imported} and bool(source.uri)


def _recommendations(run: EvalRun) -> list[str]:
    recs: list[str] = []
    item_by_id = {item.id: item for item in run.dataset.items}
    if run.qc_report.quality_score < 0.8:
        recs.append("Regenerate or repair items flagged by QC before treating scores as reliable.")
    if not run.results:
        recs.append("No target run was executed; use this package as a benchmark draft and run targets later.")
        return recs
    for summary in run.summaries:
        if summary.total_items == 0:
            continue
        if summary.errors == summary.total_items:
            recs.append(
                f"{summary.target_id}: all attempted items failed at runtime; fix API credentials or provider configuration before interpreting scores."
            )
            continue
        executed_dimension_ids = {
            item_by_id[result.item_id].dimension_id
            for result in run.results
            if result.target_id == summary.target_id and result.item_id in item_by_id
        }
        weak = [
            dimension_id
            for dimension_id, score in summary.score_by_dimension.items()
            if dimension_id in executed_dimension_ids and score < 0.4
        ]
        if weak:
            recs.append(
                f"{summary.target_id}: investigate low-scoring dimensions {', '.join(weak)} with targeted follow-up items."
            )
    return recs


def build_report(run: EvalRun) -> EvalReport:
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
        f"- Planned scale: {dataset.spec.scale}",
        f"- Planner critique score: {dataset.spec.critique.score:.1f}/5",
        "",
        "## Dimensions",
        "",
    ]
    dimension_rows = [
        [
            dimension.id,
            dimension.name,
            f"{dimension.weight:.2f}",
            dimension.target_difficulty.value,
            "yes" if dimension.needs_research else "no",
            dimension.description.replace("\n", " ")[:140],
        ]
        for dimension in dataset.spec.dimensions
    ]
    lines.append(_markdown_table(["ID", "Name", "Weight", "Target Difficulty", "Research", "Description"], dimension_rows))
    lines.extend(
        [
            "",
            "## Dataset",
            "",
            f"- Items generated: {len(dataset.items)}",
            f"- External source candidates: {len(dataset.sources)}",
            f"- Source-backed items: {sum(1 for item in dataset.items if _is_source_backed(item))}/{len(dataset.items)}",
            f"- Self-generated items: {sum(1 for item in dataset.items if item.source.kind == SourceKind.self_generated)}",
            "",
        ]
    )
    task_counts: dict[str, int] = defaultdict(int)
    difficulty_counts: dict[str, int] = defaultdict(int)
    item_source_counts: Counter[str] = Counter()
    candidate_source_counts: Counter[str] = Counter()
    for item in dataset.items:
        task_counts[item.task_type.value] += 1
        difficulty_counts[item.difficulty.value] += 1
        item_source_counts[item.source.kind.value] += 1
    for source in dataset.sources:
        candidate_source_counts[source.kind.value] += 1
    lines.append(
        _markdown_table(
            ["Bucket", "Count"],
            [[f"task:{key}", str(value)] for key, value in sorted(task_counts.items())]
            + [[f"difficulty:{key}", str(value)] for key, value in sorted(difficulty_counts.items())],
        )
    )
    lines.extend(["", "### Source Coverage", ""])
    source_rows = [[f"item_source:{key}", str(value)] for key, value in sorted(item_source_counts.items())]
    source_rows.extend(
        [[f"candidate_source:{key}", str(value)] for key, value in sorted(candidate_source_counts.items())]
    )
    if source_rows:
        lines.append(_markdown_table(["Bucket", "Count"], source_rows))
        lines.append("")
    if dataset.sources:
        source_preview_rows = [
            [source.kind.value, source.title or "-", source.uri[:140]]
            for source in dataset.sources[:10]
        ]
        lines.append(_markdown_table(["Kind", "Title", "URI"], source_preview_rows))
        lines.append("")
    lines.extend(
        [
            "",
            "## QC Gate",
            "",
            f"- Quality score: {_pct(qc.quality_score)}",
            f"- Passed items: {len(qc.passed_item_ids)}",
            f"- Rejected items: {len(qc.rejected_item_ids)}",
            f"- Issues: {len(qc.issues)}",
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

    instability_count = _judge_instability_count(run)
    if run.results:
        lines.extend(
            [
                "## Judge Audit",
                "",
                f"- Double-pass judge instability flags: {instability_count}",
                "",
            ]
        )

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
