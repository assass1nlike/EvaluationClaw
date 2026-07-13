"""QC repair loop for executable agent task suites."""
from __future__ import annotations

from collections.abc import Callable

from ..quality.qc import run_qc_gate
from ..types import (
    AgentResource,
    AgentTask,
    AgentTaskBlueprint,
    AgentTaskSuite,
    BenchmarkConfig,
    BenchmarkDataset,
    EvalSpec,
    QcReport,
    QcSeverity,
)
from .packaging import task_suite_to_dataset
from .planning import plan_agent_benchmark
from .suite import build_agent_task_suite


def _blocking_dimensions(dataset: BenchmarkDataset, qc_report: QcReport) -> set[str]:
    item_dimensions = {item.id: item.dimension_id for item in dataset.items}
    dimensions: set[str] = set()
    global_error = False
    for issue in qc_report.issues:
        if issue.severity != QcSeverity.error:
            continue
        if issue.item_id and issue.item_id in item_dimensions:
            dimensions.add(item_dimensions[issue.item_id])
        else:
            global_error = True
    if global_error:
        return {dimension.id for dimension in dataset.spec.dimensions}
    return dimensions


def _revision_contexts(
    dataset: BenchmarkDataset,
    suite: AgentTaskSuite,
    qc_report: QcReport,
    dimensions: set[str],
) -> dict[str, dict[str, object]]:
    item_dimensions = {item.id: item.dimension_id for item in dataset.items}
    contexts: dict[str, dict[str, object]] = {}
    for dimension_id in dimensions:
        issues = [
            issue.model_dump(mode="json")
            for issue in qc_report.issues
            if issue.severity == QcSeverity.error
            and (issue.item_id is None or item_dimensions.get(issue.item_id) == dimension_id)
        ]
        previous_tasks = [
            task.model_dump(mode="json")
            for task in suite.tasks
            if task.dimension_id == dimension_id
        ]
        contexts[dimension_id] = {
            "reason": "agent_task_qc_repair",
            "qc_issues": issues,
            "previous_tasks": previous_tasks,
            "instruction": (
                "Return complete replacement tasks for this dimension. Preserve sound task content, "
                "but fix every blocking QC issue and re-check prompt/tool/environment/output/evaluator consistency."
            ),
        }
    return contexts


def _dedupe_resources(resources: list[AgentResource]) -> list[AgentResource]:
    by_id: dict[str, AgentResource] = {}
    for resource in resources:
        by_id[resource.id] = resource
    return list(by_id.values())


def _merge_repaired_suite(
    previous: AgentTaskSuite,
    repaired: AgentTaskSuite,
    dimensions: set[str],
    spec: EvalSpec,
    blueprints: list[AgentTaskBlueprint],
) -> AgentTaskSuite:
    tasks: list[AgentTask] = [
        task for task in previous.tasks if task.dimension_id not in dimensions
    ]
    tasks.extend(task for task in repaired.tasks if task.dimension_id in dimensions)
    dimension_order = {dimension.id: index for index, dimension in enumerate(spec.dimensions)}
    tasks.sort(key=lambda task: (dimension_order.get(task.dimension_id, len(dimension_order)), task.id))
    return AgentTaskSuite(
        id=previous.id,
        objective=previous.objective,
        dimensions=spec.dimensions,
        blueprints=blueprints,
        resources=_dedupe_resources([*previous.resources, *repaired.resources]),
        tasks=tasks,
        construction_notes=(
            previous.construction_notes.rstrip()
            + "\nQC repair: "
            + repaired.construction_notes.strip()
        ).strip(),
    )


def build_agent_dataset_with_qc_loop(
    goal: str,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
) -> tuple[EvalSpec, BenchmarkDataset, QcReport]:
    """Plan once, then repair only QC-rejected agent dimensions."""
    spec, blueprints = plan_agent_benchmark(goal, config)
    suite = build_agent_task_suite(spec, blueprints, config)
    dataset = task_suite_to_dataset(suite, spec, config)
    qc_report = run_qc_gate(dataset, config)
    max_repairs = max(0, int(config.max_qc_iterations))

    for repair_round in range(1, max_repairs + 1):
        dimensions = _blocking_dimensions(dataset, qc_report)
        if not dimensions:
            break
        log(
            f"  Agent QC repair round {repair_round}/{max_repairs}: "
            f"rebuilding {len(dimensions)} rejected dimension(s)."
        )
        contexts = _revision_contexts(dataset, suite, qc_report, dimensions)
        selected_blueprints = [
            blueprint for blueprint in blueprints if blueprint.dimension_id in dimensions
        ]
        repaired = build_agent_task_suite(
            spec,
            selected_blueprints,
            config,
            revision_context_by_dimension=contexts,
        )
        suite = _merge_repaired_suite(suite, repaired, dimensions, spec, blueprints)
        dataset = task_suite_to_dataset(suite, spec, config)
        qc_report = run_qc_gate(dataset, config)

    if (not qc_report.is_acceptable or qc_report.rejected_item_ids) and not config.allow_incomplete_benchmark:
        raise RuntimeError(
            "Agent benchmark did not produce a runner-ready dataset after "
            f"{max_repairs} repair iteration(s): {len(qc_report.rejected_item_ids)} rejected "
            f"item(s), quality_score={qc_report.quality_score:.3f}."
        )
    return spec, dataset, qc_report


__all__ = ["build_agent_dataset_with_qc_loop"]
