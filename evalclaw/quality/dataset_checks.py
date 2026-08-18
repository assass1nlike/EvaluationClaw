"""TaskSuite-level quality checks for coverage and duplicates."""
from __future__ import annotations

import difflib
import re
from collections import Counter

from ..core.scaling import is_large_scale_budget
from ..types import (
    BenchmarkConfig,
    BenchmarkItem,
    QcCategory,
    QcIssue,
    QcSeverity,
    TaskSuite,
)
from .common import _is_source_backed, _issue


def _prompt_fingerprint(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.strip().lower())


def _token_jaccard(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9_]{3,}", left.lower()))
    right_tokens = set(re.findall(r"[a-z0-9_]{3,}", right.lower()))
    if not left_tokens and not right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _duplicate_issues(items: list[BenchmarkItem], *, near_duplicate_limit: int | None = None) -> list[QcIssue]:
    issues: list[QcIssue] = []
    seen_ids: set[str] = set()
    seen_exact: dict[str, str] = {}
    for item in items:
        if item.id in seen_ids:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    f"Item id {item.id!r} is duplicated.",
                    "Assign every benchmark item a unique stable id.",
                )
            )
        seen_ids.add(item.id)
        fingerprint = _prompt_fingerprint(item.prompt)
        first_id = seen_exact.get(fingerprint)
        if first_id:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.duplicate,
                    f"Prompt is identical to {first_id}.",
                    "Deduplicate repeated items before running a large evaluation.",
                )
            )
        else:
            seen_exact[fingerprint] = item.id

    checked_items = items[:near_duplicate_limit] if near_duplicate_limit is not None else items
    for idx, item in enumerate(checked_items):
        for other in checked_items[idx + 1 :]:
            if _prompt_fingerprint(item.prompt) == _prompt_fingerprint(other.prompt):
                continue
            ratio = difflib.SequenceMatcher(None, item.prompt.lower(), other.prompt.lower()).ratio()
            overlap = _token_jaccard(item.prompt, other.prompt)
            if ratio >= 0.92 and overlap >= 0.78:
                issues.append(
                    _issue(
                        other.id,
                        QcSeverity.warning,
                        QcCategory.duplicate,
                        f"Prompt is very similar to {item.id} (similarity {ratio:.2f}, token overlap {overlap:.2f}).",
                        "Rewrite one item to test a distinct behavior.",
                    )
                )
    return issues

def _coverage_issues(suite: TaskSuite) -> list[QcIssue]:
    issues: list[QcIssue] = []
    item_count = len(suite.tasks)
    dimension_ids = {dimension.id for dimension in suite.spec.dimensions}
    for item in suite.tasks:
        if item.dimension_id not in dimension_ids:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.coverage,
                    f"Item references unknown dimension {item.dimension_id!r}.",
                    "Assign the item to one of the benchmark's planned dimensions.",
                )
            )
    task_counts = Counter(item.task_type for item in suite.tasks)
    for dimension in suite.spec.dimensions:
        dim_items = [item for item in suite.tasks if item.dimension_id == dimension.id]
        if not dim_items:
            issues.append(
                _issue(
                    None,
                    QcSeverity.error,
                    QcCategory.coverage,
                    f"Dimension {dimension.id} has no generated items.",
                    "Generate at least one item for every planned dimension.",
                )
            )
            continue
        if suite.spec.scale_budget.value in {"high", "large", "xlarge"} and len(dim_items) < 2:
            budget_label = {
                "high": "High",
                "large": "Large",
                "xlarge": "Xlarge",
            }.get(suite.spec.scale_budget.value, suite.spec.scale_budget.value)
            issues.append(
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.coverage,
                    f"{budget_label}-budget dimension {dimension.id} has only {len(dim_items)} item(s).",
                    "Add more targeted items or Loop 3 expansion before treating this as a deep evaluation.",
                )
            )
        source_backed_target = int(dimension.target_source_backed_count or 0)
        if source_backed_target > 0:
            backed_count = sum(1 for item in dim_items if _is_source_backed(item))
            if backed_count < min(source_backed_target, len(dim_items)):
                issues.append(
                    _issue(
                        None,
                        QcSeverity.warning,
                        QcCategory.coverage,
                        f"Dimension {dimension.id} has {backed_count}/{source_backed_target} planned source-backed items.",
                        "Materialize the planned source-backed coverage or revise the plan explicitly.",
                    )
                )
    for task_type in suite.spec.task_types:
        if task_counts[task_type] == 0:
            issues.append(
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.coverage,
                    f"Planned task type {task_type.value} has no generated items.",
                    "Generate at least one item for each planned task type or remove it from the spec.",
                )
            )
    return issues


def _near_duplicate_limit(suite: TaskSuite, config: BenchmarkConfig) -> int | None:
    if suite.spec.scale_budget.value == "high":
        return max(100, min(300, int(config.large_scale_llm_qc_sample_size) * 2))
    if is_large_scale_budget(suite.spec.scale_budget):
        return max(100, min(500, int(config.large_scale_llm_qc_sample_size) * 3))
    return None
