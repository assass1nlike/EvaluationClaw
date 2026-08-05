"""Planner-supervised generation and pre-run QC repair loop."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any, Callable

from ..benchmark import build_dataset_from_spec_with_qc_loop
from ..generation.generator import target_count_for_dimension
from ..models.llm import call_llm, extract_json
from ..models.roles import role_model_settings
from ..planning.task_planner import plan_from_spec
from ..prompts.planning_loop import PLANNER_REVIEW_SYSTEM_PROMPT
from ..protocols.task_agent import compact_task_agent_for_qc
from ..types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    ChallengeEffort,
    EvalDimension,
    EvalSpec,
    Message,
    QcReport,
    TaskType,
    TaskTypeAllocation,
    safe_challenge_effort,
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")[:48] or "dimension"


def _safe_task_type(value: object) -> TaskType:
    try:
        return TaskType(str(value))
    except ValueError:
        return TaskType.generation


def _safe_effort(value: object, fallback: ChallengeEffort = ChallengeEffort.E3) -> ChallengeEffort:
    return safe_challenge_effort(value, fallback)


def _safe_positive_int(value: object, fallback: int | None = None) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _dimension_from_data(data: dict[str, Any], fallback: EvalDimension | None = None) -> EvalDimension:
    base = fallback.model_dump(mode="json") if fallback else {}
    merged = {**base, **data}
    dim_id = str(merged.get("id") or _slug(str(merged.get("name") or "dimension")))
    challenge_effort = _safe_effort(
        merged.get("challenge_effort")
        or merged.get("target_challenge_effort")
        or merged.get("task_builder_effort")
    )
    raw_allocation = merged.get("task_type_allocation", [])
    task_type_allocation = [
        TaskTypeAllocation(
            task_type=_safe_task_type(item.get("task_type")),
            count=count,
        )
        for item in raw_allocation
        if isinstance(item, dict)
        and (count := _safe_positive_int(item.get("count"))) is not None
    ]
    if "task_type_allocation" not in data and (
        "task_types" in data or "target_item_count" in data
    ):
        task_type_allocation = []
    return EvalDimension(
        id=dim_id,
        name=str(merged.get("name") or dim_id),
        measurement_target=str(merged.get("measurement_target") or ""),
        boundary=str(merged.get("boundary") or ""),
        description=str(merged.get("description") or ""),
        approach=str(merged.get("approach") or ""),
        weight=float(merged.get("weight", 1.0) or 1.0),
        challenge_effort=challenge_effort,
        needs_research=bool(merged.get("needs_research", False)),
        research_queries=[str(q) for q in merged.get("research_queries", []) if q],
        target_item_count=_safe_positive_int(merged.get("target_item_count")),
        target_source_backed_count=max(0, _safe_positive_int(merged.get("target_source_backed_count"), 0) or 0),
        target_generated_count=_safe_positive_int(merged.get("target_generated_count")),
        task_types=[_safe_task_type(x) for x in merged.get("task_types", [])],
        task_type_allocation=task_type_allocation,
        item_requirements=[str(x) for x in merged.get("item_requirements", []) if x],
    )


def _item_excerpt(item: BenchmarkItem) -> dict[str, object]:
    task_agent = item.metadata.get("task_agent")
    metadata: dict[str, object] = {}
    if isinstance(task_agent, dict):
        metadata["task_agent"] = compact_task_agent_for_qc(task_agent)
    if isinstance(item.metadata.get("turns"), list):
        metadata["turns"] = item.metadata["turns"][:5]
    agent_env = item.metadata.get("agent_env")
    if isinstance(agent_env, dict):
        metadata["agent_env_type"] = str(agent_env.get("type") or "")
    science = item.metadata.get("science")
    if isinstance(science, dict):
        metadata["science"] = {
            "schema_version": science.get("schema_version"),
            "discipline": science.get("discipline"),
            "scientific_skill": science.get("scientific_skill"),
            "evidence_context": science.get("evidence_context"),
            "answer_type": science.get("answer_type"),
            "units": science.get("units"),
        }
    return {
        "id": item.id,
        "dimension_id": item.dimension_id,
        "task_type": item.task_type.value,
        "challenge_effort": item.challenge_effort.value,
        "prompt": item.prompt[:700],
        "choices": [choice.model_dump(mode="json") for choice in item.choices],
        "correct_choice_ids": item.correct_choice_ids,
        "expected_text": item.expected_text,
        "rubric": (item.rubric or "")[:500],
        "judge_tools": [tool.model_dump(mode="json") for tool in item.judge_tools],
        "output_contract": item.output_contract,
        "source": item.source.model_dump(mode="json"),
        "tags": item.tags,
        "metadata": metadata,
    }


def _dimension_dataset_summaries(dataset: BenchmarkDataset, config: BenchmarkConfig) -> list[dict[str, object]]:
    batch_by_dimension = {batch.dimension_id: batch for batch in dataset.batches}
    summaries: list[dict[str, object]] = []
    for dimension in dataset.spec.dimensions:
        dim_items = [item for item in dataset.items if item.dimension_id == dimension.id]
        source_counts = Counter(item.source.kind.value for item in dim_items)
        task_counts = Counter(item.task_type.value for item in dim_items)
        batch = batch_by_dimension.get(dimension.id)
        summaries.append(
            {
                "dimension_id": dimension.id,
                "batch": batch.model_dump(mode="json") if batch else None,
                "planned_materialized_target": target_count_for_dimension(dimension, config),
                "current_items": len(dim_items),
                "task_counts": dict(task_counts),
                "source_counts": dict(source_counts),
                "target_item_count": dimension.target_item_count,
                "target_source_backed_count": dimension.target_source_backed_count,
                "target_generated_count": dimension.target_generated_count,
            }
        )
    return summaries


def _planner_review(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    config: BenchmarkConfig,
    *,
    human_feedback: str | None = None,
) -> dict[str, Any]:
    settings = role_model_settings(config, "planner")
    if not settings.configured:
        return {"done": True, "notes": "Local mode: planner dataset review skipped."}
    system = PLANNER_REVIEW_SYSTEM_PROMPT
    if human_feedback:
        system += (
            "\n\nA human reviewer has requested changes. Apply the requested changes when they are "
            "compatible with the evaluation objective. If the request requires new coverage, use "
            "add_dimensions, dimension_updates, delete/move actions, and needs_more_items as needed."
        )
    payload = {
        "objective": dataset.spec.objective,
        "scale_budget": dataset.spec.scale_budget.value,
        "human_feedback": human_feedback,
        "reference_model": config.reference_model.model_dump(mode="json") if config.reference_model else None,
        "dimensions": [dimension.model_dump(mode="json") for dimension in dataset.spec.dimensions],
        "dimension_dataset_summaries": _dimension_dataset_summaries(dataset, config),
        "target_counts": {
            dimension.id: target_count_for_dimension(dimension, config)
            for dimension in dataset.spec.dimensions
        },
        "current_counts": Counter(item.dimension_id for item in dataset.items),
        "qc_issues": [issue.model_dump(mode="json") for issue in qc_report.issues[:60]],
        "items": [_item_excerpt(item) for item in dataset.items[:80]],
    }
    try:
        raw = call_llm(
            [Message(role="user", content=json.dumps(payload, ensure_ascii=False, indent=2))],
            system=system,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            max_tokens=8192,
        )
        data = extract_json(raw)
        return data if isinstance(data, dict) else {"done": True, "notes": "Planner review returned non-object JSON."}
    except Exception as exc:
        return {"done": True, "notes": f"Planner dataset review failed; task rebuild used: {exc}"}


def _apply_review(
    dataset: BenchmarkDataset,
    review: dict[str, Any],
    qc_report: QcReport | None = None,
    config: BenchmarkConfig | None = None,
) -> tuple[BenchmarkDataset, list[str]]:
    notes: list[str] = []
    dimensions = list(dataset.spec.dimensions)
    items = list(dataset.items)
    sources = list(dataset.sources)
    by_dim = {dimension.id: dimension for dimension in dimensions}

    delete_ids = {str(item_id) for item_id in review.get("delete_item_ids", [])}
    if delete_ids and qc_report and config and qc_report.is_acceptable and not qc_report.rejected_item_ids:
        delete_dimensions = {
            item.dimension_id
            for item in items
            if item.id in delete_ids
        }
        remaining_counts = Counter(
            item.dimension_id
            for item in items
            if item.id not in delete_ids
        )
        protected_dimensions = {
            dimension.id
            for dimension in dimensions
            if dimension.id in delete_dimensions
            and remaining_counts[dimension.id] < target_count_for_dimension(dimension, config)
        }
        if protected_dimensions:
            delete_ids = {
                item_id
                for item_id in delete_ids
                if next((item.dimension_id for item in items if item.id == item_id), None)
                not in protected_dimensions
            }
            notes.append(
                "Ignored planner deletion of QC-passed item(s) that would underfill "
                f"dimension(s) without replacement: {', '.join(sorted(protected_dimensions))}."
            )
    if delete_ids:
        items = [item for item in items if item.id not in delete_ids]
        notes.append(f"Deleted {len(delete_ids)} planner-flagged off-target item(s).")

    for raw_update in review.get("dimension_updates", []) or []:
        if not isinstance(raw_update, dict):
            continue
        dim_id = str(raw_update.get("id") or "")
        if dim_id not in by_dim:
            continue
        updated = _dimension_from_data(raw_update, fallback=by_dim[dim_id])
        dimensions = [updated if dimension.id == dim_id else dimension for dimension in dimensions]
        by_dim[updated.id] = updated
        notes.append(f"Updated dimension {dim_id}.")

    for raw_add in review.get("add_dimensions", []) or []:
        if not isinstance(raw_add, dict):
            continue
        added = _dimension_from_data(raw_add)
        if added.id in by_dim:
            continue
        dimensions.append(added)
        by_dim[added.id] = added
        notes.append(f"Added dimension {added.id}.")

    for raw_merge in review.get("merge_dimensions", []) or []:
        if not isinstance(raw_merge, dict):
            continue
        source_ids = [str(x) for x in raw_merge.get("source_dimension_ids", []) if str(x) in by_dim]
        if len(source_ids) < 2:
            continue
        new_data = raw_merge.get("new_dimension") if isinstance(raw_merge.get("new_dimension"), dict) else {}
        base = by_dim[source_ids[0]]
        merged_dimension = _dimension_from_data(new_data, fallback=base)
        dimensions = [dimension for dimension in dimensions if dimension.id not in source_ids]
        dimensions.append(merged_dimension)
        items = [
            item.model_copy(update={"dimension_id": merged_dimension.id})
            if item.dimension_id in source_ids
            else item
            for item in items
        ]
        by_dim = {dimension.id: dimension for dimension in dimensions}
        notes.append(f"Merged dimensions {', '.join(source_ids)} into {merged_dimension.id}.")

    for raw_split in review.get("split_dimensions", []) or []:
        if not isinstance(raw_split, dict):
            continue
        source_id = str(raw_split.get("source_dimension_id") or "")
        if source_id not in by_dim:
            continue
        new_dimensions = [
            _dimension_from_data(raw_dim, fallback=by_dim[source_id])
            for raw_dim in raw_split.get("new_dimensions", [])
            if isinstance(raw_dim, dict)
        ]
        if len(new_dimensions) < 2:
            continue
        dimensions = [dimension for dimension in dimensions if dimension.id != source_id] + new_dimensions
        new_ids = {dimension.id for dimension in new_dimensions}
        assignments = {
            str(raw.get("item_id")): str(raw.get("dimension_id"))
            for raw in raw_split.get("item_assignments", [])
            if isinstance(raw, dict) and str(raw.get("dimension_id")) in new_ids
        }
        fallback_id = new_dimensions[0].id
        items = [
            item.model_copy(update={"dimension_id": assignments.get(item.id, fallback_id)})
            if item.dimension_id == source_id
            else item
            for item in items
        ]
        by_dim = {dimension.id: dimension for dimension in dimensions}
        notes.append(f"Split dimension {source_id} into {', '.join(sorted(new_ids))}.")

    move_targets = {dimension.id for dimension in dimensions}
    for raw_move in review.get("move_items", []) or []:
        if not isinstance(raw_move, dict):
            continue
        item_id = str(raw_move.get("item_id") or "")
        target_dim = str(raw_move.get("dimension_id") or "")
        if target_dim not in move_targets:
            continue
        moved = False
        updated_items: list[BenchmarkItem] = []
        for item in items:
            if item.id == item_id:
                updated_items.append(item.model_copy(update={"dimension_id": target_dim}))
                moved = True
            else:
                updated_items.append(item)
        items = updated_items
        if moved:
            notes.append(f"Moved item {item_id} to dimension {target_dim}.")

    planned_task_types = list(
        dict.fromkeys(
            task_type
            for dimension in dimensions
            for task_type in dimension.task_types
        )
    )
    planned_scale = sum(
        max(1, int(dimension.target_item_count or 1))
        for dimension in dimensions
    )
    spec = dataset.spec.model_copy(
        update={
            "dimensions": dimensions,
            "task_types": planned_task_types or dataset.spec.task_types,
            "scale": planned_scale,
        }
    )
    generation_notes = dataset.generation_notes
    if notes:
        generation_notes = (generation_notes.rstrip() + "\nPlanner pre-run review:\n" + "\n".join(notes)).strip()
    return BenchmarkDataset(
        spec=spec,
        items=items,
        sources=sources,
        batches=dataset.batches,
        generation_notes=generation_notes,
    ), notes


def format_human_review_overview(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    config: BenchmarkConfig,
) -> str:
    """Build a compact human-review summary before runner execution."""
    ready_ids = set(qc_report.passed_item_ids)
    ready_items = [item for item in dataset.items if item.id in ready_ids]
    counts = Counter(item.dimension_id for item in ready_items)
    type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in ready_items:
        type_counts[item.dimension_id][item.task_type.value] += 1

    def _format_type_counts(dimension_id: str) -> str:
        per_type = type_counts.get(dimension_id, Counter())
        if not per_type:
            return "-"
        return ", ".join(f"{task_type}: {count}" for task_type, count in sorted(per_type.items()))

    lines = [
        "EvaluationClaw benchmark is ready for human review.",
        "",
        f"Objective: {dataset.spec.objective}",
        f"Dimensions: {len(dataset.spec.dimensions)}",
        f"Ready items: {len(ready_items)}",
        "",
        "## Dimension item mix",
        "",
        "| Dimension | Target | Ready | Item types |",
        "| --- | ---: | ---: | --- |",
    ]
    for dimension in dataset.spec.dimensions:
        target_count = target_count_for_dimension(dimension, config)
        lines.append(
            f"| `{dimension.id}` {dimension.name} | {target_count} | {counts[dimension.id]} | "
            f"{_format_type_counts(dimension.id)} |"
        )

    lines.extend(["", "## Dimension details"])
    for dimension in dataset.spec.dimensions:
        planned_types = ", ".join(task_type.value for task_type in (dimension.task_types or dataset.spec.task_types))
        requirements = "; ".join(dimension.item_requirements[:3]) or "-"
        lines.extend(
            [
                "",
                f"### `{dimension.id}` {dimension.name}",
                f"- Description: {dimension.description}",
                f"- Target/ready: {target_count_for_dimension(dimension, config)} / {counts[dimension.id]}",
                f"- Item types: {_format_type_counts(dimension.id)}",
                f"- Planned types: {planned_types or '-'}",
                f"- Requirements: {requirements}",
            ]
        )
    lines.extend(
        [
            "",
            "Reply with an empty line, 'approve', or 'ok' to run targets.",
            "Or describe requested changes, for example: 'Split dimension X into A/B', "
            "'delete item Y', 'add 2 code-sandbox items to dimension Z', or "
            "'make dimension A focus on multi-turn escalation'.",
        ]
    )
    return "\n".join(lines)


def apply_human_review_feedback(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    config: BenchmarkConfig,
    feedback: str,
    *,
    log: Callable[[str], None] | None = None,
) -> tuple[EvalSpec, BenchmarkDataset, QcReport]:
    """Apply a human review request using the same planner/QC repair machinery."""
    review = _planner_review(dataset, qc_report, config, human_feedback=feedback)
    dataset, notes = _apply_review(dataset, review, qc_report, config)
    if log and notes:
        for note in notes:
            log(f"  {note}")

    plan = plan_from_spec(dataset.spec, config, log=log)
    rebuilt, qc_report = build_dataset_from_spec_with_qc_loop(
        dataset.spec,
        plan.blueprints,
        config,
        log=log or (lambda _message: None),
    )
    rebuilt.plan = plan
    if notes:
        rebuilt.generation_notes = (
            rebuilt.generation_notes.rstrip()
            + "\nHuman review changes:\n"
            + "\n".join(notes)
        ).strip()
    return rebuilt.spec, rebuilt, qc_report
