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


def benchmark_planner_system_prompt(base_prompt: str) -> str:
    """Place the base Planner prompt before the active Skill and its reference."""
    return (
        base_prompt.rstrip()
        + "\n\n<ACTIVE_EVALCLAW_PLANNER_SKILL>\n"
        + load_benchmark_planner_skill()
        + "\n</ACTIVE_EVALCLAW_PLANNER_SKILL>\n\n"
        + '<REFERENCE_FILE path="reference/universal_format.json">\n'
        + load_benchmark_plan_format()
        + "\n</REFERENCE_FILE>"
    )


__all__ = [
    "benchmark_planner_system_prompt",
    "load_benchmark_plan_format",
    "load_benchmark_planner_skill",
]
