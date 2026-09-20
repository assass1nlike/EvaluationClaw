"""Read-only tools available to the post-run analyser."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..diagnostics import redact_secrets, safe_name
from ..protocols.tool import ToolCall, ToolResult, ToolSpec

_DEFAULT_MAX_CHARS = 50_000
_MAX_CHARS = 200_000

ANALYSER_ARTIFACT_TOOL = ToolSpec(
    name="read_run_artifact",
    description=(
        "Read a UTF-8 text artifact saved in the current benchmark run. Use the relative "
        "artifact path supplied in the analysis request; this tool is read-only and cannot "
        "access files outside the current run."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "Path relative to the current run directory, such as construction.json or run.json.",
            },
            "max_chars": {
                "type": "integer",
                "minimum": 100,
                "maximum": _MAX_CHARS,
                "description": "Maximum text characters to return.",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Character offset at which to start reading (default 0).",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)

ANALYSER_ARTIFACT_LIST_TOOL = ToolSpec(
    name="list_run_artifacts",
    description=(
        "List saved files beneath a directory in the current benchmark run. Use this to "
        "discover runner, judge, actor, screenshot, and probe artifacts before reading them."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prefix": {
                "type": "string",
                "description": "Relative directory to list recursively (default: the run root).",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "File-list offset for pagination (default 0).",
            },
            "max_entries": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "description": "Maximum number of file entries to return (default 100).",
            },
        },
        "additionalProperties": False,
    },
)

ANALYSER_ITEM_EVIDENCE_TOOL = ToolSpec(
    name="read_item_evidence",
    description=(
        "Read paginated evidence for one main-run or probe item: its complete task and originating "
        "TaskDesign, construction QC, raw target response, and judge reasoning. Use this when the "
        "bounded request context is not enough to understand why an item scored as it did."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "minLength": 1,
                "description": "The target model id, e.g. deepseek-v4-flash.",
            },
            "item_id": {
                "type": "string",
                "minLength": 1,
                "description": "The item id to inspect.",
            },
            "kind": {
                "type": "string",
                "enum": ["trajectory", "judge", "both", "task", "qc", "all"],
                "description": (
                    "Evidence to return. task includes the complete task and originating "
                    "TaskDesign; qc includes item-level construction QC."
                ),
            },
            "max_chars": {
                "type": "integer",
                "minimum": 100,
                "maximum": _MAX_CHARS,
                "description": "Maximum text characters to return.",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Character offset for paged text evidence (default 0).",
            },
            "scope": {
                "type": "string",
                "enum": ["main", "probe"],
                "description": "Read the main run (default) or a probe iteration.",
            },
            "iteration": {
                "type": "integer",
                "minimum": 1,
                "description": "Probe iteration number; required when scope is probe.",
            },
        },
        "required": ["target_id", "item_id"],
        "additionalProperties": False,
    },
)


def _bounded_max_chars(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_CHARS
    return max(100, min(_MAX_CHARS, parsed))


def _nonnegative_int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _read_text_page(path: Path, offset: int, max_chars: int) -> tuple[str, bool, int | None]:
    """Read a character-indexed page without loading the whole artifact."""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        remaining = offset
        while remaining:
            chunk = handle.read(min(remaining, 65_536))
            if not chunk:
                return "", False, None
            remaining -= len(chunk)
        text = handle.read(max_chars + 1)
    content = text[:max_chars]
    truncated = len(text) > max_chars
    return content, truncated, offset + len(content) if truncated else None


def _resolve_artifact_path(run_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path.strip())
    if not raw_path.strip() or path.is_absolute():
        raise ValueError("path must be a non-empty relative path")
    root = run_dir.resolve()
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path must stay within the current run directory") from exc
    return candidate


def read_run_artifact(call: ToolCall, run_dir: Path | None) -> ToolResult:
    """Read one bounded text artifact without permitting path traversal."""
    if call.name != ANALYSER_ARTIFACT_TOOL.name:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Unknown analyser tool: {call.name}",
            error="unknown_tool",
        )
    if run_dir is None:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="The current run directory is unavailable.",
            error="artifact_directory_unavailable",
        )
    args = call.arguments if isinstance(call.arguments, dict) else {}
    try:
        candidate = _resolve_artifact_path(run_dir, str(args.get("path") or ""))
        if not candidate.is_file():
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content="The requested artifact does not exist.",
                error="artifact_not_found",
            )
        max_chars = _bounded_max_chars(args.get("max_chars"))
        offset = _nonnegative_int(args.get("offset"))
        content, truncated, next_offset = _read_text_page(candidate, offset, max_chars)
        relative = candidate.relative_to(run_dir.resolve()).as_posix()
        payload = {
            "path": relative,
            "content": content,
            "offset": offset,
            "truncated": truncated,
            "next_offset": next_offset,
        }
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=json.dumps(payload, ensure_ascii=False),
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Could not read the requested artifact: {type(exc).__name__}: {exc}",
            error="artifact_read_failed",
        )


def list_run_artifacts(call: ToolCall, run_dir: Path | None) -> ToolResult:
    """List a bounded, paginated set of artifacts inside the run directory."""
    if call.name != ANALYSER_ARTIFACT_LIST_TOOL.name:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Unknown analyser tool: {call.name}",
            error="unknown_tool",
        )
    if run_dir is None:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="The current run directory is unavailable.",
            error="artifact_directory_unavailable",
        )
    args = call.arguments if isinstance(call.arguments, dict) else {}
    try:
        prefix = str(args.get("prefix") or ".")
        directory = _resolve_artifact_path(run_dir, prefix)
        if not directory.is_dir():
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content="The requested artifact directory does not exist.",
                error="artifact_directory_not_found",
            )
        root = run_dir.resolve()
        files: list[dict[str, Any]] = []
        for candidate in directory.rglob("*"):
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError:
                continue
            files.append({"path": relative, "size_bytes": resolved.stat().st_size})
        files.sort(key=lambda item: item["path"])
        offset = _nonnegative_int(args.get("offset"))
        max_entries = min(200, max(1, _nonnegative_int(args.get("max_entries"), default=100)))
        page = files[offset : offset + max_entries]
        next_offset = offset + len(page) if offset + len(page) < len(files) else None
        payload = {
            "prefix": directory.relative_to(root).as_posix(),
            "files": page,
            "offset": offset,
            "next_offset": next_offset,
            "total_files": len(files),
        }
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=json.dumps(payload, ensure_ascii=False),
        )
    except (OSError, ValueError) as exc:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Could not list run artifacts: {type(exc).__name__}: {exc}",
            error="artifact_list_failed",
        )


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _scope_payloads(
    run_dir: Path,
    scope: str,
    iteration: int,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    if scope == "main":
        run_payload = _load_json(run_dir / "run.json") or {}
        construction = _load_json(run_dir / "construction.json") or {}
        return run_payload, construction, "runner"
    iteration_name = f"iteration-{iteration:02d}"
    iteration_payload = _load_json(run_dir / "analysis" / f"{iteration_name}.json") or {}
    return (
        iteration_payload.get("run") if isinstance(iteration_payload.get("run"), dict) else {},
        {
            "suite": iteration_payload.get("suite"),
            "qc_report": iteration_payload.get("qc_report"),
        },
        f"analysis/{iteration_name}/runner",
    )


def _find_item_result(payload: dict[str, Any], target_id: str, item_id: str) -> dict[str, Any] | None:
    results = payload.get("results", []) if isinstance(payload, dict) else []
    if not isinstance(results, list):
        return None
    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("item_id") == item_id and result.get("target_id") == target_id:
            return result
    return None


def _find_item(suite_payload: Any, item_id: str) -> dict[str, Any] | None:
    tasks = suite_payload.get("tasks", []) if isinstance(suite_payload, dict) else []
    return next(
        (task for task in tasks if isinstance(task, dict) and task.get("id") == item_id),
        None,
    )


def _find_task_design(suite_payload: Any, task: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(suite_payload, dict) or not isinstance(task, dict):
        return None
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    design_id = str(metadata.get("task_design_id") or "")
    for blueprint in suite_payload.get("blueprints", []):
        if not isinstance(blueprint, dict):
            continue
        for design in blueprint.get("task_designs", []):
            if isinstance(design, dict) and design.get("id") == design_id:
                return design
    return None


def _item_qc(qc_payload: Any, item_id: str, task=None) -> dict[str, Any]:
    qc = qc_payload if isinstance(qc_payload, dict) else {}
    from ..protocols.task_view import task_revision
    reviewed = qc.get("task_digests", {}).get(item_id)
    current = task_revision(task) if task is not None else None
    match = "unversioned" if not reviewed or not current else "matched" if reviewed == current else "stale"
    return {
        "revision_status": match,
        "reviewed_digest": reviewed,
        "current_digest": current,
        "passed": item_id in qc.get("passed_item_ids", []) if match != "stale" else None,
        "rejected": item_id in qc.get("rejected_item_ids", []) if match != "stale" else None,
        "issues": [
            issue
            for issue in qc.get("issues", [])
            if isinstance(issue, dict) and issue.get("item_id") in {None, item_id}
        ],
        "summary": qc.get("summary", ""),
    }


def _text_evidence_page(value: Any, offset: int, max_chars: int) -> tuple[str, bool, int | None]:
    text = str(value or "")
    content = text[offset : offset + max_chars]
    truncated = offset + len(content) < len(text)
    return content, truncated, offset + len(content) if truncated else None


def read_item_evidence(call: ToolCall, run_dir: Path | None) -> ToolResult:
    """Read paginated task, QC, response, and judge evidence for one item."""
    if call.name != ANALYSER_ITEM_EVIDENCE_TOOL.name:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Unknown analyser tool: {call.name}",
            error="unknown_tool",
        )
    if run_dir is None:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="The current run directory is unavailable.",
            error="artifact_directory_unavailable",
        )
    args = call.arguments if isinstance(call.arguments, dict) else {}
    target_id = str(args.get("target_id") or "").strip()
    item_id = str(args.get("item_id") or "").strip()
    if not target_id or not item_id:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="target_id and item_id are required.",
            error="invalid_arguments",
        )
    scope = str(args.get("scope") or "main").strip()
    if scope not in {"main", "probe"}:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="scope must be 'main' or 'probe'.",
            error="invalid_arguments",
        )
    iteration = _nonnegative_int(args.get("iteration"))
    if scope == "probe" and iteration < 1:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="iteration is required when scope is 'probe'.",
            error="invalid_arguments",
        )
    run_payload, construction, artifact_prefix = _scope_payloads(run_dir, scope, iteration)
    result = _find_item_result(run_payload, target_id, item_id)
    kind = str(args.get("kind") or "both").strip()
    if kind not in {"trajectory", "judge", "both", "task", "qc", "all"}:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="Unsupported evidence kind.",
            error="invalid_arguments",
        )
    if result is None and kind in {"trajectory", "judge", "both", "all"}:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"No result found for target_id={target_id!r}, item_id={item_id!r}.",
            error="item_not_found",
        )
    max_chars = _bounded_max_chars(args.get("max_chars"))
    offset = _nonnegative_int(args.get("offset"))
    evidence: dict[str, Any] = {
        "item_id": item_id,
        "target_id": target_id,
        "scope": scope,
        "iteration": iteration if scope == "probe" else None,
        "score": result.get("score") if result is not None else None,
        "error": result.get("error") if result is not None else None,
        "latency_ms": result.get("latency_ms") if result is not None else None,
        "artifact_prefix": (
            f"{artifact_prefix}/{safe_name(target_id)}/{safe_name(item_id)}"
        ),
    }
    if kind in {"trajectory", "both", "all"}:
        if result and result.get("episode") is not None:
            text, truncated, next_offset = _text_evidence_page(
                json.dumps(result["episode"], ensure_ascii=False), offset, max_chars)
            evidence.update(episode=text, episode_offset=offset,
                            episode_truncated=truncated, episode_next_offset=next_offset)
        raw, truncated, next_offset = _text_evidence_page(
            result.get("raw_response") if result is not None else "", offset, max_chars
        )
        evidence.update({
            "raw_response": raw,
            "raw_response_offset": offset,
            "raw_response_truncated": truncated,
            "raw_response_next_offset": next_offset,
        })
    if kind in {"judge", "both", "all"}:
        reasoning, truncated, next_offset = _text_evidence_page(
            result.get("judge_reasoning") if result is not None else "", offset, max_chars
        )
        evidence.update({
            "judge_reasoning": reasoning,
            "judge_reasoning_offset": offset,
            "judge_reasoning_truncated": truncated,
            "judge_reasoning_next_offset": next_offset,
        })
    suite_payload = construction.get("suite") if isinstance(construction, dict) else None
    task = _find_item(suite_payload, item_id)
    if result is None and task is None:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"No item found for target_id={target_id!r}, item_id={item_id!r}.",
            error="item_not_found",
        )
    if kind in {"task", "all"}:
        task_payload = redact_secrets({
            "task": task,
            "task_design": _find_task_design(suite_payload, task),
        })
        task_text, truncated, next_offset = _text_evidence_page(
            json.dumps(task_payload, ensure_ascii=False), offset, max_chars
        )
        evidence.update({
            "task": task_text,
            "task_offset": offset,
            "task_truncated": truncated,
            "task_next_offset": next_offset,
        })
    if kind in {"qc", "all"}:
        evidence["qc"] = _item_qc(construction.get("qc_report"), item_id, task)
    return ToolResult(
        tool_call_id=call.id,
        name=call.name,
        content=json.dumps(evidence, ensure_ascii=False),
    )


__all__ = [
    "ANALYSER_ARTIFACT_TOOL",
    "ANALYSER_ARTIFACT_LIST_TOOL",
    "ANALYSER_ITEM_EVIDENCE_TOOL",
    "list_run_artifacts",
    "read_run_artifact",
    "read_item_evidence",
]
