"""Item-generation support used by the general task constructor."""

from .generator import (
    generate_dimension_items,
    target_count_for_dimension,
)

__all__ = [
    "generate_dimension_items",
    "target_count_for_dimension",
]
