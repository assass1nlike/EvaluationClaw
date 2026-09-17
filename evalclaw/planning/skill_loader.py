"""Load the Planner Skill and the reference format it requires."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..research.authoritative import NO_RESEARCH_POLICY, RESEARCH_POLICY

_SKILL_DIR = Path(__file__).parent / "skills" / "design-benchmark-blueprints"


@lru_cache(maxsize=1)
def load_benchmark_planner_skill() -> str:
    path = _SKILL_DIR / "SKILL.md"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Planner skill is empty: {path}")
    return text


@lru_cache(maxsize=1)
def load_benchmark_plan_format() -> str:
    path = _SKILL_DIR / "reference" / "universal_format.json"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Planner output format is empty: {path}")
    return text


@lru_cache(maxsize=1)
def load_benchmark_plan_format_ablation() -> str:
    path = _SKILL_DIR / "reference" / "universal_format_ablation.json"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Planner ablation output format is empty: {path}")
    return text


_ABLATION_SKILL = """\
You are the Planner of the Evalclaw framework. Transform the user's natural-language
evaluation request into a complete benchmark content design.

Design a set of dimensions that together cover the request without obvious overlap. For each
dimension, give a concise name and a list of task designs. Each task design is one group of
similar tasks: set its task_type, task_count, and content_design (a concrete description of
what the covered tasks measure and require, detailed enough to guide construction). Make the
sum of task_count across every task design equal the user's target task count.

Use only these task types:
- choice: two or more candidate options and one or more correct positions.
- fill_blank: one or more accepted answers, scored by exact match after trimming whitespace.
- generation: an open response scored by a Judge against a rubric.

The framework owns all ids; do not emit them. Follow reference/universal_format_ablation.json
exactly. Commit finished parts progressively with update_plan and stop with no further tool
calls when the plan is complete. Return one complete JSON object that strictly follows the
reference format, pure JSON only.
"""


_AUTHORITATIVE_RESEARCH_GUIDANCE = """\
Use research when grounding is needed, when the request involves unfamiliar content,
or when the requested task count makes adequate coverage and variation difficult to plan.
Inspect raw material before relying on it; source titles and descriptions are discovery
metadata, not evidence. The framework retains loaded material for the Builder to read.
Use the exact supported ref in source_plan.suggested_urls: hf://datasets/{id},
https://en.wikipedia.org/wiki/{title}, or https://arxiv.org/abs/{id}.
Use imported_dataset for imported dataset examples, and adapted or reused when
transforming or reusing source content. Use generated when creating tasks independently.
Keep generated source_plan URLs and queries empty. Source queries search only the same
restricted catalog. For optional builder_resource_urls, use supported Wikipedia or arXiv
refs only, primarily for agent tasks and only for unfamiliar material likely to help the
Builder. For other task types, recommend such aids only when they may materially improve
construction efficiency or difficulty. These aids do not change task provenance.
Do not recommend unsupported repositories, downloads, or open-web research.
Stop when the plan is complete.
"""


def _research_sections(skill: str, authoritative: bool, enabled: bool = True) -> str:
    for tag, replacement in (
        ("RESEARCH_TOOLS", RESEARCH_POLICY),
        ("RESEARCH_GUIDANCE", _AUTHORITATIVE_RESEARCH_GUIDANCE),
        ("RESEARCH_ASSISTANCE", """builder_resource_urls is independent of source_plan and may
be nonempty for generated tasks. Recommend only supported Wikipedia or arXiv refs for
obscure or unfamiliar material the Builder is likely not to know even as a frontier LLM.
Use these aids primarily for agent tasks; for other types, require a concrete expected
gain in construction efficiency or difficulty. The Builder reads raw material through
load_source or read_research_source, not an unrestricted web or file-download tool.
These aids establish provenance only if also declared under a source-backed strategy."""),
    ):
        before, marker, rest = skill.partition(f"<{tag}>")
        if not marker:
            continue
        original, end, after = rest.partition(f"</{tag}>")
        if not end:
            raise ValueError(f"Unclosed Planner prompt section: {tag}")
        if not enabled:
            replacement = NO_RESEARCH_POLICY if tag == "RESEARCH_TOOLS" else ""
        skill = before + (replacement if authoritative or not enabled else original.strip()) + after
    return skill


def benchmark_planner_system_prompt(
    base_prompt: str,
    *,
    simplified: bool = False,
    authoritative_research: bool = False,
    use_web_research: bool = True,
) -> str:
    """Place the base Planner prompt before the active Skill and its reference."""
    if simplified:
        skill = _ABLATION_SKILL
        format_path = "reference/universal_format_ablation.json"
        format_text = load_benchmark_plan_format_ablation()
    else:
        skill = _research_sections(load_benchmark_planner_skill(), authoritative_research, use_web_research)
        format_path = "reference/universal_format.json"
        format_text = load_benchmark_plan_format()
    text = (
        base_prompt.rstrip()
        + "\n\n<ACTIVE_EVALCLAW_PLANNER_SKILL>\n"
        + skill
        + "\n</ACTIVE_EVALCLAW_PLANNER_SKILL>\n\n"
        + f'<REFERENCE_FILE path="{format_path}">\n'
        + format_text
        + "\n</REFERENCE_FILE>"
    )
    if authoritative_research and simplified:
        text += "\n\n" + RESEARCH_POLICY
    elif not use_web_research and simplified:
        text += "\n\n" + NO_RESEARCH_POLICY
    return text


__all__ = [
    "benchmark_planner_system_prompt",
    "load_benchmark_plan_format",
    "load_benchmark_plan_format_ablation",
    "load_benchmark_planner_skill",
]
