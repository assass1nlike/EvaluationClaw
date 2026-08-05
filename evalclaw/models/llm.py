"""Evalclaw: LLM call utilities (Anthropic + OpenAI-compatible)."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import anthropic
import httpx

# Pricing metadata is unrelated to inference. Use LiteLLM's bundled map so an
# unreachable GitHub endpoint cannot delay every EvalClaw process at import.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

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


class LLMProtocolAdapterError(RuntimeError):
    """LiteLLM could not adapt the request or response for the selected provider."""


def _is_litellm_protocol_adapter_failure(exc: Exception) -> bool:
    """Whether direct protocol fallback can plausibly bypass a LiteLLM failure."""
    if isinstance(exc, (ImportError, ModuleNotFoundError, LLMProtocolAdapterError)):
        return True
    try:
        import litellm
    except ImportError:
        return True

    unsupported = getattr(litellm, "UnsupportedParamsError", None)
    if isinstance(unsupported, type) and isinstance(exc, unsupported):
        return True

    bad_request = getattr(litellm, "BadRequestError", None)
    if not isinstance(bad_request, type) or not isinstance(exc, bad_request):
        return False
    message = str(exc).lower()
    adapter_markers = (
        "llm provider not provided",
        "unsupported parameter",
        "unsupported param",
        "parameter is not supported",
        "provider not supported",
        "unknown provider",
        "unrecognized request argument",
    )
    return any(marker in message for marker in adapter_markers)


def _post_with_retry(
    url: str,
    headers: dict,
    body: dict,
    max_retries: int = 3,
    *,
    request_timeout_s: float = 300.0,
    total_timeout_s: float = 300.0,
) -> dict:
    """POST with bounded retries for transient transport, 429, and 5xx errors."""
    delay = 5.0
    started = time.monotonic()
    endpoint = httpx.URL(url).host or "model endpoint"
    for attempt in range(max_retries):
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
        resp.raise_for_status()
        return resp.json()
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
        remaining = total_timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError(
                f"Streaming model request to {endpoint} exceeded "
                f"{total_timeout_s:.0f}s overall deadline."
            )
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
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


def _messages_request_json(messages: list[dict]) -> bool:
    text = "\n".join(str(message.get("content") or "") for message in messages).lower()
    return "json" in text


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
) -> dict[str, Any]:
    """Return the complete response object from a Responses API SSE stream."""
    delay = 5.0
    started = time.monotonic()
    endpoint = httpx.URL(url).host or "model endpoint"
    for attempt in range(max_retries):
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
                    event_type = str(event.get("type") or "")
                    if event_type in {"response.completed", "response.incomplete"}:
                        completed = event.get("response")
                        if isinstance(completed, dict):
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
        response = _post_streaming_responses(
            f"{base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {api_key or os.environ.get('OPENAI_API_KEY', '')}",
                "Content-Type": "application/json",
            },
            body=body,
        )
        status = response.get("status")
        incomplete = response.get("incomplete_details")
        reason = None
        if isinstance(incomplete, dict):
            reason = incomplete.get("reason")
        if status == "incomplete" and reason == "max_output_tokens":
            if retry_on_truncation and attempt == 0:
                budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                continue
            raise LLMOutputTruncatedError(
                f"Responses API output truncated at {budget} output tokens for model {model}."
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
_REASONING_MAX_TOKENS_FLOOR = 16384
_MAX_COMPLETION_TOKENS_CAP = 65536


def _is_reasoning_model(model: str) -> bool:
    """Whether a model bills internal reasoning tokens against max_tokens.

    Matches on the deployment/model segment so both ``gpt-5.5`` and
    ``azure/gpt-5.5`` are recognized.
    """
    name = model.split("/", 1)[-1].lower()
    return name.startswith(_REASONING_MODEL_MARKERS)


def _effective_max_tokens(model: str, max_tokens: int) -> int:
    """Raise max_tokens for reasoning models unless low effort was explicit.

    Reasoning models consume the completion budget with internal reasoning
    tokens first; a 4096 budget routinely yields truncated or empty text.
    Low-effort calls deliberately trade reasoning depth for latency, so keep
    the caller's stage-specific budget instead of expanding small JSON calls.
    """
    if _is_reasoning_model(model) and os.environ.get("EVALCLAW_REASONING_EFFORT") != "low":
        return max(max_tokens, _REASONING_MAX_TOKENS_FLOOR)
    return max_tokens


def _call_litellm(
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    reduce_reasoning_effort: bool = False,
    retry_on_truncation: bool = True,
) -> str:
    import litellm

    # Silence litellm's ANSI "Provider List" banner spam on every exception.
    litellm.suppress_debug_info = True

    litellm_model = model
    if base_url and not model.startswith(("openai/", "anthropic/", "gemini/", "azure/")):
        litellm_model = f"openai/{model}"
    kwargs = {
        "model": litellm_model,
        "messages": messages,
        "timeout": 300,
    }
    requests_json = _messages_request_json(messages)
    if (
        requests_json
        and base_url
        and not model.startswith(("claude-", "anthropic/"))
    ):
        kwargs["response_format"] = {"type": "json_object"}
    if model.startswith("deepseek-v4") and requests_json:
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
        response = litellm.completion(**kwargs)
        finish_reason = getattr(
            (getattr(response, "choices", None) or [None])[0], "finish_reason", None
        )
        if finish_reason == "length":
            if retry_on_truncation and attempt == 0:
                budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                continue
            raise LLMOutputTruncatedError(
                f"LLM output truncated at {budget} completion tokens "
                f"(finish_reason=length) for model {model}"
            )
        try:
            return _extract_litellm_content(response)
        except ValueError as exc:
            raise LLMProtocolAdapterError(
                f"LiteLLM returned an unsupported response shape for model {model}."
            ) from exc
    raise AssertionError("unreachable")


def _azure_legacy_completion(
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    api_key: Optional[str] = None,
    retry_on_truncation: bool = True,
) -> str:
    """Call an Azure OpenAI deployment via httpx (legacy, non-litellm backend).

    Azure OpenAI exposes chat completions at
    ``{AZURE_API_BASE}/openai/deployments/{deployment}/chat/completions?api-version=...``
    and authenticates with an ``api-key`` header. When the required Azure
    environment variables are missing we raise an actionable error telling the
    user to use the litellm backend instead.
    """
    base = os.environ.get("AZURE_API_BASE")
    version = os.environ.get("AZURE_API_VERSION")
    key = (
        api_key
        or os.environ.get("AZURE_API_KEY")
        or os.environ.get("AZURE_OPENAI_API_KEY")
    )
    if not base or not version:
        raise RuntimeError(
            "Azure OpenAI models require either the litellm backend "
            "(llm_backend='auto' or 'litellm') or, for the legacy backend, "
            "AZURE_API_BASE and AZURE_API_VERSION to be set. "
            "Export AZURE_API_BASE, AZURE_API_VERSION, and AZURE_API_KEY, "
            "or switch to the litellm backend."
        )
    deployment = model.split("/", 1)[1] if "/" in model else model
    url = (
        f"{base.rstrip('/')}/openai/deployments/{deployment}"
        f"/chat/completions?api-version={version}"
    )
    # Reasoning deployments reject max_tokens and require max_completion_tokens.
    token_field = "max_completion_tokens" if _is_reasoning_model(model) else "max_tokens"
    # Same truncation guard as the litellm path: a length-cut completion would
    # be silently "repaired" by json-repair downstream.
    budget = _effective_max_tokens(model, max_tokens)
    for attempt in range(2 if retry_on_truncation else 1):
        data = _post_with_retry(
            url,
            headers={"api-key": key or "", "Content-Type": "application/json"},
            body={"messages": messages, token_field: budget},
        )
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            if retry_on_truncation and attempt == 0:
                budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                continue
            raise LLMOutputTruncatedError(
                f"LLM output truncated at {budget} completion tokens "
                f"(finish_reason=length) for model {model}"
            )
        return choice["message"]["content"]
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
) -> str:
    client = _get_anthropic_client(api_key, base_url)
    response = client.messages.create(
        model=_anthropic_model_name(model),
        max_tokens=max_tokens,
        system=system or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
        messages=[{"role": message.role, "content": message.content} for message in messages],
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
    max_tokens: int = 4096,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    provider: Optional[str] = None,
    backend: str = "auto",
    reduce_reasoning_effort: bool = False,
    retry_on_truncation: bool = True,
) -> str:
    """Call the orchestrator LLM.

    The explicit provider selects the wire protocol. Claude models with a
    custom base URL use the native Anthropic SDK; other custom endpoints
    default to the OpenAI-compatible protocol.
    """
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
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
        )
    stream_openai_compatible = (
        _env_enabled("EVALCLAW_LLM_STREAMING")
        and bool(base_url)
        and resolved_provider == "openai_compatible"
        and backend != "litellm"
    )
    if backend in {"auto", "litellm"} and not stream_openai_compatible:
        try:
            return _call_litellm(
                model=model_name,
                messages=messages_dict,
                max_tokens=max_tokens,
                api_key=api_key,
                base_url=base_url,
                reduce_reasoning_effort=reduce_reasoning_effort,
                retry_on_truncation=retry_on_truncation,
            )
        except Exception as exc:
            if backend == "litellm" or not _is_litellm_protocol_adapter_failure(exc):
                raise
            print(
                f"  [llm] litellm adapter failed for {model_name} "
                f"({type(exc).__name__}: {str(exc)[:160]}); falling back to legacy backend"
            )

    if model_name.startswith("azure/"):
        # Legacy backend path for Azure OpenAI deployments.
        return _azure_legacy_completion(
            model=model_name,
            messages=messages_dict,
            max_tokens=max_tokens,
            api_key=api_key,
            retry_on_truncation=retry_on_truncation,
        )

    if base_url and resolved_provider != "anthropic":
        # OpenAI-compatible path (covers Gemini, local models, etc.)
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
            if _messages_request_json(messages_dict):
                body["response_format"] = {"type": "json_object"}
            if "api.deepseek.com" in base_url and model_name.startswith("deepseek-v4"):
                body["thinking"] = {"type": "disabled"}
            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            if stream_openai_compatible:
                content, finish_reason = _post_streaming_openai_compatible(
                    url,
                    headers=headers,
                    body=body,
                )
                if finish_reason == "length":
                    if retry_on_truncation and attempt == 0:
                        budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                        continue
                    raise LLMOutputTruncatedError(
                        f"LLM output truncated at {budget} completion tokens "
                        f"(finish_reason=length) for model {model_name}"
                    )
                return content
            data = _post_with_retry(url, headers=headers, body=body)
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                if retry_on_truncation and attempt == 0:
                    budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                    continue
                raise LLMOutputTruncatedError(
                    f"LLM output truncated at {budget} completion tokens "
                    f"(finish_reason=length) for model {model_name}"
                )
            message = choice["message"]
            content = message.get("content")
            if isinstance(content, str) and content:
                return content
            reasoning = message.get("reasoning_content")
            return reasoning if isinstance(reasoning, str) else ""

    if resolved_provider == "anthropic":
        return _call_anthropic_text(
            messages,
            system=system,
            model=model_name,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
        )
    raise RuntimeError(f"No LLM backend is configured for provider {resolved_provider}.")


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
    max_tokens: int = 4096,
    retry_on_truncation: bool = True,
) -> TargetToolModelResponse:
    """Call the orchestrator with provider-native tools.

    This is separate from ``call_llm`` because a tool round must preserve the
    provider-native assistant message and tool-result message structure. The
    task-builder research loop uses this for bounded external retrieval.
    """
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
        response = client.messages.create(
            model=_anthropic_model_name(model_name),
            max_tokens=_effective_max_tokens(model_name, max_tokens),
            system=system_prompt or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
            messages=messages,
            tools=anthropic_tools(tool_specs),
        )
        content_blocks = _jsonable(getattr(response, "content", []))
        return TargetToolModelResponse(
            adapter="anthropic",
            content=_anthropic_text(response),
            tool_calls=anthropic_tool_calls_from_response(response),
            assistant_message={"role": "assistant", "content": content_blocks},
            raw_response=_jsonable(response),
        )

    if backend in {"auto", "litellm"}:
        try:
            import litellm

            litellm.suppress_debug_info = True
            request_messages = list(messages)
            if system_prompt:
                request_messages.insert(0, {"role": "system", "content": system_prompt})
            budget = _effective_max_tokens(model_name, max_tokens)
            for attempt in range(2 if retry_on_truncation else 1):
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "messages": request_messages,
                    "timeout": 300,
                    "max_tokens": budget,
                }
                if tool_specs:
                    kwargs["tools"] = openai_tools(tool_specs)
                    kwargs["tool_choice"] = "auto"
                elif model_name.startswith("deepseek-v4") and _messages_request_json(request_messages):
                    kwargs["response_format"] = {"type": "json_object"}
                if api_key:
                    kwargs["api_key"] = api_key
                if base_url:
                    kwargs["base_url"] = base_url
                reasoning_effort = os.environ.get("EVALCLAW_REASONING_EFFORT")
                if reasoning_effort and _is_reasoning_model(model_name):
                    kwargs["reasoning_effort"] = reasoning_effort
                response = litellm.completion(**kwargs)
                choices = getattr(response, "choices", None)
                if choices is None and isinstance(response, dict):
                    choices = response.get("choices")
                if not choices:
                    raise LLMProtocolAdapterError(
                        f"LiteLLM returned no choices for model {model_name}."
                    )
                first = (choices or [None])[0]
                finish_reason = getattr(first, "finish_reason", None)
                if finish_reason is None and isinstance(first, dict):
                    finish_reason = first.get("finish_reason")
                if finish_reason == "length":
                    if retry_on_truncation and attempt == 0:
                        budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                        continue
                    raise LLMOutputTruncatedError(
                        f"Orchestrator tool response truncated at {budget} completion tokens "
                        f"(finish_reason=length) for model {model_name}."
                    )
                message = getattr(first, "message", None)
                if message is None and isinstance(first, dict):
                    message = first.get("message")
                if message is None:
                    raise LLMProtocolAdapterError(
                        f"LiteLLM returned no assistant message for model {model_name}."
                    )
                assistant_message = _jsonable(message) if message is not None else {}
                tool_calls = openai_tool_calls_from_response(response)
                return TargetToolModelResponse(
                    adapter="litellm",
                    content=_extract_litellm_content(response) if message and not tool_calls else "",
                    tool_calls=tool_calls,
                    assistant_message=assistant_message,
                    raw_response=_jsonable(response),
                )
        except Exception as exc:
            if backend == "litellm" or not _is_litellm_protocol_adapter_failure(exc):
                raise

    if resolved_provider == "anthropic":
        client = _get_anthropic_client(api_key, base_url)
        response = client.messages.create(
            model=_anthropic_model_name(model_name),
            max_tokens=_effective_max_tokens(model_name, max_tokens),
            system=system_prompt or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
            messages=messages,
            tools=anthropic_tools(tool_specs),
        )
        content_blocks = _jsonable(getattr(response, "content", []))
        return TargetToolModelResponse(
            adapter="anthropic",
            content=_anthropic_text(response),
            tool_calls=anthropic_tool_calls_from_response(response),
            assistant_message={"role": "assistant", "content": content_blocks},
            raw_response=_jsonable(response),
        )

    if not base_url:
        raise RuntimeError(
            f"No tool-capable orchestrator backend is configured for model {model_name}."
        )
    key = (
        api_key
        or (os.environ.get("DEEPSEEK_API_KEY") if model_name.startswith("deepseek-") else None)
        or os.environ.get("OPENAI_API_KEY", "")
    )
    request_messages = list(messages)
    if system_prompt:
        request_messages.insert(0, {"role": "system", "content": system_prompt})
    budget = _effective_max_tokens(model_name, max_tokens)
    for attempt in range(2 if retry_on_truncation else 1):
        body: dict[str, Any] = {
            "model": model_name,
            "messages": request_messages,
            "max_tokens": budget,
        }
        reasoning_effort = os.environ.get("EVALCLAW_REASONING_EFFORT")
        if reasoning_effort and _is_reasoning_model(model_name):
            body["reasoning_effort"] = reasoning_effort
        if tool_specs:
            body["tools"] = openai_tools(tool_specs)
            body["tool_choice"] = "auto"
        if "api.deepseek.com" in base_url and model_name.startswith("deepseek-v4"):
            body["thinking"] = {"type": "disabled"}
            if not tool_specs and _messages_request_json(request_messages):
                body["response_format"] = {"type": "json_object"}
        data = _post_with_retry(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            body=body,
        )
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            if retry_on_truncation and attempt == 0:
                budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                continue
            raise LLMOutputTruncatedError(
                f"Orchestrator tool response truncated at {budget} completion tokens "
                f"(finish_reason=length) for model {model_name}."
            )
        message = choice["message"]
        content = message.get("content")
        return TargetToolModelResponse(
            adapter="openai",
            content=content if isinstance(content, str) else "",
            tool_calls=openai_tool_calls_from_response(data),
            assistant_message=message,
            raw_response=data,
        )
    raise RuntimeError(f"Orchestrator tool call failed for model {model_name}.")


def call_target_model_with_tools(
    messages: list[dict[str, Any]],
    target: TargetModelConfig,
    tools: list[ToolSpec],
    *,
    system_prompt: Optional[str] = None,
    backend: str = "auto",
    max_tokens: int = 4096,
) -> TargetToolModelResponse:
    """Call a target model with provider-native tool declarations.

    This is intentionally separate from ``call_target_model`` because native
    tool calls return structured assistant messages, not just text. The caller
    owns the provider-native message history so tool result messages can be
    appended without lossy conversion through EvalClaw's simple ``Message``
    model.
    """
    adapter = tool_adapter_for_target(target)
    if adapter == "anthropic":
        client = _get_anthropic_client(target.api_key, target.base_url)
        response = client.messages.create(
            model=_anthropic_model_name(target.model),
            max_tokens=max_tokens,
            system=system_prompt or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
            messages=messages,
            tools=anthropic_tools(tools),
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
    data = _post_with_retry(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        body=body,
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
) -> str:
    """Call the target model under evaluation."""
    history = history or []

    if user_content is not None:
        if target.provider == "anthropic":
            client = _get_anthropic_client(target.api_key, target.base_url)
            response = client.messages.create(
                model=_anthropic_model_name(target.model),
                max_tokens=4096,
                system=system_prompt or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
                messages=[
                    {"role": m.role, "content": m.content}
                    for m in history
                ]
                + [{"role": "user", "content": user_content}],
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
            if backend in {"auto", "litellm"}:
                try:
                    return _call_litellm(
                        model=target.model,
                        messages=messages,
                        max_tokens=4096,
                        api_key=target.api_key,
                        base_url=target.base_url,
                    )
                except Exception as exc:
                    if backend == "litellm" or not _is_litellm_protocol_adapter_failure(exc):
                        raise
            return _azure_legacy_completion(
                model=target.model,
                messages=messages,
                max_tokens=4096,
                api_key=target.api_key,
            )
        data = _post_with_retry(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            body={"model": target.model, "messages": messages, "max_tokens": 4096},
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

    if backend in {"auto", "litellm"}:
        try:
            return _call_litellm(
                model=target.model,
                messages=messages,
                max_tokens=4096,
                api_key=api_key,
                base_url=base_url,
            )
        except Exception as exc:
            if backend == "litellm" or not _is_litellm_protocol_adapter_failure(exc):
                raise

    if target.provider == "azure" or target.model.startswith("azure/"):
        return _azure_legacy_completion(
            model=target.model,
            messages=messages,
            max_tokens=4096,
            api_key=target.api_key,
        )

    data = _post_with_retry(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        body={"model": target.model, "messages": messages, "max_tokens": 4096},
    )
    return data["choices"][0]["message"]["content"]


