"""Shared helpers for agent benchmark construction."""
from __future__ import annotations

import re

from ..types import AgentEnvironmentType, ScaleBudget


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug[:48] or "agent_benchmark"


def _safe_scale_budget(value: object, fallback: ScaleBudget = ScaleBudget.mid) -> ScaleBudget:
    if isinstance(value, ScaleBudget):
        return value
    try:
        return ScaleBudget(str(value).lower())
    except ValueError:
        return fallback


def _safe_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_environment_type(
    value: object,
    fallback: AgentEnvironmentType = AgentEnvironmentType.workspace,
) -> AgentEnvironmentType:
    try:
        return AgentEnvironmentType(str(value))
    except ValueError:
        return fallback
