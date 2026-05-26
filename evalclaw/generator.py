"""Benchmark generator: research, self-generate, and synthesize items."""
from __future__ import annotations

import json
import re
import uuid
from itertools import cycle
from typing import Callable

from .llm import call_llm, extract_json
from .hf_discovery import discover_hf_datasets
from .hf_ingest import import_hf_dataset_items
from .search import fetch_url_text, format_search_result, web_search
from .types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    BenchmarkSource,
    Difficulty,
    EvalDimension,
    EvalSpec,
    Message,
    SourceKind,
    TaskType,
)

_SYSTEM = """\
你是 EvaluationClaw 的 Generator。你要根据 eval_spec 和单个 dimension 生成高质量 benchmark items。

输出纯 JSON，不要 markdown。格式：
{
  "generation_notes": "...",
  "items": [
    {
      "task_type": "multiple_choice",
      "prompt": "...",
      "choices": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "answer": "A",
      "rubric": "评分标准；开放题必须具体到 1-5 分描述",
      "test_code": null,
      "difficulty": "L3",
      "tags": ["..."],
      "source_uri": "...",
      "source_title": "..."
    }
  ]
}

要求：
- 每题独立可执行，不依赖其他题。
- 如果考察的不是背景知识本身，题干必须提供必要背景。
- multiple_choice 必须单选且 choices 至少 4 个，answer 是选项字母。
- yes_no 的 answer 必须是 yes 或 no。
- open_generation 必须提供 rubric。
- short_answer 必须给 answer 或 rubric。
- code_execution 必须给 test_code，使用 {model_output} 作为模型输出占位符。
- multi_turn 的 rubric 必须说明追问方向和全对话评分方式。
- multi_turn 可在 metadata 中提供 turns，例如 {"turns": ["追问1", "追问2"]}；如果没有，runner 会让 judge 按 rubric 生成追问。
- agent_interaction 用于模拟环境里的 action/observation 循环，metadata 可提供 agent_env。
  - workspace 环境测试移动/整理/多步状态保持。
  - code_sandbox 环境测试多轮写代码、运行测试、读错误、再修改。
"""


def _safe_task_type(value: object, fallback: TaskType) -> TaskType:
    aliases = {
        "generation": TaskType.open_generation,
        "open_ended": TaskType.open_generation,
        "open-ended": TaskType.open_generation,
        "mcq": TaskType.multiple_choice,
        "qa": TaskType.short_answer,
        "agent": TaskType.agent_interaction,
        "agent_interactive": TaskType.agent_interaction,
    }
    text = str(value)
    if text in aliases:
        return aliases[text]
    try:
        return TaskType(text)
    except ValueError:
        return fallback


def _safe_difficulty(value: object, fallback: Difficulty = Difficulty.L3) -> Difficulty:
    aliases = {
        "low": Difficulty.L2,
        "medium": Difficulty.L3,
        "high": Difficulty.L4,
        "easy": Difficulty.L1,
        "hard": Difficulty.L4,
        "difficult": Difficulty.L4,
    }
    text = str(value)
    if text in aliases:
        return aliases[text]
    try:
        return Difficulty(text)
    except ValueError:
        return fallback


def _normalize_source(source_uri: object, source_title: object = "") -> BenchmarkSource:
    uri = str(source_uri or "").strip()
    title = str(source_title or "").strip()
    marker = re.sub(r"^https?://", "", uri.lower()).strip("/")
    title_marker = title.lower().strip()
    self_markers = {"", "self_generated", "self-generated", "generated", "n/a", "none", "null"}
    if marker in self_markers or title_marker in self_markers:
        return BenchmarkSource(kind=SourceKind.self_generated)
    if uri.startswith("hf://datasets/"):
        return BenchmarkSource(kind=SourceKind.hf_dataset, uri=uri, title=title)
    if uri.startswith("lm-eval://"):
        return BenchmarkSource(kind=SourceKind.lm_eval, uri=uri, title=title)
    return BenchmarkSource(kind=SourceKind.web, uri=uri, title=title)


def _difficulty_cycle(dimension: EvalDimension) -> cycle[Difficulty]:
    distribution = dimension.difficulty_distribution or {
        Difficulty.L1: 0.1,
        Difficulty.L2: 0.2,
        Difficulty.L3: 0.4,
        Difficulty.L4: 0.2,
        Difficulty.L5: 0.1,
    }
    expanded: list[Difficulty] = []
    for difficulty, weight in sorted(distribution.items(), key=lambda item: item[0].value):
        expanded.extend([difficulty] * max(1, round(float(weight) * 10)))
    return cycle(expanded or [Difficulty.L3])


def _select_research_sources(
    dimension: EvalDimension,
    config: BenchmarkConfig,
) -> list[BenchmarkSource]:
    sources: list[BenchmarkSource] = []
    if config.use_hf_discovery and (dimension.needs_research or config.max_hf_records_per_dimension > 0):
        sources.extend(discover_hf_datasets(dimension, limit=config.max_research_sources))
    if not config.use_web_research or not dimension.needs_research:
        return sources

    queries = dimension.research_queries or [f"{dimension.name} {dimension.description}"]
    seen: set[str] = {source.uri for source in sources}
    for query in queries[:2]:
        result = web_search(
            query,
            api_key=config.orchestrator_api_key,
            model=config.orchestrator_model,
        )
        if not result:
            continue
        for citation in result.citations[: config.max_research_sources]:
            url = citation.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append(
                BenchmarkSource(
                    kind=SourceKind.web,
                    uri=url,
                    title=str(citation.get("title") or url),
                    notes=format_search_result(result)[:1200],
                )
            )
            if len(sources) >= config.max_research_sources:
                return sources
    return sources


def _source_context(sources: list[BenchmarkSource]) -> str:
    if not sources:
        return "No external sources. Generate from the spec and clearly label source as self_generated."
    parts: list[str] = []
    for source in sources:
        if source.kind == SourceKind.hf_dataset:
            parts.append(f"--- {source.title} ---\nURI: {source.uri}\n{source.notes}")
            continue
        text = fetch_url_text(source.uri, max_chars=3000) if source.uri else None
        content = text or source.notes or "(content unavailable)"
        parts.append(f"--- {source.title or source.uri} ---\nURI: {source.uri}\n{content}")
    return "\n\n".join(parts)


def _generation_scale_guidance(spec: EvalSpec) -> str:
    guidance = {
        "low": (
            "LOW budget: generate lean, high-signal items. Prefer essential coverage over breadth; "
            "avoid over-elaborate prompts unless required by the task type."
        ),
        "mid": (
            "MID budget: generate balanced items covering the main dimension and important edge cases."
        ),
        "high": (
            "HIGH budget: generate deeper items with richer rubrics, stronger edge cases, and more careful "
            "source/agent/test metadata when the dimension supports it."
        ),
    }
    return guidance.get(spec.scale_budget.value, guidance["mid"])


def _parse_items(
    data: dict,
    *,
    spec: EvalSpec,
    dimension: EvalDimension,
    requested_count: int,
) -> tuple[list[BenchmarkItem], str]:
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []
    task_fallback = spec.task_types[0] if spec.task_types else TaskType.open_generation
    difficulties = _difficulty_cycle(dimension)
    items: list[BenchmarkItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        prompt = str(raw.get("prompt") or "").strip()
        if not prompt:
            continue
        source = _normalize_source(raw.get("source_uri"), raw.get("source_title"))
        choices = raw.get("choices") or []
        if isinstance(choices, dict):
            choices = [f"{key}. {value}" for key, value in choices.items()]
        if not isinstance(choices, list):
            choices = []
        item = BenchmarkItem(
            id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
            dimension_id=dimension.id,
            task_type=_safe_task_type(raw.get("task_type"), task_fallback),
            prompt=prompt,
            choices=[str(choice) for choice in choices],
            answer=str(raw["answer"]) if raw.get("answer") is not None else None,
            rubric=str(raw["rubric"]) if raw.get("rubric") is not None else None,
            test_code=str(raw["test_code"]) if raw.get("test_code") is not None else None,
            difficulty=_safe_difficulty(raw.get("difficulty"), next(difficulties)),
            source=source,
            tags=[str(tag) for tag in raw.get("tags", []) if tag],
            metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        )
        items.append(item)
    return items[:requested_count], str(data.get("generation_notes", ""))


def _fallback_items(spec: EvalSpec, dimension: EvalDimension, count: int) -> list[BenchmarkItem]:
    tasks = cycle(spec.task_types or [TaskType.open_generation])
    difficulties = _difficulty_cycle(dimension)
    items: list[BenchmarkItem] = []
    for idx in range(count):
        task_type = next(tasks)
        difficulty = next(difficulties)
        base = (
            f"Evaluation objective: {spec.objective}\n"
            f"Dimension: {dimension.name}\n"
            f"Task: {dimension.approach or dimension.description}\n"
            f"Difficulty: {difficulty.value}\n"
        )
        if task_type == TaskType.multiple_choice:
            item = BenchmarkItem(
                id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
                dimension_id=dimension.id,
                task_type=task_type,
                prompt=base + "Choose the best answer. This is a placeholder item for generator smoke tests.",
                choices=[
                    "A. The response fully satisfies the dimension",
                    "B. The response partially satisfies the dimension",
                    "C. The response avoids the requested behavior",
                    "D. The response is irrelevant",
                ],
                answer="A",
                difficulty=difficulty,
            )
        elif task_type == TaskType.agent_interaction:
            agent_text = f"{spec.objective} {dimension.name} {dimension.description} {dimension.approach}".lower()
            if any(keyword in agent_text for keyword in ("code", "coding", "program", "debug", "python", "代码", "编程")):
                item = BenchmarkItem(
                    id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
                    dimension_id=dimension.id,
                    task_type=TaskType.agent_interaction,
                    prompt=(
                        base
                        + "Use the code_sandbox tools to implement max_pair_sum(nums) in solution.py. "
                        "Run tests, inspect failures, and revise until tests pass."
                    ),
                    rubric=(
                        "Deterministic environment score: 1.0 when the hidden Python tests pass, "
                        "0.25 after at least one failing test run, 0.0 if tests are never run."
                    ),
                    difficulty=difficulty,
                    metadata={
                        "agent_env": {
                            "type": "code_sandbox",
                            "visible_files": {
                                "solution.py": "def max_pair_sum(nums):\n    pass\n"
                            },
                            "hidden_files": {
                                "tests.py": (
                                    "from solution import max_pair_sum\n\n"
                                    "assert max_pair_sum([1, 2, 3, 4]) == 7\n"
                                    "assert max_pair_sum([-5, -2, -3]) == -5\n"
                                    "assert max_pair_sum([10, 10, 1]) == 20\n"
                                )
                            },
                            "test_command": "python3 tests.py",
                            "max_steps": 8,
                        }
                    },
                )
                items.append(item)
                continue
            item = BenchmarkItem(
                id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
                dimension_id=dimension.id,
                task_type=TaskType.agent_interaction,
                prompt=(
                    base
                    + "Use the simulated workspace tools to place the blue_notebook and charged_tablet "
                    "in the outgoing bin. Inspect items when needed and finish within the step limit."
                ),
                rubric=(
                    "Deterministic environment score: 1.0 if all required items and no wrong items are "
                    "placed in the outgoing bin, partial credit for required items placed, penalties for invalid actions."
                ),
                difficulty=difficulty,
                metadata={
                    "agent_env": {
                        "type": "workspace",
                        "start_room": "office",
                        "rooms": {
                            "office": ["blue_notebook", "red_notebook"],
                            "lab": ["charged_tablet", "dead_tablet"],
                            "mailroom": [],
                        },
                        "item_descriptions": {
                            "blue_notebook": "A blue notebook labeled project plan.",
                            "red_notebook": "A red notebook labeled old draft.",
                            "charged_tablet": "A tablet showing 100% battery.",
                            "dead_tablet": "A tablet with an empty battery icon.",
                        },
                        "goal": {"outgoing_bin": ["blue_notebook", "charged_tablet"]},
                        "max_steps": 8,
                    }
                },
            )
        else:
            item = BenchmarkItem(
                id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
                dimension_id=dimension.id,
                task_type=TaskType.open_generation,
                prompt=base + "Produce a concise answer that demonstrates the target capability.",
                rubric=(
                    "Score 5 for a complete, correct, well-calibrated answer; 3 for a partially "
                    "correct answer with omissions; 1 for incorrect, evasive, or unsupported output."
                ),
                difficulty=difficulty,
            )
        items.append(item)
    return items


def generate_dimension_items(
    spec: EvalSpec,
    dimension: EvalDimension,
    count: int,
    config: BenchmarkConfig,
) -> tuple[list[BenchmarkItem], list[BenchmarkSource], str]:
    """Generate benchmark items for one dimension."""
    sources = _select_research_sources(dimension, config)
    imported_items = import_hf_dataset_items(
        sources,
        dimension=dimension,
        count=min(count, max(0, config.max_hf_records_per_dimension)),
    )
    remaining_count = max(0, count - len(imported_items))
    if remaining_count == 0:
        return imported_items[:count], sources, f"Imported {len(imported_items)} item(s) from HuggingFace datasets."
    if not config.orchestrator_api_key:
        fallback_items = _fallback_items(spec, dimension, remaining_count)
        return imported_items + fallback_items, sources, "Local fallback generation."

    payload = {
        "spec": spec.model_dump(mode="json"),
        "dimension": dimension.model_dump(mode="json"),
        "requested_count": remaining_count,
        "scale_budget_guidance": _generation_scale_guidance(spec),
        "research_context": _source_context(sources),
    }
    raw = call_llm(
        [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
        system=_SYSTEM,
        model=config.orchestrator_model,
        api_key=config.orchestrator_api_key,
        base_url=config.orchestrator_base_url,
        backend=config.llm_backend,
        max_tokens=8192,
    )
    items, notes = _parse_items(extract_json(raw), spec=spec, dimension=dimension, requested_count=remaining_count)
    if len(items) < remaining_count:
        items.extend(_fallback_items(spec, dimension, remaining_count - len(items)))
    all_items = imported_items + items
    if imported_items:
        notes = f"Imported {len(imported_items)} HF item(s). {notes}".strip()
    return all_items[:count], sources, notes


def generate_dataset(spec: EvalSpec, config: BenchmarkConfig) -> BenchmarkDataset:
    """Generate and synthesize the full benchmark dataset."""
    return generate_dataset_with_progress(spec, config)


def generate_dataset_with_progress(
    spec: EvalSpec,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] | None = None,
) -> BenchmarkDataset:
    """Generate and synthesize the full benchmark dataset with optional progress logs."""
    all_items: list[BenchmarkItem] = []
    all_sources: list[BenchmarkSource] = []
    notes: list[str] = []
    per_dimension = max(1, config.questions_per_dimension)
    for index, dimension in enumerate(spec.dimensions, 1):
        if log:
            log(f"  [{index}/{len(spec.dimensions)}] {dimension.id}: generating {per_dimension} item(s)...")
        items, sources, note = generate_dimension_items(spec, dimension, per_dimension, config)
        all_items.extend(items)
        all_sources.extend(sources)
        if log:
            log(f"    -> {len(items)} item(s), {len(sources)} source(s)")
        if note:
            notes.append(f"{dimension.id}: {note}")
    return BenchmarkDataset(
        spec=spec,
        items=all_items,
        sources=all_sources,
        generation_notes="\n".join(notes),
    )


# Compatibility helper for older scripts.
def generate_questions(dimension: EvalDimension, count: int, config: BenchmarkConfig) -> list[BenchmarkItem]:
    spec = EvalSpec(
        objective=dimension.description or dimension.name,
        dimensions=[dimension],
        task_types=[TaskType.open_generation, TaskType.multiple_choice],
        scale=count,
    )
    items, _, _ = generate_dimension_items(spec, dimension, count, config)
    return items
