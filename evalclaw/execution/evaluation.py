"""Canonical evaluator result protocol shared by executable environments."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluatorResult:
    score: float
    passed: bool
    returncode: int
    details: str = ""
    structured: bool = False
    source: str = "returncode"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bounded_score(value: object) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score != score or score in {float("inf"), float("-inf")}:
        return None
    return max(0.0, min(1.0, score))


def _parse_payload(value: str) -> tuple[float, bool | None, str] | None:
    text = value.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        score = _bounded_score(text)
        return (score, None, "") if score is not None else None
    if isinstance(payload, (int, float)):
        score = _bounded_score(payload)
        return (score, None, "") if score is not None else None
    if not isinstance(payload, dict):
        return None
    score = _bounded_score(payload.get("score"))
    if score is None:
        return None
    passed = payload.get("passed") if isinstance(payload.get("passed"), bool) else None
    details = str(payload.get("details") or payload.get("reason") or "")
    return score, passed, details


def parse_evaluator_result(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    result_json: str = "",
    score_text: str = "",
    allow_stdout_score: bool = False,
) -> EvaluatorResult:
    """Parse a score without conflating process success with evaluation success.

    Preferred output is a JSON object with ``score`` and optional ``passed`` and
    ``details`` fields. Numeric score files remain supported for simple local
    evaluators. Exit status is only a binary fallback.
    """
    candidates: list[tuple[str, str]] = []
    if result_json.strip():
        candidates.append(("result_json", result_json))
    if score_text.strip():
        candidates.append(("score_file", score_text))
    if allow_stdout_score:
        for line in reversed(stdout.splitlines()):
            if line.strip():
                candidates.append(("stdout", line))
    for source, value in candidates:
        parsed = _parse_payload(value)
        if parsed is None:
            continue
        score, explicit_passed, details = parsed
        return EvaluatorResult(
            score=score,
            passed=explicit_passed if explicit_passed is not None else score >= 1.0,
            returncode=returncode,
            details=details or (stderr.strip()[-2000:] if returncode else ""),
            structured=True,
            source=source,
        )
    score = 1.0 if returncode == 0 else 0.0
    return EvaluatorResult(
        score=score,
        passed=score >= 1.0,
        returncode=returncode,
        details=(stderr or stdout).strip()[-2000:],
    )
