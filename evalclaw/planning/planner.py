"""Translation and scale guidance used by Skill-driven planning."""
from __future__ import annotations

from ..diagnostics import new_debug_dir
from ..models.llm import DEFAULT_MAX_OUTPUT_TOKENS, call_llm, extract_json
from ..models.roles import role_model_settings
from ..prompts.planner import REPORT_TRANSLATION_SYSTEM_PROMPT, TRANSLATION_SYSTEM_PROMPT
from ..types import (
    BenchmarkConfig,
    Message,
)


def translate_goal_to_english(goal: str, config: BenchmarkConfig) -> str:
    """Normalize every evaluation goal to English through the Planner model."""
    settings = role_model_settings(config, "planner")
    if not settings.configured:
        raise RuntimeError(
            "Planner model is not configured; an LLM is required to normalize the evaluation goal."
        )
    trace_dir = new_debug_dir(config.output_dir, "translation")
    try:
        raw = call_llm(
            [Message(role="user", content=goal)],
            system=TRANSLATION_SYSTEM_PROMPT,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            expect_json=True,
            trace_dir=trace_dir,
            trace_name="translation",
        )
        data = extract_json(raw)
        translated = str(data.get("english_goal") or "").strip()
        if not translated:
            raise ValueError("translation response did not contain a non-empty english_goal")
        return translated
    except Exception as exc:
        raise RuntimeError(f"Could not normalize the evaluation goal to English: {exc}") from exc


def translate_report_markdown(
    markdown: str,
    language: str,
    config: BenchmarkConfig,
    *,
    trace_dir: str | None = None,
) -> str:
    """Translate a completed Markdown report through the Planner model."""
    settings = role_model_settings(config, "planner")
    if not settings.configured:
        raise RuntimeError(
            "Planner model is not configured; an LLM is required to translate the report."
        )
    target_language = str(language).strip()
    if not target_language:
        raise ValueError("Report translation language cannot be empty.")
    if not str(markdown).strip():
        raise ValueError("Cannot translate an empty report.")
    raw = call_llm(
        [
            Message(
                role="user",
                content=(
                    f"Target language: {target_language}\n\n"
                    "<report>\n"
                    f"{markdown}\n"
                    "</report>"
                ),
            )
        ],
        system=REPORT_TRANSLATION_SYSTEM_PROMPT,
        **settings.call_kwargs(),
        backend=config.llm_backend,
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        trace_dir=trace_dir,
        trace_name="report-translation",
    )
    translated = str(raw or "").strip()
    if not translated:
        raise ValueError("report translation response was empty")
    return translated


__all__ = [
    "translate_goal_to_english",
    "translate_report_markdown",
]
