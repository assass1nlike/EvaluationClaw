"""Reporter: produce human-readable benchmark reports."""
from __future__ import annotations

from collections import Counter, defaultdict

from ..types import (
    AnalysisReport,
    EvalReport,
    EvalRun,
    ItemResult,
    LaajReport,
    QcReport,
    ResearchBrief,
    SourceKind,
)
from .markdown import _escape_cell, _markdown_table, _pct
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


def _source_kind_label(source: object) -> str:
    kind = getattr(source, "kind", None)
    return getattr(kind, "value", str(kind or ""))


def build_report(
    run: EvalRun,
    *,
    research_brief: ResearchBrief | None = None,
    analysis: AnalysisReport | None = None,
    laaj: LaajReport | None = None,
) -> EvalReport:
    """Build a Markdown report from an eval run."""
    suite = run.suite
    qc: QcReport = run.qc_report
    lines: list[str] = [
        f"# EvaluationClaw Report: {suite.spec.id}",
        "",
        "## Objective",
        "",
        suite.spec.objective,
        "",
        "## Planner Spec",
        "",
        f"- Subjects: {', '.join(suite.spec.subjects)}",
        f"- Task types: {', '.join(t.value for t in suite.spec.task_types)}",
        f"- Planned item count: {suite.spec.scale:g}",
        f"- Planner critique score: {suite.spec.critique.score:.1f}/5",
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
        for dimension in suite.spec.dimensions
    ]
    lines.append(_markdown_table(["ID", "Name", "Weight", "Challenge Effort", "Research", "Description"], dimension_rows))
    used_items = _used_items(suite, qc)
    rejected_count = len(suite.tasks) - len(used_items)
    lines.extend(
        [
            "",
            "## Dataset",
            "",
            f"- Items generated: {len(suite.tasks)}",
            f"- Items accepted for run: {len(used_items)}",
            f"- Items rejected by QC: {rejected_count}",
            f"- External source candidates: {len(_dedupe_sources(suite.resources))}",
            f"- Source-backed used items: {sum(1 for item in used_items if _is_source_backed(item))}/{len(used_items)}",
            f"- Self-generated used items: {sum(1 for item in used_items if item.source.kind == SourceKind.self_generated)}",
            "",
        ]
    )
    lines.extend(_task_suite_lines(suite))
    task_counts: dict[str, int] = defaultdict(int)
    challenge_effort_counts: dict[str, int] = defaultdict(int)
    item_source_counts: Counter[str] = Counter()
    for item in used_items:
        task_counts[item.task_type.value] += 1
        challenge_effort_counts[item.challenge_effort.value] += 1
        item_source_counts[item.source.kind.value] += 1
    deduped_sources = _dedupe_sources(suite.resources)
    lines.append(
        _markdown_table(
            ["Bucket", "Count"],
            [[f"task:{key}", str(value)] for key, value in sorted(task_counts.items())]
            + [[f"challenge_effort:{key}", str(value)] for key, value in sorted(challenge_effort_counts.items())],
        )
    )
    lines.extend(["", "### Source Coverage", ""])
    source_rows = [[f"item_source:{key}", str(value)] for key, value in sorted(item_source_counts.items())]
    if source_rows:
        lines.append(_markdown_table(["Bucket", "Count"], source_rows))
        lines.append("")
    if deduped_sources:
        source_preview_rows = [
            [_source_kind_label(source), source.title or "-", source.uri[:140]]
            for source in deduped_sources[:10]
        ]
        lines.append(_markdown_table(["Kind", "Title", "URI"], source_preview_rows))
        lines.append("")
    lines.extend(_source_mapping_lines(used_items))
    average_qc_issues = len(qc.issues) / max(1, len(suite.tasks))
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
    has_harness = any(summary.harness for summary in run.summaries)
    summary_rows = [
        [
            summary.target_id,
            summary.model,
            *([summary.harness or "native"] if has_harness else []),
            _pct(summary.average_score),
            str(summary.total_items),
            str(summary.errors),
        ]
        for summary in run.summaries
    ]
    if summary_rows:
        headers = ["Target", "Model"]
        if has_harness:
            headers.append("Harness")
        lines.append(_markdown_table(headers + ["Average", "Items", "Errors"], summary_rows))
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
        headers = ["Target"] + [dimension.id for dimension in suite.spec.dimensions]
        rows: list[list[str]] = []
        for summary in run.summaries:
            rows.append(
                [summary.target_id]
                + [
                    _pct(summary.score_by_dimension[dimension.id])
                    if dimension.id in summary.score_by_dimension
                    else "-"
                    for dimension in suite.spec.dimensions
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
    item_by_id = {item.id: item for item in suite.tasks}
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

    if analysis is not None:
        lines.extend(
            [
                "## Model Performance Analysis",
                "",
                analysis.analysis,
                "",
                f"- Strategy: `{analysis.strategy}`",
                f"- Verification iterations: {len(analysis.iterations)}",
                f"- Verification tasks: {sum(len(item.suite.tasks) for item in analysis.iterations if item.suite is not None)}",
                "",
            ]
        )
        if analysis.error:
            lines.extend([f"Analysis status: {analysis.status}. {analysis.error}", ""])
        if analysis.benchmark is not None:
            lines.extend(["### Benchmark by Model Weakness", ""])
            if not analysis.benchmark:
                lines.extend(["No supported, in-scope weakness tasks selected.", ""])
            for group in analysis.benchmark:
                lines.extend([f"#### {group.name}", "", group.description, ""])
                lines.append(_markdown_table(
                    ["Source", "Task", "Target"],
                    [
                        [
                            "Main run" if item.iteration == 0 else f"Iteration {item.iteration}",
                            item.item_id,
                            item.target_id,
                        ]
                        for item in group.items
                    ],
                ))
                lines.append("")

    if laaj is not None:
        metrics = [
            ("Clarity", laaj.clarity),
            ("Correctness", laaj.correctness),
            ("Faithfulness", laaj.faithfulness),
            ("Diversity", laaj.diversity),
        ]
        if laaj.systematicness is not None:
            metrics.append(("Analyser systematicness", laaj.systematicness))
        if laaj.credibility is not None:
            metrics.append(("Analyser credibility", laaj.credibility))
        lines.extend(
            [
                "## LLM-as-a-Judge Quality Evaluation",
                "",
                f"- Judge model: `{laaj.model}`",
                f"- Evaluated items: {len(laaj.evaluated_item_ids)}/{laaj.total_item_count}",
                "",
                _markdown_table(
                    ["Criterion", "Score (1-5)", "Reasoning"],
                    [
                        [label, f"{metric.score:.1f}", _escape_cell(metric.reasoning, 320)]
                        for label, metric in metrics
                    ],
                ),
                "",
            ]
        )
        if laaj.item_results:
            lines.extend([
                "Clarity, correctness, and faithfulness are equally weighted per-task means. "
                "Diversity and the Analyser metrics are overall judgments.",
                "",
                _markdown_table(
                    ["Task", "Criterion", "Score (1-5)", "Reasoning"],
                    [
                        [item.item_id, name.capitalize(), str(getattr(item, name).score),
                         _escape_cell(getattr(item, name).reasoning, 320)]
                        for item in laaj.item_results
                        for name in ("clarity", "correctness", "faithfulness")
                    ],
                ),
                "",
            ])

    if laaj is not None and laaj.contamination is not None:
        contamination = laaj.contamination
        fraction = contamination.confirmed_overlap_fraction
        score = contamination.conditional_score
        matched = sum(bool(item.matches) for item in contamination.items)
        scored = sum(item.contamination is not None for item in contamination.items)
        lines.extend([
            "### Contamination Resistance", "",
            f"- Items assessed: {len(contamination.items)}/{contamination.total_item_count}",
            f"- Failed assessments: {sum(item.status == 'failed' for item in contamination.items)}; "
            f"not searchable as text: {sum(item.status == 'not_searchable' for item in contamination.items)}",
            f"- Confirmed overlap: {matched}/{len(contamination.items)}"
            + (f" ({_pct(fraction)})" if fraction is not None else ""),
            f"- Conditional score (confirmed matches only): {score:.2f}/5 ({scored} items)"
            if score is not None else "- Conditional score: not available; no scored confirmed matches.",
            f"- Per-item budget: {contamination.max_queries_per_item} queries, "
            f"{contamination.max_sources_per_item} source URLs, {contamination.source_character_limit} characters per document.",
            "- No confirmed match does not establish absence of contamination or training-data membership.",
            "",
        ])
        if contamination.max_tool_calls_per_item is not None:
            lines.extend([
                f"Research-agent budget: {contamination.max_tool_calls_per_item} tool calls per item. "
                f"Minimum exact overlap: {contamination.min_overlap_chars} characters after whitespace normalization.", "",
            ])
        for item in contamination.items:
            lines.extend([
                f"#### {item.item_id}", "",
                f"Status: {item.status}. Score: {item.contamination.score}/5."
                if item.contamination is not None else f"Status: {item.status}. Score: not assigned.",
                "",
            ])
            if item.contamination is not None:
                lines.extend([item.contamination.reasoning, ""])
            if item.research_summary:
                lines.extend([item.research_summary, ""])
            if item.stop_reason:
                lines.extend([f"Research ended: {item.stop_reason}; {item.tool_calls} tool calls.", ""])
            lines.extend(f"- Source: {url}" for url in item.checked_urls)
            lines.extend(f"- Unresolved lead: {url}" for url in item.unresolved_urls)
            lines.extend(f"- Limitation: {limitation}" for limitation in item.limitations)
            lines.append("")

    if laaj is not None and laaj.iteration_reports:
        lines.extend(["### Iteration Quality Evaluation", "",
                      "Each iteration is evaluated separately against the original user goal. "
                      "Contamination scores are conditional on confirmed matches.", ""])
        for number, result in sorted(laaj.iteration_reports.items()):
            rows = [
                [name.capitalize(), f"{getattr(result, name).score:.2f}",
                 _escape_cell(getattr(result, name).reasoning, 320)]
                for name in ("clarity", "correctness", "faithfulness", "diversity")
            ]
            contamination = result.contamination
            if contamination is not None:
                score = contamination.conditional_score
                rows.append([
                    "Contamination resistance", f"{score:.2f}" if score is not None else "Not assigned",
                    f"Assessed {len(contamination.items)}/{contamination.total_item_count} items; "
                    f"confirmed overlap in {sum(bool(item.matches) for item in contamination.items)}; "
                    f"failed assessments: {sum(item.status == 'failed' for item in contamination.items)}. "
                    "No confirmed match does not establish absence of contamination.",
                ])
            lines.extend([
                f"#### Iteration {number}", "",
                f"Evaluated items: {len(result.evaluated_item_ids)}/{result.total_item_count}", "",
                _markdown_table(["Criterion", "Score (1-5)", "Reasoning"], rows), "",
            ])

    recommendations = _recommendations(run)
    lines.extend(["## Recommendations", ""])
    if recommendations:
        for rec in recommendations:
            lines.append(f"- {rec}")
    else:
        lines.append("- Benchmark is ready for a larger run or deeper dynamic QC.")
    lines.append("")

    return EvalReport(
        title=f"EvaluationClaw Report: {suite.spec.id}",
        markdown="\n".join(lines),
        summaries=run.summaries,
        recommendations=recommendations,
    )
