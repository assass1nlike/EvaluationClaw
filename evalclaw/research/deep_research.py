"""Deep research loop: bounded search -> compress -> reflect -> synthesize.

Produces a structured :class:`~evalclaw.types.ResearchBrief` containing only
benchmark-design evidence for the Planner and Task Builder.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from ..models.json_utils import extract_json
from ..models.llm import DEFAULT_MAX_OUTPUT_TOKENS, call_llm
from ..models.roles import role_model_settings
from ..prompts.research import (
    RESEARCH_COMPRESS_SYSTEM_PROMPT,
    RESEARCH_QUERY_SYSTEM_PROMPT,
    RESEARCH_REFLECT_SYSTEM_PROMPT,
    RESEARCH_SYNTHESIS_SYSTEM_PROMPT,
)
from ..sources.hf_discovery import discover_hf_datasets
from ..types import (
    BenchmarkConfig,
    BenchmarkSource,
    EvalDimension,
    Message,
    ResearchBrief,
    ResearchDifficultyFactor,
    ResearchDimension,
    ResearchEvidence,
    ResearchSourceMaterial,
    ResearchSourceRecommendation,
    ResearchTaskPattern,
)
from .backends import fetch_url_text, web_search

MAX_QUERIES_PER_ROUND = 4
MAX_FETCHES_PER_ROUND = 3
FETCH_MAX_CHARS = 50_000
MAX_EVIDENCE = 60


def _call_orchestrator_json(
    config: BenchmarkConfig,
    system: str,
    payload: dict,
) -> dict:
    settings = role_model_settings(config, "research")
    raw = call_llm(
        [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
        system=system,
        **settings.call_kwargs(),
        backend=config.llm_backend,
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        expect_json=True,
    )
    data = extract_json(raw)
    return data if isinstance(data, dict) else {}


def _initial_queries(goal: str, config: BenchmarkConfig) -> list[str]:
    try:
        data = _call_orchestrator_json(
            config,
            RESEARCH_QUERY_SYSTEM_PROMPT,
            {"goal": goal, "max_queries": MAX_QUERIES_PER_ROUND},
        )
        queries = [str(q).strip() for q in data.get("queries", []) if str(q).strip()]
        if queries:
            return queries[:MAX_QUERIES_PER_ROUND]
    except Exception:
        pass
    return [goal, f"{goal} benchmark dataset", f"{goal} evaluation examples"]


def _gather_round(
    queries: list[str],
    config: BenchmarkConfig,
    fetched_urls: set[str],
) -> tuple[list[dict], list[dict]]:
    """Search each query and fetch top result URLs.

    Returns (material entries for compression, citations seen this round).
    """
    material: list[dict] = []
    citations: list[dict] = []
    settings = role_model_settings(config, "research")
    for query in queries[:MAX_QUERIES_PER_ROUND]:
        result = web_search(
            query,
            api_key=settings.api_key,
            model=settings.model,
            backend=config.search_backend,
            raise_on_error=True,
        )
        if not result:
            continue
        result_urls = [
            str(citation.get("url") or "")
            for citation in result.citations
            if citation.get("url")
        ]
        material.append(
            {"query": query, "content": result.content[:3000], "source_urls": result_urls}
        )
        for citation in result.citations:
            url = str(citation.get("url") or "")
            if url:
                citations.append({"url": url, "title": citation.get("title") or url})

    fetch_urls: list[str] = []
    for citation in citations:
        if len(fetch_urls) >= MAX_FETCHES_PER_ROUND:
            break
        url = citation["url"]
        if url in fetched_urls:
            continue
        fetched_urls.add(url)
        fetch_urls.append(url)

    with ThreadPoolExecutor(max_workers=max(1, len(fetch_urls))) as executor:
        fetched_text = list(
            executor.map(
                lambda url: fetch_url_text(url, max_chars=FETCH_MAX_CHARS),
                fetch_urls,
            )
        )
    titles_by_url = {
        str(citation.get("url") or ""): str(citation.get("title") or citation.get("url") or "")
        for citation in citations
    }
    for url, text in zip(fetch_urls, fetched_text):
        if text:
            material.append({"url": url, "title": titles_by_url.get(url, url), "content": text})
    return material, citations


def _compress(goal: str, material: list[dict], config: BenchmarkConfig) -> list[dict]:
    if not material:
        return []
    try:
        data = _call_orchestrator_json(
            config,
            RESEARCH_COMPRESS_SYSTEM_PROMPT,
            {"goal": goal, "material": material},
        )
        allowed_urls = {
            str(url)
            for entry in material
            for url in ([entry.get("url")] + list(entry.get("source_urls", [])))
            if url
        }
        evidence: list[dict] = []
        for raw in data.get("evidence", []) or []:
            if not isinstance(raw, dict):
                continue
            observation = str(raw.get("observation") or "").strip()
            implication = str(raw.get("design_implication") or "").strip()
            if not observation or not implication:
                continue
            evidence.append(
                {
                    "observation": observation,
                    "design_implication": implication,
                    "source_urls": [
                        str(url).strip()
                        for url in raw.get("source_urls", [])
                        if str(url).strip() in allowed_urls
                    ],
                }
            )
        if evidence:
            return evidence
    except Exception:
        pass
    # Fallback: keep clipped raw snippets so synthesis still has material.
    return [
        {
            "observation": str(entry.get("content", ""))[:400],
            "design_implication": (
                "Use this only as a lead for benchmark design; verify the concrete implication."
            ),
            "source_urls": (
                [str(entry["url"])]
                if entry.get("url")
                else [str(url) for url in entry.get("source_urls", []) if url]
            ),
        }
        for entry in material
        if str(entry.get("content", "")).strip()
    ]


def _reflect(
    goal: str,
    evidence: list[dict],
    round_index: int,
    max_rounds: int,
    config: BenchmarkConfig,
) -> dict:
    try:
        data = _call_orchestrator_json(
            config,
            RESEARCH_REFLECT_SYSTEM_PROMPT,
            {
                "goal": goal,
                "evidence": evidence[-MAX_EVIDENCE:],
                "round": round_index,
                "max_rounds": max_rounds,
            },
        )
        return {
            "done": bool(data.get("done", False)),
            "gaps": [str(g) for g in data.get("gaps", []) if g],
            "follow_up_queries": [
                str(q).strip() for q in data.get("follow_up_queries", []) if str(q).strip()
            ][:MAX_QUERIES_PER_ROUND],
        }
    except Exception:
        # If reflection fails, stop iterating rather than looping blindly.
        return {"done": True, "gaps": [], "follow_up_queries": []}


def _parse_brief(data: dict, *, known_source_urls: set[str] | None = None) -> ResearchBrief:
    """Convert synthesized design research into the canonical brief."""

    allowed_urls = known_source_urls

    def _as_dict(value: object) -> dict:
        return value if isinstance(value, dict) else {}

    dimensions: list[ResearchDimension] = []
    for raw in data.get("dimensions", []) or []:
        entry = _as_dict(raw)
        name = str(entry.get("name") or "").strip()
        if name:
            dimensions.append(
                ResearchDimension(
                    name=name,
                    measurement_target=str(entry.get("measurement_target") or ""),
                    boundary=str(entry.get("boundary") or ""),
                    task_shapes=[str(value) for value in entry.get("task_shapes", []) if str(value).strip()],
                )
            )

    difficulty_factors: list[ResearchDifficultyFactor] = []
    for raw in data.get("difficulty_factors", []) or []:
        entry = _as_dict(raw)
        factor = str(entry.get("factor") or "").strip()
        if factor:
            difficulty_factors.append(
                ResearchDifficultyFactor(
                    factor=factor,
                    observable_signal=str(entry.get("observable_signal") or ""),
                    design_implication=str(entry.get("design_implication") or ""),
                )
            )

    task_patterns: list[ResearchTaskPattern] = []
    for raw in data.get("task_patterns", []) or []:
        entry = _as_dict(raw)
        name = str(entry.get("name") or "").strip()
        if name:
            task_patterns.append(
                ResearchTaskPattern(
                    name=name,
                    description=str(entry.get("description") or ""),
                    suitable_task_types=[
                        str(value) for value in entry.get("suitable_task_types", []) if str(value).strip()
                    ],
                    scoring_direction=str(entry.get("scoring_direction") or ""),
                )
            )

    source_recommendations: list[ResearchSourceRecommendation] = []
    for raw in data.get("source_recommendations", []) or []:
        entry = _as_dict(raw)
        url = str(entry.get("url") or "").strip()
        if url and (allowed_urls is None or url in allowed_urls):
            source_recommendations.append(
                ResearchSourceRecommendation(
                    title=str(entry.get("title") or url),
                    url=url,
                    why_useful=str(entry.get("why_useful") or ""),
                )
            )

    evidence: list[ResearchEvidence] = []
    for raw in data.get("evidence", []) or []:
        entry = _as_dict(raw)
        observation = str(entry.get("observation") or "").strip()
        implication = str(entry.get("design_implication") or "").strip()
        if not observation or not implication:
            continue
        urls = [str(url).strip() for url in entry.get("source_urls", []) if str(url).strip()]
        if allowed_urls is not None:
            urls = [url for url in urls if url in allowed_urls]
        evidence.append(
            ResearchEvidence(
                observation=observation,
                design_implication=implication,
                source_urls=list(dict.fromkeys(urls)),
            )
        )

    anchors_raw = data.get("challenge_effort_anchors") or {}
    anchors: dict[str, str] = {}
    if isinstance(anchors_raw, dict):
        anchors = {str(key): str(value) for key, value in anchors_raw.items() if value}
    elif isinstance(anchors_raw, list):
        for entry in anchors_raw:
            if isinstance(entry, dict) and entry.get("level"):
                anchors[str(entry["level"])] = str(
                    entry.get("meaning") or entry.get("description") or ""
                )

    return ResearchBrief(
        dimensions=dimensions,
        difficulty_factors=difficulty_factors,
        task_patterns=task_patterns,
        source_recommendations=source_recommendations,
        evidence=evidence,
        challenge_effort_anchors=anchors,
        research_notes=str(data.get("research_notes") or ""),
    )


def _fallback_brief(
    goal: str,
    evidence: list[dict],
    citations: list[dict],
    hf_sources: list[BenchmarkSource],
) -> ResearchBrief:
    """Best-effort design brief from raw evidence when synthesis fails."""
    seen: set[str] = set()
    sources: list[ResearchSourceRecommendation] = []
    for citation in citations:
        url = str(citation.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        title = str(citation.get("title") or url)
        sources.append(
            ResearchSourceRecommendation(
                title=title,
                url=url,
                why_useful="Collected during benchmark-design research.",
            )
        )
    sources.extend(
        ResearchSourceRecommendation(
            title=source.title or source.uri,
            url=source.uri,
            why_useful="Dataset candidate discovered for benchmark construction.",
        )
        for source in hf_sources
        if source.uri and source.uri not in seen
    )
    return ResearchBrief(
        evidence=[ResearchEvidence(**item) for item in evidence[-MAX_EVIDENCE:] if item.get("observation")],
        source_recommendations=sources[:10],
        research_notes=(
            "Best-effort brief assembled locally because LLM synthesis failed; "
            "evidence may require further design review."
        ),
    )


def _synthesize(
    goal: str,
    evidence: list[dict],
    citations: list[dict],
    hf_sources: list[BenchmarkSource],
    config: BenchmarkConfig,
) -> ResearchBrief:
    known_sources = [
        {"title": str(c.get("title") or c.get("url") or ""), "url": str(c.get("url") or "")}
        for c in citations[:20]
    ]
    known_sources.extend(
        {"title": source.title or source.uri, "url": source.uri} for source in hf_sources[:5]
    )
    payload = {
        "goal": goal,
        "evidence": evidence[-MAX_EVIDENCE:],
        "known_sources": known_sources,
    }
    known_source_urls = {str(source.get("url") or "") for source in known_sources if source.get("url")}
    for _attempt in range(2):
        try:
            data = _call_orchestrator_json(
                config,
                RESEARCH_SYNTHESIS_SYSTEM_PROMPT,
                payload,
            )
            if data:
                return _parse_brief(data, known_source_urls=known_source_urls)
        except Exception:
            continue
    return _fallback_brief(goal, evidence, citations, hf_sources)


def _discover_benchmark_sources(
    goal: str,
    queries: list[str],
    config: BenchmarkConfig,
) -> list[BenchmarkSource]:
    if not config.use_hf_discovery:
        return []
    dimension = EvalDimension(
        id="deep_research",
        name=goal[:64] or "deep_research",
        description=goal,
        approach="Deep research benchmark discovery.",
        research_queries=queries[:3],
    )
    try:
        return discover_hf_datasets(dimension, limit=config.max_research_sources)
    except Exception:
        return []


def run_deep_research(
    goal: str,
    config: BenchmarkConfig,
    *,
    log: Optional[Callable[[str], None]] = None,
) -> Optional[ResearchBrief]:
    """Run the bounded deep-research loop and return a ResearchBrief.

    Returns ``None`` when the loop cannot run because the Research role is not
    configured or the search backend is disabled. The ordinary construction
    web-research toggle does not govern this explicitly requested stage.
    """
    _log = log or (lambda _msg: None)
    if not role_model_settings(config, "research").configured:
        return None
    if (config.search_backend or "auto").lower() == "none":
        return None

    queries = _initial_queries(goal, config)
    _log(f"  [deep-research] Initial queries: {queries}")

    hf_sources = _discover_benchmark_sources(goal, queries, config)
    if hf_sources:
        _log(f"  [deep-research] HF benchmark candidates: {len(hf_sources)}")

    evidence: list[dict] = []
    citations: list[dict] = []
    source_materials: dict[str, ResearchSourceMaterial] = {}
    fetched_urls: set[str] = set()
    max_rounds = max(1, config.max_research_iterations)

    for round_index in range(1, max_rounds + 1):
        material, round_citations = _gather_round(queries, config, fetched_urls)
        citations.extend(round_citations)
        for entry in material:
            url = str(entry.get("url") or "")
            content = str(entry.get("content") or "")
            if not url or not content:
                continue
            retained = ResearchSourceMaterial(
                title=str(entry.get("title") or url),
                url=url,
                query=str(entry.get("query") or ""),
                content=content,
            )
            current = source_materials.get(url)
            if current is None or len(retained.content) > len(current.content):
                source_materials[url] = retained
        new_evidence = _compress(goal, material, config)
        evidence.extend(new_evidence)
        _log(
            f"  [deep-research] Round {round_index}/{max_rounds}: "
            f"{len(material)} materials -> {len(new_evidence)} design evidence entries"
        )
        reflection = _reflect(goal, evidence, round_index, max_rounds, config)
        if reflection["done"] or not reflection["follow_up_queries"]:
            _log("  [deep-research] Reflection: no remaining gaps.")
            break
        queries = reflection["follow_up_queries"]
        _log(f"  [deep-research] Gaps: {reflection['gaps']} -> follow-up queries: {queries}")

    brief = _synthesize(goal, evidence, citations, hf_sources, config)
    return brief.model_copy(
        update={
            "source_materials": list(source_materials.values()),
        }
    )


def compact_brief_context(brief: ResearchBrief) -> dict:
    """Compact serialization of a brief for injection into the planner context."""
    return {
        "dimensions": [
            {
                "name": entry.name,
                "measurement_target": entry.measurement_target[:500],
                "boundary": entry.boundary[:500],
                "task_shapes": entry.task_shapes[:5],
            }
            for entry in brief.dimensions[:12]
        ],
        "difficulty_factors": [
            {
                "factor": factor.factor,
                "observable_signal": factor.observable_signal[:500],
                "design_implication": factor.design_implication[:500],
            }
            for factor in brief.difficulty_factors[:12]
        ],
        "task_patterns": [
            {
                "name": pattern.name,
                "description": pattern.description[:500],
                "suitable_task_types": pattern.suitable_task_types,
                "scoring_direction": pattern.scoring_direction[:500],
            }
            for pattern in brief.task_patterns[:12]
        ],
        "source_recommendations": [
            source.model_dump(mode="json") for source in brief.source_recommendations[:10]
        ],
        "evidence": [
            {
                "observation": item.observation[:600],
                "design_implication": item.design_implication[:600],
                "source_urls": item.source_urls[:5],
            }
            for item in brief.evidence[:30]
        ],
        "source_material_index": [
            {
                "title": material.title,
                "url": material.url,
                "content_chars": len(material.content),
            }
            for material in brief.source_materials
        ],
        "challenge_effort_anchors": dict(list(brief.challenge_effort_anchors.items())[:4]),
    }


def compact_brief_field_guide() -> str:
    """Field-by-field guidance for the compact brief payload the planner receives.

    The compact brief is a condensed, planner-facing view of the deep-research
    results. This text is appended after the JSON payload so the planner does not
    have to guess field semantics from their names.
    """
    return (
        "Field meanings for the Benchmark Design Research brief above "
        "(the brief is reference material, not an output schema):\n"
        "- dimensions: evidence-supported candidates for measurable, non-overlapping "
        "benchmark dimensions; the Planner decides whether to adopt them.\n"
        "- difficulty_factors: observable sources of task difficulty and their direct "
        "construction implications.\n"
        "- task_patterns: task shapes that can measure the goal, including suitable "
        "task types and scoring directions.\n"
        "- source_recommendations: verified documents or datasets that can ground "
        "source-backed tasks.\n"
        "- evidence: external observations paired with concrete benchmark-design "
        "implications and their source URLs.\n"
        "- source_material_index: a list of {title, url, content_chars} describing the "
        "fetched source bodies retained by the framework; the TaskBuilder may read a "
        "full source body by URL via read_research_source rather than re-fetching.\n"
        "- challenge_effort_anchors: what E1-E3 construction effort means for this "
        "evaluation goal, as a guide for choosing TaskDesign.challenge_effort."
    )


def render_brief_markdown(brief: ResearchBrief) -> str:
    """Render a ResearchBrief as a readable Markdown document."""
    lines: list[str] = ["# Benchmark Design Research Brief", "", f"- Created at: {brief.created_at}", ""]
    if brief.dimensions:
        lines.extend(["## Candidate Dimensions", ""])
        for dimension in brief.dimensions:
            lines.append(f"- **{dimension.name}**: {dimension.measurement_target}")
            if dimension.boundary:
                lines.append(f"  - Boundary: {dimension.boundary}")
            for shape in dimension.task_shapes:
                lines.append(f"  - Task shape: {shape}")
        lines.append("")
    if brief.difficulty_factors:
        lines.extend(["## Difficulty Factors", ""])
        for factor in brief.difficulty_factors:
            lines.append(f"- **{factor.factor}**")
            if factor.observable_signal:
                lines.append(f"  - Observable signal: {factor.observable_signal}")
            if factor.design_implication:
                lines.append(f"  - Design implication: {factor.design_implication}")
        lines.append("")
    if brief.task_patterns:
        lines.extend(["## Task Patterns", ""])
        for pattern in brief.task_patterns:
            lines.append(f"- **{pattern.name}**: {pattern.description}")
            if pattern.suitable_task_types:
                lines.append(f"  - Task types: {', '.join(pattern.suitable_task_types)}")
            if pattern.scoring_direction:
                lines.append(f"  - Scoring: {pattern.scoring_direction}")
        lines.append("")
    if brief.source_recommendations:
        lines.extend(["## Source Recommendations", ""])
        for source in brief.source_recommendations:
            why = f" - {source.why_useful}" if source.why_useful else ""
            lines.append(f"- {source.title} ({source.url}){why}")
        lines.append("")
    if brief.evidence:
        lines.extend(["## Design Evidence", ""])
        for item in brief.evidence:
            lines.append(f"- Observation: {item.observation}")
            lines.append(f"  - Design implication: {item.design_implication}")
            if item.source_urls:
                lines.append(f"  - Sources: {', '.join(item.source_urls)}")
        lines.append("")
    if brief.challenge_effort_anchors:
        lines.extend(["## Challenge Effort Anchors", ""])
        for level in sorted(brief.challenge_effort_anchors):
            lines.append(f"- {level}: {brief.challenge_effort_anchors[level]}")
        lines.append("")
    if brief.research_notes:
        lines.extend(["## Research Notes", "", brief.research_notes, ""])
    return "\n".join(lines)
