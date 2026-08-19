"""Single-route benchmark planning, task construction, and QC repair."""
from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .construction.suite import build_task_suite
from .planning.task_planner import plan_benchmark
from .quality.qc import run_qc_gate
from .types import (
    BenchmarkConfig,
    EvalSpec,
    QcReport,
    QcSeverity,
    TaskBlueprint,
    TaskResource,
    TaskSuite,
)


def _affected_builder_job_ids(
    suite: TaskSuite,
    qc_report: QcReport,
) -> set[str]:
    item_by_id = {item.id: item for item in suite.tasks}
    affected: set[str] = set()
    for issue in qc_report.issues:
        if issue.severity != QcSeverity.error or not issue.item_id:
            continue
        item = item_by_id.get(issue.item_id)
        if item is None:
            continue
        builder_job_id = item.builder_job_id
        if builder_job_id:
            affected.add(builder_job_id)
    return affected


def _revision_contexts(
    suite: TaskSuite,
    qc_report: QcReport,
    affected_ids: set[str],
) -> dict[str, dict[str, object]]:
    item_by_id = {item.id: item for item in suite.tasks}
    job_by_id = {job.id: job for job in suite.builder_jobs}
    dimensions = {
        job_by_id[job_id].dimension_id
        for job_id in affected_ids
        if job_id in job_by_id
    }
    contexts: dict[str, dict[str, object]] = {}
    for dimension_id in dimensions:
        issues = []
        for issue in qc_report.issues:
            if issue.severity != QcSeverity.error:
                continue
            item = item_by_id.get(issue.item_id or "")
            if issue.item_id is None or (item is not None and item.dimension_id == dimension_id):
                issues.append(issue.model_dump(mode="json"))
        previous_tasks: list[dict[str, object]] = []
        for item in suite.tasks:
            if item.dimension_id != dimension_id:
                continue
            source = item.source_definition
            previous_tasks.append(
                source.model_dump(mode="json") if source is not None else item.model_dump(mode="json")
            )
        contexts[dimension_id] = {
            "reason": "task_qc_repair",
            "qc_issues": issues,
            "previous_tasks": previous_tasks,
            "instruction": (
                "Return replacements only for task ids named by the listed QC issues. Fix every "
                "listed problem and preserve each affected task id. Do not return or modify any "
                "QC-passed task, including other tasks from the same TaskDesign."
            ),
        }
    return contexts


def _merge_repaired_resources(
    previous: list[TaskResource],
    repaired: list[TaskResource],
) -> list[TaskResource]:
    replacements = {resource.id: resource for resource in repaired}
    merged = [replacements.pop(resource.id, resource) for resource in previous]
    merged.extend(replacements.values())
    return merged


def _merge_repaired_suite(
    previous: TaskSuite,
    repaired: TaskSuite,
    *,
    item_ids: set[str] | None = None,
) -> TaskSuite:
    repaired_tasks = [
        item for item in repaired.tasks if item_ids is None or item.id in item_ids
    ]
    replacements = {item.id: item for item in repaired_tasks}
    tasks = [replacements.pop(item.id, item) for item in previous.tasks]
    tasks.extend(replacements.values())
    repaired_resources = repaired.resources
    if item_ids is not None:
        resource_ids: set[str] = set()
        source_uris: set[str] = set()
        for item in repaired_tasks:
            if item.source_definition is not None:
                resource_ids.update(item.source_definition.resource_ids)
            if item.source.uri:
                source_uris.add(item.source.uri)
        repaired_resources = [
            resource
            for resource in repaired.resources
            if resource.id in resource_ids or resource.uri in source_uris
        ]
    return previous.model_copy(
        update={
            "tasks": tasks,
            "resources": _merge_repaired_resources(
                previous.resources,
                repaired_resources,
            ),
            "construction_notes": (
                previous.construction_notes.rstrip()
                + "\nQC repair: "
                + repaired.construction_notes.strip()
            ).strip(),
        }
    )


def _item_blocking_error_counts(report: QcReport) -> Counter[str]:
    return Counter(
        issue.item_id
        for issue in report.issues
        if issue.severity == QcSeverity.error and issue.item_id
    )


def build_benchmark_suite_with_qc_loop(
    goal: str,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
) -> tuple[EvalSpec, TaskSuite, QcReport]:
    """Plan TaskDesigns and build each through one independent Builder call."""
    plan = plan_benchmark(goal, config, log=log)
    spec = plan.to_eval_spec()
    suite, qc_report = build_suite_from_spec_with_qc_loop(
        spec,
        plan.builder_jobs,
        config,
        log=log,
    )
    suite.plan = plan
    return spec, suite, qc_report


def build_suite_from_spec_with_qc_loop(
    spec: EvalSpec,
    builder_jobs: list[TaskBlueprint],
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
) -> tuple[TaskSuite, QcReport]:
    """Build and QC an already planned specification through the general route."""
    qc_debug_root = None
    if config.task_builder_debug_dir:
        qc_debug_root = (
            Path(config.task_builder_debug_dir).expanduser().parent
            / "qc"
            / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
                + "-"
                + uuid.uuid4().hex[:8]
            )
        )

    def run_traced_qc(candidate: TaskSuite, stage: str) -> QcReport:
        if qc_debug_root is None:
            return run_qc_gate(candidate, config)
        trace_dir = qc_debug_root / stage
        report = run_qc_gate(candidate, config, trace_dir=trace_dir)
        log(f"  QC: saved complete trace: {trace_dir}.")
        return report

    planned_dimension_ids = {job.dimension_id for job in builder_jobs}
    missing_dimension_ids = [
        dimension.id
        for dimension in spec.dimensions
        if dimension.id not in planned_dimension_ids
    ]
    if missing_dimension_ids:
        raise ValueError(
            "Missing TaskDesign Builder jobs for dimension(s): "
            + ", ".join(missing_dimension_ids)
        )

    suite = build_task_suite(spec, builder_jobs, config, log=log)
    qc_report = run_traced_qc(suite, "00-initial")
    log(f"  QC: reviewing {len(suite.tasks)} constructed task(s). {qc_report.summary}")

    max_repairs = max(0, int(config.max_qc_iterations))
    for repair_round in range(1, max_repairs + 1):
        affected_ids = _affected_builder_job_ids(suite, qc_report)
        if not affected_ids:
            break
        selected = [job for job in builder_jobs if job.id in affected_ids]
        log(
            f"  QC repair round {repair_round}/{max_repairs}: "
            f"repairing {len(selected)} affected TaskDesign job(s)."
        )
        repaired = build_task_suite(
            spec,
            selected,
            config,
            revision_context_by_dimension=_revision_contexts(
                suite,
                qc_report,
                affected_ids,
            ),
            log=log,
        )
        candidate_suite = _merge_repaired_suite(suite, repaired)
        candidate_qc = run_traced_qc(candidate_suite, f"{repair_round:02d}-repair-candidate")
        log(f"  QC after repair round {repair_round}: {candidate_qc.summary}")
        previous_errors = _item_blocking_error_counts(qc_report)
        candidate_errors = _item_blocking_error_counts(candidate_qc)
        repaired_ids = {item.id for item in repaired.tasks}
        improved_ids = {
            item_id
            for item_id in repaired_ids
            if candidate_errors[item_id] < previous_errors[item_id]
        }
        if not improved_ids:
            log(
                f"  QC repair round {repair_round}: discarded non-improving replacement(s); "
                "no repaired item strictly reduced its blocking error count."
            )
            continue

        selected_suite = candidate_suite
        selected_qc = candidate_qc
        selection_pass = 0
        if improved_ids != repaired_ids:
            selected_suite = _merge_repaired_suite(
                suite,
                repaired,
                item_ids=improved_ids,
            )
            selection_pass += 1
            selected_qc = run_traced_qc(
                selected_suite,
                f"{repair_round:02d}-selected-{selection_pass:02d}",
            )

        while improved_ids:
            selected_errors = _item_blocking_error_counts(selected_qc)
            no_longer_improved = {
                item_id
                for item_id in improved_ids
                if selected_errors[item_id] >= previous_errors[item_id]
            }
            if not no_longer_improved:
                break
            improved_ids -= no_longer_improved
            if not improved_ids:
                break
            selected_suite = _merge_repaired_suite(
                suite,
                repaired,
                item_ids=improved_ids,
            )
            selection_pass += 1
            selected_qc = run_traced_qc(
                selected_suite,
                f"{repair_round:02d}-selected-{selection_pass:02d}",
            )

        if not improved_ids:
            log(
                f"  QC repair round {repair_round}: discarded non-improving replacement(s); "
                "no repaired item remained improved after partial merge."
            )
            continue

        rolled_back = repaired_ids - improved_ids
        log(
            f"  QC repair round {repair_round}: kept {len(improved_ids)} improved item repair(s), "
            f"rolled back {len(rolled_back)} non-improving item repair(s)."
        )
        suite = selected_suite
        qc_report = selected_qc

    if (not qc_report.is_acceptable or qc_report.rejected_item_ids) and not config.allow_incomplete_benchmark:
        blocking = [issue for issue in qc_report.issues if issue.severity == QcSeverity.error]
        for issue in blocking[:10]:
            log(f"  QC blocking issue [{issue.item_id or 'dataset'}]: {issue.message}")
        raise RuntimeError(
            "Benchmark did not produce a runner-ready suite after unified task QC: "
            f"{len(qc_report.rejected_item_ids)} rejected item(s), "
            f"quality_score={qc_report.quality_score:.3f}."
        )
    return suite, qc_report


__all__ = [
    "build_benchmark_suite_with_qc_loop",
    "build_suite_from_spec_with_qc_loop",
    "plan_benchmark",
]
