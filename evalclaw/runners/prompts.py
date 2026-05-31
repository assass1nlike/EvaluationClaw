"""Prompt rendering helpers for runner execution."""
from __future__ import annotations

from ..types import BenchmarkItem, TaskType


def target_prompt(item: BenchmarkItem) -> str:
    if item.task_type != TaskType.multiple_choice or not item.choices:
        return item.prompt
    choices_text = "\n".join(str(choice).strip() for choice in item.choices if str(choice).strip())
    if not choices_text:
        return item.prompt
    return (
        f"{item.prompt.rstrip()}\n\n"
        f"Choices:\n{choices_text}\n\n"
        "Answer with the best option. You may include brief reasoning, but make the final answer clear."
    )
