"""Prompt rendering helpers for runner execution."""
from __future__ import annotations

from ..types import BenchmarkItem, TaskType


def target_prompt(item: BenchmarkItem) -> str:
    from ..protocols.submission import submission_instructions
    prompt = item.prompt + submission_instructions(item)
    if item.task_type != TaskType.choice or not item.choices:
        return prompt
    choices_text = "\n".join(
        f"{choice.id}: {choice.text.strip()}"
        for choice in item.choices
        if choice.id.strip() and choice.text.strip()
    )
    if not choices_text:
        return prompt
    return (
        f"{prompt.rstrip()}\n\n"
        f"Choices:\n{choices_text}\n\n"
        "Return only the selected choice id. If more than one choice is correct, "
        "return the selected ids as a JSON array."
    )
