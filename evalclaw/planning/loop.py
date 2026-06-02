"""Planner-supervised generation and pre-run QC repair loop."""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter, defaultdict
from typing import Any, Callable

from ..generation.fallback import fallback_items
from ..generator import (
    generate_dataset_with_progress,
    generate_dimension_items,
    target_count_for_dimension,
)
from ..llm import call_llm, extract_json
from ..prompts.planning_loop import PLANNER_REVIEW_SYSTEM_PROMPT
from ..protocols.task_agent import compact_task_agent_for_qc
from ..quality.qc import run_qc_gate
from ..types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    BenchmarkSource,
    Difficulty,
    EvalDimension,
    EvalSpec,
    Message,
    QcReport,
    TaskType,
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")[:48] or "dimension"


def _safe_task_type(value: object) -> TaskType:
    aliases = {
        "pairwise": TaskType.pairwise_preference,
        "preference": TaskType.pairwise_preference,
        "arena": TaskType.pairwise_preference,
    }
    text = str(value)
    if text in aliases:
        return aliases[text]
    try:
        return TaskType(text)
    except ValueError:
        return TaskType.open_generation


def _safe_difficulty(value: object, fallback: Difficulty = Difficulty.L4) -> Difficulty:
    try:
        return Difficulty(str(value))
    except ValueError:
        return fallback


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
    return EvalDimension(
        id=dim_id,
        name=str(merged.get("name") or dim_id),
        description=str(merged.get("description") or ""),
        approach=str(merged.get("approach") or ""),
        weight=float(merged.get("weight", 1.0) or 1.0),
        target_difficulty=_safe_difficulty(merged.get("target_difficulty"), Difficulty.L4),
        needs_research=bool(merged.get("needs_research", False)),
        research_queries=[str(q) for q in merged.get("research_queries", []) if q],
        target_item_count=_safe_positive_int(merged.get("target_item_count")),
        target_source_backed_count=max(0, _safe_positive_int(merged.get("target_source_backed_count"), 0) or 0),
        target_generated_count=_safe_positive_int(merged.get("target_generated_count")),
        task_types=[_safe_task_type(x) for x in merged.get("task_types", [])],
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
    return {
        "id": item.id,
        "dimension_id": item.dimension_id,
        "task_type": item.task_type.value,
        "difficulty": item.difficulty.value,
        "prompt": item.prompt[:700],
        "answer": item.answer,
        "rubric": (item.rubric or "")[:500],
        "source": item.source.model_dump(mode="json"),
        "tags": item.tags,
        "metadata": metadata,
    }


def _planner_review(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    config: BenchmarkConfig,
    *,
    human_feedback: str | None = None,
) -> dict[str, Any]:
    if not config.orchestrator_api_key:
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
            model=config.orchestrator_model,
            api_key=config.orchestrator_api_key,
            base_url=config.orchestrator_base_url,
            backend=config.llm_backend,
            max_tokens=8192,
        )
        data = extract_json(raw)
        return data if isinstance(data, dict) else {"done": True, "notes": "Planner review returned non-object JSON."}
    except Exception as exc:
        return {"done": True, "notes": f"Planner dataset review failed; static repair used: {exc}"}


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

    spec = dataset.spec.model_copy(update={"dimensions": dimensions})
    generation_notes = dataset.generation_notes
    if notes:
        generation_notes = (generation_notes.rstrip() + "\nPlanner pre-run review:\n" + "\n".join(notes)).strip()
    return BenchmarkDataset(spec=spec, items=items, sources=sources, generation_notes=generation_notes), notes


def _remove_qc_rejected_items(dataset: BenchmarkDataset, qc_report: QcReport) -> tuple[BenchmarkDataset, int]:
    rejected = set(qc_report.rejected_item_ids)
    if not rejected:
        return dataset, 0
    items = [item for item in dataset.items if item.id not in rejected]
    notes = f"Removed {len(rejected)} QC-rejected item(s) before runner execution."
    generation_notes = (dataset.generation_notes.rstrip() + "\n" + notes).strip()
    return dataset.model_copy(update={"items": items, "generation_notes": generation_notes}), len(rejected)


def _dimension_deficits(
    dataset: BenchmarkDataset,
    config: BenchmarkConfig,
    review: dict[str, Any] | None = None,
) -> dict[str, int]:
    counts = Counter(item.dimension_id for item in dataset.items)
    deficits: dict[str, int] = {}
    for dimension in dataset.spec.dimensions:
        target = target_count_for_dimension(dimension, config)
        missing = max(0, target - counts[dimension.id])
        if missing:
            deficits[dimension.id] = missing
    for raw_need in (review or {}).get("needs_more_items", []) or []:
        if not isinstance(raw_need, dict):
            continue
        dimension_id = str(raw_need.get("dimension_id") or "")
        count = _safe_positive_int(raw_need.get("count"), 0) or 0
        if dimension_id and count:
            deficits[dimension_id] = max(deficits.get(dimension_id, 0), count)
    return deficits


def _runner_ready(dataset: BenchmarkDataset, qc_report: QcReport, config: BenchmarkConfig) -> bool:
    return (
        qc_report.is_acceptable
        and not qc_report.rejected_item_ids
        and not _dimension_deficits(dataset, config, None)
    )


def _raise_not_ready(
    stage: str,
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    config: BenchmarkConfig,
) -> None:
    deficits = _dimension_deficits(dataset, config, None)
    issue_preview = "; ".join(issue.message for issue in qc_report.issues[:3]) or "no issue details"
    raise RuntimeError(
        f"{stage} did not produce a runner-ready dataset after "
        f"{max(1, int(config.max_qc_iterations))} repair iteration(s): "
        f"{len(qc_report.rejected_item_ids)} rejected item(s), "
        f"{len(deficits)} dimension deficit(s), quality={qc_report.quality_score:.2f}. "
        f"First issues: {issue_preview}"
    )


def _dedupe_sources(sources: list[BenchmarkSource]) -> list[BenchmarkSource]:
    deduped: list[BenchmarkSource] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        key = (source.kind.value, source.uri, source.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _is_duplicate(candidate: BenchmarkItem, existing_items: list[BenchmarkItem]) -> bool:
    return any(
        difflib.SequenceMatcher(None, candidate.prompt.lower(), existing.prompt.lower()).ratio() >= 0.92
        for existing in existing_items
    )


def _repair_guidance_by_dimension(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    item_dimensions = {item.id: item.dimension_id for item in dataset.items}
    item_prompts = {item.id: item.prompt[:700] for item in dataset.items}
    guidance: defaultdict[str, list[str]] = defaultdict(list)
    avoid_prompts: defaultdict[str, list[str]] = defaultdict(list)
    for issue in qc_report.issues:
        if not issue.item_id:
            continue
        dimension_id = item_dimensions.get(issue.item_id)
        if not dimension_id:
            continue
        text = issue.message
        if issue.suggested_action:
            text = f"{text} Suggested action: {issue.suggested_action}"
        if text not in guidance[dimension_id]:
            guidance[dimension_id].append(text)
        prompt = item_prompts.get(issue.item_id)
        if prompt and prompt not in avoid_prompts[dimension_id]:
            avoid_prompts[dimension_id].append(prompt)
    return dict(guidance), dict(avoid_prompts)


def _fill_dimension_deficits(
    dataset: BenchmarkDataset,
    deficits: dict[str, int],
    config: BenchmarkConfig,
    log: Callable[[str], None] | None,
    *,
    repair_guidance: dict[str, list[str]] | None = None,
    avoid_prompts: dict[str, list[str]] | None = None,
) -> BenchmarkDataset:
    if not deficits:
        return dataset
    by_dimension = {dimension.id: dimension for dimension in dataset.spec.dimensions}
    items = list(dataset.items)
    sources = list(dataset.sources)
    notes: list[str] = []
    generated_by_dimension: defaultdict[str, int] = defaultdict(int)
    for dimension_id, count in deficits.items():
        dimension = by_dimension.get(dimension_id)
        if not dimension or count <= 0:
            continue
        if log:
            log(f"  [Generation/QC] Filling {dimension_id}: {count} item(s)...")
        attempts = 0
        local_avoid_prompts = list((avoid_prompts or {}).get(dimension_id, []))
        while generated_by_dimension[dimension_id] < count and attempts < count * 3:
            attempts += 1
            generated_items, generated_sources, note = generate_dimension_items(
                dataset.spec,
                dimension,
                1,
                config,
                repair_guidance=(repair_guidance or {}).get(dimension_id, []),
                avoid_prompts=local_avoid_prompts,
            )
            for item in generated_items:
                if _is_duplicate(item, items):
                    prompt_excerpt = item.prompt[:700]
                    if prompt_excerpt not in local_avoid_prompts:
                        local_avoid_prompts.append(prompt_excerpt)
                    continue
                sources.extend(generated_sources)
                items.append(item)
                generated_by_dimension[dimension_id] += 1
                if note:
                    notes.append(f"{dimension_id}: {note}")
                break
        if generated_by_dimension[dimension_id] < count:
            remaining = count - generated_by_dimension[dimension_id]
            fallback_candidates = fallback_items(dataset.spec, dimension, remaining)
            for candidate in fallback_candidates:
                if _is_duplicate(candidate, items):
                    continue
                items.append(candidate)
                generated_by_dimension[dimension_id] += 1
                notes.append(
                    f"{dimension_id}: Used local fallback item after repeated duplicate generation attempts."
                )
                if generated_by_dimension[dimension_id] >= count:
                    break
    generation_notes = dataset.generation_notes
    if notes:
        generation_notes = (generation_notes.rstrip() + "\nPre-run repair generation:\n" + "\n".join(notes)).strip()
    return BenchmarkDataset(
        spec=dataset.spec,
        items=items,
        sources=_dedupe_sources(sources),
        generation_notes=generation_notes,
    )


def format_human_review_overview(
    dataset: BenchmarkDataset,
    qc_report: QcReport,
    config: BenchmarkConfig,
) -> str:
    """Build a compact human-review summary before runner execution."""
    ready_ids = set(qc_report.passed_item_ids or [item.id for item in dataset.items])
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

    max_iterations = max(1, int(config.max_qc_iterations))
    for _ in range(max_iterations):
        repair_guidance, avoid_prompts = _repair_guidance_by_dimension(dataset, qc_report)
        deficits = _dimension_deficits(dataset, config, review)
        dataset = _fill_dimension_deficits(
            dataset,
            deficits,
            config,
            log,
            repair_guidance=repair_guidance,
            avoid_prompts=avoid_prompts,
        )
        qc_report = run_qc_gate(dataset, config)
        repair_guidance, avoid_prompts = _repair_guidance_by_dimension(dataset, qc_report)
        dataset, removed = _remove_qc_rejected_items(dataset, qc_report)
        if log and removed:
            log(f"  Removed {removed} QC-rejected item(s) after human review.")
        qc_report = run_qc_gate(dataset, config)
        if _runner_ready(dataset, qc_report, config):
            break

    if not _runner_ready(dataset, qc_report, config):
        _raise_not_ready("Human-review repair", dataset, qc_report, config)

    return dataset.spec, dataset, qc_report


def generate_dataset_with_qc_loop(
    spec: EvalSpec,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] | None = None,
) -> tuple[EvalSpec, BenchmarkDataset, QcReport]:
    """Generate items, repair QC/planner issues, and return runner-ready items."""
    dataset = generate_dataset_with_progress(spec, config, log=log)
    qc_report = run_qc_gate(dataset, config)
    max_iterations = max(0, int(config.max_qc_iterations))
    if max_iterations == 0:
        return dataset.spec, dataset, qc_report

    for iteration in range(1, max_iterations + 1):
        if log:
            log(f"\n[Generation/QC] Pre-run self-check iteration {iteration}/{max_iterations}...")
            log(f"  {qc_report.summary}")
        repair_guidance, avoid_prompts = _repair_guidance_by_dimension(dataset, qc_report)
        dataset, removed = _remove_qc_rejected_items(dataset, qc_report)
        if log and removed:
            log(f"  Removed {removed} QC-rejected item(s).")

        review = _planner_review(dataset, qc_report, config)
        dataset, review_notes = _apply_review(dataset, review, qc_report, config)
        if log and review_notes:
            for note in review_notes:
                log(f"  {note}")

        deficits = _dimension_deficits(dataset, config, review)
        dataset = _fill_dimension_deficits(
            dataset,
            deficits,
            config,
            log,
            repair_guidance=repair_guidance,
            avoid_prompts=avoid_prompts,
        )
        next_qc = run_qc_gate(dataset, config)
        next_deficits = _dimension_deficits(dataset, config, None)
        stable = next_qc.is_acceptable and not next_qc.rejected_item_ids and not next_deficits and not review_notes and not deficits
        qc_report = next_qc
        if stable or (review.get("done") is True and not next_qc.rejected_item_ids and not next_deficits):
            break

    if not _runner_ready(dataset, qc_report, config):
        _raise_not_ready("Pre-run generation/QC loop", dataset, qc_report, config)

    return dataset.spec, dataset, qc_report
