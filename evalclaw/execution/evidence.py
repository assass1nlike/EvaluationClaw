"""Stable evaluator-facing evidence for completed target episodes."""
from __future__ import annotations

from typing import Any

EVALUATOR_EVIDENCE_PATH = "/evalclaw-evidence/episode.json"
EVALUATOR_EVIDENCE_SCHEMA = "evalclaw.evaluator_evidence.v1"


def execution_failure(exc: BaseException) -> dict[str, Any]:
    def text(value: Any) -> str:
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")

    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "command": getattr(exc, "cmd", None),
        "returncode": getattr(exc, "returncode", None),
        "timeout_seconds": getattr(exc, "timeout", None),
        "stdout": text(getattr(exc, "stdout", "")),
        "stderr": text(getattr(exc, "stderr", "")),
    }


def redact_evidence(value: Any, secrets: list[str | None]) -> Any:
    """Remove exact configured credentials without heuristic content filtering."""
    if isinstance(value, str):
        for secret in secrets:
            if secret and len(secret) >= 6:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [redact_evidence(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [redact_evidence(item, secrets) for item in value]
    if isinstance(value, dict):
        return {str(key): redact_evidence(item, secrets) for key, item in value.items()}
    return value
