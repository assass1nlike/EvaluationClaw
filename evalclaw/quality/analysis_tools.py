"""Read-only tools available to the post-run analyser."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)

ANALYSER_ITEM_EVIDENCE_TOOL = ToolSpec(
    name="read_item_evidence",
    description=(
        "Read detailed evidence for one evaluated item: its full raw target response (e.g. a "
        "complete agent tool trajectory) and/or the judge's scoring reasoning. Use this when the "
        "truncated raw_response or summary judge_reasoning in the request is not enough to "
        "understand why an item scored as it did."
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
                "enum": ["trajectory", "judge", "both"],
                "description": "Which evidence to return: the raw response, the judge reasoning, or both (default).",
            },
            "max_chars": {
                "type": "integer",
                "minimum": 100,
                "maximum": _MAX_CHARS,
                "description": "Maximum text characters to return.",
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
        with candidate.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(max_chars + 1)
        relative = candidate.relative_to(run_dir.resolve()).as_posix()
        payload = {
            "path": relative,
            "content": text[:max_chars],
            "truncated": len(text) > max_chars,
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


def _find_item_result(run_dir: Path, target_id: str, item_id: str) -> dict[str, Any] | None:
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        return None
    try:
        payload = json.loads(run_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    results = payload.get("results", []) if isinstance(payload, dict) else []
    if not isinstance(results, list):
        return None
    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("item_id") == item_id and result.get("target_id") == target_id:
            return result
    return None


def read_item_evidence(call: ToolCall, run_dir: Path | None) -> ToolResult:
    """Read one item's full raw response and judge reasoning from the saved run."""
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
    result = _find_item_result(run_dir, target_id, item_id)
    if result is None:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"No result found for target_id={target_id!r}, item_id={item_id!r}.",
            error="item_not_found",
        )
    kind = str(args.get("kind") or "both").strip()
    max_chars = _bounded_max_chars(args.get("max_chars"))
    evidence: dict[str, Any] = {
        "item_id": item_id,
        "target_id": target_id,
        "score": result.get("score"),
    }
    if kind in {"trajectory", "both"}:
        raw = str(result.get("raw_response") or "")
        evidence["raw_response"] = raw[:max_chars]
        evidence["raw_response_truncated"] = len(raw) > max_chars
    if kind in {"judge", "both"}:
        reasoning = str(result.get("judge_reasoning") or "")
        evidence["judge_reasoning"] = reasoning[:max_chars]
        evidence["judge_reasoning_truncated"] = len(reasoning) > max_chars
    return ToolResult(
        tool_call_id=call.id,
        name=call.name,
        content=json.dumps(evidence, ensure_ascii=False),
    )


__all__ = [
    "ANALYSER_ARTIFACT_TOOL",
    "ANALYSER_ITEM_EVIDENCE_TOOL",
    "read_run_artifact",
    "read_item_evidence",
]
