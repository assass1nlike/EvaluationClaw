"""Translation and deterministic fallbacks used by Skill-driven planning."""
from __future__ import annotations

import re
from typing import Optional

from ..core.scaling import scale_budget_target_items
from ..models.llm import call_llm, extract_json
from ..models.roles import role_model_settings
from ..prompts.planner import TRANSLATION_SYSTEM_PROMPT
from ..protocols.science import text_requests_science
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


def _safe_scale_budget(
    value: object,
    fallback: ScaleBudget = ScaleBudget.mid,
) -> ScaleBudget:
    if isinstance(value, ScaleBudget):
        return value
    try:
        return ScaleBudget(str(value).lower())
    except ValueError:
        return fallback


def _scale_budget_guidance(scale_budget: ScaleBudget) -> str:
    target = scale_budget_target_items(scale_budget)
    guidance = {
        ScaleBudget.low: (
            f"Use LOW budget: plan about {target} total items. Make a compact but non-trivial "
            "benchmark with enough dimensions to cover the core capability without over-fragmenting it."
        ),
        ScaleBudget.mid: (
            f"Use MID budget: plan about {target} total items. Make a broad, balanced benchmark "
            "covering major dimensions and representative edge cases."
        ),
        ScaleBudget.high: (
            f"Use HIGH budget: plan about {target} total items. Make a deep production-style "
            "benchmark with fine-grained dimensions where needed and targeted edge-case coverage."
        ),
        ScaleBudget.large: (
            f"Use LARGE budget: plan about {target} total items. Prefer scalable source-backed or "
            "imported coverage and use model-generated tasks for targeted gaps."
        ),
        ScaleBudget.xlarge: (
            f"Use XLARGE budget: plan about {target} total items. Prefer scalable source-backed "
            "collections, stratified allocation, and only targeted model generation."
        ),
    }
    return guidance[scale_budget]


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
        else:
            explicit_items += max(1, int(dimension.target_item_count))
    if not missing:
        return dimensions

    remaining_items = max(len(missing), target_items - explicit_items)
    weights = [max(0.0, dimension.weight) for dimension in missing]
    if not any(weights):
        weights = [1.0] * len(missing)
    weight_total = sum(weights)
    extras = remaining_items - len(missing)
    quotas = [extras * weight / weight_total for weight in weights]
    allocations = [1 + int(quota) for quota in quotas]
    unallocated = remaining_items - sum(allocations)
    fractional_order = sorted(
        range(len(missing)),
        key=lambda index: (quotas[index] - int(quotas[index]), weights[index], -index),
        reverse=True,
    )
    for index in fractional_order[:unallocated]:
        allocations[index] += 1

    updated_by_id = {
        dimension.id: dimension.model_copy(update={"target_item_count": allocation})
        for dimension, allocation in zip(missing, allocations, strict=True)
    }
    return [updated_by_id.get(dimension.id, dimension) for dimension in dimensions]


def _fallback_dimensions(goal: str) -> list[EvalDimension]:
    if text_requests_science(goal):
        return _science_fallback_dimensions(goal)
    return [
        EvalDimension(
            id="core_capability",
            name="Core capability",
            description=f"Directly measure the central capability requested by: {goal}",
            approach="Create tasks that isolate the requested capability with explicit scoring criteria.",
            challenge_effort=ChallengeEffort.E3,
            task_types=[TaskType.generation, TaskType.choice],
            item_requirements=[
                "Measure only the central capability requested by the user.",
                "Provide clear scoring criteria and avoid generic trivia.",
            ],
        ),
        EvalDimension(
            id="robustness",
            name="Robustness",
            description="Measure whether performance holds under edge cases, ambiguity, and distractors.",
            approach="Create boundary-condition tasks while keeping expected behavior clear.",
            challenge_effort=ChallengeEffort.E3,
            task_types=[TaskType.generation, TaskType.choice],
            item_requirements=[
                "Use edge cases, ambiguity, or distractors while staying aligned with the user goal.",
                "Do not drift into unrelated robustness topics.",
            ],
        ),
        EvalDimension(
            id="calibration",
            name="Calibration",
            description="Measure whether the model recognizes uncertainty and avoids unsupported claims.",
            approach="Use tasks where abstention, caveats, or concise uncertainty handling is expected.",
            challenge_effort=ChallengeEffort.E3,
            task_types=[TaskType.generation],
            item_requirements=[
                "Test calibrated uncertainty and avoidance of unsupported claims.",
                "Reward concise uncertainty handling when evidence is insufficient.",
            ],
        ),
    ]


def _science_fallback_dimensions(goal: str) -> list[EvalDimension]:
    return [
        EvalDimension(
            id="science_conceptual_reasoning",
            name="Science conceptual reasoning",
            description=f"Measure discipline-aware scientific understanding requested by: {goal}",
            approach="Use self-contained science questions that require applying concepts.",
            challenge_effort=ChallengeEffort.E3,
            needs_research=True,
            research_queries=[
                f"{goal} science reasoning benchmark",
                "GPQA science QA benchmark",
                "SciQ science question answering dataset",
            ],
            target_source_backed_count=1,
            task_types=[TaskType.choice, TaskType.fill_blank],
            item_requirements=[
                "Test conceptual scientific reasoning in the requested discipline or disciplines.",
                "Provide all necessary scientific facts or source context unless testing established knowledge.",
                "Include metadata.science using schema_version evalclaw.science.v1.",
            ],
        ),
        EvalDimension(
            id="quantitative_units",
            name="Quantitative reasoning with units",
            description="Measure calculations, dimensional analysis, approximations, and unit handling.",
            approach="Use numeric science problems with explicit constants and assumptions.",
            challenge_effort=ChallengeEffort.E3,
            task_types=[TaskType.fill_blank, TaskType.choice],
            item_requirements=[
                "Include all constants, equations, data, and unit conventions needed to solve the problem.",
                "Score numeric correctness, units, assumptions, and reasoning steps.",
                "Include metadata.science using schema_version evalclaw.science.v1.",
            ],
        ),
        EvalDimension(
            id="experimental_evidence",
            name="Experimental and evidence reasoning",
            description="Measure hypothesis, controls, confounders, evidence limits, and observations.",
            approach="Use experiment-design or result-interpretation tasks with explicit variables.",
            challenge_effort=ChallengeEffort.E3,
            needs_research=True,
            research_queries=[
                f"{goal} experimental reasoning benchmark",
                "scientific reasoning experiment design benchmark",
                "PubMedQA scientific evidence reasoning dataset",
            ],
            target_source_backed_count=1,
            task_types=[TaskType.generation, TaskType.choice],
            item_requirements=[
                "Ask about controls, variables, confounders, causal inference, or evidence limits.",
                "Provide the study excerpt, observations, or table needed to answer.",
                "Include metadata.science using schema_version evalclaw.science.v1.",
            ],
        ),
    ]


def _fallback_outline(
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
        id=re.sub(r"[^a-zA-Z0-9]+", "_", goal.lower()).strip("_")[:48]
        or "evalclaw_spec",
        objective=goal,
        subjects=target_ids or ["user_supplied_targets"],
        task_types=[TaskType.generation, TaskType.choice],
        dimensions=_apply_budget_targets(_fallback_dimensions(goal), scale_budget),
        scale_budget=scale_budget,
        scale=scale_budget_target_items(scale_budget),
        metrics=[Metric.judge_score, Metric.accuracy],
        planner_notes="Local fallback planner output.",
        critique=critique,
    )


__all__ = [
    "_fallback_dimensions",
    "_fallback_outline",
    "_safe_scale_budget",
    "_scale_budget_guidance",
    "translate_goal_to_english",
]
