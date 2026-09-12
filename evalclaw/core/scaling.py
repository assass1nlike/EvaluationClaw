"""Item-count helpers for large-scale benchmarks."""
from __future__ import annotations

from ..types import BenchmarkConfig, EvalDimension


def is_large_scale(item_count: int, threshold: int) -> bool:
    """Return True when the benchmark is large enough to need sampled QC and caps."""
    return item_count >= threshold


def target_count_for_dimension(
    dimension: EvalDimension,
    config: BenchmarkConfig,
) -> int:
    planned = max(1, int(dimension.target_item_count or 1))
    if not is_large_scale(config.item_count or 0, config.large_scale_item_threshold):
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
