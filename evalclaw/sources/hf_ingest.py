"""HuggingFace dataset row ingestion for source-backed benchmark items."""
from __future__ import annotations

import json
import re
import uuid
from itertools import cycle
from typing import Any

from ..core.task_summary import TASK_CONTENT_SUMMARY_METADATA_KEY, compact_task_content_summary
from ..types import (
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
    "ctx",
    "context",
    "input",
    "inputs",
    "query",
    "instruction",
    "statement",
    "text",
)
ANSWER_KEYS = (
    "solution",
    "answer",
    "final_answer",
    "best_answer",
    "correct_answer",
    "correct_answers",
    "canonical_solution",
    "reference",
    "target",
    "label",
    "labels",
    "output",
    "response",
    "completion",
)
CHOICE_KEYS = ("choices", "options", "candidates", "endings")
HF_DATASET_PREFIX = "hf://datasets/"
DIMENSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "arithmetic_number_theory": (
        "integer",
        "positive integer",
        "prime",
        "mod",
        "modulo",
        "congru",
        "divisor",
        "divisible",
        "remainder",
        "gcd",
        "lcm",
        "factor",
        "diophantine",
        "totient",
        "number theory",
        "arithmetic",
    ),
    "algebra_functions": (
        "algebra",
        "function",
        "polynomial",
        "quadratic",
        "equation",
        "inequality",
        "system of equations",
        "roots",
        "sequence",
        "series",
        "radical",
        "simplify",
        "expression",
    ),
    "geometry_trigonometry": (
        "geometry",
        "triangle",
        "circle",
        "trapezoid",
        "angle",
        "area",
        "volume",
        "coordinate",
        "sin",
        "cos",
        "tan",
        "trigonometry",
        "vector",
    ),
    "probability_statistics": (
        "probability",
        "random",
        "expected",
        "expectation",
        "variance",
        "standard deviation",
        "mean",
        "distribution",
        "conditional",
        "bayes",
        "combinatorics",
        "statistics",
    ),
    "calculus_analysis": (
        "limit",
        "derivative",
        "differentiate",
        "integral",
        "integration",
        "series",
        "converges",
        "diverges",
        "differential equation",
        "taylor",
        "maclaurin",
        "calculus",
        "analysis",
    ),
    "number_theory": (
        "integer",
        "prime",
        "mod",
        "congru",
        "divisor",
        "factor",
        "diophantine",
        "rational",
        "factorial",
        "数论",
        "整数",
        "素数",
        "同余",
    ),
    "combinatorics": (
        "graph",
        "vertex",
        "edge",
        "count",
        "subset",
        "pigeonhole",
        "permutation",
        "combination",
        "binomial",
        "arrangement",
        "steiner",
        "组合",
        "计数",
        "图",
    ),
    "abstract_algebra": (
        "group",
        "ring",
        "field",
        "ideal",
        "module",
        "homomorphism",
        "isomorphism",
        "abelian",
        "finite group",
        "群",
        "环",
        "域",
        "同态",
    ),
    "geometry_linear_algebra": (
        "matrix",
        "vector",
        "eigen",
        "linear",
        "space",
        "basis",
        "cube",
        "triangle",
        "geometry",
        "coordinate",
        "矩阵",
        "向量",
        "特征值",
        "几何",
    ),
    "probability_discrete": (
        "probability",
        "random",
        "expected",
        "expectation",
        "markov",
        "martingale",
        "stopping time",
        "walk",
        "frog",
        "概率",
        "随机",
        "期望",
        "马尔可夫",
    ),
    "biology": (
        "biology",
        "biological",
        "genetics",
        "cell",
        "protein",
        "enzyme",
        "organism",
        "evolution",
        "ecology",
        "生物",
    ),
    "chemistry": (
        "chemistry",
        "chemical",
        "molecule",
        "reaction",
        "organic",
        "inorganic",
        "enthalpy",
        "bond",
        "orbital",
        "化学",
    ),
    "physics": (
        "physics",
        "quantum",
        "mechanics",
        "electromagnetic",
        "wave",
        "force",
        "energy",
        "field",
        "relativity",
        "物理",
    ),
}


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


def _reference_text(text: str, limit: int = 8000) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    half = max(1000, (limit - 20) // 2)
    return text[:half].rstrip() + "\n...\n" + text[-half:].lstrip()


def _sanitize_prompt(prompt: str) -> str:
    prompt = re.sub(r"\s+", " ", prompt).strip()
    return re.sub(r"^\s*\d+\s*[\).]\s*", "", prompt).strip()


def _dominant_difficulty(dimension: EvalDimension) -> Difficulty:
    if not dimension.difficulty_distribution:
        return dimension.target_difficulty
    return max(dimension.difficulty_distribution.items(), key=lambda item: item[1])[0]


def _dimension_keywords(dimension: EvalDimension) -> tuple[str, ...]:
    text = f"{dimension.id} {dimension.id.replace('_', ' ')} {dimension.name}".lower()
    keywords: list[str] = []
    for key, values in DIMENSION_KEYWORDS.items():
        if key in text or key.replace("_", " ") in text or any(value in text for value in values):
            keywords.extend(values)
    return tuple(dict.fromkeys(keyword.lower() for keyword in keywords))


def _contains_keyword(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 ]*[a-z0-9]", keyword):
        pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
        return bool(re.search(pattern, text))
    return keyword in text


def _matches_dimension(item: BenchmarkItem, dimension: EvalDimension) -> bool:
    keywords = _dimension_keywords(dimension)
    if not keywords:
        return True
    metadata_text = " ".join(_stringify(value) for key, value in item.metadata.items() if key.startswith("hf_"))
    text = f"{item.prompt} {item.answer or ''} {item.rubric or ''} {metadata_text}".lower()
    return any(_contains_keyword(text, keyword) for keyword in keywords)


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


def _normalize_choice_answer(answer: str, choices: list[str]) -> str:
    if not choices:
        return answer
    stripped = answer.strip()
    if stripped.isdigit():
        index = int(stripped)
        if 0 <= index < len(choices):
            return choices[index]
        if 1 <= index <= len(choices):
            return choices[index - 1]
    letter = stripped.upper()
    if len(letter) == 1 and "A" <= letter <= "Z":
        index = ord(letter) - ord("A")
        if 0 <= index < len(choices):
            return choices[index]
    return answer


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
    prompt = _sanitize_prompt(prompt)
    if len(prompt) < 40:
        return None

    choices = _choices(row)
    answer = _normalize_choice_answer(answer, choices)
    task_type = TaskType.multiple_choice if len(choices) >= 2 and answer else TaskType.open_generation
    if task_type == TaskType.open_generation and len(answer.strip()) < 20:
        return None
    dataset_id = _dataset_id(source)
    config_part = f"&config={config_name}" if config_name else ""
    record_uri = f"{source.uri}#split={split}{config_part}&row={row_index}"
    reference_answer = _reference_text(answer, 8000)
    rubric = (
        "Score 5 for a mathematically correct, rigorous solution that reaches the reference answer "
        "or an equivalent conclusion; 3 for a partially correct solution with important gaps; "
        "1 for an incorrect, unsupported, or non-responsive solution."
    )
    if reference_answer:
        rubric += f"\nReference answer or solution: {reference_answer}"

    category = row.get("category") or row.get("subject") or row.get("topic") or row.get("domain")
    return BenchmarkItem(
        id=f"{dimension.id}_hf_{uuid.uuid4().hex[:8]}",
        dimension_id=dimension.id,
        task_type=task_type,
        prompt=_compact(prompt, 4000),
        choices=choices,
        answer=reference_answer or None,
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
            TASK_CONTENT_SUMMARY_METADATA_KEY: compact_task_content_summary(category, source.title, prompt),
            "hf_dataset_id": dataset_id,
            "hf_config": config_name,
            "hf_split": split,
            "hf_row_index": row_index,
            "hf_category": category,
            "hf_src": row.get("src") or row.get("source"),
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
    difficulties = cycle([_dominant_difficulty(dimension)])
    items: list[BenchmarkItem] = []
    skip_viable_rows = sum(ord(ch) for ch in dimension.id) % 25
    skipped_viable_rows = 0
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
            if not _matches_dimension(item, dimension):
                continue
            if skipped_viable_rows < skip_viable_rows:
                skipped_viable_rows += 1
                continue
            items.append(item)
            if len(items) >= count:
                return items
    return items
