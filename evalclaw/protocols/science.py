"""Science-domain planning and item metadata guidance."""
from __future__ import annotations

from typing import Any

from ..types import BenchmarkItem

SCIENCE_METADATA_KEY = "science"
SCIENCE_SCHEMA_VERSION = "evalclaw.science.v1"


def get_science_spec(item: BenchmarkItem) -> dict[str, Any] | None:
    spec = item.metadata.get(SCIENCE_METADATA_KEY)
    return spec if isinstance(spec, dict) else None


def science_metadata_issues(item: BenchmarkItem) -> list[str]:
    spec = get_science_spec(item)
    if not spec:
        return []
    issues: list[str] = []
    if spec.get("schema_version") != SCIENCE_SCHEMA_VERSION:
        issues.append("metadata.science.schema_version must be evalclaw.science.v1.")
    for key in ("discipline", "scientific_skill", "evidence_context", "answer_type"):
        if not str(spec.get(key) or "").strip():
            issues.append(f"metadata.science.{key} must be populated.")
    assumptions = spec.get("assumptions")
    if assumptions is not None and not isinstance(assumptions, list):
        issues.append("metadata.science.assumptions must be a list when provided.")
    return issues
