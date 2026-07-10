"""Browser-oriented diagnostic reports for EvaluationClaw packages."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from typing import Any

from ..core.scaling import simple_equivalent_workload
from ..types import BenchmarkItem, BenchmarkPackage, SourceKind, TaskType
from .reporter import _is_safety_eval, _is_source_backed, _risk_labels, _risk_severity
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


def _text_blob(*parts: object) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def _display_label(value: object, *, strip_hash: bool = False) -> str:
    text = str(value or "").strip()
    if strip_hash:
        text = re.sub(r"[_-][0-9a-f]{8,16}$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "-"
    return " ".join(word if word.isupper() else word[:1].upper() + word[1:] for word in text.split())


def _eval_families(pkg: BenchmarkPackage) -> list[str]:
    dataset = pkg.dataset
    item_types = {item.task_type for item in dataset.items}
    metadata_types = {
        str(item.metadata.get("agent_env", {}).get("type", ""))
        for item in dataset.items
        if isinstance(item.metadata.get("agent_env"), dict)
    }
    blob = _text_blob(
        pkg.goal,
        dataset.spec.id,
        dataset.spec.objective,
        " ".join(dataset.spec.subjects),
        " ".join(dataset.spec.constraints),
        " ".join(
            _text_blob(dimension.id, dimension.name, dimension.description, dimension.approach)
            for dimension in dataset.spec.dimensions
        ),
        " ".join(_text_blob(item.id, item.dimension_id, item.prompt, item.rubric, " ".join(item.tags)) for item in dataset.items),
    )
    families: list[str] = []
    if _is_safety_eval(dataset):
        families.append("safety")
    if TaskType.agent_interaction in item_types or TaskType.multi_turn in item_types:
        families.append("agent")
    if TaskType.code_execution in item_types or "code_sandbox" in metadata_types or any(item.test_code for item in dataset.items):
        families.append("code")
    if any(keyword in blob for keyword in ("math", "reasoning", "proof", "theorem", "logic", "knowledge", "science", "graduate")):
        families.append("reasoning")
    if any(keyword in blob for keyword in ("instruction", "format", "constraint", "schema", "follow")):
        families.append("instruction")
    if not families:
        families.append("general")
    return families


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
    item_by_id = {item.id: item for item in pkg.dataset.items}
    records: list[dict[str, Any]] = []
    for result in pkg.run.results:
        item = item_by_id.get(result.item_id)
        risks: list[str] = []
        if item is not None and _is_safety_eval(pkg.dataset):
            risk_text = _text_blob(
                item.id,
                item.dimension_id,
                " ".join(item.tags),
                result.judge_reasoning if result.score < 0.8 else "",
                result.error,
            )
            risks = _risk_labels(risk_text)
            if not risks and result.score < 0.8:
                risks = ["role_overreach"]
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
                "difficulty": item.difficulty.value if item else "-",
                "prompt": _clip(item.prompt, 30000) if item else "",
                "rubric": _clip(item.rubric or "", 20000) if item else "",
                "answer": item.answer if item else None,
                "choices": item.choices if item else [],
                "tags": item.tags if item else [],
                "metadata": item.metadata if item else {},
                "source": item.source.model_dump(mode="json") if item else None,
                "source_backed": _is_source_backed(item) if item else False,
                "risks": risks,
                "risk_severity": _risk_severity(result.score, has_error=bool(result.error)) if risks else "none",
                "agent_trace": _agent_trace(result.raw_response),
            }
        )
    return records


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


def _safety_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    risk_rows: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    severity_rank = {"none": 0, "low": 1, "medium": 2, "unknown": 2, "high": 3}
    for record in records:
        for risk in record["risks"]:
            row = risk_rows.setdefault(
                risk,
                {
                    "risk": risk,
                    "severity": record["risk_severity"],
                    "items": set(),
                    "worst_score": record["score"],
                    "evidence": "",
                },
            )
            row["items"].add(record["item_id"])
            row["worst_score"] = min(float(row["worst_score"]), float(record["score"]))
            if severity_rank.get(record["risk_severity"], 0) > severity_rank.get(row["severity"], 0):
                row["severity"] = record["risk_severity"]
            if not row["evidence"]:
                row["evidence"] = record["error"] or _first_sentence(record["judge_reasoning"])
            evidence.append(
                {
                    "item_id": record["item_id"],
                    "target_id": record["target_id"],
                    "risk": risk,
                    "severity": record["risk_severity"],
                    "score": record["score"],
                    "evidence": record["error"] or _first_sentence(record["judge_reasoning"]),
                }
            )
    rows = []
    max_severity = "none"
    for payload in sorted(risk_rows.values(), key=lambda row: (-severity_rank.get(row["severity"], 0), row["risk"])):
        max_severity = payload["severity"] if severity_rank.get(payload["severity"], 0) > severity_rank.get(max_severity, 0) else max_severity
        rows.append(
            {
                "risk": payload["risk"],
                "severity": payload["severity"],
                "items": len(payload["items"]),
                "worst_score": payload["worst_score"],
                "evidence": payload["evidence"],
            }
        )
    priority = "high" if max_severity == "high" else "medium" if max_severity in {"medium", "unknown"} else "low"
    return {"priority": priority, "max_severity": max_severity, "risk_rows": rows, "evidence": evidence[:30]}


def _viewer_payload(pkg: BenchmarkPackage) -> dict[str, Any]:
    dataset = pkg.dataset
    records = _result_records(pkg)
    passed = set(pkg.qc_report.passed_item_ids or [item.id for item in dataset.items])
    used_items = [item for item in dataset.items if item.id in passed]
    source_backed = sum(1 for item in used_items if _is_source_backed(item))
    item_source_counts = Counter(item.source.kind.value for item in used_items)
    task_counts = Counter(item.task_type.value for item in used_items)
    difficulty_counts = Counter(item.difficulty.value for item in used_items)
    agent_records = [record for record in records if record.get("agent_trace")]
    code_items: list[BenchmarkItem] = [
        item
        for item in dataset.items
        if item.task_type == TaskType.code_execution
        or bool(item.test_code)
        or (isinstance(item.metadata.get("agent_env"), dict) and item.metadata.get("agent_env", {}).get("type") == "code_sandbox")
    ]
    llm_judged = sum(1 for record in records if record["judge_reasoning"])
    deterministic = max(0, len(records) - llm_judged)
    payload = {
        "package": pkg.model_dump(mode="json"),
        "diagnostics": {
            "families": _eval_families(pkg),
            "generated_items": len(dataset.items),
            "used_items": len(used_items),
            "rejected_items": len(dataset.items) - len(used_items),
            "batch_count": len(dataset.batches),
            "simple_equivalent_workload": round(simple_equivalent_workload(used_items), 2),
            "source_candidates": len({(source.kind.value, source.uri, source.title) for source in dataset.sources}),
            "source_backed_items": source_backed,
            "self_generated_items": sum(1 for item in used_items if item.source.kind == SourceKind.self_generated),
            "item_source_counts": dict(item_source_counts),
            "task_counts": dict(task_counts),
            "difficulty_counts": dict(difficulty_counts),
            "result_records": records,
            "failure_modes": _failure_modes(records),
            "safety": _safety_diagnostics(records) if _is_safety_eval(dataset) else None,
            "agent": {
                "agent_result_count": len(agent_records),
                "total_steps": sum(record["agent_trace"]["steps"] for record in agent_records if record.get("agent_trace")),
                "tool_errors": sum(record["agent_trace"]["errors"] for record in agent_records if record.get("agent_trace")),
                "environments": sorted({record["agent_trace"]["environment"] for record in agent_records if record.get("agent_trace")}),
            },
            "code": {
                "code_item_count": len(code_items),
                "sandbox_item_count": sum(
                    1
                    for item in code_items
                    if isinstance(item.metadata.get("agent_env"), dict) and item.metadata.get("agent_env", {}).get("type") == "code_sandbox"
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
                "llm_judged_results": llm_judged,
                "deterministic_or_unjudged_results": deterministic,
                "instability_flags": sum(
                    1 for record in records if "judge_instability=true" in str(record["judge_reasoning"])
                ),
            },
        },
    }
    return payload


def build_report_viewer_html(pkg: BenchmarkPackage) -> str:
    """Build a self-contained HTML diagnostic report."""
    display_id = _display_label(pkg.spec.id)
    title = f"EvaluationClaw Diagnostic Report: {display_id}"
    payload = _viewer_payload(pkg)
    data = (
        json.dumps(payload, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return (
        HTML_TEMPLATE.replace("__TITLE__", escape(title))
        .replace("__SPEC_ID__", escape(display_id))
        .replace("__OBJECTIVE__", escape(pkg.spec.objective))
        .replace("__DATA__", data)
    )


def write_report_viewer(pkg: BenchmarkPackage, html_path: Path) -> Path:
    html_path.write_text(build_report_viewer_html(pkg), encoding="utf-8")
    return html_path
