"""Reusable Markdown report sections for benchmark runs."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from ..types import (
    BenchmarkItem,
    EvalRun,
    ItemResult,
    QcReport,
    ResearchBrief,
    SourceKind,
    TaskSuite,
    TaskType,
)
from .markdown import (
    _clip,
    _code_block,
    _escape_cell,
    _first_sentence,
    _markdown_table,
    _parse_json,
    _pct,
)


def _source_label(item: object) -> str:
    source = getattr(item, "source", None)
    if source is None:
        return "-"
    title = source.title or source.uri or source.kind.value
    return f"{source.kind.value}: {title}"


def _dedupe_sources(sources: list[object]) -> list[object]:
    deduped: list[object] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        kind = getattr(getattr(source, "kind", None), "value", str(getattr(source, "kind", "")))
        key = (kind, getattr(source, "uri", ""), getattr(source, "title", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped

def _judge_instability_count(run: EvalRun) -> int:
    return sum(
        1
        for result in run.results
        if result.judge_reasoning and "judge_instability=true" in result.judge_reasoning
    )


def _judge_failure_count(run: EvalRun) -> int:
    return sum(
        1
        for result in run.results
        if result.error and result.judge_reasoning and result.error == result.judge_reasoning
    )


def _is_source_backed(item: object) -> bool:
    metadata = getattr(item, "metadata", {})
    if isinstance(metadata, dict):
        package = metadata.get("agent_task_package")
        if isinstance(package, dict):
            provenance = package.get("resource_provenance")
            if isinstance(provenance, dict) and provenance.get("source_kind") == "generated_fixture":
                return False
    source = getattr(item, "source", None)
    if source is None:
        return False
    return source.kind in {SourceKind.web, SourceKind.hf_dataset, SourceKind.lm_eval, SourceKind.imported} and bool(source.uri)


def _recommendations(run: EvalRun) -> list[str]:
    recs: list[str] = []
    item_by_id = {item.id: item for item in run.suite.tasks}
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


def _failure_mode_rows(run: EvalRun) -> list[list[str]]:
    item_by_id = {item.id: item for item in run.suite.tasks}
    grouped: dict[tuple[str, str], list[ItemResult]] = defaultdict(list)
    for result in run.results:
        item = item_by_id.get(result.item_id)
        dimension_id = item.dimension_id if item else "-"
        if result.error or result.score < 0.8:
            grouped[(result.target_id, dimension_id)].append(result)

    rows: list[list[str]] = []
    for (target_id, dimension_id), results in sorted(grouped.items()):
        worst = min(results, key=lambda result: result.score)
        evidence = worst.error or _first_sentence(worst.judge_reasoning or "")
        rows.append(
            [
                target_id,
                dimension_id,
                str(len(results)),
                _pct(sum(result.score for result in results) / len(results)),
                _escape_cell(evidence, 220),
            ]
        )
    return rows


def _score_semantics_lines() -> list[str]:
    return [
        "## Score Semantics",
        "",
        "- Direction: higher is better unless a custom runner explicitly documents otherwise.",
        "- Normalized range: `0.0` to `1.0`.",
        "- LLM-judged open responses use the item rubric. The default judge schema expects a raw `1-5` score and normalizes it to `0.2-1.0`; deterministic runners may emit `0.0`, partial credit, or `1.0` directly.",
        "- Runner or evaluator errors are counted separately from model performance and excluded from target averages.",
        "- Suggested interpretation: `>= 0.80` strong/pass, `0.50-0.79` review, `< 0.50` weak/fail. Domain owners can override these thresholds.",
        "",
    ]


def _run_provenance_lines(run: EvalRun) -> list[str]:
    results = run.results
    latencies = [result.latency_ms for result in results if result.latency_ms is not None]
    total_latency = sum(latencies) if latencies else None
    avg_latency = total_latency / len(latencies) if total_latency is not None and latencies else None
    target_rows = [
        [
            summary.target_id,
            summary.model,
            str(summary.total_items),
            str(summary.errors),
            _pct(summary.average_score),
        ]
        for summary in run.summaries
    ]
    lines = [
        "## Run Provenance",
        "",
        f"- Suite created at: `{run.suite.created_at}`",
        f"- Run created at: `{run.created_at}`",
        f"- Evaluated results: {len(results)}",
        f"- Target count: {len(run.summaries)}",
        f"- Total recorded latency: {total_latency} ms" if total_latency is not None else "- Total recorded latency: not captured",
        f"- Average recorded latency: {avg_latency:.0f} ms/item" if avg_latency is not None else "- Average recorded latency: not captured",
        "- Token and cost usage: not captured by the current direct runner unless a provider-specific artifact records it.",
        "",
    ]
    if target_rows:
        lines.append(_markdown_table(["Target", "Model", "Items", "Errors", "Average"], target_rows))
        lines.append("")
    return lines


def _used_items(suite: TaskSuite, qc: QcReport) -> list[object]:
    passed = set(qc.passed_item_ids)
    return [item for item in suite.tasks if item.id in passed]


def _source_mapping_lines(items: list[object]) -> list[str]:
    rows = [
        [
            item.id,
            item.dimension_id,
            item.task_type.value,
            item.source.kind.value,
            _escape_cell(item.source.title or "-", 120),
            _escape_cell(item.source.uri or "-", 160),
        ]
        for item in items
    ]
    lines = ["### Source To Used Item Mapping", ""]
    if rows:
        lines.append(_markdown_table(["Item", "Dimension", "Task Type", "Source Kind", "Source Title", "URI"], rows))
    else:
        lines.append("No items available.")
    lines.append("")
    return lines


def _suite_task_env(task: object) -> str:
    metadata = getattr(task, "metadata", {})
    if isinstance(metadata, dict):
        agent_env = metadata.get("agent_env")
        if isinstance(agent_env, dict):
            return str(agent_env.get("type") or "-")
    return "-"


def _task_suite_lines(suite: TaskSuite) -> list[str]:
    lines = [
        "## Task Construction",
        "",
        f"- Task suite: {suite.id}",
        f"- Tasks: {len(suite.tasks)}",
        f"- Resources: {len(suite.resources)}",
        f"- Builder jobs: {len(suite.builder_jobs)}",
        "",
    ]
    if suite.builder_jobs:
        rows = [
            [
                blueprint.id,
                blueprint.dimension_id,
                ", ".join(
                    f"{item.task_type.value}×{item.count}"
                    for item in blueprint.task_type_allocation
                ),
                str(blueprint.planned_task_count),
                blueprint.environment_type.value if blueprint.environment_type else "-",
                blueprint.title,
            ]
            for blueprint in suite.builder_jobs
        ]
        lines.extend([
            _markdown_table(
                ["Builder Job", "Dimension", "Types", "Tasks", "Env", "TaskDesign"],
                rows,
            ),
            "",
        ])
    if suite.resources:
        rows = [
            [
                resource.id,
                resource.kind,
                resource.title or "-",
                resource.uri[:120] or "-",
            ]
            for resource in suite.resources[:10]
        ]
        lines.extend([_markdown_table(["Resource", "Kind", "Title", "URI"], rows), ""])
    if suite.tasks:
        rows = [
            [
                task.id,
                task.dimension_id,
                task.task_type.value,
                _suite_task_env(task),
                _escape_cell(task.prompt, 120),
            ]
            for task in suite.tasks[:10]
        ]
        lines.extend([_markdown_table(["Task", "Dimension", "Type", "Env", "Prompt"], rows), ""])
    return lines


def _qc_summary_lines(qc: QcReport) -> list[str]:
    severity_counts = Counter(issue.severity.value for issue in qc.issues)
    category_counts = Counter(issue.category.value for issue in qc.issues)
    lines = ["### QC Issue Summary", ""]
    rows = [[f"severity:{key}", str(value)] for key, value in sorted(severity_counts.items())]
    rows.extend([[f"category:{key}", str(value)] for key, value in sorted(category_counts.items())])
    if rows:
        lines.append(_markdown_table(["Bucket", "Count"], rows))
    else:
        lines.append("No QC issues.")
    lines.append("")
    return lines


def _item_result_table(run: EvalRun) -> str:
    item_by_id = {item.id: item for item in run.suite.tasks}
    rows: list[list[str]] = []
    for result in run.results:
        item = item_by_id.get(result.item_id)
        rows.append(
            [
                result.item_id,
                result.target_id,
                item.dimension_id if item else "-",
                item.task_type.value if item else "-",
                _pct(result.score),
                str(result.latency_ms) if result.latency_ms is not None else "-",
                _escape_cell(result.error or "", 120),
                _escape_cell(_source_label(item), 120) if item else "-",
                _escape_cell(_first_sentence(result.judge_reasoning or ""), 180),
            ]
        )
    return _markdown_table(
        ["Item", "Target", "Dimension", "Task Type", "Score", "Latency ms", "Error", "Source", "Judge Summary"],
        rows,
    )


def _extract_double_pass_fields(reasoning: str | None) -> tuple[str, str, str]:
    if not reasoning:
        return "-", "-", "-"
    pass1 = re.search(r"pass1=([0-9.]+)", reasoning)
    pass2 = re.search(r"pass2=([0-9.]+)", reasoning)
    disagreement = re.search(r"disagreement=([0-9.]+)", reasoning)
    return (
        pass1.group(1) if pass1 else "-",
        pass2.group(1) if pass2 else "-",
        disagreement.group(1) if disagreement else "-",
    )


def _judge_audit_lines(run: EvalRun) -> list[str]:
    instability_count = _judge_instability_count(run)
    judge_failure_count = _judge_failure_count(run)
    rows: list[list[str]] = []
    for result in run.results:
        pass1, pass2, disagreement = _extract_double_pass_fields(result.judge_reasoning)
        rows.append(
            [
                result.item_id,
                result.target_id,
                _pct(result.score),
                pass1,
                pass2,
                disagreement,
                "yes" if result.error and result.judge_reasoning and result.error == result.judge_reasoning else "no",
                "yes" if result.judge_reasoning and "judge_instability=true" in result.judge_reasoning else "no",
            ]
        )
    lines = [
        "## Judge Audit",
        "",
        f"- Double-pass judge instability flags: {instability_count}",
        f"- Judge/evaluator failure flags: {judge_failure_count}",
        "- `pass1/pass2/disagreement` are shown when the runner used double-pass judging; `-` means the item was single-pass judged or deterministically scored.",
        "",
    ]
    if rows:
        lines.append(
            _markdown_table(
                ["Item", "Target", "Final", "Pass1", "Pass2", "Disagreement", "Judge Failure", "Instability"],
                rows,
            )
        )
        lines.append("")
    return lines


def _format_transcript(raw_response: str, item: BenchmarkItem | None) -> str:
    task_type = item.task_type if item else TaskType.generation
    parsed = _parse_json(raw_response)
    if task_type == TaskType.multi_turn and isinstance(parsed, list):
        chunks: list[str] = []
        for index, message in enumerate(parsed, start=1):
            if isinstance(message, dict):
                chunks.append(f"[{index}] {message.get('role', 'unknown').upper()}: {message.get('content', '')}")
        if chunks:
            return "\n\n".join(chunks)
    if task_type == TaskType.agent and isinstance(parsed, dict):
        trace = parsed.get("trace")
        if isinstance(trace, list):
            chunks = [
                f"Environment: {parsed.get('environment', '-')}",
                "",
                "Trace:",
            ]
            for step in trace:
                if not isinstance(step, dict):
                    continue
                chunks.append(
                    "\n".join(
                        [
                            f"- step: {step.get('step')}",
                            f"  action: {json.dumps(step.get('parsed_action'), ensure_ascii=False)}",
                            f"  score_after_step: {step.get('score_after_step')}",
                            f"  done: {step.get('done')}",
                            f"  error: {step.get('error') or '-'}",
                            f"  observation: {_clip(step.get('observation', ''), 1200)}",
                        ]
                    )
                )
            chunks.extend(["", "Final state:", json.dumps(parsed.get("final_state", {}), ensure_ascii=False, indent=2)])
            return "\n".join(chunks)
    return raw_response


def _evidence_lines(result: ItemResult) -> list[str]:
    text = result.error or result.judge_reasoning or ""
    if not text:
        return ["- No judge evidence captured."]
    sentences = re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s+", " ".join(text.split()))
    keywords = [
        "because",
        "however",
        "error",
        "failed",
        "incorrect",
        "concern",
        "risk",
        "score",
        "passes",
        "does not",
        "missing",
    ]
    selected = [
        sentence
        for sentence in sentences
        if any(keyword in sentence.lower() for keyword in keywords)
    ][:4]
    if not selected:
        selected = sentences[:3]
    return [f"- {_escape_cell(sentence, 320)}" for sentence in selected if sentence]


def _detailed_item_lines(run: EvalRun) -> list[str]:
    item_by_id = {item.id: item for item in run.suite.tasks}
    lines = ["## Detailed Item Records", ""]
    if not run.results:
        lines.extend(["No item responses were recorded.", ""])
        return lines
    for result in run.results:
        item = item_by_id.get(result.item_id)
        task_type = item.task_type if item else TaskType.generation
        summary = f"{result.item_id} / {result.target_id} / score {_pct(result.score)}"
        lines.extend(
            [
                f"<details>",
                f"<summary>{summary}</summary>",
                "",
                f"- Dimension: `{item.dimension_id if item else '-'}`",
                f"- Task type: `{task_type.value}`",
                f"- Challenge effort: `{item.challenge_effort.value if item else '-'}`",
                f"- Source: {_source_label(item) if item else '-'}",
                f"- Latency: {result.latency_ms if result.latency_ms is not None else '-'} ms",
                f"- Error: {result.error or '-'}",
                "",
                "### Prompt",
                "",
                _code_block(item.prompt if item else "", ""),
            ]
        )
        if item and item.rubric:
            lines.extend(["", "### Rubric", "", _code_block(item.rubric, "")])
        if item and item.metadata:
            lines.extend(["", "### Metadata", "", _code_block(json.dumps(item.metadata, ensure_ascii=False, indent=2), "json")])
        lines.extend(
            [
                "",
                "### Response / Trace",
                "",
                _code_block(_format_transcript(result.raw_response, item), "text"),
                "",
                "### Judge Reasoning",
                "",
                _code_block(result.judge_reasoning or "", "text"),
                "",
                "### Evidence Excerpts",
                "",
                *_evidence_lines(result),
                "",
                "</details>",
                "",
            ]
        )
    return lines


def artifact_index_markdown(
    *,
    package_path: Path,
    report_path: Path,
    frontend_report_path: Path | None = None,
    task_viewer_path: Path | None = None,
    manifest_path: Path,
    lm_eval_paths: dict[str, Path],
) -> str:
    """Build a Markdown artifact index once persistence paths are known."""
    rows = [
        ["canonical_package_json", str(package_path)],
        ["markdown_report", str(report_path)],
        ["manifest", str(manifest_path)],
    ]
    if frontend_report_path is not None:
        rows.append(["frontend_report_html", str(frontend_report_path)])
    if task_viewer_path is not None:
        rows.append(["task_viewer_html", str(task_viewer_path)])
    rows.extend([[f"lm_eval_{key}", str(value)] for key, value in lm_eval_paths.items()])
    return "\n".join(
        [
            "## Artifact Index",
            "",
            _markdown_table(["Artifact", "Path"], rows),
            "",
            "The canonical JSON contains full raw responses and traces. The Markdown report may clip very long values for readability. The HTML report provides a diagnostic view; the task viewer provides a focused page for reading generated tasks.",
            "",
        ]
    )

def _research_brief_lines(research_brief: ResearchBrief | None) -> list[str]:
    if research_brief is None:
        return []
    return [
        "## Benchmark Design Research",
        "",
        "- Planning and generation used a benchmark-design research brief "
        "(see research_brief.md / research_brief.json).",
        f"- Candidate dimensions: {len(research_brief.dimensions)}",
        f"- Difficulty factors: {len(research_brief.difficulty_factors)}",
        f"- Task patterns: {len(research_brief.task_patterns)}",
        f"- Source recommendations: {len(research_brief.source_recommendations)}",
        "",
    ]
