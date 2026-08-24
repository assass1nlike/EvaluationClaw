"""Scale-budget helpers based on explicit raw item counts."""
from __future__ import annotations

from ..types import BenchmarkConfig, EvalDimension, ScaleBudget

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


def target_count_for_dimension(
    dimension: EvalDimension,
    config: BenchmarkConfig,
) -> int:
    planned = max(1, int(dimension.target_item_count or 1))
    if not is_large_scale_budget(config.scale_budget):
        return planned
    if dimension.target_source_backed_count > 0:
        source_target = min(planned, dimension.target_source_backed_count)
    elif config.source_backed_ratio is None:
        source_target = 0
    else:
        ratio = max(0.0, min(1.0, float(config.source_backed_ratio)))
        source_target = min(planned, int(round(planned * ratio)))
    generated_cap = max(0, int(config.large_scale_generated_item_cap_per_dimension))
    if dimension.target_generated_count is not None:
        generated_target = min(
            planned,
            max(0, int(dimension.target_generated_count)),
            generated_cap,
        )
    else:
        generated_target = min(max(0, planned - source_target), generated_cap)
    return max(1, min(planned, source_target + generated_target))
