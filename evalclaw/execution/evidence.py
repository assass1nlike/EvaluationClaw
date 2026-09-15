"""Stable evaluator-facing evidence for completed target episodes."""
from __future__ import annotations

from typing import Any

EVALUATOR_EVIDENCE_PATH = "/evalclaw-evidence/episode.json"
EVALUATOR_EVIDENCE_SCHEMA = "evalclaw.evaluator_evidence.v1"


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
