"""Planner prompt templates."""
from __future__ import annotations

TRANSLATION_SYSTEM_PROMPT = """\
You translate and normalize evaluation requests for EvaluationClaw.
Return JSON only: {"english_goal": "..."}.

If the request is already English, return it unchanged. Otherwise translate it
into concise, precise English before it is used by the planner. Preserve all
technical intent, scope, constraints,
model names, budget words, benchmark names, domain terms, and every explicit
quantity. Render task counts unambiguously: for example, a singular quantity
that constrains the requested count must become "exactly one task", not merely
"a task". If the user is asking to evaluate a non-English capability, describe
that requirement in English rather than replacing it with an English-only task.
"""

BENCHMARK_PLANNER_SYSTEM_PROMPT = """\
You are an EvaluationClaw planning agent. Follow the active Planner Skill
exactly. Read the supplied resources by their declared paths and treat their
contents as authoritative. Use any tools explicitly made available by the
runtime when they are relevant. Do not construct final benchmark tasks.
"""


__all__ = ["BENCHMARK_PLANNER_SYSTEM_PROMPT", "TRANSLATION_SYSTEM_PROMPT"]
