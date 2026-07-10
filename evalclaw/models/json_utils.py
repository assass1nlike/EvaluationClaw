"""JSON extraction helpers for model responses."""
from __future__ import annotations

import json
import re


def _json_candidates(text: str) -> list[str]:
    """Return likely JSON snippets from a model response."""
    candidates: list[str] = []
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)

    for match in re.finditer(r"```(?:json)?[ \t]*\n?", text):
        after_open = text[match.end():]
        fence_close = after_open.find("```")
        if fence_close != -1:
            block = after_open[:fence_close].strip()
            if block:
                candidates.append(block)

    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        candidates.append(text[idx : idx + end])

    return candidates


def _normalize_json_candidate(candidate: str) -> str:
    candidate = candidate.strip()
    candidate = re.sub(r':\s*\n\s*(")', r": \1", candidate)
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    return candidate


def extract_json(text: str) -> dict:
    """Extract the first JSON object from an LLM response.

    Handles:
    - Markdown code fences (```json ... ```)
    - Leading/trailing prose around the JSON
    - Trailing commas before } or ] (common Gemini quirk)
    """
    last_candidate = ""
    for candidate in _json_candidates(text):
        last_candidate = _normalize_json_candidate(candidate)
        try:
            parsed = json.loads(last_candidate)
            if isinstance(parsed, (dict, list)):
                return parsed  # type: ignore[return-value]
        except json.JSONDecodeError:
            continue

    try:
        from json_repair import repair_json  # type: ignore[import-untyped]

        repaired = repair_json(last_candidate or text, return_objects=True)
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
