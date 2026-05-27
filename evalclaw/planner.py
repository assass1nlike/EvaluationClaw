"""Planner loop: turn a vague user goal into a structured eval spec."""
from __future__ import annotations

import json
import re
from typing import Optional

from .llm import call_llm, extract_json
from .types import (
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

_TRANSLATION_SYSTEM = """\
You translate and normalize evaluation requests for EvaluationClaw.
Return JSON only: {"english_goal": "..."}.

Translate non-English user requests into concise, precise English before they
are used by the planner. Preserve all technical intent, scope, constraints,
model names, budget words, benchmark names, and domain terms. If the user is
asking to evaluate a non-English capability, describe that requirement in
English rather than replacing it with an English-only task.
"""

_SYSTEM = """\
You are the EvaluationClaw Planner. Your job is to disambiguate a natural-language
evaluation request into an executable eval_spec.

Use English for all generated JSON fields unless the evaluation explicitly tests
non-English language ability. If the input request was originally non-English,
assume it has been translated/normalized to English before planning.

You must cover these 6 checklist items:
1. objective: what capability or behavior is being evaluated
2. subjects: which models or model families are being evaluated
3. format: task types and task forms
4. content: dimensions, subdomains, and target difficulty
5. scale: evaluation size
6. metrics: metrics such as accuracy, exact_match, judge_score, pass@1

Return pure JSON only, with no markdown. Format:
{
  "spec": {
    "id": "snake_case_id",
    "objective": "...",
    "subjects": ["..."],
    "task_types": ["multiple_choice", "open_generation"],
    "scale_budget": "mid",
    "scale": 40,
    "metrics": ["accuracy", "judge_score"],
    "constraints": ["..."],
    "planner_notes": "...",
    "dimensions": [
      {
        "id": "snake_case",
        "name": "...",
        "description": "...",
        "approach": "...",
        "weight": 1.0,
        "target_difficulty": "L4",
        "needs_research": true,
        "research_queries": ["..."]
      }
    ]
  },
  "critique": {
    "checklist": {"objective": true, "subjects": true, "format": true, "content": true, "scale": true, "metrics": true},
    "score": 4.5,
    "missing_items": [],
    "notes": "..."
  }
}

Requirements:
- Usually create 3-6 dimensions with non-overlapping measurement targets.
- If the user did not specify models, use subjects ["user_supplied_targets"].
- Use needs_research/search sparingly. Set needs_research=true only when existing
  resources are better than model-generated items, such as when tasks are hard to
  synthesize, require large or standardized coverage, exceed reliable model item
  generation, require real sources, or need calibration against existing benchmarks.
- If you choose search/research_queries, prefer harder, authoritative,
  reproducible benchmarks/sources that match the user need. Do not introduce
  content drift merely to find a source.
- If the model can reliably generate relevant high-difficulty items and existing
  resources would reduce relevance or difficulty, set needs_research=false.
- Agent or tool-interaction capabilities may use task_type "agent_interaction".
- Do not design a difficulty ladder or drift away from the requested content just
  to include hard tasks. Within content that matches the user need, target the
  hardest suitable difficulty.
- target_difficulty is the intended difficulty for the dimension. Usually use L4;
  use L5 for expert, long-horizon, or complex interaction evaluations; use L3
  only for basic smoke dimensions.
- scale_budget is the global relative budget specified by the user and must be
  one of low/mid/high. Do not change it.
- scale is your estimate of the relative item count based on both scale_budget and
  how much the content deserves to be evaluated. Do not mechanically apply fixed
  item counts.
- low: cover only core dimensions, keep dimensions/metrics/constraints lean, and
  fit a smoke-test-sized run.
- mid: cover main dimensions and key boundary cases for a regular evaluation.
- high: split dimensions more finely and cover sources, difficulty, and
  interaction details for a deeper evaluation.
"""


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def translate_goal_to_english(goal: str, config: BenchmarkConfig) -> str:
    """Translate non-English evaluation goals to English before planning."""
    if not _contains_cjk(goal):
        return goal
    try:
        raw = call_llm(
            [Message(role="user", content=goal)],
            system=_TRANSLATION_SYSTEM,
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
    }
    text = str(value)
    if text in aliases:
        return aliases[text]
    try:
        return TaskType(text)
    except ValueError:
        return TaskType.open_generation


def _safe_metric(value: object) -> Metric:
    aliases = {"pass@1": Metric.pass_at_1, "pass_at_1": Metric.pass_at_1}
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


def _scale_budget_guidance(scale_budget: ScaleBudget) -> str:
    guidance = {
        ScaleBudget.low: (
            "Use LOW budget: make a lean eval spec. Prefer 2-3 dimensions, minimal metrics, "
            "and only essential constraints. The planned scale should reflect a smoke-test-sized run "
            "unless the content truly requires more."
        ),
        ScaleBudget.mid: (
            "Use MID budget: make a balanced eval spec. Prefer 3-5 dimensions, core metrics, "
            "and enough constraints to make generation/execution reliable. The planned scale should "
            "cover main capabilities and key edge cases."
        ),
        ScaleBudget.high: (
            "Use HIGH budget: make a deeper eval spec. Prefer 4-7 dimensions when justified, "
            "explicit source/execution/scoring constraints, richer difficulty coverage, and more detailed "
            "approaches for complex or agentic tasks."
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
        ),
        EvalDimension(
            id="robustness",
            name="Robustness",
            description="Measure whether performance holds under edge cases, ambiguity, and distractors.",
            approach="Create adversarial or boundary-condition tasks while keeping expected behavior clear.",
            weight=1.0,
            target_difficulty=Difficulty.L4,
            needs_research=False,
        ),
        EvalDimension(
            id="calibration",
            name="Calibration",
            description="Measure whether the model recognizes uncertainty and avoids unsupported claims.",
            approach="Include tasks where abstention, caveats, or concise uncertainty handling is expected.",
            weight=1.0,
            target_difficulty=Difficulty.L4,
            needs_research=False,
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
        "questions_per_dimension": config.questions_per_dimension,
        "feedback": feedback,
        "previous_spec": previous_spec.model_dump(mode="json") if previous_spec else None,
    }

    for _ in range(max(1, config.max_planner_iterations)):
        raw = call_llm(
            [Message(role="user", content=json.dumps(context, ensure_ascii=False, indent=2))],
            system=_SYSTEM,
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
