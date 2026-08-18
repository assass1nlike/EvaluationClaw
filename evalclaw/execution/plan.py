"""Build the immutable accepted-item view consumed by every runner/exporter."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..types import QcReport, TaskSuite


@dataclass(frozen=True)
class ExecutionPlan:
    suite: TaskSuite
    accepted_item_ids: tuple[str, ...]
    rejected_item_ids: tuple[str, ...]


def build_execution_plan(suite: TaskSuite, qc_report: QcReport) -> ExecutionPlan:
    item_by_id = {item.id: item for item in suite.tasks}
    if len(item_by_id) != len(suite.tasks):
        raise ValueError("Benchmark item ids must be unique before an execution plan can be built.")
    passed_ids = tuple(qc_report.passed_item_ids)
    rejected_ids = tuple(qc_report.rejected_item_ids)
    duplicate_passed = sorted(item_id for item_id, count in Counter(passed_ids).items() if count > 1)
    duplicate_rejected = sorted(item_id for item_id, count in Counter(rejected_ids).items() if count > 1)
    if duplicate_passed:
        raise ValueError(f"QC passed_item_ids contains duplicates: {', '.join(duplicate_passed)}")
    if duplicate_rejected:
        raise ValueError(f"QC rejected_item_ids contains duplicates: {', '.join(duplicate_rejected)}")
    unknown_passed = [item_id for item_id in passed_ids if item_id not in item_by_id]
    unknown_rejected = [item_id for item_id in rejected_ids if item_id not in item_by_id]
    if unknown_passed:
        raise ValueError(f"QC passed_item_ids contains unknown items: {', '.join(unknown_passed)}")
    if unknown_rejected:
        raise ValueError(f"QC rejected_item_ids contains unknown items: {', '.join(unknown_rejected)}")
    overlap = sorted(set(passed_ids) & set(rejected_ids))
    if overlap:
        raise ValueError(f"QC item ids cannot be both passed and rejected: {', '.join(overlap)}")
    accepted_ids = passed_ids
    accepted = [item_by_id[item_id] for item_id in accepted_ids]
    execution_suite = suite.model_copy(update={"tasks": accepted})
    return ExecutionPlan(
        suite=execution_suite,
        accepted_item_ids=accepted_ids,
        rejected_item_ids=rejected_ids,
    )
