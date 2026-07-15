"""Planner loop: turn a vague user goal into a structured eval spec."""
from __future__ import annotations

import json
import re
from typing import Optional

from ..core.scaling import scale_budget_target_items
from ..models.llm import call_llm, extract_json
from ..models.roles import role_model_settings
from ..prompts.planner import PLANNER_SYSTEM_PROMPT, TRANSLATION_SYSTEM_PROMPT
from ..protocols.multimodal import (
    MULTIMODAL_GENERATION_GUIDANCE,
    MULTIMODAL_SCHEMA,
    text_requests_multimodal,
)
from ..protocols.science import (
    SCIENCE_GENERATION_GUIDANCE,
    SCIENCE_PLANNER_GUIDANCE,
    SCIENCE_SCHEMA,
    text_requests_science,
)
from ..research.deep_research import compact_brief_context
from ..types import (
    BenchmarkConfig,
    ChallengeEffort,
    EvalDimension,
    EvalSpec,
    Message,
    Metric,
    PlannerChecklist,
    PlannerCritique,
    ScaleBudget,
    TaskType,
    safe_challenge_effort,
)

_CJK_RE = re.compile(r"[\u3400-\u9fff]")

def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def translate_goal_to_english(goal: str, config: BenchmarkConfig) -> str:
    """Translate non-English evaluation goals to English before planning."""
    if not _contains_cjk(goal):
        return goal
    settings = role_model_settings(config, "planner")
    if not settings.configured:
        base_url = (settings.base_url or "").lower()
        if not any(host in base_url for host in ("localhost", "127.0.0.1", "0.0.0.0")):
            return goal
    try:
        raw = call_llm(
            [Message(role="user", content=goal)],
            system=TRANSLATION_SYSTEM_PROMPT,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            max_tokens=1024,
        )
        data = extract_json(raw)
        translated = str(data.get("english_goal") or "").strip()
        return translated or goal
    except Exception:
        return goal


def _safe_task_type(value: object) -> TaskType:
    aliases = {
        "generation": TaskType.open_generation,
        "open-ended": TaskType.open_generation,
        "open_ended": TaskType.open_generation,
        "mcq": TaskType.multiple_choice,
        "qa": TaskType.short_answer,
        "agent": TaskType.agent_interaction,
        "agent_interactive": TaskType.agent_interaction,
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


def _safe_metric(value: object) -> Metric:
    aliases = {"pass@1": Metric.pass_at_1, "pass_at_1": Metric.pass_at_1, "winrate": Metric.win_rate}
    text = str(value)
    if text in aliases:
        return aliases[text]
    try:
        return Metric(text)
    except ValueError:
        return Metric.judge_score


def _safe_scale_budget(value: object, fallback: ScaleBudget = ScaleBudget.mid) -> ScaleBudget:
    if isinstance(value, ScaleBudget):
        return value
    try:
        return ScaleBudget(str(value).lower())
    except ValueError:
        return fallback


def _safe_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _scale_budget_guidance(scale_budget: ScaleBudget) -> str:
    target = scale_budget_target_items(scale_budget)
    guidance = {
        ScaleBudget.low: (
            f"Use LOW budget: plan about {target} total items. Make a compact but non-trivial eval spec. "
            "Prefer enough dimensions to cover the core "
            "capability without over-fragmenting the objective."
        ),
        ScaleBudget.mid: (
            f"Use MID budget: plan about {target} total items. Make a broad, balanced eval spec. "
            "Cover major dimensions and representative "
            "edge cases while planning a scalable mix of source-backed and generated items."
        ),
        ScaleBudget.high: (
            f"Use HIGH budget: plan about {target} total items. Make a deep production-style eval spec. "
            "Split dimensions more finely when needed, "
            "increase source-backed coverage, and reserve generated items for targeted gaps and high-value "
            "edge cases."
        ),
        ScaleBudget.large: (
            f"Use LARGE budget: plan about {target} total items for a genuinely large evaluation. "
            "Use many source-backed or imported items, "
            "sample across dimensions and challenge-effort slices, and avoid relying on model-generated items for "
            "the bulk of the dataset. Set target_source_backed_count and target_generated_count explicitly."
        ),
        ScaleBudget.xlarge: (
            f"Use XLARGE budget: plan about {target} total items for a benchmark-scale evaluation. "
            "Prefer scalable source-backed collections, "
            "stratified allocation, automated QC/sampling assumptions, and only targeted model generation "
            "for missing or under-covered slices. Set target_source_backed_count and target_generated_count explicitly."
        ),
    }
    return guidance[scale_budget]


def _fallback_scale(scale_budget: ScaleBudget) -> int:
    return scale_budget_target_items(scale_budget)


def _apply_budget_targets(
    dimensions: list[EvalDimension],
    scale_budget: ScaleBudget,
) -> list[EvalDimension]:
    """Fill missing per-dimension targets from the raw item-count budget."""
    if not dimensions:
        return dimensions

    target_items = scale_budget_target_items(scale_budget)
    explicit_items = 0
    missing: list[EvalDimension] = []
    for dimension in dimensions:
        if dimension.target_item_count is None:
            missing.append(dimension)
            continue
        explicit_items += max(1, int(dimension.target_item_count))

    if not missing:
        return dimensions

    remaining_items = max(len(missing), target_items - explicit_items)
    weights = [max(0.0, dimension.weight) for dimension in missing]
    if not any(weights):
        weights = [1.0] * len(missing)
    weight_total = sum(weights)
    extras = remaining_items - len(missing)
    quotas = [(extras * weight / weight_total) for weight in weights]
    allocations = [1 + int(quota) for quota in quotas]
    unallocated = remaining_items - sum(allocations)
    fractional_order = sorted(
        range(len(missing)),
        key=lambda index: (quotas[index] - int(quotas[index]), weights[index], -index),
        reverse=True,
    )
    for index in fractional_order[:unallocated]:
        allocations[index] += 1

    updated_by_id: dict[str, EvalDimension] = {}
    for dimension, allocation in zip(missing, allocations, strict=True):
        updated_by_id[dimension.id] = dimension.model_copy(update={"target_item_count": allocation})

    return [updated_by_id.get(dimension.id, dimension) for dimension in dimensions]


def _dimension_challenge_effort(dim: dict, fallback: ChallengeEffort = ChallengeEffort.E3) -> ChallengeEffort:
    return safe_challenge_effort(
        dim.get("challenge_effort")
        or dim.get("target_challenge_effort")
        or dim.get("task_builder_effort"),
        fallback,
    )


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug[:48] or "evalclaw_spec"


def _parse_spec(data: dict, goal: str, scale_budget: ScaleBudget) -> EvalSpec:
    if isinstance(data, list):
        for candidate in data:
            if isinstance(candidate, dict):
                return _parse_spec(candidate, goal, scale_budget)
        data = {}
    spec_data = data.get("spec", data)
    parsed_budget = _safe_scale_budget(spec_data.get("scale_budget"), scale_budget)
    dims: list[EvalDimension] = []
    for idx, dim in enumerate(spec_data.get("dimensions", []) or [], 1):
        if not isinstance(dim, dict):
            continue
        dim_id = str(dim.get("id") or f"dimension_{idx}")
        challenge_effort = _dimension_challenge_effort(dim)
        dims.append(
            EvalDimension(
                id=dim_id,
                name=str(dim.get("name") or dim_id),
                description=str(dim.get("description") or ""),
                approach=str(dim.get("approach") or ""),
                weight=float(dim.get("weight", 1.0) or 1.0),
                challenge_effort=challenge_effort,
                needs_research=bool(dim.get("needs_research", False)),
                research_queries=[str(q) for q in dim.get("research_queries", []) if q],
                target_item_count=_safe_optional_int(dim.get("target_item_count")),
                target_source_backed_count=max(0, _safe_optional_int(dim.get("target_source_backed_count")) or 0),
                target_generated_count=_safe_optional_int(dim.get("target_generated_count")),
                task_types=[_safe_task_type(x) for x in dim.get("task_types", [])],
                item_requirements=[str(x) for x in dim.get("item_requirements", []) if x],
            )
        )

    if not dims:
        dims = _fallback_dimensions(goal)

    critique_data = data.get("critique", {}) if isinstance(data.get("critique", {}), dict) else {}
    checklist_data = critique_data.get("checklist", {})
    critique = PlannerCritique(
        checklist=PlannerChecklist(
            objective=bool(checklist_data.get("objective", True)),
            subjects=bool(checklist_data.get("subjects", True)),
            format=bool(checklist_data.get("format", True)),
            content=bool(checklist_data.get("content", True)),
            scale=bool(checklist_data.get("scale", True)),
            metrics=bool(checklist_data.get("metrics", True)),
        ),
        score=float(critique_data.get("score", 4.0) or 4.0),
        missing_items=[str(x) for x in critique_data.get("missing_items", [])],
        notes=str(critique_data.get("notes", "")),
    )

    spec_task_types = [_safe_task_type(x) for x in spec_data.get("task_types", ["open_generation"])]
    dims = _apply_budget_targets(dims, parsed_budget)
    return EvalSpec(
        id=str(spec_data.get("id") or _slug(goal)),
        objective=str(spec_data.get("objective") or goal),
        subjects=[str(x) for x in spec_data.get("subjects", ["user_supplied_targets"])],
        task_types=spec_task_types,
        dimensions=dims,
        scale_budget=parsed_budget,
        scale=int(spec_data.get("scale", _fallback_scale(parsed_budget)) or _fallback_scale(parsed_budget)),
        metrics=[_safe_metric(x) for x in spec_data.get("metrics", ["judge_score"])],
        constraints=[str(x) for x in spec_data.get("constraints", [])],
        planner_notes=str(spec_data.get("planner_notes", "")),
        critique=critique,
    )


def _fallback_dimensions(goal: str) -> list[EvalDimension]:
    if text_requests_science(goal):
        return _science_fallback_dimensions(goal)
    return [
        EvalDimension(
            id="core_capability",
            name="Core capability",
            description=f"Directly measure the central capability requested by: {goal}",
            approach="Create tasks that isolate the requested capability with explicit scoring criteria.",
            weight=1.0,
            challenge_effort=ChallengeEffort.E3,
            needs_research=False,
            target_item_count=None,
            target_source_backed_count=0,
            target_generated_count=None,
            task_types=[TaskType.open_generation, TaskType.multiple_choice],
            item_requirements=[
                "Measure only the central capability requested by the user.",
                "Provide clear scoring criteria and avoid generic trivia.",
            ],
        ),
        EvalDimension(
            id="robustness",
            name="Robustness",
            description="Measure whether performance holds under edge cases, ambiguity, and distractors.",
            approach="Create adversarial or boundary-condition tasks while keeping expected behavior clear.",
            weight=1.0,
            challenge_effort=ChallengeEffort.E3,
            needs_research=False,
            target_item_count=None,
            target_source_backed_count=0,
            target_generated_count=None,
            task_types=[TaskType.open_generation, TaskType.multiple_choice],
            item_requirements=[
                "Use edge cases, ambiguity, or distractors while staying aligned with the user goal.",
                "Do not drift into unrelated robustness topics.",
            ],
        ),
        EvalDimension(
            id="calibration",
            name="Calibration",
            description="Measure whether the model recognizes uncertainty and avoids unsupported claims.",
            approach="Include tasks where abstention, caveats, or concise uncertainty handling is expected.",
            weight=1.0,
            challenge_effort=ChallengeEffort.E3,
            needs_research=False,
            target_item_count=None,
            target_source_backed_count=0,
            target_generated_count=None,
            task_types=[TaskType.open_generation],
            item_requirements=[
                "Test calibrated uncertainty and avoidance of unsupported claims.",
                "Rubrics should reward concise uncertainty handling when evidence is insufficient.",
            ],
        ),
    ]


def _science_fallback_dimensions(goal: str) -> list[EvalDimension]:
    return [
        EvalDimension(
            id="science_conceptual_reasoning",
            name="Science conceptual reasoning",
            description=f"Measure discipline-aware scientific understanding requested by: {goal}",
            approach="Use self-contained science questions that require applying concepts, not recalling trivia.",
            weight=1.0,
            challenge_effort=ChallengeEffort.E3,
            needs_research=True,
            research_queries=[
                f"{goal} science reasoning benchmark",
                "GPQA science QA benchmark",
                "SciQ science question answering dataset",
            ],
            target_item_count=None,
            target_source_backed_count=1,
            target_generated_count=None,
            task_types=[TaskType.multiple_choice, TaskType.short_answer],
            item_requirements=[
                "Test conceptual scientific reasoning in the requested discipline or disciplines.",
                "Provide all necessary scientific facts or source context unless the item intentionally tests established knowledge.",
                "Include metadata.science using schema_version evalclaw.science.v1.",
            ],
        ),
        EvalDimension(
            id="quantitative_units",
            name="Quantitative reasoning with units",
            description="Measure calculations, dimensional analysis, approximations, and unit handling.",
            approach="Use numeric science problems with explicit constants, assumptions, and unambiguous units.",
            weight=1.0,
            challenge_effort=ChallengeEffort.E3,
            needs_research=False,
            target_item_count=None,
            target_source_backed_count=0,
            target_generated_count=None,
            task_types=[TaskType.short_answer, TaskType.multiple_choice],
            item_requirements=[
                "Include all constants, equations, data, and unit conventions needed to solve the problem.",
                "Score numeric correctness, units, assumptions, and reasoning steps.",
                "Include metadata.science using schema_version evalclaw.science.v1.",
            ],
        ),
        EvalDimension(
            id="experimental_evidence",
            name="Experimental and evidence reasoning",
            description="Measure hypothesis, controls, confounders, evidence limits, and interpretation of observations.",
            approach="Use experiment-design or result-interpretation tasks with explicit variables and constraints.",
            weight=1.0,
            challenge_effort=ChallengeEffort.E3,
            needs_research=True,
            research_queries=[
                f"{goal} experimental reasoning benchmark",
                "scientific reasoning experiment design benchmark",
                "PubMedQA scientific evidence reasoning dataset",
            ],
            target_item_count=None,
            target_source_backed_count=1,
            target_generated_count=None,
            task_types=[TaskType.open_generation, TaskType.multiple_choice],
            item_requirements=[
                "Ask about controls, variables, confounders, causal inference, or limits of evidence.",
                "Provide the study excerpt, observations, or table needed to answer without unstated context.",
                "Include metadata.science using schema_version evalclaw.science.v1.",
            ],
        ),
    ]


def fallback_spec(
    goal: str,
    target_ids: Optional[list[str]] = None,
    scale_budget: ScaleBudget = ScaleBudget.mid,
) -> EvalSpec:
    """Build a deterministic local spec when no Planner-role key is available."""
    critique = PlannerCritique(
        checklist=PlannerChecklist(
            objective=True,
            subjects=True,
            format=True,
            content=True,
            scale=True,
            metrics=True,
        ),
        score=4.0,
        notes="Fallback spec generated locally because no Planner call was available.",
    )
    return EvalSpec(
        id=_slug(goal),
        objective=goal,
        subjects=target_ids or ["user_supplied_targets"],
        task_types=[TaskType.open_generation, TaskType.multiple_choice],
        dimensions=_apply_budget_targets(
            _fallback_dimensions(goal),
            scale_budget,
        ),
        scale_budget=scale_budget,
        scale=_fallback_scale(scale_budget),
        metrics=[Metric.judge_score, Metric.accuracy],
        planner_notes="Local fallback planner output.",
        critique=critique,
    )


def plan_eval_spec(
    goal: str,
    config: BenchmarkConfig,
    *,
    feedback: Optional[str] = None,
    previous_spec: Optional[EvalSpec] = None,
) -> EvalSpec:
    """Run the Planner self-critique loop and return the best eval spec."""
    target_ids = [target.id for target in config.targets] or ["user_supplied_targets"]
    scale_budget = _safe_scale_budget(config.scale_budget)
    settings = role_model_settings(config, "planner")
    if not settings.configured:
        return fallback_spec(goal, target_ids, scale_budget)

    best: Optional[EvalSpec] = None
    context = {
        "goal": goal,
        "target_ids": target_ids,
        "scale_budget": scale_budget.value,
        "scale_budget_guidance": _scale_budget_guidance(scale_budget),
        "research_policy": (
            "Set needs_research=true only when external resources are likely better than self-generation: "
            "hard-to-synthesize tasks, large/standardized coverage, expert challenge beyond reliable model generation, "
            "or need for real benchmark/source calibration. Prefer the hardest suitable sources that match the user goal."
        ),
        "reference_model": config.reference_model.model_dump(mode="json") if config.reference_model else None,
        "pairwise_policy": (
            "If reference_model is present, you may include pairwise_preference task types for dimensions where "
            "target-vs-reference comparison is more informative than absolute scoring. Do not use pairwise_preference "
            "without reference_model."
        ),
        "questions_per_dimension": config.questions_per_dimension,
        "feedback": feedback,
        "previous_spec": previous_spec.model_dump(mode="json") if previous_spec else None,
    }
    if config.research_brief is not None:
        context["research_brief"] = compact_brief_context(config.research_brief)
        context["research_brief_policy"] = (
            "A deep-research brief for this domain is provided in research_brief. Ground the spec in it: "
            "derive dimensions from the taxonomy entries, use challenge_effort_anchors to calibrate "
            "challenge_effort, and avoid duplicating existing_benchmarks without addressing their "
            "known weaknesses. Do not invent domain structure that contradicts the brief."
        )
    if text_requests_multimodal(goal):
        context["multimodal_policy"] = (
            "The user explicitly requested non-text or multimodal evaluation. Create at least one dimension "
            "that requires metadata.multimodal, and keep multimodal assets necessary for the tested capability."
        )
        context["multimodal_schema"] = MULTIMODAL_SCHEMA
        context["multimodal_generation_guidance"] = MULTIMODAL_GENERATION_GUIDANCE
    if text_requests_science(goal):
        context["science_policy"] = SCIENCE_PLANNER_GUIDANCE
        context["science_schema"] = SCIENCE_SCHEMA
        context["science_generation_guidance"] = SCIENCE_GENERATION_GUIDANCE

    for _ in range(max(1, config.max_planner_iterations)):
        raw = call_llm(
            [Message(role="user", content=json.dumps(context, ensure_ascii=False, indent=2))],
            system=PLANNER_SYSTEM_PROMPT,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            max_tokens=8192,
        )
        spec = _parse_spec(extract_json(raw), goal, scale_budget)
        best = spec
        if spec.critique.passed:
            break
        context["previous_spec"] = spec.model_dump(mode="json")
        context["feedback"] = (
            "Self-critique did not pass. Fix missing checklist items and raise specificity. "
            f"Missing: {', '.join(spec.critique.missing_items) or 'unspecified'}"
        )

    return best or fallback_spec(goal, target_ids, scale_budget)
