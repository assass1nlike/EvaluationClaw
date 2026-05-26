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

_SYSTEM = """\
你是 EvaluationClaw 的 Planner。你的任务是把自然语言评测需求消歧为可执行 eval_spec。

你必须覆盖 6 项 checklist：
1. objective: 评测什么能力或行为
2. subjects: 要测哪些模型或模型族
3. format: 题型/任务形式
4. content: 维度、子领域、难度分布
5. scale: 评测规模
6. metrics: 指标，例如 accuracy、exact_match、judge_score、pass@1

输出必须是纯 JSON，不要 markdown。格式：
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
        "needs_research": true,
        "research_queries": ["..."],
        "difficulty_distribution": {"L1": 0.1, "L2": 0.2, "L3": 0.4, "L4": 0.2, "L5": 0.1}
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

要求：
- 维度通常 3-6 个，彼此测量点不要重叠。
- 如果用户没有指定模型，subjects 写 ["user_supplied_targets"]。
- 对知识密集型评测给出 research_queries；行为类评测可以 needs_research=false。
- agent 或工具交互能力可以使用 task_type "agent_interaction"。
- scale_budget 是用户指定的全局相对预算，只能是 low/mid/high，不要擅自改变。
- scale 是你结合 scale_budget 和评测内容估出的相对题量尺度；不要机械套固定数字。
- low: 只覆盖最核心维度，维度/metrics/constraints 保持精简，适合 smoke test。
- mid: 覆盖主要维度和关键边界情况，适合常规评测。
- high: 更细地拆维度、覆盖来源/难度/交互细节，适合深度评测。
"""


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


def _safe_distribution(raw: object) -> dict[Difficulty, float]:
    if not isinstance(raw, dict):
        return {
            Difficulty.L1: 0.1,
            Difficulty.L2: 0.2,
            Difficulty.L3: 0.4,
            Difficulty.L4: 0.2,
            Difficulty.L5: 0.1,
        }
    result: dict[Difficulty, float] = {}
    for key, value in raw.items():
        try:
            result[Difficulty(str(key))] = float(value)
        except (ValueError, TypeError):
            continue
    return result or {
        Difficulty.L1: 0.1,
        Difficulty.L2: 0.2,
        Difficulty.L3: 0.4,
        Difficulty.L4: 0.2,
        Difficulty.L5: 0.1,
    }


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
                needs_research=bool(dim.get("needs_research", False)),
                research_queries=[str(q) for q in dim.get("research_queries", []) if q],
                difficulty_distribution=_safe_distribution(dim.get("difficulty_distribution")),
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
            needs_research=False,
        ),
        EvalDimension(
            id="robustness",
            name="Robustness",
            description="Measure whether performance holds under edge cases, ambiguity, and distractors.",
            approach="Create adversarial or boundary-condition tasks while keeping expected behavior clear.",
            weight=1.0,
            needs_research=False,
        ),
        EvalDimension(
            id="calibration",
            name="Calibration",
            description="Measure whether the model recognizes uncertainty and avoids unsupported claims.",
            approach="Include tasks where abstention, caveats, or concise uncertainty handling is expected.",
            weight=1.0,
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
