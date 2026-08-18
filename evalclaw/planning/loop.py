"""Planner-supervised generation and pre-run QC repair loop."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Callable

from ..construction.suite import build_task_suite
from ..generation.generator import target_count_for_dimension
from ..models.llm import call_llm, extract_json
from ..models.roles import role_model_settings
from ..planning.task_planner import plan_from_spec
from ..prompts.planning_loop import PLANNER_REVIEW_SYSTEM_PROMPT
from ..protocols.task_agent import compact_task_agent_for_qc
from ..quality.qc import run_qc_gate
from ..types import (
    BenchmarkConfig,
    BenchmarkItem,
    ChallengeEffort,
    EvalDimension,
    EvalSpec,
    Message,
    QcReport,
    TaskSuite,
    TaskType,
    TaskTypeAllocation,
    safe_challenge_effort,
)

_RESULT_DIMENSION_FIELDS = ("measurement_target", "boundary", "task_types")


@dataclass
class _HumanReviewPlan:
    """A fully-resolved human-review plan: what to keep, rewrite, and generate."""

    spec: EvalSpec
    notes: list[str]
    retained_items: list[BenchmarkItem] = dataclass_field(default_factory=list)
    update_requests: list[dict[str, object]] = dataclass_field(default_factory=list)
    extra_guidance: dict[str, str] = dataclass_field(default_factory=dict)


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


def _dimension_suite_summaries(suite: TaskSuite, config: BenchmarkConfig) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for dimension in suite.spec.dimensions:
        dim_items = [item for item in suite.tasks if item.dimension_id == dimension.id]
        source_counts = Counter(item.source.kind.value for item in dim_items)
        task_counts = Counter(item.task_type.value for item in dim_items)
        summaries.append(
            {
                "dimension_id": dimension.id,
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
    suite: TaskSuite,
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
        "objective": suite.spec.objective,
        "scale_budget": suite.spec.scale_budget.value,
        "human_feedback": human_feedback,
        "dimensions": [dimension.model_dump(mode="json") for dimension in suite.spec.dimensions],
        "dimension_dataset_summaries": _dimension_suite_summaries(suite, config),
        "target_counts": {
            dimension.id: target_count_for_dimension(dimension, config)
            for dimension in suite.spec.dimensions
        },
        "current_counts": Counter(item.dimension_id for item in suite.tasks),
        "qc_issues": [issue.model_dump(mode="json") for issue in qc_report.issues[:60]],
        "items": [_item_excerpt(item) for item in suite.tasks[:80]],
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
    suite: TaskSuite,
    review: dict[str, Any],
    qc_report: QcReport | None = None,
    config: BenchmarkConfig | None = None,
) -> _HumanReviewPlan:
    """Resolve a planner/human review into a concrete build plan.

    Applies everything in the review to the suite without doing any LLM
    building. Returns a ``_HumanReviewPlan`` describing: the revised EvalSpec,
    which existing items survive verbatim (``retained_items``), which items must
    be rewritten in place (``update_requests``, from ``update_items``), and any
    per-dimension extra generation guidance.

    Retained items are only those that are (a) not deleted, (b) not queued for a
    content rewrite, and (c) belong to a dimension whose identity is unchanged
    (not merged, split, newly added, or given a new measurement
    target/boundary/task types). Every other item is dropped and regenerated to
    satisfy the dimension's target count, so a dimension change never leaves
    stale items behind.
    """
    notes: list[str] = []
    dimensions = list(suite.spec.dimensions)
    by_dim = {dimension.id: dimension for dimension in dimensions}
    items = list(suite.tasks)
    item_by_id = {item.id: item for item in items}
    restructured: set[str] = set()

    # ---- delete (with QC-protection against underfilling) ----
    delete_ids = {str(item_id) for item_id in review.get("delete_item_ids", [])}
    if delete_ids and qc_report and config and qc_report.is_acceptable and not qc_report.rejected_item_ids:
        delete_dimensions = {item.dimension_id for item in items if item.id in delete_ids}
        remaining_counts = Counter(item.dimension_id for item in items if item.id not in delete_ids)
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

    # ---- update_items: pull these out of retention into rewrite requests ----
    update_requests: list[dict[str, object]] = []
    update_by_id: dict[str, dict[str, object]] = {}
    for raw in review.get("update_items", []) or []:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("item_id") or "")
        existing = item_by_id.get(item_id)
        dimension_id = str(raw.get("dimension_id") or (existing.dimension_id if existing is not None else ""))
        guidance = str(raw.get("guidance") or "").strip()
        if not item_id or not guidance:
            continue
        target_dimension_id = dimension_id if dimension_id in by_dim else (existing.dimension_id if existing is not None else "")
        update_by_id[item_id] = {
            "item_id": item_id,
            "dimension_id": target_dimension_id,
            "guidance": guidance,
        }
    if update_by_id:
        items = [item for item in items if item.id not in update_by_id]
        update_requests = list(update_by_id.values())
        notes.append(f"Queued {len(update_requests)} item rewrite(s) from review.")

    # ---- dimension_updates ----
    for raw_update in review.get("dimension_updates", []) or []:
        if not isinstance(raw_update, dict):
            continue
        dim_id = str(raw_update.get("id") or "")
        if dim_id not in by_dim:
            continue
        previous = by_dim[dim_id]
        updated = _dimension_from_data(raw_update, fallback=previous)
        if any(getattr(updated, field, None) != getattr(previous, field, None) for field in _RESULT_DIMENSION_FIELDS):
            restructured.add(dim_id)
        dimensions = [updated if dimension.id == dim_id else dimension for dimension in dimensions]
        by_dim[updated.id] = updated
        notes.append(f"Updated dimension {dim_id}.")

    # ---- add_dimensions ----
    for raw_add in review.get("add_dimensions", []) or []:
        if not isinstance(raw_add, dict):
            continue
        added = _dimension_from_data(raw_add)
        if added.id in by_dim:
            continue
        dimensions.append(added)
        by_dim[added.id] = added
        restructured.add(added.id)
        notes.append(f"Added dimension {added.id}.")

    # ---- merge_dimensions ----
    for raw_merge in review.get("merge_dimensions", []) or []:
        if not isinstance(raw_merge, dict):
            continue
        source_ids = [str(x) for x in raw_merge.get("source_dimension_ids", []) if str(x) in by_dim]
        if len(source_ids) < 2:
            continue
        new_data = raw_merge.get("new_dimension") if isinstance(raw_merge.get("new_dimension"), dict) else {}
        merged_dimension = _dimension_from_data(new_data, fallback=by_dim[source_ids[0]])
        merged_dimension = merged_dimension.model_copy(
            update={"target_item_count": max(1, int(merged_dimension.target_item_count or 1))}
        )
        dimensions = [dimension for dimension in dimensions if dimension.id not in source_ids]
        dimensions.append(merged_dimension)
        restructured.update(source_ids)
        restructured.add(merged_dimension.id)
        items = [item for item in items if item.dimension_id not in source_ids]
        by_dim = {dimension.id: dimension for dimension in dimensions}
        notes.append(f"Merged dimensions {', '.join(source_ids)} into {merged_dimension.id}.")

    # ---- split_dimensions ----
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
        restructured.add(source_id)
        restructured.update(dimension.id for dimension in new_dimensions)
        items = [item for item in items if item.dimension_id != source_id]
        by_dim = {dimension.id: dimension for dimension in dimensions}
        notes.append(f"Split dimension {source_id} into {', '.join(sorted(dimension.id for dimension in new_dimensions))}.")

    # ---- move_items (into a surviving dimension only) ----
    move_targets = {dimension.id for dimension in dimensions}
    for raw_move in review.get("move_items", []) or []:
        if not isinstance(raw_move, dict):
            continue
        item_id = str(raw_move.get("item_id") or "")
        target_dim = str(raw_move.get("dimension_id") or "")
        if target_dim not in move_targets or item_id not in item_by_id:
            continue
        moved: list[BenchmarkItem] = []
        for item in items:
            if item.id == item_id:
                if target_dim not in restructured:
                    moved.append(item.model_copy(update={"dimension_id": target_dim}))
            else:
                moved.append(item)
        items = moved
        if target_dim not in restructured:
            notes.append(f"Moved item {item_id} to dimension {target_dim}.")

    # ---- needs_more_items: raise target + collect per-dimension guidance ----
    extra_guidance: dict[str, str] = {}
    for raw in review.get("needs_more_items", []) or []:
        if not isinstance(raw, dict):
            continue
        dimension_id = str(raw.get("dimension_id") or "")
        if dimension_id not in by_dim:
            continue
        requested = max(0, int(raw.get("count") or 1))
        guidance = str(raw.get("guidance") or "").strip()
        dimension = by_dim[dimension_id]
        kept_now = sum(1 for item in items if item.dimension_id == dimension_id)
        target = int(dimension.target_item_count or 0) if dimension.target_item_count is not None else 0
        new_target = max(target, kept_now + requested)
        updated = dimension.model_copy(update={"target_item_count": new_target})
        dimensions = [updated if d.id == dimension_id else d for d in dimensions]
        by_dim[dimension_id] = updated
        if guidance:
            extra_guidance[dimension_id] = guidance
        notes.append(f"Queued {requested} additional item(s) for {dimension_id}.")

    # ---- drop items now dangling in restructured dimensions ----
    if restructured:
        kept_items = [item for item in items if item.dimension_id not in restructured]
        dropped = len(items) - len(kept_items)
        items = kept_items
        if dropped:
            notes.append(f"Regenerating {dropped} item(s) whose dimension changed structure.")

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
    spec = suite.spec.model_copy(
        update={
            "dimensions": dimensions,
            "task_types": planned_task_types or suite.spec.task_types,
            "scale": planned_scale,
        }
    )
    return _HumanReviewPlan(
        spec=spec,
        notes=notes,
        retained_items=items,
        update_requests=update_requests,
        extra_guidance=extra_guidance,
    )


def format_human_review_overview(
    suite: TaskSuite,
    qc_report: QcReport,
    config: BenchmarkConfig,
) -> str:
    """Build a compact human-review summary before runner execution."""
    ready_ids = set(qc_report.passed_item_ids)
    ready_items = [item for item in suite.tasks if item.id in ready_ids]
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
        f"Objective: {suite.spec.objective}",
        f"Dimensions: {len(suite.spec.dimensions)}",
        f"Ready items: {len(ready_items)}",
        "",
        "## Dimension item mix",
        "",
        "| Dimension | Target | Ready | Item types |",
        "| --- | ---: | ---: | --- |",
    ]
    for dimension in suite.spec.dimensions:
        target_count = target_count_for_dimension(dimension, config)
        lines.append(
            f"| `{dimension.id}` {dimension.name} | {target_count} | {counts[dimension.id]} | "
            f"{_format_type_counts(dimension.id)} |"
        )

    lines.extend(["", "## Dimension details"])
    for dimension in suite.spec.dimensions:
        planned_types = ", ".join(task_type.value for task_type in (dimension.task_types or suite.spec.task_types))
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


def _rewrite_items(
    current_items: list[BenchmarkItem],
    source_suite: TaskSuite,
    spec: EvalSpec,
    update_requests: list[dict[str, object]],
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] | None = None,
) -> list[BenchmarkItem]:
    """Rewrite the given items in place via a targeted Builder revision.

    Each ``update_items`` request becomes a revision task that rewrites exactly
    that one item (preserving its id) using the Builder's revision mechanism,
    with the review's ``guidance`` passed as the concrete change request. Items
    not listed in ``update_requests`` are returned untouched. A request whose
    dimension no longer exists in the revised ``spec`` is dropped (it will be
    regenerated by the missing-count pass instead).
    """
    original_by_id = {item.id: item for item in source_suite.tasks}
    blueprint_by_id = {blueprint.id: blueprint for blueprint in source_suite.blueprints}
    dim_ids = {dimension.id for dimension in spec.dimensions}
    result = list(current_items)
    result_by_id = {item.id: item for item in result}
    by_blueprint: dict[str, list[dict[str, object]]] = defaultdict(list)
    for request in update_requests:
        item_id = str(request.get("item_id") or "")
        original = original_by_id.get(item_id)
        if original is None or original.source_definition is None:
            continue
        dimension_id = str(request.get("dimension_id") or original.dimension_id)
        if dimension_id not in dim_ids:
            continue
        blueprint_id = str(original.source_definition.metadata.get("builder_job_id") or "")
        by_blueprint[blueprint_id].append({**request, "dimension_id": dimension_id})

    for blueprint_id, requests in by_blueprint.items():
        blueprint = blueprint_by_id.get(blueprint_id)
        if blueprint is None:
            continue
        revision_by_dimension: dict[str, dict[str, object]] = {}
        for request in requests:
            item_id = str(request.get("item_id") or "")
            original = original_by_id[item_id]
            dimension_id = str(request["dimension_id"])
            guidance = str(request.get("guidance") or "")
            revision_by_dimension.setdefault(
                dimension_id,
                {
                    "reason": "human_review_item_update",
                    "previous_tasks": [],
                    "qc_issues": [],
                    "instruction": (
                        "Return replacements only for the tasks listed in previous_tasks, preserving "
                        "each task id. Apply the concrete rewrite request in the listed guidance for "
                        "each task; do not return or modify any other task from the TaskDesign."
                    ),
                },
            )["previous_tasks"].append(original.source_definition.model_dump(mode="json"))
            revision_by_dimension[dimension_id]["qc_issues"].append(
                {"item_id": item_id, "message": guidance, "severity": "error"}
            )

        try:
            rebuilt = build_task_suite(
                spec,
                [blueprint],
                config,
                revision_context_by_dimension=revision_by_dimension,
                log=log,
            )
        except RuntimeError as exc:
            if log:
                log(f"  [Human Review] rewrite failed for {blueprint.id}: {exc}")
            continue
        for item in rebuilt.tasks:
            if item.id in result_by_id:
                result = [item if candidate.id == item.id else candidate for candidate in result]
                result_by_id[item.id] = item
            else:
                result.append(item)
                result_by_id[item.id] = item
    if log:
        log(f"  [Human Review] rewrote {len(update_requests)} item(s) per review guidance.")
    return result


def _generate_for_dimension(
    source_suite: TaskSuite,
    spec: EvalSpec,
    dimension: EvalDimension,
    *,
    count: int,
    config: BenchmarkConfig,
    guidance: str | None,
    log: Callable[[str], None] | None,
) -> tuple[list[BenchmarkItem], list]:
    """Generate ``count`` fresh items for ``dimension`` and return them."""
    scoped_dimension = dimension.model_copy(
        update={
            "target_item_count": count,
            "target_source_backed_count": min(count, int(dimension.target_source_backed_count or 0)),
            "target_generated_count": count - min(count, int(dimension.target_source_backed_count or 0)),
        }
    )
    scoped_spec = spec.model_copy(
        update={
            "dimensions": [scoped_dimension],
            "task_types": dimension.task_types or spec.task_types,
            "scale": count,
        }
    )
    blueprints = list(plan_from_spec(scoped_spec, config, log=log).builder_jobs)
    if guidance:
        blueprints = [
            blueprint.model_copy(
                update={
                    "task_designs": [
                        design.model_copy(
                            update={
                                "construction_requirements": [
                                    *(design.construction_requirements or []),
                                    f"Review requirement: {guidance}",
                                ]
                            }
                        )
                        for design in blueprint.task_designs
                    ]
                }
            )
            for blueprint in blueprints
        ]
    partial = build_task_suite(scoped_spec, blueprints, config, log=log)
    return list(partial.tasks), list(partial.blueprints)


def _order_items_by_dimension(items: list[BenchmarkItem], spec: EvalSpec) -> list[BenchmarkItem]:
    """Order items following the spec's dimension order; dangling items go last."""
    order = {dimension.id: index for index, dimension in enumerate(spec.dimensions)}
    known = [item for item in items if item.dimension_id in order]
    known.sort(key=lambda item: order[item.dimension_id])
    unknown = [item for item in items if item.dimension_id not in order]
    return known + unknown


def _dedupe_blueprints(blueprints: list) -> list:
    seen: dict[str, object] = {}
    for blueprint in blueprints:
        seen.setdefault(getattr(blueprint, "id", id(blueprint)), blueprint)
    return list(seen.values())


def apply_human_review_feedback(
    suite: TaskSuite,
    qc_report: QcReport,
    config: BenchmarkConfig,
    feedback: str,
    *,
    log: Callable[[str], None] | None = None,
) -> tuple[EvalSpec, TaskSuite, QcReport]:
    """Apply a human review request, keeping unaffected items verbatim.

    Instead of discarding the whole suite and regenerating from scratch, this
    keeps everything the review did not touch, rewrites the items named by
    ``update_items`` in place (via a targeted Builder revision that preserves
    their ids), and generates only the missing items each dimension still needs.
    """
    review = _planner_review(suite, qc_report, config, human_feedback=feedback)
    outcome = _apply_review(suite, review, qc_report, config)
    notes = outcome.notes
    if log and notes:
        for note in notes:
            log(f"  {note}")

    materialized = list(outcome.retained_items)
    generated_blueprints: list = list(suite.blueprints)

    # 1) Rewrite items named by update_items, preserving their ids.
    if outcome.update_requests:
        materialized = _rewrite_items(
            materialized,
            suite,
            outcome.spec,
            outcome.update_requests,
            config,
            log=log,
        )

    # 2) Generate whatever each dimension is still short of its target.
    for dimension in outcome.spec.dimensions:
        target = int(dimension.target_item_count or 0)
        current = sum(1 for item in materialized if item.dimension_id == dimension.id)
        missing = max(0, target - current)
        if missing <= 0:
            continue
        guidance = outcome.extra_guidance.get(dimension.id)
        generated, blueprints = _generate_for_dimension(
            suite,
            outcome.spec,
            dimension,
            count=missing,
            config=config,
            guidance=guidance,
            log=log,
        )
        materialized.extend(generated)
        generated_blueprints.extend(blueprints)

    new_suite = suite.model_copy(
        update={
            "spec": outcome.spec,
            "dimensions": outcome.spec.dimensions,
            "blueprints": _dedupe_blueprints(generated_blueprints),
            "tasks": _order_items_by_dimension(materialized, outcome.spec),
            "resources": suite.resources,
            "construction_notes": (
                suite.construction_notes.rstrip()
                + "\nHuman review changes:\n"
                + "\n".join(notes)
            ).strip(),
        }
    )
    new_suite.plan = suite.plan
    revised_spec = new_suite.spec
    revised_qc = run_qc_gate(new_suite, config)
    return revised_spec, new_suite, revised_qc
