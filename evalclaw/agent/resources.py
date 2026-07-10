"""Resource discovery and normalization for agent benchmarks."""
from __future__ import annotations

from typing import Any

from ..research.backends import format_search_result, web_search
from ..types import (
    AgentResource,
    AgentTaskBlueprint,
    BenchmarkConfig,
    BenchmarkSource,
    EvalDimension,
    SourceKind,
)
from .common import _slug


def _resource_from_raw(raw: dict[str, Any], fallback_id: str) -> AgentResource:
    return AgentResource(
        id=str(raw.get("id") or fallback_id),
        kind=str(raw.get("kind") or "web"),
        uri=str(raw.get("uri") or ""),
        title=str(raw.get("title") or ""),
        license=str(raw.get("license") or ""),
        content_summary=str(raw.get("content_summary") or ""),
        notes=str(raw.get("notes") or ""),
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def _agent_resource_from_source(source: BenchmarkSource, fallback_id: str) -> AgentResource:
    return AgentResource(
        id=_slug(fallback_id),
        kind=source.kind.value,
        uri=source.uri,
        title=source.title,
        content_summary=source.notes[:1000],
        notes="Discovered by agent benchmark resource search.",
    )


def _select_blueprint_sources(
    dimension: EvalDimension,
    blueprint: AgentTaskBlueprint,
    config: BenchmarkConfig,
) -> list[BenchmarkSource]:
    if not config.use_web_research or not config.orchestrator_api_key:
        return []
    queries = blueprint.resource_queries or dimension.research_queries
    if not queries:
        queries = [
            f"{dimension.name} {blueprint.title} agent benchmark task resources",
            f"{dimension.name} {blueprint.task_family.value} benchmark dataset",
        ]
    sources: list[BenchmarkSource] = []
    seen: set[str] = set()
    for query in queries[:2]:
        result = web_search(
            query,
            api_key=config.orchestrator_api_key,
            model=config.orchestrator_model,
            backend=config.search_backend,
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


def _dedupe_agent_resources(resources: list[AgentResource]) -> list[AgentResource]:
    deduped: list[AgentResource] = []
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
        used_ids.add(resource.id)
        deduped.append(resource)
    return deduped
