"""Planner loop: turn a vague user goal into a structured eval spec."""
from __future__ import annotations

import json
import re
from typing import Optional

from ..llm import call_llm, extract_json
from ..prompts.planner import PLANNER_SYSTEM_PROMPT, TRANSLATION_SYSTEM_PROMPT
from ..protocols.multimodal import (
    MULTIMODAL_GENERATION_GUIDANCE,
    MULTIMODAL_SCHEMA,
    text_requests_multimodal,
)
from ..types import (
    BenchmarkConfig,
    Difficulty,
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
    try:
        raw = call_llm(
            [Message(role="user", content=goal)],
            system=TRANSLATION_SYSTEM_PROMPT,
            model=config.orchestrator_model,
            api_key=config.orchestrator_api_key,
            base_url=config.orchestrator_base_url,
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
    guidance = {
        ScaleBudget.low: (
            "Use LOW budget: make a lean eval spec. Treat this as a rough anchor for about 2-3 dimensions "
            "and roughly 12 items, but adjust downward if the task requires heavier items or upward if the "
            "objective needs a little more breadth. Simple multiple_choice/open_generation items are lighter; "
            "multi_turn, agent_interaction, and code_sandbox items are heavier, so fewer of them may still "
            "fit the budget. Keep only essential metrics and constraints."
        ),
        ScaleBudget.mid: (
            "Use MID budget: make a balanced eval spec. Treat this as a rough anchor for about 3-5 dimensions "
            "and roughly 30 items, then adjust for the actual objective. Use a heavier item mix only when the "
            "capability naturally requires it: one multi_turn or agent_interaction item can carry more workload "
            "than several simple items. Cover main capabilities and key edge cases without forcing a fixed quota."
        ),
        ScaleBudget.high: (
            "Use HIGH budget: make a deeper eval spec. Treat this as a rough anchor for about 4-7 dimensions "
            "and roughly 60 items, but let the objective determine whether breadth or depth matters more. Split "
            "dimensions more finely when needed, and use richer source/execution/scoring detail for complex or "
            "agentic tasks. Heavier interactive items may count as more workload than many simple items."
        ),
    }
    return guidance[scale_budget]


def _fallback_scale(scale_budget: ScaleBudget) -> int:
    return {ScaleBudget.low: 12, ScaleBudget.mid: 30, ScaleBudget.high: 60}[scale_budget]


def _safe_difficulty(value: object, fallback: Difficulty = Difficulty.L4) -> Difficulty:
    try:
        return Difficulty(str(value))
    except ValueError:
        return fallback


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
        dims.append(
            EvalDimension(
                id=dim_id,
                name=str(dim.get("name") or dim_id),
                description=str(dim.get("description") or ""),
                approach=str(dim.get("approach") or ""),
                weight=float(dim.get("weight", 1.0) or 1.0),
                target_difficulty=_safe_difficulty(dim.get("target_difficulty"), Difficulty.L4),
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

    return EvalSpec(
        id=str(spec_data.get("id") or _slug(goal)),
        objective=str(spec_data.get("objective") or goal),
        subjects=[str(x) for x in spec_data.get("subjects", ["user_supplied_targets"])],
        task_types=[_safe_task_type(x) for x in spec_data.get("task_types", ["open_generation"])],
        dimensions=dims,
        scale_budget=parsed_budget,
        scale=int(spec_data.get("scale", _fallback_scale(parsed_budget)) or _fallback_scale(parsed_budget)),
        metrics=[_safe_metric(x) for x in spec_data.get("metrics", ["judge_score"])],
        constraints=[str(x) for x in spec_data.get("constraints", [])],
        planner_notes=str(spec_data.get("planner_notes", "")),
        critique=critique,
    )


def _fallback_dimensions(goal: str) -> list[EvalDimension]:
    return [
        EvalDimension(
            id="core_capability",
            name="Core capability",
            description=f"Directly measure the central capability requested by: {goal}",
            approach="Create tasks that isolate the requested capability with explicit scoring criteria.",
            weight=1.0,
            target_difficulty=Difficulty.L4,
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
            target_difficulty=Difficulty.L4,
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
            target_difficulty=Difficulty.L4,
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


def fallback_spec(
    goal: str,
    target_ids: Optional[list[str]] = None,
    scale_budget: ScaleBudget = ScaleBudget.mid,
) -> EvalSpec:
    """Build a deterministic local spec when no orchestrator key is available."""
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
        notes="Fallback spec generated locally because no orchestrator call was available.",
    )
    return EvalSpec(
        id=_slug(goal),
        objective=goal,
        subjects=target_ids or ["user_supplied_targets"],
        task_types=[TaskType.open_generation, TaskType.multiple_choice],
        dimensions=_fallback_dimensions(goal),
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
    if not config.orchestrator_api_key:
        return fallback_spec(goal, target_ids, scale_budget)

    best: Optional[EvalSpec] = None
    context = {
        "goal": goal,
        "target_ids": target_ids,
        "scale_budget": scale_budget.value,
        "scale_budget_guidance": _scale_budget_guidance(scale_budget),
        "research_policy": (
            "Set needs_research=true only when external resources are likely better than self-generation: "
            "hard-to-synthesize tasks, large/standardized coverage, expert difficulty beyond reliable model generation, "
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
    if text_requests_multimodal(goal):
        context["multimodal_policy"] = (
            "The user explicitly requested non-text or multimodal evaluation. Create at least one dimension "
            "that requires metadata.multimodal, and keep multimodal assets necessary for the tested capability."
        )
        context["multimodal_schema"] = MULTIMODAL_SCHEMA
        context["multimodal_generation_guidance"] = MULTIMODAL_GENERATION_GUIDANCE

    for _ in range(max(1, config.max_planner_iterations)):
        raw = call_llm(
            [Message(role="user", content=json.dumps(context, ensure_ascii=False, indent=2))],
            system=PLANNER_SYSTEM_PROMPT,
            model=config.orchestrator_model,
            api_key=config.orchestrator_api_key,
            base_url=config.orchestrator_base_url,
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
