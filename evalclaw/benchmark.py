"""Single-route benchmark planning, task construction, and QC repair."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .construction.packaging import task_suite_to_dataset
from .construction.suite import build_task_suite
from .planning.task_planner import plan_benchmark
from .quality.qc import run_qc_gate
from .types import (
    BenchmarkConfig,
    BenchmarkDataset,
    EvalSpec,
    QcReport,
    QcSeverity,
    TaskBlueprint,
    TaskResource,
    TaskSuite,
)


def _affected_builder_job_ids(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
) -> set[str]:
    item_by_id = {item.id: item for item in dataset.items}
    affected: set[str] = set()
    global_error = False
    for issue in qc_report.issues:
        if issue.severity != QcSeverity.error:
            continue
        if not issue.item_id:
            global_error = True
            continue
        item = item_by_id.get(issue.item_id)
        if item is None:
            continue
        builder_job_id = str(item.metadata.get("builder_job_id") or "")
        if builder_job_id:
            affected.add(builder_job_id)
    if global_error:
        affected.update(job.id for job in dataset.builder_jobs)
    return affected


def _revision_contexts(
    dataset: BenchmarkDataset,
    suite: TaskSuite,
    qc_report: QcReport,
    affected_ids: set[str],
) -> dict[str, dict[str, object]]:
    item_by_id = {item.id: item for item in dataset.items}
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
        contexts[dimension_id] = {
            "reason": "task_qc_repair",
            "qc_issues": issues,
            "previous_tasks": [
                task.model_dump(mode="json")
                for task in suite.tasks
                if task.dimension_id == dimension_id
            ],
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
) -> TaskSuite:
    replacements = {task.id: task for task in repaired.tasks}
    tasks = [replacements.pop(task.id, task) for task in previous.tasks]
    tasks.extend(replacements.values())
    return previous.model_copy(
        update={
            "tasks": tasks,
            "resources": _merge_repaired_resources(
                previous.resources,
                repaired.resources,
            ),
            "construction_notes": (
                previous.construction_notes.rstrip()
                + "\nQC repair: "
                + repaired.construction_notes.strip()
            ).strip(),
        }
    )


def _blocking_error_count(report: QcReport) -> int:
    return sum(issue.severity == QcSeverity.error for issue in report.issues)


def build_benchmark_dataset_with_qc_loop(
    goal: str,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
) -> tuple[EvalSpec, BenchmarkDataset, QcReport]:
    """Plan TaskDesigns and build each through one independent Builder call."""
    plan = plan_benchmark(goal, config, log=log)
    spec = plan.to_eval_spec()
    dataset, qc_report = build_dataset_from_spec_with_qc_loop(
        spec,
        plan.builder_jobs,
        config,
        log=log,
    )
    dataset.plan = plan
    return spec, dataset, qc_report


def build_dataset_from_spec_with_qc_loop(
    spec: EvalSpec,
    builder_jobs: list[TaskBlueprint],
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
) -> tuple[BenchmarkDataset, QcReport]:
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

    def run_traced_qc(candidate: BenchmarkDataset, stage: str) -> QcReport:
        if qc_debug_root is None:
            return run_qc_gate(candidate, config)
        trace_dir = qc_debug_root / stage
        report = run_qc_gate(candidate, config, trace_dir=trace_dir)
        log(f"  QC: saved complete trace: {trace_dir}.")
        return report

    suite = build_task_suite(spec, builder_jobs, config, log=log)
    dataset = task_suite_to_dataset(suite, spec, config)
    qc_report = run_traced_qc(dataset, "00-initial")
    log(f"  QC: reviewing {len(dataset.items)} constructed task(s). {qc_report.summary}")

    max_repairs = max(0, int(config.max_qc_iterations))
    for repair_round in range(1, max_repairs + 1):
        affected_ids = _affected_builder_job_ids(dataset, qc_report)
        if not affected_ids:
            break
        selected = [
            job
            for job in builder_jobs
            if job.id in affected_ids
        ]
        log(
            f"  QC repair round {repair_round}/{max_repairs}: "
            f"repairing {len(selected)} affected TaskDesign job(s)."
        )
        repaired = build_task_suite(
            spec,
            selected,
            config,
            revision_context_by_dimension=_revision_contexts(
                dataset,
                suite,
                qc_report,
                affected_ids,
            ),
            log=log,
        )
        candidate_suite = _merge_repaired_suite(suite, repaired)
        candidate_dataset = task_suite_to_dataset(candidate_suite, spec, config)
        candidate_qc = run_traced_qc(
            candidate_dataset,
            f"{repair_round:02d}-repair-candidate",
        )
        log(f"  QC after repair round {repair_round}: {candidate_qc.summary}")
        previous_errors = _blocking_error_count(qc_report)
        candidate_errors = _blocking_error_count(candidate_qc)
        if candidate_errors >= previous_errors:
            log(
                f"  QC repair round {repair_round}: discarded non-improving replacement "
                f"({candidate_errors} blocking issue(s), current best {previous_errors})."
            )
            continue
        suite = candidate_suite
        dataset = candidate_dataset
        qc_report = candidate_qc

    if (not qc_report.is_acceptable or qc_report.rejected_item_ids) and not config.allow_incomplete_benchmark:
        blocking = [issue for issue in qc_report.issues if issue.severity == QcSeverity.error]
        for issue in blocking[:10]:
            log(f"  QC blocking issue [{issue.item_id or 'dataset'}]: {issue.message}")
        raise RuntimeError(
            "Benchmark did not produce a runner-ready dataset after unified task QC: "
            f"{len(qc_report.rejected_item_ids)} rejected item(s), "
            f"quality_score={qc_report.quality_score:.3f}."
        )
    return dataset, qc_report


__all__ = [
    "build_benchmark_dataset_with_qc_loop",
    "build_dataset_from_spec_with_qc_loop",
    "plan_benchmark",
]
