"""Markdown formatting helpers for EvaluationClaw reports."""
from __future__ import annotations

import json
import re


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def _escape_cell(value: object, limit: int = 160) -> str:
    text = str(value if value is not None else "-")
    text = text.replace("|", "\\|").replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _clip(value: object, limit: int = 8000) -> str:
    text = str(value if value is not None else "")
    if len(text) <= limit:
        return text
    half = max(1, limit // 2)
    return text[:half] + "\n\n...[truncated in Markdown; see canonical JSON for full value]...\n\n" + text[-half:]


def _code_block(value: object, language: str = "") -> str:
    text = _clip(value)
    fence = "```"
    if fence in text:
        fence = "````"
    return f"{fence}{language}\n{text}\n{fence}"


def _first_sentence(value: str, limit: int = 240) -> str:
    text = " ".join(value.split())
    if not text:
        return "-"
    match = re.search(r"(?<=[.!?\u3002\uff01\uff1f])\s+", text)
    sentence = text[: match.start()] if match else text
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1] + "..."


def _parse_json(value: str) -> object | None:
    try:
        return json.loads(value)
    except Exception:
        return None
