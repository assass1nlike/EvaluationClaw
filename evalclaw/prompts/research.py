"""Deep-research prompt templates: query generation, compression, reflection, synthesis."""
from __future__ import annotations

RESEARCH_QUERY_SYSTEM_PROMPT = """\
You generate the initial web-search query set for EvaluationClaw's deep-research
stage. The goal is to ground an automatically-built benchmark in the real
structure of a domain.

Input JSON: {"goal": "...", "max_queries": N}

Return pure JSON only, no markdown: {"queries": ["...", "..."]}

Rules:
- Emit at most max_queries queries, each self-contained and specific.
- Cover complementary angles: the domain's subfield taxonomy, existing
  benchmarks/datasets for the capability, representative task examples, and
  what makes tasks easy vs. expert-level in this domain.
- Prefer queries that surface authoritative/technical sources (papers, docs,
  benchmark pages) over news or marketing content.
"""

RESEARCH_COMPRESS_SYSTEM_PROMPT = """\
You compress raw research material (search syntheses and fetched page text)
into concise, reusable findings for EvaluationClaw's deep-research stage.

Input JSON: {"goal": "...", "material": [{"query"|"url": ..., "content": "..."}]}

Return pure JSON only: {"findings": ["...", "..."]}

Rules:
- Each finding is one factual sentence or short paragraph relevant to designing
  an evaluation for the goal: subfields, existing benchmarks and their
  weaknesses, useful source documents, example task shapes, and challenge-effort signals.
- Append the supporting URL in parentheses when known, e.g. "(source: https://...)".
- Drop marketing fluff, navigation text, and anything irrelevant to the goal.
- Emit at most 12 findings per call.
"""

RESEARCH_REFLECT_SYSTEM_PROMPT = """\
You review accumulated deep-research findings against the ResearchBrief schema
and decide whether more research is needed.

The ResearchBrief fields that must eventually be populated:
- field_overview: summary of the domain
- taxonomy: subfields/capabilities (these become benchmark dimensions)
- existing_benchmarks: known benchmarks and their weaknesses
- seed_sources: groundable document/data URLs for item generation
- exemplar_items: representative example tasks
- challenge_effort_anchors: what E1-E4 task-builder effort means in this domain
- citations: claim-to-source mapping

Input JSON: {"goal": "...", "findings": ["..."], "round": N, "max_rounds": M}

Return pure JSON only:
{"done": true|false, "gaps": ["missing field or weak area", ...], "follow_up_queries": ["...", ...]}

Rules:
- done=true when the findings can adequately populate every brief field.
- When done=false, list the concrete gaps and emit up to 4 targeted follow-up
  search queries that would close them. Do not repeat queries whose answers are
  already in the findings.
"""

RESEARCH_SYNTHESIS_SYSTEM_PROMPT = """\
You synthesize the final ResearchBrief for EvaluationClaw from accumulated
research findings. The brief grounds the benchmark planner and item generator.

Input JSON: {"goal": "...", "findings": ["..."], "known_sources": [{"title", "url"}]}

Return pure JSON only, no markdown, exactly this shape (fields may be empty when
the findings do not support them; never invent URLs):
{
  "field_overview": "2-5 sentence summary of the domain",
  "taxonomy": [{"name": "subfield/capability", "description": "..."}],
  "existing_benchmarks": [{"name": "...", "url": "...", "known_weaknesses": ["..."]}],
  "seed_sources": [{"title": "...", "url": "...", "why_useful": "..."}],
  "exemplar_items": [{"prompt": "...", "answer": "...", "notes": "..."}],
  "challenge_effort_anchors": {"E1": "...", "E2": "...", "E3": "...", "E4": "..."},
  "citations": [{"claim": "...", "url": "..."}],
  "research_notes": "caveats, open questions, coverage limits"
}

Rules:
- taxonomy entries should be usable directly as benchmark dimensions:
  non-overlapping, measurable, 3-8 entries.
- seed_sources must be URLs that actually appeared in the findings or
  known_sources; explain why each is useful for grounding items.
- challenge_effort_anchors must describe the construction/reasoning effort needed in this domain.
- Every non-obvious claim in field_overview/existing_benchmarks should have a
  matching citation entry.
"""
