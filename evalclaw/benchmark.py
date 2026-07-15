"""Single-route benchmark planning, task construction, and QC repair."""
from __future__ import annotations

from collections.abc import Callable

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


def _affected_blueprint_ids(
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
        blueprint_id = str(item.metadata.get("builder_blueprint_id") or "")
        if blueprint_id:
            affected.add(blueprint_id)
    if global_error:
        affected.update(blueprint.id for blueprint in dataset.blueprints)
    return affected


def _revision_contexts(
    dataset: BenchmarkDataset,
    suite: TaskSuite,
    qc_report: QcReport,
    affected_ids: set[str],
) -> dict[str, dict[str, object]]:
    item_by_id = {item.id: item for item in dataset.items}
    blueprint_by_id = {blueprint.id: blueprint for blueprint in suite.blueprints}
    dimensions = {
        blueprint_by_id[blueprint_id].dimension_id
        for blueprint_id in affected_ids
        if blueprint_id in blueprint_by_id
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
                "QC-passed task, including other tasks from the same Blueprint."
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


def build_benchmark_dataset_with_qc_loop(
    goal: str,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
) -> tuple[EvalSpec, BenchmarkDataset, QcReport]:
    """Plan adaptive Blueprints and build each through one Builder call."""
    plan = plan_benchmark(goal, config, log=log)
    spec = plan.to_eval_spec()
    dataset, qc_report = build_dataset_from_spec_with_qc_loop(
        spec,
        plan.blueprints,
        config,
        log=log,
    )
    dataset.plan = plan
    return spec, dataset, qc_report


def build_dataset_from_spec_with_qc_loop(
    spec: EvalSpec,
    blueprints: list[TaskBlueprint],
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
) -> tuple[BenchmarkDataset, QcReport]:
    """Build and QC an already planned specification through the general route."""
    suite = build_task_suite(spec, blueprints, config, log=log)
    dataset = task_suite_to_dataset(suite, spec, config)
    qc_report = run_qc_gate(dataset, config)
    log(f"  QC: reviewing {len(dataset.items)} constructed task(s). {qc_report.summary}")

    max_repairs = max(0, int(config.max_qc_iterations))
    for repair_round in range(1, max_repairs + 1):
        affected_ids = _affected_blueprint_ids(dataset, qc_report)
        if not affected_ids:
            break
        selected = [
            blueprint
            for blueprint in blueprints
            if blueprint.id in affected_ids
        ]
        log(
            f"  QC repair round {repair_round}/{max_repairs}: "
            f"repairing {len(selected)} affected blueprint(s)."
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
        suite = _merge_repaired_suite(suite, repaired)
        dataset = task_suite_to_dataset(suite, spec, config)
        qc_report = run_qc_gate(dataset, config)
        log(f"  QC after repair round {repair_round}: {qc_report.summary}")

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
