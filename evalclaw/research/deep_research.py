"""Deep research loop: bounded search -> compress -> reflect -> synthesize.

Produces a structured :class:`~evalclaw.types.ResearchBrief` that grounds the
planner (taxonomy, challenge-effort anchors) and the generator (seed sources). The
loop is research-role-LLM driven and degrades gracefully: with no research-role
key or with search disabled it returns ``None`` and the pipeline continues on
the existing single-shot research path.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from ..models.json_utils import extract_json
from ..models.llm import call_llm
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
    ResearchBenchmarkNote,
    ResearchBrief,
    ResearchCitation,
    ResearchExemplarItem,
    ResearchSeedSource,
    ResearchTaxonomyEntry,
)
from .backends import fetch_url_text, web_search

MAX_QUERIES_PER_ROUND = 4
MAX_FETCHES_PER_ROUND = 3
FETCH_MAX_CHARS = 2500
MAX_FINDINGS = 60


def _call_orchestrator_json(
    config: BenchmarkConfig,
    system: str,
    payload: dict,
    *,
    max_tokens: int = 4096,
) -> dict:
    settings = role_model_settings(config, "research")
    raw = call_llm(
        [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
        system=system,
        **settings.call_kwargs(),
        backend=config.llm_backend,
        max_tokens=max_tokens,
    )
    data = extract_json(raw)
    return data if isinstance(data, dict) else {}


def _initial_queries(goal: str, config: BenchmarkConfig) -> list[str]:
    try:
        data = _call_orchestrator_json(
            config,
            RESEARCH_QUERY_SYSTEM_PROMPT,
            {"goal": goal, "max_queries": MAX_QUERIES_PER_ROUND},
            max_tokens=1024,
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
        )
        if not result:
            continue
        material.append({"query": query, "content": result.content[:3000]})
        for citation in result.citations:
            url = str(citation.get("url") or "")
            if url:
                citations.append({"url": url, "title": citation.get("title") or url})

    fetches = 0
    for citation in citations:
        if fetches >= MAX_FETCHES_PER_ROUND:
            break
        url = citation["url"]
        if url in fetched_urls:
            continue
        fetched_urls.add(url)
        text = fetch_url_text(url, max_chars=FETCH_MAX_CHARS)
        if text:
            material.append({"url": url, "content": text})
            fetches += 1
    return material, citations


def _compress(goal: str, material: list[dict], config: BenchmarkConfig) -> list[str]:
    if not material:
        return []
    try:
        data = _call_orchestrator_json(
            config,
            RESEARCH_COMPRESS_SYSTEM_PROMPT,
            {"goal": goal, "material": material},
        )
        findings = [str(f).strip() for f in data.get("findings", []) if str(f).strip()]
        if findings:
            return findings
    except Exception:
        pass
    # Fallback: keep clipped raw snippets so synthesis still has material.
    return [
        f"[{entry.get('query') or entry.get('url') or 'material'}] {str(entry.get('content', ''))[:400]}"
        for entry in material
    ]


def _reflect(
    goal: str,
    findings: list[str],
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
                "findings": findings[-MAX_FINDINGS:],
                "round": round_index,
                "max_rounds": max_rounds,
            },
            max_tokens=1024,
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


def _parse_brief(data: dict) -> ResearchBrief:
    """Tolerantly convert synthesized JSON into a ResearchBrief."""

    def _as_dict(value: object) -> dict:
        return value if isinstance(value, dict) else {}

    taxonomy: list[ResearchTaxonomyEntry] = []
    for entry in data.get("taxonomy", []) or []:
        if isinstance(entry, str) and entry.strip():
            taxonomy.append(ResearchTaxonomyEntry(name=entry.strip()))
        elif isinstance(entry, dict) and (entry.get("name") or entry.get("id")):
            taxonomy.append(
                ResearchTaxonomyEntry(
                    name=str(entry.get("name") or entry.get("id")),
                    description=str(entry.get("description") or ""),
                )
            )

    benchmarks: list[ResearchBenchmarkNote] = []
    for entry in data.get("existing_benchmarks", []) or []:
        entry = _as_dict(entry) if not isinstance(entry, str) else {"name": entry}
        if not entry.get("name"):
            continue
        weaknesses = entry.get("known_weaknesses") or []
        if isinstance(weaknesses, str):
            weaknesses = [weaknesses]
        benchmarks.append(
            ResearchBenchmarkNote(
                name=str(entry["name"]),
                url=str(entry.get("url") or entry.get("source") or ""),
                known_weaknesses=[str(w) for w in weaknesses if w],
            )
        )

    seeds: list[ResearchSeedSource] = []
    for entry in data.get("seed_sources", []) or []:
        entry = _as_dict(entry)
        if not (entry.get("title") or entry.get("url")):
            continue
        seeds.append(
            ResearchSeedSource(
                title=str(entry.get("title") or entry.get("url")),
                url=str(entry.get("url") or ""),
                why_useful=str(entry.get("why_useful") or ""),
            )
        )

    exemplars: list[ResearchExemplarItem] = []
    for entry in data.get("exemplar_items", []) or []:
        if isinstance(entry, str) and entry.strip():
            exemplars.append(ResearchExemplarItem(prompt=entry.strip()))
        elif isinstance(entry, dict) and entry.get("prompt"):
            exemplars.append(
                ResearchExemplarItem(
                    prompt=str(entry["prompt"]),
                    answer=str(entry.get("answer") or ""),
                    notes=str(entry.get("notes") or ""),
                )
            )

    anchors_raw = data.get("challenge_effort_anchors") or {}
    anchors: dict[str, str] = {}
    if isinstance(anchors_raw, dict):
        anchors = {str(k): str(v) for k, v in anchors_raw.items() if v}
    elif isinstance(anchors_raw, list):
        for entry in anchors_raw:
            if isinstance(entry, dict) and entry.get("level"):
                anchors[str(entry["level"])] = str(entry.get("meaning") or entry.get("description") or "")

    citations: list[ResearchCitation] = []
    for entry in data.get("citations", []) or []:
        entry = _as_dict(entry)
        if not (entry.get("claim") or entry.get("url")):
            continue
        citations.append(
            ResearchCitation(
                claim=str(entry.get("claim") or ""),
                url=str(entry.get("url") or ""),
            )
        )

    return ResearchBrief(
        field_overview=str(data.get("field_overview") or ""),
        taxonomy=taxonomy,
        existing_benchmarks=benchmarks,
        seed_sources=seeds,
        exemplar_items=exemplars,
        challenge_effort_anchors=anchors,
        citations=citations,
        research_notes=str(data.get("research_notes") or ""),
    )


def _fallback_brief(
    goal: str,
    findings: list[str],
    citations: list[dict],
    hf_sources: list[BenchmarkSource],
) -> ResearchBrief:
    """Best-effort brief from accumulated raw material when synthesis fails."""
    seen: set[str] = set()
    seeds: list[ResearchSeedSource] = []
    brief_citations: list[ResearchCitation] = []
    for citation in citations:
        url = str(citation.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        title = str(citation.get("title") or url)
        seeds.append(
            ResearchSeedSource(title=title, url=url, why_useful="Collected during deep research search.")
        )
        brief_citations.append(ResearchCitation(claim=f"Search result relevant to: {goal}", url=url))
    benchmarks = [
        ResearchBenchmarkNote(name=source.title or source.uri, url=source.uri)
        for source in hf_sources
    ]
    return ResearchBrief(
        field_overview="\n".join(findings)[:4000],
        seed_sources=seeds[:10],
        existing_benchmarks=benchmarks[:10],
        citations=brief_citations[:20],
        research_notes=(
            "Best-effort brief assembled locally because LLM synthesis failed; "
            "field_overview contains raw findings."
        ),
    )


def _synthesize(
    goal: str,
    findings: list[str],
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
        "findings": findings[-MAX_FINDINGS:],
        "known_sources": known_sources,
    }
    for _attempt in range(2):
        try:
            data = _call_orchestrator_json(
                config,
                RESEARCH_SYNTHESIS_SYSTEM_PROMPT,
                payload,
                max_tokens=8192,
            )
            if data:
                return _parse_brief(data)
        except Exception:
            continue
    return _fallback_brief(goal, findings, citations, hf_sources)


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

    Returns ``None`` when the loop cannot run (no research-role key, web
    research disabled, or the ``none`` search backend), so callers can fall
    back to the existing single-shot research path.
    """
    _log = log or (lambda _msg: None)
    if not role_model_settings(config, "research").configured:
        return None
    if not config.use_web_research or (config.search_backend or "auto").lower() == "none":
        return None

    queries = _initial_queries(goal, config)
    _log(f"  [deep-research] Initial queries: {queries}")

    hf_sources = _discover_benchmark_sources(goal, queries, config)
    if hf_sources:
        _log(f"  [deep-research] HF benchmark candidates: {len(hf_sources)}")

    findings: list[str] = []
    citations: list[dict] = []
    fetched_urls: set[str] = set()
    max_rounds = max(1, config.max_research_iterations)

    for round_index in range(1, max_rounds + 1):
        material, round_citations = _gather_round(queries, config, fetched_urls)
        citations.extend(round_citations)
        new_findings = _compress(goal, material, config)
        findings.extend(new_findings)
        _log(
            f"  [deep-research] Round {round_index}/{max_rounds}: "
            f"{len(material)} materials -> {len(new_findings)} findings"
        )
        reflection = _reflect(goal, findings, round_index, max_rounds, config)
        if reflection["done"] or not reflection["follow_up_queries"]:
            _log("  [deep-research] Reflection: no remaining gaps.")
            break
        queries = reflection["follow_up_queries"]
        _log(f"  [deep-research] Gaps: {reflection['gaps']} -> follow-up queries: {queries}")

    return _synthesize(goal, findings, citations, hf_sources, config)


def compact_brief_context(brief: ResearchBrief) -> dict:
    """Compact serialization of a brief for injection into the planner context."""
    return {
        "field_overview": brief.field_overview[:1500],
        "taxonomy": [
            {"name": entry.name, "description": entry.description[:300]}
            for entry in brief.taxonomy[:12]
        ],
        "existing_benchmarks": [
            {
                "name": benchmark.name,
                "url": benchmark.url,
                "known_weaknesses": benchmark.known_weaknesses[:3],
            }
            for benchmark in brief.existing_benchmarks[:10]
        ],
        "challenge_effort_anchors": dict(list(brief.challenge_effort_anchors.items())[:4]),
    }


def render_brief_markdown(brief: ResearchBrief) -> str:
    """Render a ResearchBrief as a readable Markdown document."""
    lines: list[str] = ["# Research Brief", "", f"- Created at: {brief.created_at}", ""]
    if brief.field_overview:
        lines.extend(["## Field Overview", "", brief.field_overview, ""])
    if brief.taxonomy:
        lines.extend(["## Taxonomy", ""])
        for entry in brief.taxonomy:
            suffix = f": {entry.description}" if entry.description else ""
            lines.append(f"- **{entry.name}**{suffix}")
        lines.append("")
    if brief.existing_benchmarks:
        lines.extend(["## Existing Benchmarks", ""])
        for benchmark in brief.existing_benchmarks:
            url = f" ({benchmark.url})" if benchmark.url else ""
            lines.append(f"- **{benchmark.name}**{url}")
            for weakness in benchmark.known_weaknesses:
                lines.append(f"  - weakness: {weakness}")
        lines.append("")
    if brief.seed_sources:
        lines.extend(["## Seed Sources", ""])
        for seed in brief.seed_sources:
            url = f" ({seed.url})" if seed.url else ""
            why = f" - {seed.why_useful}" if seed.why_useful else ""
            lines.append(f"- {seed.title}{url}{why}")
        lines.append("")
    if brief.exemplar_items:
        lines.extend(["## Exemplar Items", ""])
        for exemplar in brief.exemplar_items:
            lines.append(f"- Prompt: {exemplar.prompt}")
            if exemplar.answer:
                lines.append(f"  - Answer: {exemplar.answer}")
            if exemplar.notes:
                lines.append(f"  - Notes: {exemplar.notes}")
        lines.append("")
    if brief.challenge_effort_anchors:
        lines.extend(["## Challenge Effort Anchors", ""])
        for level in sorted(brief.challenge_effort_anchors):
            lines.append(f"- {level}: {brief.challenge_effort_anchors[level]}")
        lines.append("")
    if brief.citations:
        lines.extend(["## Citations", ""])
        for citation in brief.citations:
            url = f" - {citation.url}" if citation.url else ""
            lines.append(f"- {citation.claim}{url}")
        lines.append("")
    if brief.research_notes:
        lines.extend(["## Research Notes", "", brief.research_notes, ""])
    return "\n".join(lines)
