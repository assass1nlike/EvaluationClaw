"""Framework-owned identifiers for structured LLM output."""
from __future__ import annotations


def choice_id(index: int) -> str:
    """Return a compact, stable option id for a zero-based option index."""
    if index < 0:
        raise ValueError("choice index must be non-negative")
    value = index + 1
    letters: list[str] = []
    while value:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return "".join(reversed(letters))


def normalize_choice_data(
    raw_choices: object,
    *,
    correct_choice_indices: object = None,
    correct_choice_ids: object = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Assign framework option ids and translate legacy answer references.

    ``correct_choice_indices`` is the canonical LLM contract and is zero-based.
    ``correct_choice_ids`` remains accepted as a compatibility input only; its
    values are resolved against the raw option order and never become canonical
    ids.
    """
    if not isinstance(raw_choices, list):
        return [], []
    entries: list[tuple[str, str]] = []
    for value in raw_choices:
        if isinstance(value, dict):
            source_id = str(value.get("id") or "").strip()
            text = str(value.get("text") or "").strip()
        else:
            source_id = ""
            text = str(value or "").strip()
        if text:
            entries.append((source_id, text))

    choices = [{"id": choice_id(index), "text": text} for index, (_, text) in enumerate(entries)]
    if not choices:
        return choices, []

    selected: list[int] = []
    if isinstance(correct_choice_indices, list):
        for value in correct_choice_indices:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(choices):
                selected.append(index)

    source_to_index = {
        source_id: index
        for index, (source_id, _) in enumerate(entries)
        if source_id
    }
    if isinstance(correct_choice_ids, list):
        for value in correct_choice_ids:
            token = str(value or "").strip()
            if token in source_to_index:
                selected.append(source_to_index[token])
                continue
            generated_index = next(
                (index for index, choice in enumerate(choices) if choice["id"] == token),
                None,
            )
            if generated_index is not None:
                selected.append(generated_index)

    unique_ids = dict.fromkeys(choices[index]["id"] for index in selected)
    return choices, list(unique_ids)


def remap_indexed_references(values: object, aliases: dict[str, str]) -> list[str]:
    """Resolve framework-issued aliases while preserving known references."""
    if not isinstance(values, list):
        return []
    return [aliases.get(str(value), str(value)) for value in values if str(value).strip()]


__all__ = ["choice_id", "normalize_choice_data", "remap_indexed_references"]
