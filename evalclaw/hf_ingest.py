"""HuggingFace dataset row ingestion for source-backed benchmark items."""
from __future__ import annotations

import json
import re
import uuid
from itertools import cycle
from typing import Any

from .types import (
    BenchmarkItem,
    BenchmarkSource,
    Difficulty,
    EvalDimension,
    SourceKind,
    TaskType,
)

QUESTION_KEYS = (
    "problem",
    "question",
    "prompt",
    "input",
    "query",
    "instruction",
    "statement",
)
ANSWER_KEYS = (
    "solution",
    "answer",
    "final_answer",
    "target",
    "output",
    "response",
    "completion",
)
CHOICE_KEYS = ("choices", "options", "candidates")
HF_DATASET_PREFIX = "hf://datasets/"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _compact(text: str, limit: int = 2000) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    lowered = {str(key).lower(): key for key in row}
    for key in keys:
        actual = lowered.get(key)
        if actual is not None:
            text = _stringify(row.get(actual))
            if text:
                return text
    return ""


def _conversation_text(row: dict[str, Any]) -> tuple[str, str]:
    messages = row.get("messages") or row.get("conversation") or row.get("conversations")
    if not isinstance(messages, list):
        return "", ""
    user_parts: list[str] = []
    assistant_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or message.get("from") or "").lower()
        content = _stringify(message.get("content") or message.get("value") or message.get("text"))
        if not content:
            continue
        if role in {"user", "human"} and not user_parts:
            user_parts.append(content)
        elif role in {"assistant", "gpt", "model"} and not assistant_parts:
            assistant_parts.append(content)
    return "\n".join(user_parts), "\n".join(assistant_parts)


def _choices(row: dict[str, Any]) -> list[str]:
    for key in CHOICE_KEYS:
        value = row.get(key)
        if isinstance(value, list):
            return [_stringify(choice) for choice in value if _stringify(choice)]
        if isinstance(value, dict):
            return [f"{label}. {_stringify(choice)}" for label, choice in value.items()]
    return []


def _dataset_id(source: BenchmarkSource) -> str:
    if not source.uri.startswith(HF_DATASET_PREFIX):
        return ""
    return source.uri[len(HF_DATASET_PREFIX) :].split("#", 1)[0]


def item_from_hf_record(
    row: dict[str, Any],
    *,
    source: BenchmarkSource,
    dimension: EvalDimension,
    difficulty: Difficulty,
    split: str,
    row_index: int,
    config_name: str | None = None,
) -> BenchmarkItem | None:
    """Convert a HuggingFace dataset row into a benchmark item when possible."""
    prompt = _first_text(row, QUESTION_KEYS)
    answer = _first_text(row, ANSWER_KEYS)
    if not prompt:
        prompt, answer_from_messages = _conversation_text(row)
        answer = answer or answer_from_messages
    if len(prompt) < 20:
        return None

    choices = _choices(row)
    task_type = TaskType.multiple_choice if len(choices) >= 2 and answer else TaskType.open_generation
    dataset_id = _dataset_id(source)
    config_part = f"&config={config_name}" if config_name else ""
    record_uri = f"{source.uri}#split={split}{config_part}&row={row_index}"
    rubric = (
        "Score 5 for a mathematically correct, rigorous solution that reaches the reference answer "
        "or an equivalent conclusion; 3 for a partially correct solution with important gaps; "
        "1 for an incorrect, unsupported, or non-responsive solution."
    )
    if answer:
        rubric += f"\nReference answer or solution excerpt: {_compact(answer, 1200)}"

    return BenchmarkItem(
        id=f"{dimension.id}_hf_{uuid.uuid4().hex[:8]}",
        dimension_id=dimension.id,
        task_type=task_type,
        prompt=_compact(prompt, 4000),
        choices=choices,
        answer=answer if task_type == TaskType.multiple_choice else None,
        rubric=rubric,
        difficulty=difficulty,
        source=BenchmarkSource(
            kind=SourceKind.hf_dataset,
            uri=record_uri,
            title=source.title or dataset_id,
            notes=(
                "Imported from HuggingFace dataset row. "
                f"split={split}; config={config_name or 'default'}; row={row_index}"
            ),
        ),
        tags=["hf_dataset", dataset_id] if dataset_id else ["hf_dataset"],
        metadata={
            "hf_dataset_id": dataset_id,
            "hf_config": config_name,
            "hf_split": split,
            "hf_row_index": row_index,
            "hf_columns": sorted(map(str, row.keys())),
        },
    )


def _iter_hf_rows(dataset_id: str, *, max_scan_rows: int = 200):
    try:
        from datasets import get_dataset_config_names, load_dataset
    except Exception:
        return

    configs: list[str | None] = [None]
    try:
        configs.extend(get_dataset_config_names(dataset_id)[:3])
    except Exception:
        pass

    seen_configs: set[str | None] = set()
    for config_name in configs:
        if config_name in seen_configs:
            continue
        seen_configs.add(config_name)
        for split in ("test", "validation", "train"):
            try:
                if config_name:
                    dataset = load_dataset(dataset_id, config_name, split=split, streaming=True)
                else:
                    dataset = load_dataset(dataset_id, split=split, streaming=True)
                for row_index, row in enumerate(dataset):
                    if row_index >= max_scan_rows:
                        break
                    if isinstance(row, dict):
                        yield config_name, split, row_index, row
                return
            except Exception:
                continue


def import_hf_dataset_items(
    sources: list[BenchmarkSource],
    *,
    dimension: EvalDimension,
    count: int,
) -> list[BenchmarkItem]:
    """Import up to ``count`` benchmark items from discovered HF dataset sources."""
    if count <= 0:
        return []
    difficulties = cycle(
        sorted(dimension.difficulty_distribution.keys(), key=lambda difficulty: difficulty.value)
        if dimension.difficulty_distribution
        else [Difficulty.L4]
    )
    items: list[BenchmarkItem] = []
    for source in sources:
        if source.kind != SourceKind.hf_dataset:
            continue
        dataset_id = _dataset_id(source)
        if not dataset_id:
            continue
        for config_name, split, row_index, row in _iter_hf_rows(dataset_id) or ():
            item = item_from_hf_record(
                row,
                source=source,
                dimension=dimension,
                difficulty=next(difficulties),
                config_name=config_name,
                split=split,
                row_index=row_index,
            )
            if item is None:
                continue
            items.append(item)
            if len(items) >= count:
                return items
    return items
