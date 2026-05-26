"""HuggingFace dataset discovery for benchmark reuse signals."""
from __future__ import annotations

from .types import BenchmarkSource, EvalDimension, SourceKind

MATH_HINTS = {
    "math",
    "mathematics",
    "number theory",
    "combinatorics",
    "algebra",
    "geometry",
    "linear algebra",
    "probability",
    "discrete",
    "proof",
    "theorem",
    "olympiad",
    "数论",
    "组合",
    "代数",
    "几何",
    "概率",
    "证明",
}
MATH_FALLBACK_QUERIES = [
    "math reasoning",
    "olympiad math",
    "mathematical proof",
]


def _expanded_queries(dimension: EvalDimension) -> list[str]:
    base = [*dimension.research_queries, dimension.name, dimension.description]
    text = " ".join(base + [dimension.id]).lower()
    queries: list[str] = []
    seen: set[str] = set()
    for query in base:
        query = query.strip()
        if query and query not in seen:
            seen.add(query)
            queries.append(query)
    if any(hint in text for hint in MATH_HINTS):
        for query in MATH_FALLBACK_QUERIES:
            if query not in seen:
                seen.add(query)
                queries.append(query)
    return queries


def discover_hf_datasets(
    dimension: EvalDimension,
    *,
    limit: int = 5,
) -> list[BenchmarkSource]:
    """Search HuggingFace Hub for datasets that may match a dimension."""
    try:
        from huggingface_hub import HfApi
    except Exception:
        return []
    api = HfApi()
    queries = _expanded_queries(dimension)
    results: list[BenchmarkSource] = []
    seen: set[str] = set()
    for query in queries:
        if not query:
            continue
        try:
            datasets = api.list_datasets(search=query, limit=limit)
            for dataset in datasets:
                dataset_id = getattr(dataset, "id", None) or getattr(dataset, "card_id", None)
                if not dataset_id or dataset_id in seen:
                    continue
                seen.add(dataset_id)
                likes = getattr(dataset, "likes", None)
                downloads = getattr(dataset, "downloads", None)
                tags = getattr(dataset, "tags", None) or []
                results.append(
                    BenchmarkSource(
                        kind=SourceKind.hf_dataset,
                        uri=f"hf://datasets/{dataset_id}",
                        title=str(dataset_id),
                        notes=f"likes={likes}; downloads={downloads}; tags={', '.join(map(str, tags[:10]))}",
                    )
                )
                if len(results) >= limit:
                    return results
        except Exception:
            continue
    return results
