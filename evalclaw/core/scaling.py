"""Scale-budget helpers based on explicit raw item counts."""
from __future__ import annotations

from ..types import ScaleBudget

SCALE_BUDGET_ITEM_COUNTS: dict[ScaleBudget, int] = {
    ScaleBudget.low: 100,
    ScaleBudget.mid: 500,
    ScaleBudget.high: 1000,
    ScaleBudget.large: 5000,
    ScaleBudget.xlarge: 20000,
}

LARGE_SCALE_BUDGETS = {ScaleBudget.large, ScaleBudget.xlarge}


def scale_budget_target_items(scale_budget: ScaleBudget) -> int:
    """Return the planned raw item count for a scale budget."""
    return SCALE_BUDGET_ITEM_COUNTS.get(scale_budget, SCALE_BUDGET_ITEM_COUNTS[ScaleBudget.mid])


def is_large_scale_budget(scale_budget: ScaleBudget) -> bool:
    return scale_budget in LARGE_SCALE_BUDGETS
