"""Retry unusable judge responses without replaying evidence tools."""
from __future__ import annotations

from ..models.llm import LLMFinalContentMissingError
from .errors import EvaluationExecutionError, JudgeResponseError


def call_judge_model(call, *args, **kwargs):
    for attempt in range(3):
        options = dict(kwargs)
        if attempt:
            options["trace_name"] = f"{kwargs.get('trace_name', 'judge')}-empty-retry-{attempt}"
        try:
            response = call(*args, **options)
            if not response.tool_calls and not response.content.strip():
                raise LLMFinalContentMissingError("Judge returned neither text nor tool calls.")
            return response
        except LLMFinalContentMissingError as exc:
            if attempt == 2:
                raise JudgeResponseError(
                    f"Judge returned no usable response after {attempt + 1} attempts: {exc}"
                ) from exc
        except EvaluationExecutionError:
            raise
        except Exception as exc:
            raise EvaluationExecutionError(f"Judge model call failed: {exc}") from exc
