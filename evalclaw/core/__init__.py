"""Core shared utilities used across EvaluationClaw subsystems."""

from .scaling import is_large_scale, target_count_for_dimension
from .task_summary import TASK_CONTENT_SUMMARY_METADATA_KEY, compact_task_content_summary

__all__ = [
    "TASK_CONTENT_SUMMARY_METADATA_KEY",
    "compact_task_content_summary",
    "is_large_scale",
    "target_count_for_dimension",
]
