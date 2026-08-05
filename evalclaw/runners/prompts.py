"""Prompt rendering helpers for runner execution."""
from __future__ import annotations

from ..types import BenchmarkItem, TaskType


def target_prompt(item: BenchmarkItem) -> str:
    if item.task_type != TaskType.choice or not item.choices:
        return item.prompt
    choices_text = "\n".join(
        f"{choice.id}: {choice.text.strip()}"
        for choice in item.choices
        if choice.id.strip() and choice.text.strip()
    )
    if not choices_text:
        return item.prompt
    return (
        f"{item.prompt.rstrip()}\n\n"
        f"Choices:\n{choices_text}\n\n"
        "Return only the selected choice id. If more than one choice is correct, "
        "return the selected ids as a JSON array."
    )
