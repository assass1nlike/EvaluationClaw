"""Search failures exposed to research tool callers."""
from __future__ import annotations

import json

from ..diagnostics import redact_secrets
from ..protocols.tool import ToolCall, ToolResult
from .backends import SearchError


def search_failure_result(call: ToolCall, error: SearchError) -> ToolResult:
    guidance = {
        True: "You may retry this query later.",
        False: "The configuration or request needs correction before retrying.",
        None: "Inspect the failure before deciding whether to retry.",
    }[error.retryable]
    payload = redact_secrets({
        "query": str(call.arguments.get("query") or "").strip(),
        "status": "search_failed",
        "failure_type": type(error).__name__,
        "detail": str(error),
        "attempts": error.attempts,
        "retryable": error.retryable,
        "note": (
            "The search did not complete; this is not evidence that no sources exist. "
            f"{guidance} If left unresolved, report the research gap."
        ),
    })
    return ToolResult(
        tool_call_id=call.id, name=call.name, error="search_failed",
        content=json.dumps(payload, ensure_ascii=False), raw=payload,
    )
