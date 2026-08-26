"""Evalclaw: LLM call utilities (Anthropic + OpenAI-compatible)."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import anthropic
import httpx

# Pricing metadata is unrelated to inference. Use LiteLLM's bundled map so an
# unreachable GitHub endpoint cannot delay every EvalClaw process at import.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from ..diagnostics import error_record, invocation_id, safe_name, write_json
from ..protocols.tool import ToolCall, ToolSpec
from ..protocols.tool_adapters import (
    anthropic_tool_calls_from_response,
    anthropic_tools,
    openai_tool_calls_from_response,
    openai_tools,
    tool_adapter_for_target,
)
from ..types import Message, TargetModelConfig
from .json_utils import extract_json
from .providers import infer_provider


class LLMOutputTruncatedError(RuntimeError):
    """The provider ended a completion because its output budget was exhausted."""

    def __init__(self, message: str, *, raw_response: Any = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class LLMFinalContentMissingError(RuntimeError):
    """The provider completed without returning a usable final response."""


class LLMProtocolAdapterError(RuntimeError):
    """LiteLLM could not adapt the request or response for the selected provider."""


DEFAULT_MAX_OUTPUT_TOKENS = 32_768


def _require_supported_backend(backend: str) -> None:
    if backend not in {"auto", "litellm"}:
        raise ValueError(f"Unsupported LLM backend {backend!r}; expected 'auto' or 'litellm'.")


def _post_with_retry(
    url: str,
    headers: dict,
    body: dict,
    max_retries: int = 3,
    *,
    request_timeout_s: float = 300.0,
    total_timeout_s: float = 300.0,
    trace_dir: str | Path | None = None,
    trace_name: str = "http",
) -> dict:
    """POST with bounded retries for transient transport, 429, and 5xx errors."""
    delay = 5.0
    started = time.monotonic()
    endpoint = httpx.URL(url).host or "model endpoint"
    for attempt in range(max_retries):
        trace_path = _llm_trace_path(trace_dir, trace_name, attempt + 1)
        request = {"url": url, "body": body}
        remaining = total_timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError(
                f"Model request to {endpoint} exceeded {total_timeout_s:.0f}s overall deadline."
            )
        try:
            resp = httpx.post(
                url,
                headers=headers,
                json=body,
                timeout=min(request_timeout_s, remaining),
            )
        except httpx.TransportError as exc:
            _write_llm_trace(trace_path, request=request, status="failed", error=exc)
            if attempt == max_retries - 1:
                raise
            wait_s = min(delay, max(0.0, total_timeout_s - (time.monotonic() - started)))
            if wait_s <= 0:
                raise TimeoutError(
                    f"Model request to {endpoint} exceeded {total_timeout_s:.0f}s overall deadline."
                ) from exc
            print(
                f"  [llm network] {endpoint} attempt {attempt + 1}/{max_retries} "
                f"failed ({type(exc).__name__}); retrying in {wait_s:.0f}s."
            )
            time.sleep(wait_s)
            delay = min(delay * 2, 30.0)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            _write_llm_trace(
                trace_path,
                request=request,
                status="failed",
                response={"status_code": resp.status_code, "body": resp.text},
            )
            if attempt == max_retries - 1:
                resp.raise_for_status()
            retry_after = resp.headers.get("retry-after")
            try:
                requested_wait = float(retry_after) if retry_after else delay
            except ValueError:
                requested_wait = delay
            wait_s = min(
                max(0.0, requested_wait),
                30.0,
                max(0.0, total_timeout_s - (time.monotonic() - started)),
            )
            if wait_s <= 0:
                resp.raise_for_status()
            print(
                f"  [llm network] {endpoint} returned HTTP {resp.status_code} "
                f"on attempt {attempt + 1}/{max_retries}; retrying in {wait_s:.0f}s."
            )
            time.sleep(wait_s)
            delay = min(delay * 2, 30.0)
            continue
        if resp.is_error:
            error = httpx.HTTPStatusError(
                f"HTTP {resp.status_code}",
                request=resp.request,
                response=resp,
            )
            _write_llm_trace(
                trace_path,
                request=request,
                status="failed",
                response={"status_code": resp.status_code, "body": resp.text},
                error=error,
            )
        resp.raise_for_status()
        data = resp.json()
        finish_reason = str((data.get("choices") or [{}])[0].get("finish_reason") or "") or None
        _write_llm_trace(
            trace_path,
            request=request,
            status="completed",
            response=data,
            finish_reason=finish_reason,
        )
        return data
    raise RuntimeError("Max retries exceeded")


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_transient_streaming_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    message = str(exc).lower()
    return "upstream_error" in message or "temporarily unavailable" in message


def _post_streaming_openai_compatible(
    url: str,
    headers: dict,
    body: dict[str, Any],
    *,
    max_retries: int = 3,
    request_timeout_s: float = 300.0,
    total_timeout_s: float = 300.0,
    raw_events: list[dict[str, Any]] | None = None,
    trace_dir: str | Path | None = None,
    trace_name: str = "stream-http",
) -> tuple[str, str | None]:
    """Read an OpenAI-compatible streaming chat response and return full text.

    This intentionally covers only the standard SSE shape used by
    /chat/completions. Tool streaming remains on the existing non-streaming
    path.
    """
    stream_body = {**body, "stream": True}
    delay = 5.0
    started = time.monotonic()
    endpoint = httpx.URL(url).host or "model endpoint"
    for attempt in range(max_retries):
        trace_path = _llm_trace_path(trace_dir, trace_name, attempt + 1)
        request = {"url": url, "body": stream_body}
        remaining = total_timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError(
                f"Streaming model request to {endpoint} exceeded "
                f"{total_timeout_s:.0f}s overall deadline."
            )
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        attempt_events: list[dict[str, Any]] = []
        finish_reason: str | None = None
        try:
            with httpx.stream(
                "POST",
                url,
                headers=headers,
                json=stream_body,
                timeout=min(request_timeout_s, remaining),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    payload = line.removeprefix("data:").strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    attempt_events.append(chunk)
                    if isinstance(chunk.get("error"), dict):
                        raise RuntimeError(str(chunk["error"]))
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta") or choice.get("message") or {}
                    content = delta.get("content")
                    if isinstance(content, str):
                        content_parts.append(content)
                    reasoning = delta.get("reasoning_content")
                    if isinstance(reasoning, str):
                        reasoning_parts.append(reasoning)
        except (httpx.TransportError, httpx.HTTPStatusError, RuntimeError) as exc:
            if raw_events is not None:
                raw_events.extend(attempt_events)
            _write_llm_trace(
                trace_path,
                request=request,
                status="failed",
                response=attempt_events,
                finish_reason=finish_reason,
                error=exc,
            )
            if attempt == max_retries - 1 or not _is_transient_streaming_error(exc):
                raise
            wait_s = min(
                delay,
                30.0,
                max(0.0, total_timeout_s - (time.monotonic() - started)),
            )
            if wait_s <= 0:
                raise TimeoutError(
                    f"Streaming model request to {endpoint} exceeded "
                    f"{total_timeout_s:.0f}s overall deadline."
                ) from exc
            print(
                f"  [llm network] {endpoint} streaming attempt "
                f"{attempt + 1}/{max_retries} failed ({type(exc).__name__}); "
                f"retrying in {wait_s:.0f}s."
            )
            time.sleep(wait_s)
            delay = min(delay * 2, 30.0)
            continue
        content = "".join(content_parts)
        if raw_events is not None:
            raw_events.extend(attempt_events)
        _write_llm_trace(
            trace_path,
            request=request,
            status="completed",
            response=attempt_events,
            finish_reason=finish_reason,
        )
        if content:
            return content, finish_reason
        return "".join(reasoning_parts), finish_reason
    raise RuntimeError("Max streaming retries exceeded")

DEFAULT_ORCHESTRATOR_MODEL = "claude-opus-4-6"

# Module-level Anthropic clients, isolated by credential and endpoint.
_anthropic_clients: dict[tuple[str, str], anthropic.Anthropic] = {}


def _message_dicts(messages: list[Message], system: Optional[str] = None) -> list[dict]:
    result: list[dict] = []
    if system:
        result.append({"role": "system", "content": system})
    result.extend({"role": m.role, "content": m.content} for m in messages)
    return result


def _extract_litellm_content(response: object) -> str:
    choices = getattr(response, "choices", None)
    if choices is None and isinstance(response, dict):
        choices = response.get("choices")
    if not choices:
        raise ValueError("LiteLLM response has no choices")
    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        if parts:
            return "\n".join(parts)
    raise ValueError("LiteLLM response has no text content")


def _extract_responses_content(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text is None and isinstance(response, dict):
        output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text
    output = getattr(response, "output", None)
    if output is None and isinstance(response, dict):
        output = response.get("output")
    parts: list[str] = []
    for item in output or []:
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        for block in content or []:
            block_type = getattr(block, "type", None)
            text = getattr(block, "text", None)
            if isinstance(block, dict):
                block_type = block.get("type")
                text = block.get("text")
            if block_type == "output_text" and isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        if message.get("type") in {"function_call", "function_call_output"}:
            result.append(message)
            continue
        role = str(message.get("role") or "")
        if role == "tool":
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or ""),
                    "output": str(message.get("content") or ""),
                }
            )
        elif role in {"user", "assistant", "developer"}:
            result.append({"role": role, "content": message.get("content") or ""})
    return result


def _responses_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in tools
    ]


def _post_streaming_responses(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    max_retries: int = 3,
    request_timeout_s: float = 300.0,
    total_timeout_s: float = 900.0,
    trace_dir: str | Path | None = None,
    trace_name: str = "responses-http",
) -> dict[str, Any]:
    """Return the complete response object from a Responses API SSE stream."""
    delay = 5.0
    started = time.monotonic()
    endpoint = httpx.URL(url).host or "model endpoint"
    for attempt in range(max_retries):
        trace_path = _llm_trace_path(trace_dir, trace_name, attempt + 1)
        request = {"url": url, "body": {**body, "stream": True}}
        events: list[dict[str, Any]] = []
        remaining = total_timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError(
                f"Responses API request to {endpoint} exceeded "
                f"{total_timeout_s:.0f}s overall deadline."
            )
        try:
            with httpx.stream(
                "POST",
                url,
                headers=headers,
                json={**body, "stream": True},
                timeout=min(request_timeout_s, remaining),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line.removeprefix("data:").strip()
                    if payload == "[DONE]":
                        break
                    event = json.loads(payload)
                    events.append(event)
                    event_type = str(event.get("type") or "")
                    if event_type in {"response.completed", "response.incomplete"}:
                        completed = event.get("response")
                        if isinstance(completed, dict):
                            _write_llm_trace(
                                trace_path,
                                request=request,
                                status=(
                                    "truncated"
                                    if event_type == "response.incomplete"
                                    else "completed"
                                ),
                                response=events,
                                finish_reason=str(completed.get("status") or "") or None,
                            )
                            return completed
                        raise LLMProtocolAdapterError(
                            f"Responses API {event_type} event has no response object."
                        )
                    if event_type in {"error", "response.failed"}:
                        detail = event.get("error") or event.get("response") or event
                        raise RuntimeError(f"Responses API stream failed: {detail}")
            raise LLMProtocolAdapterError(
                "Responses API stream ended without a completed response."
            )
        except (httpx.TransportError, httpx.HTTPStatusError, RuntimeError) as exc:
            _write_llm_trace(
                trace_path,
                request=request,
                status="failed",
                response=events,
                error=exc,
            )
            if attempt == max_retries - 1 or not _is_transient_streaming_error(exc):
                raise
            wait_s = min(
                delay,
                30.0,
                max(0.0, total_timeout_s - (time.monotonic() - started)),
            )
            if wait_s <= 0:
                raise TimeoutError(
                    f"Responses API request to {endpoint} exceeded "
                    f"{total_timeout_s:.0f}s overall deadline."
                ) from exc
            print(
                f"  [llm network] {endpoint} Responses API attempt "
                f"{attempt + 1}/{max_retries} failed ({type(exc).__name__}); "
                f"retrying in {wait_s:.0f}s."
            )
            time.sleep(wait_s)
            delay = min(delay * 2, 30.0)
    raise RuntimeError("Max Responses API retries exceeded")


def _call_openai_responses(
    *,
    model: str,
    messages: list[dict[str, Any]],
    system: str | None,
    max_tokens: int,
    api_key: str | None,
    base_url: str | None,
    reduce_reasoning_effort: bool,
    retry_on_truncation: bool,
    tools: list[ToolSpec] | None = None,
    trace_dir: str | Path | None = None,
    trace_name: str = "llm",
) -> dict[str, Any]:
    if not base_url:
        raise RuntimeError("The openai_responses provider requires a base URL.")
    budget = _effective_max_tokens(model, max_tokens)
    for attempt in range(2 if retry_on_truncation else 1):
        body: dict[str, Any] = {
            "model": model.removeprefix("openai/"),
            "input": _responses_input(messages),
            "max_output_tokens": budget,
        }
        if system:
            body["instructions"] = system
        requested_tools = tools or []
        if requested_tools:
            body["tools"] = _responses_tools(requested_tools)
            body["tool_choice"] = "auto"
        reasoning_effort = (
            "low" if reduce_reasoning_effort else os.environ.get("EVALCLAW_REASONING_EFFORT")
        )
        if reasoning_effort and _is_reasoning_model(model):
            body["reasoning"] = {"effort": reasoning_effort}
        trace_path = _llm_trace_path(trace_dir, trace_name, attempt + 1)
        request = {
            "provider": "openai_responses",
            "base_url": base_url,
            "body": body,
        }
        try:
            response = _post_streaming_responses(
                f"{base_url.rstrip('/')}/responses",
                headers={
                    "Authorization": f"Bearer {api_key or os.environ.get('OPENAI_API_KEY', '')}",
                    "Content-Type": "application/json",
                },
                body=body,
                trace_dir=Path(trace_dir) / "http" if trace_dir is not None else None,
                trace_name=trace_name,
            )
        except BaseException as exc:
            _write_llm_trace(trace_path, request=request, status="failed", error=exc)
            raise
        status = response.get("status")
        incomplete = response.get("incomplete_details")
        reason = None
        if isinstance(incomplete, dict):
            reason = incomplete.get("reason")
        if status == "incomplete" and reason == "max_output_tokens":
            _write_llm_trace(
                trace_path,
                request=request,
                status="truncated",
                response=response,
                finish_reason=reason,
            )
            if retry_on_truncation and attempt == 0:
                budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                continue
            raise LLMOutputTruncatedError(
                f"Responses API output truncated at {budget} output tokens for model {model}.",
                raw_response=_jsonable(response),
            )
        _write_llm_trace(
            trace_path,
            request=request,
            status="completed",
            response=response,
            finish_reason=str(status or "") or None,
        )
        return response
    raise AssertionError("unreachable")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(inner) for inner in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    if hasattr(value, "__dict__"):
        return {
            key: _jsonable(inner)
            for key, inner in vars(value).items()
            if not key.startswith("_")
        }
    return repr(value)


def _llm_trace_path(
    trace_dir: str | Path | None,
    trace_name: str,
    attempt: int,
) -> Path | None:
    if trace_dir is None:
        return None
    return Path(trace_dir) / f"{safe_name(trace_name)}-{attempt:02d}-{invocation_id()}.json"


def _response_usage(response: Any) -> Any:
    data = _jsonable(response)
    if isinstance(data, dict):
        return data.get("usage")
    if isinstance(data, list):
        for event in reversed(data):
            if isinstance(event, dict) and event.get("usage") is not None:
                return event["usage"]
    return None


def _write_llm_trace(
    path: Path | None,
    *,
    request: dict[str, Any],
    status: str,
    response: Any = None,
    finish_reason: str | None = None,
    error: BaseException | None = None,
) -> None:
    if path is None:
        return
    payload: dict[str, Any] = {
        "status": status,
        "request": request,
        "response": _jsonable(response),
        "usage": _response_usage(response),
        "finish_reason": finish_reason,
    }
    if error is not None:
        payload.update(error_record(error))
    write_json(path, payload, redact=True)


def _anthropic_text(response: Any) -> str:
    blocks = getattr(response, "content", None)
    if blocks is None and isinstance(response, dict):
        blocks = response.get("content")
    parts: list[str] = []
    for block in blocks or []:
        block_type = getattr(block, "type", None) if not isinstance(block, dict) else block.get("type")
        if block_type != "text":
            continue
        text = getattr(block, "text", None) if not isinstance(block, dict) else block.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


@dataclass(frozen=True)
class TargetToolModelResponse:
    """Provider-native target response containing canonical tool calls."""

    adapter: str
    content: str
    tool_calls: list[ToolCall]
    assistant_message: dict[str, Any]
    raw_response: Any


_REASONING_MODEL_MARKERS = ("gpt-5", "o1", "o3", "o4", "deepseek-reasoner")
_MAX_COMPLETION_TOKENS_CAP = 65536


def _is_reasoning_model(model: str) -> bool:
    """Whether a model bills internal reasoning tokens against max_tokens.

    Matches on the deployment/model segment so both ``gpt-5.5`` and
    ``azure/gpt-5.5`` are recognized.
    """
    name = model.split("/", 1)[-1].lower()
    return name.startswith(_REASONING_MODEL_MARKERS)


def _effective_max_tokens(model: str, max_tokens: int) -> int:
    """Apply the framework-wide minimum output budget."""
    return max(max_tokens, DEFAULT_MAX_OUTPUT_TOKENS)


def _litellm_model_name(model: str, base_url: Optional[str]) -> str:
    if base_url and not model.startswith(("openai/", "anthropic/", "gemini/", "azure/")):
        return f"openai/{model}"
    return model


def _call_litellm(
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    reduce_reasoning_effort: bool = False,
    retry_on_truncation: bool = True,
    expect_json: bool = False,
    trace_dir: str | Path | None = None,
    trace_name: str = "llm",
) -> str:
    import litellm

    # Silence litellm's ANSI "Provider List" banner spam on every exception.
    litellm.suppress_debug_info = True

    kwargs = {
        "model": _litellm_model_name(model, base_url),
        "messages": messages,
        "timeout": 300,
    }
    if (
        expect_json
        and base_url
        and not model.startswith(("claude-", "anthropic/"))
    ):
        kwargs["response_format"] = {"type": "json_object"}
    if model.startswith("deepseek-v4") and expect_json:
        # DeepSeek V4's thinking mode can consume the entire response window
        # before emitting the JSON body. Match the direct OpenAI-compatible
        # path for framework calls that explicitly require structured JSON.
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        kwargs["response_format"] = {"type": "json_object"}
    elif reduce_reasoning_effort:
        if model.startswith("deepseek-v4"):
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        elif _is_reasoning_model(model):
            kwargs["reasoning_effort"] = "low"
    else:
        reasoning_effort = os.environ.get("EVALCLAW_REASONING_EFFORT")
        if reasoning_effort and _is_reasoning_model(model):
            kwargs["reasoning_effort"] = reasoning_effort
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url

    # A truncated completion (finish_reason=length) would be silently "repaired"
    # by json-repair downstream, injecting cut-off prompts into datasets. Retry
    # once with a doubled budget, then fail loudly.
    budget = _effective_max_tokens(model, max_tokens)
    for attempt in range(2 if retry_on_truncation else 1):
        kwargs["max_tokens"] = budget
        trace_path = _llm_trace_path(trace_dir, trace_name, attempt + 1)
        try:
            response = litellm.completion(**kwargs)
        except BaseException as exc:
            _write_llm_trace(
                trace_path,
                request={"provider": "litellm", **kwargs},
                status="failed",
                error=exc,
            )
            raise
        finish_reason = getattr(
            (getattr(response, "choices", None) or [None])[0], "finish_reason", None
        )
        if finish_reason == "length":
            _write_llm_trace(
                trace_path,
                request={"provider": "litellm", **kwargs},
                status="truncated",
                response=response,
                finish_reason=finish_reason,
            )
            if retry_on_truncation and attempt == 0:
                budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                continue
            raise LLMOutputTruncatedError(
                f"LLM output truncated at {budget} completion tokens "
                f"(finish_reason=length) for model {model}",
                raw_response=_jsonable(response),
            )
        try:
            content = _extract_litellm_content(response)
        except ValueError as exc:
            _write_llm_trace(
                trace_path,
                request={"provider": "litellm", **kwargs},
                status="invalid_response",
                response=response,
                finish_reason=finish_reason,
                error=exc,
            )
            raise LLMProtocolAdapterError(
                f"LiteLLM returned an unsupported response shape for model {model}."
            ) from exc
        _write_llm_trace(
            trace_path,
            request={"provider": "litellm", **kwargs},
            status="completed",
            response=response,
            finish_reason=finish_reason,
        )
        return content
    raise AssertionError("unreachable")


def _get_anthropic_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> anthropic.Anthropic:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    endpoint = str(base_url or "").rstrip("/")
    cache_key = (key, endpoint)
    if cache_key not in _anthropic_clients:
        kwargs: dict[str, Any] = {"api_key": key}
        if endpoint:
            kwargs["base_url"] = endpoint
        _anthropic_clients[cache_key] = anthropic.Anthropic(**kwargs)
    return _anthropic_clients[cache_key]


def _anthropic_model_name(model: str) -> str:
    return model.removeprefix("anthropic/")


def _call_anthropic_text(
    messages: list[Message],
    *,
    system: Optional[str],
    model: str,
    max_tokens: int,
    api_key: Optional[str],
    base_url: Optional[str],
    trace_dir: str | Path | None = None,
    trace_name: str = "llm",
) -> str:
    client = _get_anthropic_client(api_key, base_url)
    request = {
        "provider": "anthropic",
        "model": _anthropic_model_name(model),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": message.role, "content": message.content} for message in messages],
        "base_url": base_url,
    }
    trace_path = _llm_trace_path(trace_dir, trace_name, 1)
    try:
        response = client.messages.create(
            model=_anthropic_model_name(model),
            max_tokens=max_tokens,
            system=system or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
            messages=request["messages"],
        )
    except BaseException as exc:
        _write_llm_trace(trace_path, request=request, status="failed", error=exc)
        raise
    stop_reason = str(getattr(response, "stop_reason", "") or "") or None
    _write_llm_trace(
        trace_path,
        request=request,
        status="truncated" if stop_reason == "max_tokens" else "completed",
        response=response,
        finish_reason=stop_reason,
    )
    if stop_reason == "max_tokens":
        raise LLMOutputTruncatedError(
            f"Anthropic output truncated for model {model}.",
            raw_response=_jsonable(response),
        )
    for block in response.content:
        if block.type == "text":
            return block.text
    raise ValueError("No text content in LLM response")


def call_llm(
    messages: list[Message],
    *,
    system: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    provider: Optional[str] = None,
    backend: str = "auto",
    reduce_reasoning_effort: bool = False,
    retry_on_truncation: bool = True,
    expect_json: bool = False,
    trace_dir: str | Path | None = None,
    trace_name: str = "llm",
) -> str:
    """Call the orchestrator LLM.

    The explicit provider selects the wire protocol. Claude models with a
    custom base URL use the native Anthropic SDK; other custom endpoints
    default to the OpenAI-compatible protocol. Set ``expect_json`` when the
    caller parses the response as JSON, so providers that support a structured
    output mode are asked for one.
    """
    _require_supported_backend(backend)
    model_name = model or DEFAULT_ORCHESTRATOR_MODEL
    resolved_provider, _ = infer_provider(model_name, base_url, provider)
    messages_dict = _message_dicts(messages, system)
    if resolved_provider == "openai_responses":
        response = _call_openai_responses(
            model=model_name,
            messages=[{"role": message.role, "content": message.content} for message in messages],
            system=system,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
            reduce_reasoning_effort=reduce_reasoning_effort,
            retry_on_truncation=retry_on_truncation,
            trace_dir=trace_dir,
            trace_name=trace_name,
        )
        content = _extract_responses_content(response)
        if content:
            return content
        raise LLMProtocolAdapterError(
            f"Responses API returned no text content for model {model_name}."
        )
    if (
        resolved_provider == "anthropic"
        and (provider is not None or base_url)
        and backend != "litellm"
    ):
        return _call_anthropic_text(
            messages,
            system=system,
            model=model_name,
            max_tokens=_effective_max_tokens(model_name, max_tokens),
            api_key=api_key,
            base_url=base_url,
            trace_dir=trace_dir,
            trace_name=trace_name,
        )
    stream_openai_compatible = (
        _env_enabled("EVALCLAW_LLM_STREAMING")
        and bool(base_url)
        and resolved_provider == "openai_compatible"
        and backend != "litellm"
    )
    if stream_openai_compatible:
        key = (
            api_key
            or (os.environ.get("DEEPSEEK_API_KEY") if model_name.startswith("deepseek-") else None)
            or (os.environ.get("GEMINI_API_KEY") if model_name.startswith("gemini") else None)
            or os.environ.get("OPENAI_API_KEY", "")
        )
        budget = _effective_max_tokens(model_name, max_tokens)
        for attempt in range(2 if retry_on_truncation else 1):
            body: dict[str, Any] = {"model": model_name, "messages": messages_dict, "max_tokens": budget}
            reasoning_effort = (
                "low" if reduce_reasoning_effort else os.environ.get("EVALCLAW_REASONING_EFFORT")
            )
            if reasoning_effort and _is_reasoning_model(model_name):
                body["reasoning_effort"] = reasoning_effort
            if expect_json:
                body["response_format"] = {"type": "json_object"}
            if (
                "api.deepseek.com" in base_url
                and model_name.startswith("deepseek-v4")
                and (expect_json or reduce_reasoning_effort)
            ):
                body["thinking"] = {"type": "disabled"}
            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            trace_path = _llm_trace_path(trace_dir, trace_name, attempt + 1)
            request = {
                "provider": "openai_compatible_stream",
                "base_url": base_url,
                "body": body,
            }
            try:
                raw_response: list[dict[str, Any]] = []
                content, finish_reason = _post_streaming_openai_compatible(
                    url,
                    headers=headers,
                    body=body,
                    raw_events=raw_response,
                    trace_dir=Path(trace_dir) / "http" if trace_dir is not None else None,
                    trace_name=trace_name,
                )
            except BaseException as exc:
                _write_llm_trace(trace_path, request=request, status="failed", error=exc)
                raise
            if finish_reason == "length":
                _write_llm_trace(
                    trace_path,
                    request=request,
                    status="truncated",
                    response=raw_response,
                    finish_reason=finish_reason,
                )
                if retry_on_truncation and attempt == 0:
                    budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                    continue
                raise LLMOutputTruncatedError(
                    f"LLM output truncated at {budget} completion tokens "
                    f"(finish_reason=length) for model {model_name}",
                    raw_response=raw_response,
                )
            _write_llm_trace(
                trace_path,
                request=request,
                status="completed",
                response=raw_response,
                finish_reason=finish_reason,
            )
            return content
        raise AssertionError("unreachable")

    return _call_litellm(
        model=model_name,
        messages=messages_dict,
        max_tokens=max_tokens,
        api_key=api_key,
        base_url=base_url,
        reduce_reasoning_effort=reduce_reasoning_effort,
        retry_on_truncation=retry_on_truncation,
        expect_json=expect_json,
        trace_dir=trace_dir,
        trace_name=trace_name,
    )


def call_orchestrator_with_tools(
    messages: list[dict[str, Any]],
    *,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    provider: Optional[str] = None,
    backend: str = "auto",
    tools: list[ToolSpec] | None = None,
    max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    retry_on_truncation: bool = True,
    expect_json: bool = False,
    trace_dir: str | Path | None = None,
    trace_name: str = "llm-tools",
) -> TargetToolModelResponse:
    """Call the orchestrator with provider-native tools.

    This is separate from ``call_llm`` because a tool round must preserve the
    provider-native assistant message and tool-result message structure. The
    task-builder research loop uses this for bounded external retrieval. Set
    ``expect_json`` when the caller parses a tool-free response as JSON.
    """
    _require_supported_backend(backend)
    model_name = model or DEFAULT_ORCHESTRATOR_MODEL
    resolved_provider, _ = infer_provider(model_name, base_url, provider)
    tool_specs = tools or []

    if resolved_provider == "openai_responses":
        response = _call_openai_responses(
            model=model_name,
            messages=messages,
            system=system_prompt,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
            reduce_reasoning_effort=False,
            retry_on_truncation=retry_on_truncation,
            tools=tool_specs,
            trace_dir=trace_dir,
            trace_name=trace_name,
        )
        output = getattr(response, "output", None)
        if output is None and isinstance(response, dict):
            output = response.get("output")
        return TargetToolModelResponse(
            adapter="openai_responses",
            content=_extract_responses_content(response),
            tool_calls=openai_tool_calls_from_response(response),
            assistant_message={"responses_output": _jsonable(output or [])},
            raw_response=_jsonable(response),
        )

    if (
        resolved_provider == "anthropic"
        and (provider is not None or base_url)
        and backend != "litellm"
    ):
        client = _get_anthropic_client(api_key, base_url)
        request = {
            "provider": "anthropic",
            "model": _anthropic_model_name(model_name),
            "max_tokens": _effective_max_tokens(model_name, max_tokens),
            "system": system_prompt,
            "messages": messages,
            "tools": anthropic_tools(tool_specs),
            "base_url": base_url,
        }
        trace_path = _llm_trace_path(trace_dir, trace_name, 1)
        try:
            response = client.messages.create(
                model=request["model"],
                max_tokens=request["max_tokens"],
                system=system_prompt or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
                messages=messages,
                tools=request["tools"],
            )
        except BaseException as exc:
            _write_llm_trace(trace_path, request=request, status="failed", error=exc)
            raise
        stop_reason = str(getattr(response, "stop_reason", "") or "") or None
        _write_llm_trace(
            trace_path,
            request=request,
            status="truncated" if stop_reason == "max_tokens" else "completed",
            response=response,
            finish_reason=stop_reason,
        )
        if stop_reason == "max_tokens":
            raise LLMOutputTruncatedError(
                f"Anthropic tool response truncated for model {model_name}.",
                raw_response=_jsonable(response),
            )
        content_blocks = _jsonable(getattr(response, "content", []))
        return TargetToolModelResponse(
            adapter="anthropic",
            content=_anthropic_text(response),
            tool_calls=anthropic_tool_calls_from_response(response),
            assistant_message={"role": "assistant", "content": content_blocks},
            raw_response=_jsonable(response),
        )

    import litellm

    litellm.suppress_debug_info = True
    request_messages = list(messages)
    if system_prompt:
        request_messages.insert(0, {"role": "system", "content": system_prompt})
    budget = _effective_max_tokens(model_name, max_tokens)
    for attempt in range(2 if retry_on_truncation else 1):
        kwargs: dict[str, Any] = {
            "model": _litellm_model_name(model_name, base_url),
            "messages": request_messages,
            "timeout": 300,
            "max_tokens": budget,
        }
        if tool_specs:
            kwargs["tools"] = openai_tools(tool_specs)
            kwargs["tool_choice"] = "auto"
        elif model_name.startswith("deepseek-v4") and expect_json:
            kwargs["response_format"] = {"type": "json_object"}
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        reasoning_effort = os.environ.get("EVALCLAW_REASONING_EFFORT")
        if reasoning_effort and _is_reasoning_model(model_name):
            kwargs["reasoning_effort"] = reasoning_effort
        trace_path = _llm_trace_path(trace_dir, trace_name, attempt + 1)
        try:
            response = litellm.completion(**kwargs)
        except BaseException as exc:
            _write_llm_trace(
                trace_path,
                request={"provider": "litellm", **kwargs},
                status="failed",
                error=exc,
            )
            raise
        choices = getattr(response, "choices", None)
        if choices is None and isinstance(response, dict):
            choices = response.get("choices")
        if not choices:
            _write_llm_trace(
                trace_path,
                request={"provider": "litellm", **kwargs},
                status="invalid_response",
                response=response,
            )
            raise LLMProtocolAdapterError(
                f"LiteLLM returned no choices for model {model_name}."
            )
        first = (choices or [None])[0]
        finish_reason = getattr(first, "finish_reason", None)
        if finish_reason is None and isinstance(first, dict):
            finish_reason = first.get("finish_reason")
        if finish_reason == "length":
            _write_llm_trace(
                trace_path,
                request={"provider": "litellm", **kwargs},
                status="truncated",
                response=response,
                finish_reason=finish_reason,
            )
            if retry_on_truncation and attempt == 0:
                budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                continue
            raise LLMOutputTruncatedError(
                f"Orchestrator tool response truncated at {budget} completion tokens "
                f"(finish_reason=length) for model {model_name}.",
                raw_response=_jsonable(response),
            )
        message = getattr(first, "message", None)
        if message is None and isinstance(first, dict):
            message = first.get("message")
        if message is None:
            _write_llm_trace(
                trace_path,
                request={"provider": "litellm", **kwargs},
                status="invalid_response",
                response=response,
                finish_reason=finish_reason,
            )
            raise LLMProtocolAdapterError(
                f"LiteLLM returned no assistant message for model {model_name}."
            )
        assistant_message = _jsonable(message)
        tool_calls = openai_tool_calls_from_response(response)
        try:
            content = _extract_litellm_content(response) if not tool_calls else ""
        except ValueError as exc:
            _write_llm_trace(
                trace_path,
                request={"provider": "litellm", **kwargs},
                status="invalid_response",
                response=response,
                finish_reason=finish_reason,
                error=exc,
            )
            raise LLMProtocolAdapterError(
                f"LiteLLM returned no final content for model {model_name}."
            ) from exc
        _write_llm_trace(
            trace_path,
            request={"provider": "litellm", **kwargs},
            status="completed",
            response=response,
            finish_reason=finish_reason,
        )
        return TargetToolModelResponse(
            adapter="litellm",
            content=content,
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            raw_response=_jsonable(response),
        )
    raise AssertionError("unreachable")


def call_target_model_with_tools(
    messages: list[dict[str, Any]],
    target: TargetModelConfig,
    tools: list[ToolSpec],
    *,
    system_prompt: Optional[str] = None,
    backend: str = "auto",
    max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    trace_dir: str | Path | None = None,
    trace_name: str = "target-tools",
) -> TargetToolModelResponse:
    """Call a target model with provider-native tool declarations.

    This is intentionally separate from ``call_target_model`` because native
    tool calls return structured assistant messages, not just text. The caller
    owns the provider-native message history so tool result messages can be
    appended without lossy conversion through EvalClaw's simple ``Message``
    model.
    """
    _require_supported_backend(backend)
    adapter = tool_adapter_for_target(target)
    if adapter == "anthropic":
        client = _get_anthropic_client(target.api_key, target.base_url)
        request = {
            "provider": "anthropic",
            "model": _anthropic_model_name(target.model),
            "max_tokens": _effective_max_tokens(target.model, max_tokens),
            "system": system_prompt,
            "messages": messages,
            "tools": anthropic_tools(tools),
            "base_url": target.base_url,
        }
        trace_path = _llm_trace_path(trace_dir, trace_name, 1)
        try:
            response = client.messages.create(
                model=request["model"],
                max_tokens=request["max_tokens"],
                system=system_prompt or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
                messages=messages,
                tools=request["tools"],
            )
        except BaseException as exc:
            _write_llm_trace(trace_path, request=request, status="failed", error=exc)
            raise
        stop_reason = str(getattr(response, "stop_reason", "") or "") or None
        _write_llm_trace(
            trace_path,
            request=request,
            status="truncated" if stop_reason == "max_tokens" else "completed",
            response=response,
            finish_reason=stop_reason,
        )
        if stop_reason == "max_tokens":
            raise LLMOutputTruncatedError(
                f"Target Anthropic tool response truncated for model {target.model}.",
                raw_response=_jsonable(response),
            )
        content_blocks = _jsonable(getattr(response, "content", []))
        return TargetToolModelResponse(
            adapter="anthropic",
            content=_anthropic_text(response),
            tool_calls=anthropic_tool_calls_from_response(response),
            assistant_message={"role": "assistant", "content": content_blocks},
            raw_response=_jsonable(response),
        )

    if adapter != "openai":
        raise RuntimeError(f"Native target tool calls are not implemented for adapter {adapter or '<none>'}.")

    base_url = target.base_url or "https://api.openai.com/v1"
    api_key = (
        target.api_key
        or (os.environ.get("DEEPSEEK_API_KEY") if target.model.startswith("deepseek-") else None)
        or os.environ.get("OPENAI_API_KEY", "")
    )
    request_messages: list[dict[str, Any]] = []
    if system_prompt:
        request_messages.append({"role": "system", "content": system_prompt})
    request_messages.extend(messages)
    body: dict[str, Any] = {
        "model": target.model,
        "messages": request_messages,
        "tools": openai_tools(tools),
        "tool_choice": "auto",
        "max_tokens": _effective_max_tokens(target.model, max_tokens),
    }
    if "api.deepseek.com" in base_url and target.model.startswith("deepseek-v4"):
        body["thinking"] = {"type": "disabled"}
    if backend == "litellm":
        # LiteLLM can route tool calls for many providers, but the rest of the
        # runner needs the native assistant message. For now, keep this path
        # explicit instead of silently returning a lossy text-only response.
        raise RuntimeError("Native agent tool calls currently require the direct OpenAI-compatible backend.")
    request = {"provider": "openai_compatible", "base_url": base_url, "body": body}
    trace_path = _llm_trace_path(trace_dir, trace_name, 1)
    try:
        data = _post_with_retry(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            body=body,
            trace_dir=Path(trace_dir) / "http" if trace_dir is not None else None,
            trace_name=trace_name,
        )
    except BaseException as exc:
        _write_llm_trace(trace_path, request=request, status="failed", error=exc)
        raise
    finish_reason = str((data.get("choices") or [{}])[0].get("finish_reason") or "") or None
    _write_llm_trace(
        trace_path,
        request=request,
        status="truncated" if finish_reason == "length" else "completed",
        response=data,
        finish_reason=finish_reason,
    )
    if finish_reason == "length":
        raise LLMOutputTruncatedError(
            f"Target tool response truncated for model {target.model}.",
            raw_response=data,
        )
    message = data["choices"][0]["message"]
    content = message.get("content")
    return TargetToolModelResponse(
        adapter="openai",
        content=content if isinstance(content, str) else "",
        tool_calls=openai_tool_calls_from_response(data),
        assistant_message=message,
        raw_response=data,
    )


def call_target_model(
    prompt: str,
    target: TargetModelConfig,
    *,
    system_prompt: Optional[str] = None,
    history: Optional[list[Message]] = None,
    backend: str = "auto",
    user_content: Any | None = None,
    trace_dir: str | Path | None = None,
    trace_name: str = "target",
) -> str:
    """Call the target model under evaluation."""
    _require_supported_backend(backend)
    history = history or []

    if user_content is not None:
        if target.provider == "anthropic":
            client = _get_anthropic_client(target.api_key, target.base_url)
            request = {
                "provider": "anthropic",
                "model": _anthropic_model_name(target.model),
                "max_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
                "system": system_prompt,
                "messages": [{"role": m.role, "content": m.content} for m in history]
                + [{"role": "user", "content": user_content}],
                "base_url": target.base_url,
            }
            trace_path = _llm_trace_path(trace_dir, trace_name, 1)
            try:
                response = client.messages.create(
                    model=request["model"],
                    max_tokens=request["max_tokens"],
                    system=system_prompt or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
                    messages=request["messages"],
                )
            except BaseException as exc:
                _write_llm_trace(trace_path, request=request, status="failed", error=exc)
                raise
            stop_reason = str(getattr(response, "stop_reason", "") or "") or None
            _write_llm_trace(
                trace_path,
                request=request,
                status="truncated" if stop_reason == "max_tokens" else "completed",
                response=response,
                finish_reason=stop_reason,
            )
            if stop_reason == "max_tokens":
                raise LLMOutputTruncatedError(
                    f"Target Anthropic response truncated for model {target.model}.",
                    raw_response=_jsonable(response),
                )
            for block in response.content:
                if block.type == "text":
                    return block.text
            raise ValueError("No text content in LLM response")

        base_url = target.base_url or "https://api.openai.com/v1"
        api_key = (
            target.api_key
            or (os.environ.get("DEEPSEEK_API_KEY") if target.model.startswith("deepseek-") else None)
            or (os.environ.get("GEMINI_API_KEY") if target.model.startswith("gemini") else None)
            or os.environ.get("OPENAI_API_KEY", "")
        )
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in history:
            messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": user_content})
        if target.provider == "azure" or target.model.startswith("azure/"):
            return _call_litellm(
                model=target.model,
                messages=messages,
                max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
                api_key=target.api_key,
                base_url=target.base_url,
                trace_dir=trace_dir,
                trace_name=trace_name,
            )
        body = {
            "model": target.model,
            "messages": messages,
            "max_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
        }
        request = {"provider": "openai_compatible", "base_url": base_url, "body": body}
        trace_path = _llm_trace_path(trace_dir, trace_name, 1)
        try:
            data = _post_with_retry(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                body=body,
                trace_dir=Path(trace_dir) / "http" if trace_dir is not None else None,
                trace_name=trace_name,
            )
        except BaseException as exc:
            _write_llm_trace(trace_path, request=request, status="failed", error=exc)
            raise
        finish_reason = str((data.get("choices") or [{}])[0].get("finish_reason") or "") or None
        _write_llm_trace(
            trace_path,
            request=request,
            status="truncated" if finish_reason == "length" else "completed",
            response=data,
            finish_reason=finish_reason,
        )
        if finish_reason == "length":
            raise LLMOutputTruncatedError(
                f"Target response truncated for model {target.model}.",
                raw_response=data,
            )
        return data["choices"][0]["message"]["content"]

    if target.provider == "anthropic":
        msgs = [*history, Message(role="user", content=prompt)]
        return call_llm(
            msgs,
            system=system_prompt,
            model=target.model,
            api_key=target.api_key,
            base_url=target.base_url,
            provider=target.provider,
            backend=backend,
            trace_dir=trace_dir,
            trace_name=trace_name,
        )

    # OpenAI or OpenAI-compatible
    base_url = target.base_url or "https://api.openai.com/v1"
    api_key = (
        target.api_key
        or (os.environ.get("DEEPSEEK_API_KEY") if target.model.startswith("deepseek-") else None)
        or (os.environ.get("GEMINI_API_KEY") if target.model.startswith("gemini") else None)
        or os.environ.get("OPENAI_API_KEY", "")
    )

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": prompt})

    return _call_litellm(
        model=target.model,
        messages=messages,
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        api_key=api_key,
        base_url=base_url,
        trace_dir=trace_dir,
        trace_name=trace_name,
    )
