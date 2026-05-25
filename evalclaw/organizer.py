"""Compatibility wrapper for the old Organizer name.

New code should import :mod:`evalclaw.qc` and :mod:`evalclaw.reporter`.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from .qc import run_qc_gate
from .types import BenchmarkConfig, BenchmarkDataset, BenchmarkItem, EvalSpec, ItemResult


class MarkType(str, Enum):
    problematic = "problematic"
    redundant = "redundant"
    difficult = "difficult"


class OrganizerMark(BaseModel):
    question_id: str
    mark_type: MarkType
    reason: str
    guidance: str


def run_organizer(
    questions: list[BenchmarkItem],
    results: list[ItemResult],
    config: BenchmarkConfig,
) -> tuple[str, list[OrganizerMark], bool]:
    """Map old organizer behavior onto the new QC gate."""
    dimension_ids = sorted({item.dimension_id for item in questions})
    spec = EvalSpec(
        objective="Compatibility organizer run",
        dimensions=[
            {
                "id": dimension_id,
                "name": dimension_id,
                "description": "",
                "approach": "",
            }
            for dimension_id in dimension_ids
        ],
    )
    report = run_qc_gate(BenchmarkDataset(spec=spec, items=questions), config)
    marks: list[OrganizerMark] = []
    for issue in report.issues:
        if not issue.item_id:
            continue
        mark_type = MarkType.problematic
        if issue.category.value == "duplicate":
            mark_type = MarkType.redundant
        marks.append(
            OrganizerMark(
                question_id=issue.item_id,
                mark_type=mark_type,
                reason=issue.message,
                guidance=issue.suggested_action,
            )
        )
    return report.summary, marks, report.is_acceptable
