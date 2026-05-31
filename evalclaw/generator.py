"""Benchmark generator: research, self-generate, and synthesize items."""
from __future__ import annotations

import json
import re
import uuid
from itertools import cycle
from typing import Callable

from .generation.fallback import (
    attach_multimodal_metadata_if_needed,
    fallback_items,
    has_programmatic_multimodal_fallback,
)
from .hf_discovery import discover_hf_datasets
from .hf_ingest import import_hf_dataset_items
from .llm import call_llm, extract_json
from .prompts.generator import GENERATOR_MULTIMODAL_PROMPT, GENERATOR_SYSTEM_PROMPT
from .protocols.multimodal import (
    MULTIMODAL_GENERATION_GUIDANCE,
    MULTIMODAL_SCHEMA,
    text_requests_multimodal,
)
from .protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE, TASK_AGENT_SCHEMA
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


def _safe_task_type(value: object, fallback: TaskType) -> TaskType:
    aliases = {
        "generation": TaskType.open_generation,
        "open_ended": TaskType.open_generation,
        "open-ended": TaskType.open_generation,
        "mcq": TaskType.multiple_choice,
        "qa": TaskType.short_answer,
        "agent": TaskType.agent_interaction,
        "agent_interactive": TaskType.agent_interaction,
        "pairwise": TaskType.pairwise_preference,
        "preference": TaskType.pairwise_preference,
        "arena": TaskType.pairwise_preference,
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
    if not dimension.difficulty_distribution:
        return cycle([dimension.target_difficulty])
    # Backward compatibility for old specs. New specs should use target_difficulty.
    distribution = dimension.difficulty_distribution
    expanded: list[Difficulty] = []
    for difficulty, weight in sorted(distribution.items(), key=lambda item: item[0].value):
        expanded.extend([difficulty] * max(1, round(float(weight) * 10)))
    return cycle(expanded or [dimension.target_difficulty])


def target_count_for_dimension(dimension: EvalDimension, config: BenchmarkConfig) -> int:
    return max(1, int(dimension.target_item_count or config.questions_per_dimension))


def _source_backed_target_for_dimension(
    dimension: EvalDimension,
    count: int,
    config: BenchmarkConfig,
) -> int:
    if dimension.target_source_backed_count > 0:
        return min(count, dimension.target_source_backed_count)
    return min(count, max(0, config.max_hf_records_per_dimension))


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


def _research_tokens(dimension: EvalDimension) -> set[str]:
    text = " ".join([dimension.name, dimension.description, *dimension.research_queries]).lower()
    return {
        token
        for token in re.findall(r"[a-z0-9_]{4,}", text)
        if token
        not in {
            "evaluate",
            "evaluation",
            "model",
            "models",
            "ability",
            "capability",
            "tasks",
            "benchmark",
        }
    }


def _find_shared_research_sources(
    dimension: EvalDimension,
    config: BenchmarkConfig,
    research_cache: list[tuple[set[str], list[BenchmarkSource]]],
) -> list[BenchmarkSource] | None:
    if not (config.use_hf_discovery or config.use_web_research):
        return None
    if not (dimension.needs_research or config.max_hf_records_per_dimension > 0):
        return None
    tokens = _research_tokens(dimension)
    for cached_tokens, cached_sources in research_cache:
        if not tokens or not cached_tokens:
            continue
        overlap = len(tokens & cached_tokens) / max(1, min(len(tokens), len(cached_tokens)))
        if overlap >= 0.5:
            return cached_sources
    sources = _select_research_sources(dimension, config)
    research_cache.append((tokens, sources))
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
            "LOW budget: generate lean, high-signal items. Treat the budget as a rough anchor for a small run, "
            "not a hard quota. Prefer essential coverage over breadth; a few simple items can be enough, but a "
            "single multi_turn, agent_interaction, or code_sandbox item may already carry more workload than "
            "several simple items."
        ),
        "mid": (
            "MID budget: generate balanced items covering the main dimension and important edge cases. Adjust "
            "the simple-versus-interactive mix to the objective instead of forcing the same count across task types."
        ),
        "high": (
            "HIGH budget: generate deeper items with richer rubrics, stronger edge cases, and more careful "
            "source/agent/test metadata when the dimension supports it. Use a heavier interactive item mix when "
            "the task naturally requires it, but keep the overall breadth/depth aligned to the objective rather "
            "than to a fixed item count."
        ),
    }
    return guidance.get(spec.scale_budget.value, guidance["mid"])


def _dimension_requests_multimodal(dimension: EvalDimension) -> bool:
    text = " ".join([dimension.name, dimension.description, dimension.approach, *dimension.item_requirements])
    return text_requests_multimodal(text)


def _parse_items(
    data: dict | list,
    *,
    spec: EvalSpec,
    dimension: EvalDimension,
    requested_count: int,
) -> tuple[list[BenchmarkItem], str]:
    generation_notes = ""
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        raw_items = data.get("items", [])
        generation_notes = str(data.get("generation_notes", ""))
    else:
        raw_items = []
    if not isinstance(raw_items, list):
        raw_items = []
    task_plan = dimension.task_types or spec.task_types
    task_fallback = task_plan[0] if task_plan else TaskType.open_generation
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
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        rubric = raw.get("rubric")
        if rubric is None and metadata.get("judge_rubric") is not None:
            judge_rubric = metadata["judge_rubric"]
            rubric = (
                judge_rubric
                if isinstance(judge_rubric, str)
                else json.dumps(judge_rubric, ensure_ascii=False)
            )
        task_agent = metadata.get("task_agent")
        if "agent_env" not in metadata and isinstance(task_agent, dict):
            execution = task_agent.get("execution")
            agent_env = execution.get("agent_env") if isinstance(execution, dict) else None
            if isinstance(agent_env, dict):
                metadata["agent_env"] = agent_env
        task_type = _safe_task_type(raw.get("task_type"), task_fallback)
        if task_plan and task_type not in task_plan:
            task_type = task_fallback
        item = BenchmarkItem(
            id=f"{dimension.id}_{uuid.uuid4().hex[:10]}",
            dimension_id=dimension.id,
            task_type=task_type,
            prompt=prompt,
            choices=[str(choice) for choice in choices],
            answer=str(raw["answer"]) if raw.get("answer") is not None else None,
            rubric=str(rubric) if rubric is not None else None,
            test_code=str(raw["test_code"]) if raw.get("test_code") is not None else None,
            difficulty=_safe_difficulty(raw.get("difficulty"), next(difficulties)),
            source=source,
            tags=[str(tag) for tag in raw.get("tags", []) if tag],
            metadata=metadata,
        )
        items.append(attach_multimodal_metadata_if_needed(item, dimension, len(items)))
    return items[:requested_count], generation_notes


def generate_dimension_items(
    spec: EvalSpec,
    dimension: EvalDimension,
    count: int,
    config: BenchmarkConfig,
    *,
    research_sources: list[BenchmarkSource] | None = None,
    repair_guidance: list[str] | None = None,
    avoid_prompts: list[str] | None = None,
) -> tuple[list[BenchmarkItem], list[BenchmarkSource], str]:
    """Generate benchmark items for one dimension."""
    sources = research_sources if research_sources is not None else _select_research_sources(dimension, config)
    source_backed_target = _source_backed_target_for_dimension(dimension, count, config)
    imported_items = import_hf_dataset_items(
        sources,
        dimension=dimension,
        count=source_backed_target,
    )
    remaining_count = max(0, count - len(imported_items))
    if remaining_count == 0:
        return imported_items[:count], sources, f"Imported {len(imported_items)} item(s) from HuggingFace datasets."
    if not sources and has_programmatic_multimodal_fallback(dimension):
        fallback = fallback_items(spec, dimension, remaining_count)
        return imported_items + fallback, sources, "Programmatic multimodal fallback generation."
    if not config.orchestrator_api_key:
        fallback = fallback_items(spec, dimension, remaining_count)
        return imported_items + fallback, sources, "Local fallback generation."

    payload = {
        "spec": spec.model_dump(mode="json"),
        "dimension": dimension.model_dump(mode="json"),
        "requested_count": remaining_count,
        "dimension_item_requirements": dimension.item_requirements,
        "dimension_task_type_plan": [task_type.value for task_type in (dimension.task_types or spec.task_types)],
        "reference_model": config.reference_model.model_dump(mode="json") if config.reference_model else None,
        "dimension_source_allocation": {
            "target_total": count,
            "target_source_backed": source_backed_target,
            "target_generated": dimension.target_generated_count or remaining_count,
        },
        "task_agent_schema": TASK_AGENT_SCHEMA,
        "task_agent_generation_guidance": TASK_AGENT_GENERATION_GUIDANCE,
        "scale_budget_guidance": _generation_scale_guidance(spec),
        "research_context": _source_context(sources),
        "repair_guidance": repair_guidance or [],
        "avoid_prompts": (avoid_prompts or [])[:5],
    }
    system_prompt = GENERATOR_SYSTEM_PROMPT
    if _dimension_requests_multimodal(dimension):
        payload["multimodal_schema"] = MULTIMODAL_SCHEMA
        payload["multimodal_generation_guidance"] = MULTIMODAL_GENERATION_GUIDANCE
        system_prompt += "\n\n" + GENERATOR_MULTIMODAL_PROMPT
    raw = call_llm(
        [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
        system=system_prompt,
        model=config.orchestrator_model,
        api_key=config.orchestrator_api_key,
        base_url=config.orchestrator_base_url,
        backend=config.llm_backend,
        max_tokens=8192,
    )
    try:
        items, notes = _parse_items(
            extract_json(raw),
            spec=spec,
            dimension=dimension,
            requested_count=remaining_count,
        )
    except Exception as exc:
        fallback = fallback_items(spec, dimension, remaining_count)
        return (
            imported_items + fallback,
            sources,
            f"LLM generation JSON parse failed; local fallback generation used: {exc}",
        )
    if len(items) < remaining_count:
        items.extend(fallback_items(spec, dimension, remaining_count - len(items)))
    all_items = imported_items + items
    if imported_items:
        notes = f"Imported {len(imported_items)} HF item(s). {notes}".strip()
    return all_items[:count], sources, notes


def generate_dataset(spec: EvalSpec, config: BenchmarkConfig) -> BenchmarkDataset:
    """Generate and synthesize the full benchmark dataset."""
    return generate_dataset_with_progress(spec, config)


def _dedupe_sources(sources: list[BenchmarkSource]) -> list[BenchmarkSource]:
    deduped: list[BenchmarkSource] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        key = (source.kind.value, source.uri, source.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


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
    research_cache: list[tuple[set[str], list[BenchmarkSource]]] = []
    for index, dimension in enumerate(spec.dimensions, 1):
        target_count = target_count_for_dimension(dimension, config)
        if log:
            log(f"  [{index}/{len(spec.dimensions)}] {dimension.id}: generating {target_count} item(s)...")
        research_sources = _find_shared_research_sources(dimension, config, research_cache)
        items, sources, note = generate_dimension_items(
            spec,
            dimension,
            target_count,
            config,
            research_sources=research_sources,
        )
        all_items.extend(items)
        all_sources.extend(sources)
        if log:
            log(f"    -> {len(items)} item(s), {len(sources)} source(s)")
        if note:
            notes.append(f"{dimension.id}: {note}")
    return BenchmarkDataset(
        spec=spec,
        items=all_items,
        sources=_dedupe_sources(all_sources),
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

