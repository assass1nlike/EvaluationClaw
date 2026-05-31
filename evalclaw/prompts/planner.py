"""Planner prompt templates."""
from __future__ import annotations

import json

from ..protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE, TASK_AGENT_SCHEMA

TRANSLATION_SYSTEM_PROMPT = """\
You translate and normalize evaluation requests for EvaluationClaw.
Return JSON only: {"english_goal": "..."}.

Translate non-English user requests into concise, precise English before they
are used by the planner. Preserve all technical intent, scope, constraints,
model names, budget words, benchmark names, and domain terms. If the user is
asking to evaluate a non-English capability, describe that requirement in
English rather than replacing it with an English-only task.
"""

PLANNER_SYSTEM_PROMPT = """\
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
        "research_queries": ["..."],
        "target_item_count": 4,
        "target_source_backed_count": 1,
        "target_generated_count": 3,
        "task_types": ["multiple_choice", "open_generation"],
        "item_requirements": ["What the item-generation worker must test and avoid."]
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
- Usually create 3-6 dimensions with non-overlapping measurement targets, but
  let the budget and objective shift that range: LOW often lands around 2-3
  dimensions, MID around 3-5, and HIGH around 4-7 when justified.
- For every dimension, plan the desired item count, source-backed/generated
  allocation, task types, and concrete item_requirements. These requirements are
  handed to item-generation/search workers, so be specific about what each
  dimension must test, what counts as off-target, and what scoring metadata is
  required.
- Keep task_types feasible for the planned item count. If a dimension has only
  one planned item, usually choose one primary task_type rather than listing
  several task types that cannot all be represented.
- If the user did not specify models, use subjects ["user_supplied_targets"].
- Use needs_research/search sparingly. Set needs_research=true only when existing
  resources are better than model-generated items, such as when tasks are hard to
  synthesize, require large or standardized coverage, exceed reliable model item
  generation, require real sources, or need calibration against existing benchmarks.
- For self-contained code review, regression-detection, and missing-test tasks,
  prefer needs_research=false and target_source_backed_count=0 unless the user
  explicitly wants evaluation against a real repository or external change set.
  Generate a tiny self-contained diff locally instead of searching for external
  sources.
- If you choose search/research_queries, prefer harder, authoritative,
  reproducible benchmarks/sources that match the user need. Do not introduce
  content drift merely to find a source.
- If the model can reliably generate relevant high-difficulty items and existing
  resources would reduce relevance or difficulty, set needs_research=false.
- Multi-turn dialogue capabilities may use task_type "multi_turn". Agent or
  tool-interaction capabilities may use task_type "agent_interaction".
- Only create non-text or multimodal dimensions when the user explicitly asks to
  evaluate that capability. Do not add media assets to ordinary text, code,
  reasoning, or agent tasks.
- If reference_model is configured, comparative quality dimensions may use
  task_type "pairwise_preference". These items send the same prompt to the
  target model and the reference model, then a judge scores whether the target
  wins, ties, or loses against the reference. Use pairwise_preference only when
  target-vs-reference comparison is meaningful for the user's objective.
- If a dimension uses multi_turn or agent_interaction, its item_requirements
  must explicitly tell the item-generation worker to create metadata.task_agent
  as the standardized task-agent JSON object. Keep requirements compatible with
  the schema: system_prompt should be concise and limited to role, secrecy, and
  turn policy; files, repository state, environment config, tests, commands, and
  scoring must be requested in structured fields such as initial_content.files,
  metadata.agent_env, execution.environment_type, interaction, and scoring. For
  iterative code-repair dimensions, prefer built-in code_sandbox agent_env over
  a long free-form environment-controller prompt.
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
- Treat the budget as a rough anchor rather than a hard quota: LOW is often about
  2-3 dimensions and ~12 items, MID about 3-5 dimensions and ~30 items, HIGH about
  4-7 dimensions and ~60 items. Adjust up or down when the objective naturally
  needs less or more breadth.
- Treat task types as having different workload weights. A single multi_turn,
  agent_interaction, or code_sandbox item can represent more evaluation depth than
  several simple multiple_choice or open_generation items. Choose the task-type mix
  that best fits the objective instead of forcing the same count across all types.
""" + "\n\nStandardized task-agent file guidance for complex interactive items:\n" + TASK_AGENT_GENERATION_GUIDANCE + "\nCanonical metadata.task_agent schema:\n" + json.dumps(
    TASK_AGENT_SCHEMA,
    ensure_ascii=False,
    indent=2,
) + "\n"
