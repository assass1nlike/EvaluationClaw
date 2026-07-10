"""Shared helpers for quality-control checks."""
from __future__ import annotations

from ..types import BenchmarkItem, QcCategory, QcIssue, QcSeverity, SourceKind

DIFFICULTY_RANK = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}

def _issue(
    item_id: str | None,
    severity: QcSeverity,
    category: QcCategory,
    message: str,
    suggested_action: str = "",
) -> QcIssue:
    return QcIssue(
        item_id=item_id,
        severity=severity,
        category=category,
        message=message,
        suggested_action=suggested_action,
    )

def _is_source_backed(item: BenchmarkItem) -> bool:
    package = item.metadata.get("agent_task_package") if isinstance(item.metadata, dict) else None
    if isinstance(package, dict):
        provenance = package.get("resource_provenance")
        if isinstance(provenance, dict) and provenance.get("source_kind") == "generated_fixture":
            return False
    return item.source.kind in {SourceKind.web, SourceKind.hf_dataset, SourceKind.lm_eval, SourceKind.imported} and bool(item.source.uri)
