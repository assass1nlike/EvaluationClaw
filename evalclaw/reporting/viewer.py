"""Browser-oriented diagnostic reports for EvaluationClaw packages."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from typing import Any

from ..types import BenchmarkItem, BenchmarkPackage, SourceKind, TaskType
from .reporter import _is_safety_eval, _is_source_backed, _risk_labels, _risk_severity


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
        if record["error"] or record["score"] < 0.8:
            grouped[(record["target_id"], record["dimension_id"])].append(record)
    rows: list[dict[str, Any]] = []
    for (target_id, dimension_id), group in sorted(grouped.items()):
        worst = min(group, key=lambda row: float(row["score"]))
        rows.append(
            {
                "target_id": target_id,
                "dimension_id": dimension_id,
                "items": len(group),
                "average_score": sum(float(row["score"]) for row in group) / len(group),
                "worst_item": worst["item_id"],
                "evidence": worst["error"] or _first_sentence(str(worst["judge_reasoning"])),
            }
        )
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
    title = f"EvaluationClaw Diagnostic Report: {pkg.spec.id}"
    payload = _viewer_payload(pkg)
    data = (
        json.dumps(payload, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return (
        _HTML_TEMPLATE.replace("__TITLE__", escape(title))
        .replace("__SPEC_ID__", escape(pkg.spec.id))
        .replace("__OBJECTIVE__", escape(pkg.spec.objective))
        .replace("__DATA__", data)
    )


def write_report_viewer(pkg: BenchmarkPackage, html_path: Path) -> Path:
    html_path.write_text(build_report_viewer_html(pkg), encoding="utf-8")
    return html_path


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d7dce2;
      --soft: #eef1f5;
      --accent: #155eef;
      --good: #147a4f;
      --warn: #a75c00;
      --bad: #b42318;
      --shadow: 0 10px 24px rgba(16, 24, 40, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 20;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(8px);
    }
    .topbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: center;
      max-width: 1480px;
      margin: 0 auto;
      padding: 14px 24px;
    }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: 20px; line-height: 1.2; font-weight: 700; }
    h2 { font-size: 16px; margin-bottom: 12px; }
    h3 { font-size: 14px; margin-bottom: 8px; }
    .objective { color: var(--muted); margin-top: 5px; max-width: 980px; }
    .app {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 18px;
      max-width: 1480px;
      margin: 0 auto;
      padding: 18px 24px 32px;
    }
    aside {
      position: sticky;
      top: 88px;
      align-self: start;
      display: grid;
      gap: 10px;
    }
    nav, section, .card, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    nav { padding: 10px; }
    nav a {
      display: block;
      color: var(--ink);
      text-decoration: none;
      padding: 8px 10px;
      border-radius: 6px;
    }
    nav a:hover { background: var(--soft); }
    main { display: grid; gap: 18px; min-width: 0; }
    section { padding: 16px; }
    .grid { display: grid; gap: 12px; }
    .grid.cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .stat {
      background: var(--soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 72px;
    }
    .stat .label { color: var(--muted); font-size: 12px; }
    .stat .value { margin-top: 6px; font-size: 20px; font-weight: 700; overflow-wrap: anywhere; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 999px;
      padding: 4px 9px;
      color: var(--muted);
      font-size: 12px;
    }
    .tone-good { color: var(--good); }
    .tone-warn { color: var(--warn); }
    .tone-bad { color: var(--bad); }
    .scorebar {
      height: 8px;
      background: #e5e7eb;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 8px;
    }
    .scorebar span { display: block; height: 100%; background: var(--accent); }
    .scorebar span.good { background: var(--good); }
    .scorebar span.warn { background: var(--warn); }
    .scorebar span.bad { background: var(--bad); }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 8px 7px;
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--muted); font-size: 12px; font-weight: 650; }
    td { overflow-wrap: anywhere; }
    .filters {
      display: grid;
      grid-template-columns: minmax(220px, 2fr) repeat(4, minmax(120px, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 8px 9px;
      font: inherit;
    }
    details.item {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      margin-top: 10px;
      overflow: hidden;
    }
    details.item[open] { box-shadow: 0 6px 16px rgba(16, 24, 40, 0.06); }
    details.item summary {
      cursor: pointer;
      list-style: none;
      padding: 12px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      border-bottom: 1px solid transparent;
    }
    details.item[open] summary { border-bottom-color: var(--line); }
    summary::-webkit-details-marker { display: none; }
    .item-body { padding: 12px; display: grid; gap: 12px; }
    .two-col { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
    pre {
      margin: 0;
      max-height: 420px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      background: #111827;
      color: #f9fafb;
      border-radius: 8px;
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
    }
    .empty { color: var(--muted); padding: 10px 0; }
    .small { color: var(--muted); font-size: 12px; }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; padding: 14px; }
      aside { position: static; }
      .grid.cols-4, .grid.cols-3, .two-col, .filters { grid-template-columns: 1fr; }
      .topbar { grid-template-columns: 1fr; padding: 12px 14px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div>
        <h1>EvaluationClaw Diagnostic Report: __SPEC_ID__</h1>
        <p class="objective">__OBJECTIVE__</p>
      </div>
      <div id="header-chips" class="chips"></div>
    </div>
  </header>
  <div class="app">
    <aside>
      <nav>
        <a href="#overview">Overview</a>
        <a href="#capability">Capability Profile</a>
        <a href="#diagnostics">Diagnostics</a>
        <a href="#explorer">Item Explorer</a>
        <a href="#qc">QC and Judge</a>
        <a href="#artifacts">Artifacts</a>
      </nav>
    </aside>
    <main>
      <section id="overview"></section>
      <section id="capability"></section>
      <section id="diagnostics"></section>
      <section id="explorer"></section>
      <section id="qc"></section>
      <section id="artifacts"></section>
    </main>
  </div>
  <script id="eval-data" type="application/json">__DATA__</script>
  <script>
    const payload = JSON.parse(document.getElementById("eval-data").textContent);
    const pkg = payload.package;
    const diag = payload.diagnostics;
    const records = diag.result_records || [];
    const itemById = new Map((pkg.dataset.items || []).map(item => [item.id, item]));
    const qs = id => document.getElementById(id);
    const pct = value => `${(Number(value || 0) * 100).toFixed(1)}%`;
    const scoreTone = value => Number(value || 0) >= 0.8 ? "good" : Number(value || 0) >= 0.5 ? "warn" : "bad";
    function node(tag, attrs = {}, text = null) {
      const el = document.createElement(tag);
      for (const [key, value] of Object.entries(attrs)) {
        if (key === "class") el.className = value;
        else if (key.startsWith("data-")) el.setAttribute(key, value);
        else el[key] = value;
      }
      if (text !== null && text !== undefined) el.textContent = String(text);
      return el;
    }
    function chip(text) { return node("span", {class: "chip"}, text); }
    function stat(label, value, tone = "") {
      const box = node("div", {class: "stat"});
      box.append(node("div", {class: "label"}, label));
      box.append(node("div", {class: `value ${tone ? "tone-" + tone : ""}`}, value));
      return box;
    }
    function pre(text) { return node("pre", {}, text || "-"); }
    function scorebar(value) {
      const outer = node("div", {class: "scorebar"});
      const inner = node("span", {class: scoreTone(value)});
      inner.style.width = `${Math.max(0, Math.min(100, Number(value || 0) * 100))}%`;
      outer.append(inner);
      return outer;
    }
    function table(headers, rows) {
      if (!rows || rows.length === 0) return node("p", {class: "empty"}, "No rows.");
      const tbl = node("table");
      const thead = node("thead");
      const trh = node("tr");
      headers.forEach(header => trh.append(node("th", {}, header)));
      thead.append(trh);
      tbl.append(thead);
      const tbody = node("tbody");
      rows.forEach(row => {
        const tr = node("tr");
        row.forEach(cell => {
          const td = node("td");
          if (cell instanceof Node) td.append(cell);
          else td.textContent = String(cell ?? "-");
          tr.append(td);
        });
        tbody.append(tr);
      });
      tbl.append(tbody);
      return tbl;
    }
    function renderHeader() {
      const chips = qs("header-chips");
      chips.innerHTML = "";
      (diag.families || ["general"]).forEach(family => chips.append(chip(family)));
      chips.append(chip(`${pkg.spec.scale_budget || "mid"} budget`));
      chips.append(chip(`${diag.used_items ?? (pkg.dataset.items || []).length} used items`));
    }
    function renderOverview() {
      const section = qs("overview");
      section.innerHTML = "<h2>Overview</h2>";
      const summaries = pkg.run.summaries || [];
      const avg = summaries.length ? summaries.reduce((sum, row) => sum + Number(row.average_score || 0), 0) / summaries.length : 0;
      const grid = node("div", {class: "grid cols-4"});
      grid.append(stat("Target models", summaries.length));
      grid.append(stat("Generated items", diag.generated_items ?? (pkg.dataset.items || []).length));
      grid.append(stat("Used items", diag.used_items ?? (pkg.run.results || []).length));
      grid.append(stat("Rejected items", diag.rejected_items ?? ((pkg.qc_report.rejected_item_ids || []).length)));
      grid.append(stat("Source-backed used items", `${diag.source_backed_items}/${diag.used_items ?? (pkg.dataset.items || []).length}`));
      grid.append(stat("Mean target score", summaries.length ? pct(avg) : "not run", summaries.length ? scoreTone(avg) : ""));
      section.append(grid);
      const targetRows = summaries.map(row => [row.target_id, row.model, pct(row.average_score), row.total_items, row.errors]);
      section.append(node("h3", {}, "Targets"));
      section.append(table(["Target", "Model", "Average", "Items", "Errors"], targetRows));
    }
    function renderCapability() {
      const section = qs("capability");
      section.innerHTML = "<h2>Capability Profile</h2>";
      const rows = [];
      (pkg.run.summaries || []).forEach(summary => {
        Object.entries(summary.score_by_dimension || {}).forEach(([dimension, score]) => rows.push([summary.target_id, dimension, pct(score), scorebar(score)]));
      });
      section.append(table(["Target", "Dimension", "Score", "Distribution"], rows));
      const counts = [
        ...Object.entries(diag.task_counts || {}).map(([k, v]) => [`task:${k}`, v]),
        ...Object.entries(diag.difficulty_counts || {}).map(([k, v]) => [`difficulty:${k}`, v]),
        ...Object.entries(diag.item_source_counts || {}).map(([k, v]) => [`source:${k}`, v]),
      ];
      section.append(node("h3", {}, "Dataset Composition"));
      section.append(table(["Bucket", "Count"], counts));
    }
    function renderDiagnostics() {
      const section = qs("diagnostics");
      section.innerHTML = "<h2>Diagnostics</h2>";
      const failureRows = (diag.failure_modes || []).map(row => [row.target_id, row.dimension_id, row.items, pct(row.average_score), row.worst_item, row.evidence]);
      section.append(node("h3", {}, "Failure Modes"));
      section.append(table(["Target", "Dimension", "Items", "Average", "Worst Item", "Evidence"], failureRows));
      if (diag.safety) {
        section.append(node("h3", {}, "Safety Audit Overlay"));
        const grid = node("div", {class: "grid cols-3"});
        grid.append(stat("Human review priority", diag.safety.priority, diag.safety.priority === "high" ? "bad" : diag.safety.priority === "medium" ? "warn" : "good"));
        grid.append(stat("Highest observed risk", diag.safety.max_severity, diag.safety.max_severity === "high" ? "bad" : diag.safety.max_severity === "medium" ? "warn" : "good"));
        grid.append(stat("Risk evidence rows", (diag.safety.evidence || []).length));
        section.append(grid);
        section.append(table(["Risk", "Severity", "Items", "Worst Score", "Evidence"], (diag.safety.risk_rows || []).map(row => [row.risk, row.severity, row.items, pct(row.worst_score), row.evidence])));
      }
      if ((diag.agent || {}).agent_result_count) {
        section.append(node("h3", {}, "Agent Interaction Diagnostics"));
        const grid = node("div", {class: "grid cols-4"});
        grid.append(stat("Agent traces", diag.agent.agent_result_count));
        grid.append(stat("Total steps", diag.agent.total_steps));
        grid.append(stat("Tool/action errors", diag.agent.tool_errors, diag.agent.tool_errors ? "warn" : "good"));
        grid.append(stat("Environments", (diag.agent.environments || []).join(", ") || "-"));
        section.append(grid);
      }
      if ((diag.code || {}).code_item_count) {
        section.append(node("h3", {}, "Code Execution Diagnostics"));
        section.append(table(["Metric", "Value"], [
          ["Code items", diag.code.code_item_count],
          ["Code sandbox items", diag.code.sandbox_item_count],
          ["Test commands", (diag.code.test_commands || []).join(", ") || "-"],
        ]));
      }
    }
    function uniqueValues(key) {
      return [...new Set(records.map(row => row[key]).filter(Boolean))].sort();
    }
    function fillSelect(id, values) {
      const sel = qs(id);
      values.forEach(value => sel.append(node("option", {value}, value)));
    }
    function recordSearchText(record) {
      return [record.item_id, record.target_id, record.dimension_id, record.task_type, record.prompt, record.rubric, record.judge_reasoning, record.error, (record.risks || []).join(" ")].join(" ").toLowerCase();
    }
    function renderExplorer() {
      const section = qs("explorer");
      section.innerHTML = `<h2>Item Explorer</h2>
        <div class="filters">
          <input id="filter-search" placeholder="Search item, prompt, judge evidence, risk">
          <select id="filter-target"><option value="">All targets</option></select>
          <select id="filter-dimension"><option value="">All dimensions</option></select>
          <select id="filter-task"><option value="">All task types</option></select>
          <select id="filter-severity"><option value="">All outcomes</option></select>
        </div>
        <div id="item-list"></div>`;
      fillSelect("filter-target", uniqueValues("target_id"));
      fillSelect("filter-dimension", uniqueValues("dimension_id"));
      fillSelect("filter-task", uniqueValues("task_type"));
      fillSelect("filter-severity", uniqueValues("severity"));
      ["filter-search", "filter-target", "filter-dimension", "filter-task", "filter-severity"].forEach(id => qs(id).addEventListener("input", applyFilters));
      applyFilters();
    }
    function renderRecord(record) {
      const item = node("details", {class: "item"});
      item.setAttribute("data-target", record.target_id);
      item.setAttribute("data-dimension", record.dimension_id);
      item.setAttribute("data-task", record.task_type);
      item.setAttribute("data-severity", record.severity);
      item.setAttribute("data-search", recordSearchText(record));
      const summary = node("summary");
      const left = node("div");
      left.append(node("strong", {}, `${record.item_id} / ${record.target_id}`));
      left.append(node("div", {class: "small"}, `${record.dimension_id} | ${record.task_type} | ${record.difficulty} | ${record.source_backed ? "source-backed" : "self/generated"}`));
      const right = node("div", {class: `tone-${scoreTone(record.score)}`}, `${record.score_label} ${record.severity}`);
      summary.append(left, right);
      item.append(summary);
      const body = node("div", {class: "item-body"});
      const chips = node("div", {class: "chips"});
      (record.tags || []).forEach(tag => chips.append(chip(tag)));
      (record.risks || []).forEach(risk => chips.append(chip(`risk:${risk}`)));
      if (record.source) chips.append(chip(`${record.source.kind}: ${record.source.title || record.source.uri || "-"}`));
      body.append(chips);
      const cols = node("div", {class: "two-col"});
      const promptBox = node("div");
      promptBox.append(node("h3", {}, "Prompt"));
      promptBox.append(pre(record.prompt));
      const responseBox = node("div");
      responseBox.append(node("h3", {}, "Response / Trace"));
      responseBox.append(pre(record.raw_response));
      cols.append(promptBox, responseBox);
      body.append(cols);
      if (record.rubric) {
        body.append(node("h3", {}, "Rubric"));
        body.append(pre(record.rubric));
      }
      body.append(node("h3", {}, "Judge Reasoning"));
      body.append(pre(record.error || record.judge_reasoning || "-"));
      if (record.agent_trace) {
        body.append(node("h3", {}, "Agent Trace Summary"));
        body.append(table(["Step", "Action", "Score", "Done", "Error", "Observation"], (record.agent_trace.trace || []).map(step => [
          step.step,
          JSON.stringify(step.action || {}),
          step.score_after_step ?? "-",
          step.done ?? "-",
          step.error || "-",
          step.observation || "-",
        ])));
        body.append(node("h3", {}, "Final State"));
        body.append(pre(JSON.stringify(record.agent_trace.final_state || {}, null, 2)));
      }
      item.append(body);
      return item;
    }
    function applyFilters() {
      const list = qs("item-list");
      list.innerHTML = "";
      const search = (qs("filter-search").value || "").toLowerCase();
      const target = qs("filter-target").value;
      const dimension = qs("filter-dimension").value;
      const task = qs("filter-task").value;
      const severity = qs("filter-severity").value;
      const filtered = records.filter(record =>
        (!search || recordSearchText(record).includes(search)) &&
        (!target || record.target_id === target) &&
        (!dimension || record.dimension_id === dimension) &&
        (!task || record.task_type === task) &&
        (!severity || record.severity === severity)
      );
      if (!filtered.length) {
        list.append(node("p", {class: "empty"}, "No matching item records."));
        return;
      }
      filtered.forEach(record => list.append(renderRecord(record)));
    }
    function renderQc() {
      const section = qs("qc");
      section.innerHTML = "<h2>QC and Judge Audit</h2>";
      const qc = pkg.qc_report || {};
      const grid = node("div", {class: "grid cols-4"});
      grid.append(stat("QC quality", pct(qc.quality_score), scoreTone(qc.quality_score)));
      grid.append(stat("Passed items", (qc.passed_item_ids || []).length));
      grid.append(stat("Rejected items", (qc.rejected_item_ids || []).length));
      grid.append(stat("QC issues", (qc.issues || []).length, (qc.issues || []).length ? "warn" : "good"));
      section.append(grid);
      section.append(table(["Severity", "Category", "Item", "Message", "Suggested Action"], (qc.issues || []).map(issue => [issue.severity, issue.category, issue.item_id || "-", issue.message, issue.suggested_action || "-"])));
      section.append(node("h3", {}, "Judge Signals"));
      section.append(table(["Metric", "Value"], [
        ["LLM-judged results", diag.judge.llm_judged_results],
        ["Deterministic or unjudged results", diag.judge.deterministic_or_unjudged_results],
        ["Double-pass instability flags", diag.judge.instability_flags],
      ]));
    }
    function renderArtifacts() {
      const section = qs("artifacts");
      section.innerHTML = "<h2>Artifacts</h2>";
      const rows = [
        ["Canonical JSON", "This HTML embeds a clipped viewer payload; use the package JSON for full raw values."],
        ["Markdown", "The Markdown report remains generated for terminal and diff-friendly review."],
        ["lm-eval export", "Interoperability artifacts are generated when the pipeline persists a package."],
      ];
      section.append(table(["Artifact", "Purpose"], rows));
      if (pkg.report && pkg.report.recommendations) {
        section.append(node("h3", {}, "Recommendations"));
        section.append(table(["Recommendation"], pkg.report.recommendations.map(row => [row])));
      }
    }
    renderHeader();
    renderOverview();
    renderCapability();
    renderDiagnostics();
    renderExplorer();
    renderQc();
    renderArtifacts();
  </script>
</body>
</html>
"""
