"""Load the Planner Skill and the reference format it requires."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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


def benchmark_planner_system_prompt(base_prompt: str, *, simplified: bool = False) -> str:
    """Place the base Planner prompt before the active Skill and its reference."""
    if simplified:
        skill = _ABLATION_SKILL
        format_path = "reference/universal_format_ablation.json"
        format_text = load_benchmark_plan_format_ablation()
    else:
        skill = load_benchmark_planner_skill()
        format_path = "reference/universal_format.json"
        format_text = load_benchmark_plan_format()
    return (
        base_prompt.rstrip()
        + "\n\n<ACTIVE_EVALCLAW_PLANNER_SKILL>\n"
        + skill
        + "\n</ACTIVE_EVALCLAW_PLANNER_SKILL>\n\n"
        + f'<REFERENCE_FILE path="{format_path}">\n'
        + format_text
        + "\n</REFERENCE_FILE>"
    )


__all__ = [
    "benchmark_planner_system_prompt",
    "load_benchmark_plan_format",
    "load_benchmark_plan_format_ablation",
    "load_benchmark_planner_skill",
]
