"""Resource discovery and normalization for task construction."""
from __future__ import annotations

import re
from typing import Any

from ..models.roles import role_model_settings
from ..research.authoritative import load_source
from ..research.backends import (
    SearchError,
    SearchResult,
    SearchTimeoutError,
    fetch_url_text,
    format_search_result,
    web_search,
)
from ..types import (
    BenchmarkConfig,
    BenchmarkSource,
    EvalDimension,
    ResearchBrief,
    SourceKind,
    TaskBlueprint,
    TaskResource,
)

_SOURCE_SEARCH_MAX_ATTEMPTS = 3


def _source_context(
    sources: list[BenchmarkSource],
    research_brief: ResearchBrief | None = None,
) -> str:
    if not sources:
        return "No external sources. Generate from the spec and clearly label source as self_generated."
    retained_by_url = {
        material.url: material.content
        for material in (
            research_brief.source_materials if research_brief is not None else []
        )
    }
    parts: list[str] = []
    for source in sources:
        if source.kind == SourceKind.hf_dataset:
            content = source.notes
            if source.uri.startswith("hf://datasets/"):
                content = load_source(source.uri, limit=3)
            parts.append(f"--- {source.title} ---\nURI: {source.uri}\n{content}")
            continue
        text = retained_by_url.get(source.uri)
        if text is None and source.uri:
            text = fetch_url_text(source.uri, max_chars=3000)
        content = (text[:3000] if text is not None else None) or source.notes or "(content unavailable)"
        parts.append(
            f"--- {source.title or source.uri} ---\nURI: {source.uri}\n{content}"
        )
    return "\n\n".join(parts)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug[:48] or "task_resource"


def _resource_from_raw(raw: dict[str, Any], fallback_id: str) -> TaskResource:
    """Normalize resource content; ``fallback_id`` is always canonical."""
    return TaskResource(
        id=fallback_id,
        kind=str(raw.get("kind") or "web"),
        uri=str(raw.get("uri") or ""),
        title=str(raw.get("title") or ""),
        license=str(raw.get("license") or ""),
        content_summary=str(raw.get("content_summary") or raw.get("notes") or ""),
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def _resource_from_source(source: BenchmarkSource, fallback_id: str) -> TaskResource:
    return TaskResource(
        id=_slug(fallback_id),
        kind=source.kind.value,
        uri=source.uri,
        title=source.title,
        content_summary=source.notes[:1000],
    )


def _search_source_query(
    query: str,
    config: BenchmarkConfig,
    *,
    api_key: str | None,
    model: str | None,
) -> SearchResult | None:
    for attempt in range(1, _SOURCE_SEARCH_MAX_ATTEMPTS + 1):
        try:
            return web_search(
                query,
                api_key=api_key,
                model=model or "",
                backend=config.search_backend,
                raise_on_error=True,
            )
        except (SearchTimeoutError, TimeoutError) as exc:
            if attempt == _SOURCE_SEARCH_MAX_ATTEMPTS:
                raise RuntimeError(
                    "Task Builder source search timed out after "
                    f"{_SOURCE_SEARCH_MAX_ATTEMPTS} attempts for query {query!r}."
                ) from exc
        except SearchError as exc:
            raise RuntimeError(
                f"Task Builder source search failed for query {query!r}: {exc}"
            ) from exc
    raise AssertionError("source search retry loop terminated unexpectedly")


def _select_blueprint_sources(
    dimension: EvalDimension,
    blueprint: TaskBlueprint,
    config: BenchmarkConfig,
) -> list[BenchmarkSource]:
    if blueprint.source_strategy == "generated":
        return []
    sources = [
        BenchmarkSource(
            kind=(
                SourceKind.hf_dataset
                if uri.lower().startswith("hf://datasets/")
                else SourceKind.web
            ),
            uri=uri,
            title=uri,
            notes="Planner-suggested source from the benchmark plan.",
        )
        for uri in blueprint.source_plan.suggested_urls[: config.max_research_sources]
    ]
    if len(sources) >= config.max_research_sources:
        return sources
    settings = role_model_settings(config, "research")
    if not dimension.needs_research or not config.use_web_research:
        return sources
    if not settings.configured:
        raise RuntimeError(
            "Task Builder source search was required, but the Research role has no API key."
        )
    queries = blueprint.resource_queries or dimension.research_queries
    if not queries:
        queries = [
            f"{dimension.name} {blueprint.title} benchmark task resources",
            f"{dimension.name} {blueprint.description} benchmark dataset",
        ]
    seen: set[str] = {source.uri for source in sources}
    for query in queries[:2]:
        result = _search_source_query(
            query,
            config,
            api_key=settings.api_key,
            model=settings.model,
        )
        if not result:
            continue
        notes = format_search_result(result)[:1600]
        for citation in result.citations[: config.max_research_sources]:
            uri = str(citation.get("url") or "")
            if not uri or uri in seen:
                continue
            seen.add(uri)
            sources.append(
                BenchmarkSource(
                    kind=SourceKind.web,
                    uri=uri,
                    title=str(citation.get("title") or uri),
                    notes=notes,
                )
            )
            if len(sources) >= config.max_research_sources:
                return sources
    return sources


def _dedupe_resources(resources: list[TaskResource]) -> list[TaskResource]:
    deduped: list[TaskResource] = []
    seen: set[tuple[str, str, str]] = set()
    used_ids: set[str] = set()
    for resource in resources:
        key = (resource.kind, resource.uri, resource.title)
        if key in seen:
            continue
        seen.add(key)
        resource_id = resource.id
        if resource_id in used_ids:
            resource_id = f"{resource_id}_{len(used_ids) + 1}"
            resource = resource.model_copy(update={"id": resource_id})
        used_ids.add(resource_id)
        deduped.append(resource)
    return deduped
