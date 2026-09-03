"""Browser-oriented diagnostic reports for EvaluationClaw packages."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from typing import Any

from ..types import BenchmarkItem, BenchmarkPackage, SourceKind, TaskType
from ._katex_assets import inject_katex
from .reporter import _is_source_backed, _source_kind_label
from .viewer_template import HTML_TEMPLATE


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _clip(value: object, limit: int = 60000) -> str:
    text = str(value if value is not None else "")
    if len(text) <= limit:
        return text
    half = max(1, limit // 2)
    return text[:half] + "\n\n...[truncated in HTML viewer; see canonical JSON for full value]...\n\n" + text[-half:]


def _json_loads(value: str) -> object | None:
    try:
        return json.loads(value)
    except Exception:
        return None


def _display_label(value: object, *, strip_hash: bool = False) -> str:
    text = str(value or "").strip()
    if strip_hash:
        text = re.sub(r"[_-][0-9a-f]{8,16}$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "-"
    return " ".join(word if word.isupper() else word[:1].upper() + word[1:] for word in text.split())


def _result_severity(score: float, has_error: bool) -> str:
    if has_error:
        return "error"
    if score < 0.5:
        return "weak"
    if score < 0.8:
        return "review"
    return "strong"


def _agent_trace(raw_response: str) -> dict[str, Any] | None:
    parsed = _json_loads(raw_response)
    if not isinstance(parsed, dict):
        return None
    trace = parsed.get("trace")
    if not isinstance(trace, list):
        return None
    action_counts: Counter[str] = Counter()
    step_rows: list[dict[str, Any]] = []
    errors = 0
    for step in trace:
        if not isinstance(step, dict):
            continue
        action = step.get("parsed_action")
        action_name = "unknown"
        if isinstance(action, dict):
            action_name = str(action.get("action") or "unknown")
        action_counts[action_name] += 1
        if step.get("error"):
            errors += 1
        step_rows.append(
            {
                "step": step.get("step"),
                "action": action,
                "score_after_step": step.get("score_after_step"),
                "done": step.get("done"),
                "error": step.get("error") or "",
                "observation": _clip(step.get("observation", ""), 4000),
            }
        )
    final_state = parsed.get("final_state") if isinstance(parsed.get("final_state"), dict) else {}
    last_test = final_state.get("last_test") if isinstance(final_state, dict) and isinstance(final_state.get("last_test"), dict) else None
    return {
        "environment": parsed.get("environment") or "-",
        "steps": len(step_rows),
        "errors": errors,
        "action_counts": dict(action_counts),
        "last_test": last_test,
        "final_state": final_state,
        "trace": step_rows,
    }


def _result_records(pkg: BenchmarkPackage) -> list[dict[str, Any]]:
    item_by_id = {item.id: item for item in pkg.suite.tasks}
    records: list[dict[str, Any]] = []
    for result in pkg.run.results:
        item = item_by_id.get(result.item_id)
        records.append(
            {
                "item_id": result.item_id,
                "target_id": result.target_id,
                "score": result.score,
                "score_label": _pct(result.score),
                "severity": _result_severity(result.score, bool(result.error)),
                "latency_ms": result.latency_ms,
                "error": result.error or "",
                "judge_reasoning": _clip(result.judge_reasoning or "", 30000),
                "raw_response": _clip(result.raw_response, 60000),
                "dimension_id": item.dimension_id if item else "-",
                "task_type": item.task_type.value if item else "-",
                "challenge_effort": item.challenge_effort.value if item else "-",
                "prompt": _clip(item.prompt, 30000) if item else "",
                "rubric": _clip(item.rubric or "", 20000) if item else "",
                "choices": [choice.model_dump(mode="json") for choice in item.choices] if item else [],
                "correct_choice_ids": item.correct_choice_ids if item else [],
                "expected_text": item.expected_text if item else None,
                "judge_tools": [tool.model_dump(mode="json") for tool in item.judge_tools] if item else [],
                "output_contract": item.output_contract if item else {},
                "tags": item.tags if item else [],
                "metadata": item.metadata if item else {},
                "source": item.source.model_dump(mode="json") if item else None,
                "source_backed": _is_source_backed(item) if item else False,
                "agent_trace": _agent_trace(result.raw_response),
            }
        )
    return records


def _planned_uses_llm_judge(item: BenchmarkItem) -> bool:
    """Whether this item's runner path needs an LLM judge for scoring."""
    if item.task_type in {
        TaskType.agent,
    }:
        return False
    if item.task_type == TaskType.fill_blank:
        return False
    return item.task_type in {TaskType.generation, TaskType.multi_turn}


def _judge_double_pass_enabled(pkg: BenchmarkPackage, records: list[dict[str, Any]]) -> bool:
    judge_artifacts = pkg.run.runner_artifacts.get("judge") if isinstance(pkg.run.runner_artifacts, dict) else None
    if isinstance(judge_artifacts, dict) and "double_pass_enabled" in judge_artifacts:
        return bool(judge_artifacts.get("double_pass_enabled"))
    return any("pass1=" in str(record["judge_reasoning"]) and "pass2=" in str(record["judge_reasoning"]) for record in records)


def _failure_modes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["target_id"], record["dimension_id"])].append(record)
    rows_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (target_id, dimension_id), group in sorted(grouped.items()):
        worst = min(group, key=lambda row: float(row["score"]))
        rows_by_target[target_id].append(
            {
                "target_id": target_id,
                "dimension_id": dimension_id,
                "items": len(group),
                "average_score": sum(float(row["score"]) for row in group) / len(group),
                "worst_item": worst["item_id"],
                "evidence": worst["error"] or _first_sentence(str(worst["judge_reasoning"])),
            }
        )
    rows: list[dict[str, Any]] = []
    for target_rows in rows_by_target.values():
        rows.extend(sorted(target_rows, key=lambda row: (float(row["average_score"]), row["dimension_id"]))[:2])
    return rows


def _first_sentence(value: str, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "-"
    match = re.search(r"(?<=[.!?])\s+", text)
    sentence = text[: match.start()] if match else text
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1] + "..."


def _viewer_payload(
    pkg: BenchmarkPackage,
    *,
    item_limit: int = 1000,
    result_limit: int = 2000,
) -> dict[str, Any]:
    suite = pkg.suite
    passed = set(pkg.qc_report.passed_item_ids)
    accepted_results = [result for result in pkg.run.results if result.item_id in passed]
    records = [
        record for record in _result_records(pkg) if record.get("item_id") in passed
    ][: max(0, result_limit)]
    used_items = [item for item in suite.tasks if item.id in passed]
    source_backed = sum(1 for item in used_items if _is_source_backed(item))
    item_source_counts = Counter(item.source.kind.value for item in used_items)
    task_counts = Counter(item.task_type.value for item in used_items)
    challenge_effort_counts = Counter(item.challenge_effort.value for item in used_items)
    agent_records = [record for record in records if record.get("agent_trace")]
    code_items: list[BenchmarkItem] = [
        item
        for item in used_items
        if any(tool.tool == "python_tests" for tool in item.judge_tools)
        or (
            isinstance(item.metadata.get("agent_env"), dict)
            and item.metadata.get("agent_env", {}).get("type") == "docker_workspace"
        )
    ]
    planned_llm_judged = sum(1 for item in used_items if _planned_uses_llm_judge(item))
    planned_deterministic = max(0, len(used_items) - planned_llm_judged)
    results_with_reasoning = sum(1 for record in records if record["judge_reasoning"])
    judge_double_pass_enabled = _judge_double_pass_enabled(pkg, records)
    embedded_items = suite.tasks[: max(0, item_limit)]
    embedded_ids = {item.id for item in embedded_items}
    embedded_suite = suite.model_copy(update={"tasks": embedded_items})
    embedded_results = [
        result for result in accepted_results if result.item_id in embedded_ids
    ][: max(0, result_limit)]
    embedded_run = pkg.run.model_copy(
        update={"suite": embedded_suite, "results": embedded_results}
    )
    embedded_analysis = None
    if pkg.analysis is not None:
        embedded_analysis = pkg.analysis.model_copy(
            update={
                "iterations": [
                    iteration.model_copy(update={"suite": None, "qc_report": None, "run": None})
                    for iteration in pkg.analysis.iterations
                ]
            }
        )
    embedded_pkg = pkg.model_copy(
        update={
            "suite": embedded_suite,
            "run": embedded_run,
            "analysis": embedded_analysis,
        }
    )
    payload = {
        "package": embedded_pkg.model_dump(mode="json"),
        "diagnostics": {
            "viewer_truncation": {
                "items_embedded": len(embedded_items),
                "items_total": len(suite.tasks),
                "results_embedded": len(embedded_results),
                "results_total": len(accepted_results),
            },
            "generated_items": len(suite.tasks),
            "used_items": len(used_items),
            "rejected_items": len(suite.tasks) - len(used_items),
            "source_candidates": len({(_source_kind_label(source), source.uri, source.title) for source in suite.resources}),
            "source_backed_items": source_backed,
            "self_generated_items": sum(1 for item in used_items if item.source.kind == SourceKind.self_generated),
            "item_source_counts": dict(item_source_counts),
            "task_counts": dict(task_counts),
            "challenge_effort_counts": dict(challenge_effort_counts),
            "result_records": records,
            "failure_modes": _failure_modes(records),
            "agent": {
                "agent_result_count": len(agent_records),
                "total_steps": sum(record["agent_trace"]["steps"] for record in agent_records if record.get("agent_trace")),
                "tool_errors": sum(record["agent_trace"]["errors"] for record in agent_records if record.get("agent_trace")),
                "environments": sorted({record["agent_trace"]["environment"] for record in agent_records if record.get("agent_trace")}),
            },
            "code": {
                "code_item_count": len(code_items),
                "docker_workspace_item_count": sum(
                    1
                    for item in code_items
                    if isinstance(item.metadata.get("agent_env"), dict)
                    and item.metadata.get("agent_env", {}).get("type") == "docker_workspace"
                ),
                "test_commands": sorted(
                    {
                        str(item.metadata.get("agent_env", {}).get("test_command"))
                        for item in code_items
                        if isinstance(item.metadata.get("agent_env"), dict) and item.metadata.get("agent_env", {}).get("test_command")
                    }
                ),
            },
            "judge": {
                "planned_llm_judged_items": planned_llm_judged,
                "planned_deterministic_items": planned_deterministic,
                "executed_results": len(records),
                "results_with_judge_reasoning": results_with_reasoning,
                "results_without_judge_reasoning": max(0, len(records) - results_with_reasoning),
                "double_pass_enabled": judge_double_pass_enabled,
                "instability_flags": sum(
                    1 for record in records if "judge_instability=true" in str(record["judge_reasoning"])
                ),
            },
        },
    }
    return payload


def build_report_viewer_html(
    pkg: BenchmarkPackage,
    *,
    item_limit: int = 1000,
    result_limit: int = 2000,
) -> str:
    """Build a self-contained HTML diagnostic report."""
    display_id = _display_label(pkg.spec.id)
    title = f"EvaluationClaw Diagnostic Report: {display_id}"
    payload = _viewer_payload(pkg, item_limit=item_limit, result_limit=result_limit)
    data = (
        json.dumps(payload, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return inject_katex(
        HTML_TEMPLATE.replace("__TITLE__", escape(title))
        .replace("__SPEC_ID__", escape(display_id))
        .replace("__OBJECTIVE__", escape(pkg.spec.objective))
        .replace("__DATA__", data)
    )


def write_report_viewer(pkg: BenchmarkPackage, html_path: Path) -> Path:
    html_path.write_text(build_report_viewer_html(pkg), encoding="utf-8")
    return html_path
