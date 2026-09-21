"""Context-window failures and output reservations based on provider counts."""
from __future__ import annotations

import re

import httpx


class LLMContextWindowError(RuntimeError):
    """The caller must shorten its context; this is not an endpoint outage."""

    def __init__(self, message, *, limit=None, input_tokens=None, output_tokens=None):
        super().__init__(message)
        self.limit = limit
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


# DeepSeek reports counts in this API error sentence rather than JSON fields.
# Parse the complete grammar and validate its arithmetic, not log keywords.
_COUNT_ERROR = re.compile(
    r"This model's maximum context length is (\d+) tokens\. However, you requested "
    r"(\d+) tokens \((\d+) in the messages, (\d+) in the completion\)\. "
    r"Please reduce the length of the messages or completion\."
)


def context_window_error(exc, requested_output):
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", getattr(exc, "status_code", None))
    if status not in {400, 422}:
        return None
    try:
        payload = response.json() if response is not None else getattr(exc, "body", None)
    except (ValueError, httpx.HTTPError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error", payload)
    if not isinstance(error, dict):
        return None
    message = error.get("message", "")
    if not isinstance(message, str):
        return None
    if error.get("type") == "invalid_request_error" and error.get("code") == "invalid_request_error":
        match = _COUNT_ERROR.fullmatch(message)
        if match:
            limit, total, inputs, output = map(int, match.groups())
            if total == inputs + output and total > limit > 0 and output == requested_output:
                return LLMContextWindowError(message, limit=limit, input_tokens=inputs, output_tokens=output)
    if error.get("code") == "context_length_exceeded":
        return LLMContextWindowError(message)
    return None


def remaining_output(error, requested):
    """Keep a useful completion allowance; never silently shrink it to near zero."""
    if error.limit is None or error.input_tokens is None:
        raise error
    available = error.limit - error.input_tokens - 1024
    if available < min(requested, 32768) or available >= requested:
        raise error
    return available
