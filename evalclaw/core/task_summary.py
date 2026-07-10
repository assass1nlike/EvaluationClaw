"""Task display-summary helpers."""
from __future__ import annotations

import re
from typing import Any

TASK_CONTENT_SUMMARY_METADATA_KEY = "task_content_summary"


def _human_label(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    return " ".join(word if word.isupper() else word[:1].upper() + word[1:] for word in text.split())


def compact_task_content_summary(*candidates: object, max_words: int = 8) -> str:
    """Return a short human-readable summary for report item titles."""
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        text = re.sub(r"[_]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        words = text.split()
        summary = " ".join(words[:max_words])
        if len(words) > max_words:
            summary += "..."
        return _human_label(summary)
    return ""


def task_content_summary_from_metadata(metadata: dict[str, Any]) -> str:
    value = metadata.get(TASK_CONTENT_SUMMARY_METADATA_KEY)
    if isinstance(value, str) and value.strip():
        return compact_task_content_summary(value)
    return ""
