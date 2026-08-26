"""Translation and scale guidance used by Skill-driven planning."""
from __future__ import annotations

from ..core.scaling import scale_budget_target_items
from ..models.llm import DEFAULT_MAX_OUTPUT_TOKENS, call_llm, extract_json
from ..models.roles import role_model_settings
from ..prompts.planner import TRANSLATION_SYSTEM_PROMPT
from ..types import (
    BenchmarkConfig,
    Message,
    ScaleBudget,
)


def translate_goal_to_english(goal: str, config: BenchmarkConfig) -> str:
    """Normalize every evaluation goal to English through the Planner model."""
    settings = role_model_settings(config, "planner")
    if not settings.configured:
        raise RuntimeError(
            "Planner model is not configured; an LLM is required to normalize the evaluation goal."
        )
    try:
        raw = call_llm(
            [Message(role="user", content=goal)],
            system=TRANSLATION_SYSTEM_PROMPT,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            expect_json=True,
        )
        data = extract_json(raw)
        translated = str(data.get("english_goal") or "").strip()
        if not translated:
            raise ValueError("translation response did not contain a non-empty english_goal")
        return translated
    except Exception as exc:
        raise RuntimeError(f"Could not normalize the evaluation goal to English: {exc}") from exc


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


__all__ = [
    "_safe_scale_budget",
    "_scale_budget_guidance",
    "translate_goal_to_english",
]
