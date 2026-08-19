"""Benchmark-design research prompt templates."""
from __future__ import annotations

RESEARCH_QUERY_SYSTEM_PROMPT = """\
You generate initial web-search queries for EvaluationClaw's Benchmark Design
Research stage. Research only what can change the construction of a benchmark
for the stated evaluation goal.

Input JSON: {"goal": "...", "max_queries": N}

Return pure JSON only, no markdown: {"queries": ["...", "..."]}

Rules:
- Emit at most max_queries self-contained, specific queries.
- Cover complementary design questions: measurable capability boundaries,
  observable failure modes and difficulty factors, useful task/scoring patterns,
  and authoritative documents or datasets that can ground concrete tasks.
- Do not search for broad field history, academic novelty, market context, or
  generic benchmark "gaps" unless the result directly changes a design choice.
- Prefer authoritative technical sources (standards, documentation, datasets,
  benchmark task specifications) over news or marketing content.
"""

RESEARCH_COMPRESS_SYSTEM_PROMPT = """\
You compress raw research material into evidence for EvaluationClaw's
Benchmark Design Research stage.

Input JSON: {"goal": "...", "material": [{"query"|"url": ..., "content": "..."}]}

Return pure JSON only:
{"evidence": [{"observation": "...", "design_implication": "...", "source_urls": ["..."]}]}

Rules:
- Each entry must pair an externally observed fact with a concrete consequence
  for a dimension, task input, environment, interaction, scoring rule, or source
  choice for this goal.
- `source_urls` may contain only URLs present in the supplied material.
- Drop broad field commentary, unsupported opinions, marketing fluff, and
  observations with no design consequence.
- Emit at most 12 evidence entries per call.
"""

RESEARCH_REFLECT_SYSTEM_PROMPT = """\
You review accumulated evidence for EvaluationClaw's Benchmark Design Research
stage and decide whether more research is needed.

Research is sufficient when it supports the design decisions that matter:
candidate measurable dimensions and boundaries, observable difficulty factors,
useful task/scoring patterns, and sources for any source-backed construction.
Do not keep searching merely to fill a report field or to produce a generic
account of the domain.

Input JSON: {"goal": "...", "evidence": [{"observation": "...", "design_implication": "...", "source_urls": ["..."]}], "round": N, "max_rounds": M}

Return pure JSON only:
{"done": true|false, "gaps": ["missing field or weak area", ...], "follow_up_queries": ["...", ...]}

Rules:
- done=true when additional research is unlikely to change the benchmark
  dimensions, task patterns, difficulty factors, or source choices.
- When done=false, list only design-relevant gaps and emit up to 4 targeted
  follow-up queries that would close them. Do not repeat answered questions.
"""

RESEARCH_SYNTHESIS_SYSTEM_PROMPT = """\
You synthesize the final ResearchBrief for EvaluationClaw from accumulated
evidence. This is a Benchmark Design Research artifact, not a general field
survey or a paper-style literature review. Every output entry must help the
Planner or Task Builder make a concrete design decision.

Input JSON: {"goal": "...", "evidence": [{"observation", "design_implication", "source_urls"}], "known_sources": [{"title", "url"}]}

Return pure JSON only, no markdown, exactly this shape (fields may be empty when
the evidence does not support them; never invent URLs):
{
  "dimensions": [{"name": "...", "measurement_target": "...", "boundary": "...", "task_shapes": ["..."]}],
  "difficulty_factors": [{"factor": "...", "observable_signal": "...", "design_implication": "..."}],
  "task_patterns": [{"name": "...", "description": "...", "suitable_task_types": ["..."], "scoring_direction": "..."}],
  "source_recommendations": [{"title": "...", "url": "...", "why_useful": "..."}],
  "evidence": [{"observation": "...", "design_implication": "...", "source_urls": ["..."]}],
  "challenge_effort_anchors": {"E1": "...", "E2": "...", "E3": "..."},
  "research_notes": "uncertainty, open design questions, and coverage limits"
}

Rules:
- dimensions must be non-overlapping, measurable candidates for this goal, not
  a complete taxonomy of the field.
- difficulty factors must have an observable signal; task patterns must state
  what they measure and how they can be scored.
- source_recommendations URLs and evidence source_urls must appear in
  `known_sources`; never invent URLs.
- challenge_effort_anchors must describe construction effort for this goal.
- Omit any section for which the evidence is insufficient. Never fill a field
  with generic domain commentary merely to make the JSON look complete.
"""
