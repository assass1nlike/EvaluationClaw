"""JSON extraction helpers for model responses."""
from __future__ import annotations

import json
import logging
import re


def _json_candidates(text: str) -> list[str]:
    """Return likely JSON snippets from a model response."""
    candidates: list[str] = []
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)

    # Only extract outer documents. Scanning each opening brace separately can
    # silently accept an inner object after the actual response failed to parse.
    start = None
    depth = 0
    in_string = False
    escaped = False
    for idx, char in enumerate(text):
        if start is None:
            if char in "{[":
                start, depth = idx, 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                candidates.append(text[start:idx + 1])
                start = None

    return candidates


def _normalize_json_candidate(candidate: str) -> str:
    # JSON string tokens are indivisible: embedded source code and data are assets.
    return re.sub(
        r'"(?:[^"\\]|\\.)*"|,\s*(?=[}\]])',
        lambda match: match.group() if match.group().startswith('"') else "",
        candidate.strip(),
    )


def extract_json(text: str, *, allow_repair: bool = True) -> dict:
    """Extract the first JSON object from an LLM response.

    Handles:
    - Markdown code fences (```json ... ```)
    - Leading/trailing prose around the JSON
    - Trailing commas before } or ] (common Gemini quirk)
    """
    last_candidate = ""
    for candidate in _json_candidates(text):
        last_candidate = candidate
        for value in (candidate, _normalize_json_candidate(candidate)):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, (dict, list)):
                    if value != candidate:
                        logging.getLogger(__name__).warning("Removed JSON trailing commas outside strings.")
                    return parsed  # type: ignore[return-value]
            except json.JSONDecodeError:
                continue

    if not allow_repair:
        raise ValueError("JSON is not structurally valid; repair the output without changing embedded files or data.")
    try:
        from json_repair import repair_json  # type: ignore[import-untyped]

        repaired = repair_json(last_candidate or text, return_objects=True)
        logging.getLogger(__name__).warning("Model JSON required structural repair; validate the repaired document.")
        if isinstance(repaired, (dict, list)):
            return repaired  # type: ignore[return-value]
        if isinstance(repaired, str):
            parsed = json.loads(_normalize_json_candidate(repaired))
            if isinstance(parsed, (dict, list)):
                return parsed  # type: ignore[return-value]
        raise ValueError(f"json_repair returned unexpected type: {type(repaired)}")
    except Exception as exc:
        raise ValueError(
            f"JSON parse failed after repair attempt: {exc}\n"
            f"Candidate (first 800 chars):\n{(last_candidate or text)[:800]}"
        ) from exc
