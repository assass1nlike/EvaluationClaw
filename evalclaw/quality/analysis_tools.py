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


__all__ = ["ANALYSER_ARTIFACT_TOOL", "read_run_artifact"]
