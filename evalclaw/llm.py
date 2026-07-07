"""Evalclaw: LLM call utilities (Anthropic + OpenAI-compatible)."""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import anthropic
import httpx

from .llm_json import extract_json
from .types import Message, TargetModelConfig


def _post_with_retry(url: str, headers: dict, body: dict, max_retries: int = 6) -> dict:
    """POST with exponential backoff on 429 / 5xx."""
    delay = 15.0
    for attempt in range(max_retries):
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=120.0)
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as exc:
            if attempt == max_retries - 1:
                raise
            print(f"  [retry {attempt + 1}/{max_retries}] network error ({exc}), waiting {delay:.0f}s…")
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == max_retries - 1:
                resp.raise_for_status()
            print(f"  [retry {attempt + 1}/{max_retries}] HTTP {resp.status_code}, waiting {delay:.0f}s…")
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Max retries exceeded")

DEFAULT_ORCHESTRATOR_MODEL = "claude-opus-4-6"

# Module-level Anthropic clients, keyed by api_key to avoid re-creating
_anthropic_clients: dict[str, anthropic.Anthropic] = {}


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
    """Raise (never lower) max_tokens for reasoning models.

    Reasoning models consume the completion budget with internal reasoning
    tokens first; a 4096 budget routinely yields truncated or empty text.
    """
    if _is_reasoning_model(model):
        return max(max_tokens, _REASONING_MAX_TOKENS_FLOOR)
    return max_tokens


def _call_litellm(
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
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
    for attempt in range(2):
        kwargs["max_tokens"] = budget
        response = litellm.completion(**kwargs)
        finish_reason = getattr(
            (getattr(response, "choices", None) or [None])[0], "finish_reason", None
        )
        if finish_reason == "length":
            if attempt == 0:
                budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                continue
            raise RuntimeError(
                f"LLM output truncated at {budget} completion tokens "
                f"(finish_reason=length) for model {model}"
            )
        return _extract_litellm_content(response)
    raise AssertionError("unreachable")


def _azure_legacy_completion(
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    api_key: Optional[str] = None,
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
    for attempt in range(2):
        data = _post_with_retry(
            url,
            headers={"api-key": key or "", "Content-Type": "application/json"},
            body={"messages": messages, token_field: budget},
        )
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            if attempt == 0:
                budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                continue
            raise RuntimeError(
                f"LLM output truncated at {budget} completion tokens "
                f"(finish_reason=length) for model {model}"
            )
        return choice["message"]["content"]
    raise AssertionError("unreachable")


def _get_anthropic_client(api_key: Optional[str] = None) -> anthropic.Anthropic:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if key not in _anthropic_clients:
        _anthropic_clients[key] = anthropic.Anthropic(api_key=key)
    return _anthropic_clients[key]


def call_llm(
    messages: list[Message],
    *,
    system: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 4096,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    backend: str = "auto",
) -> str:
    """Call the orchestrator LLM.

    When base_url is set (e.g. Gemini OpenAI-compatible endpoint), uses httpx.
    Otherwise falls back to the native Anthropic SDK.
    """
    model_name = model or DEFAULT_ORCHESTRATOR_MODEL
    messages_dict = _message_dicts(messages, system)
    if backend in {"auto", "litellm"}:
        try:
            return _call_litellm(
                model=model_name,
                messages=messages_dict,
                max_tokens=max_tokens,
                api_key=api_key,
                base_url=base_url,
            )
        except Exception as exc:
            if backend == "litellm":
                raise
            print(
                f"  [llm] litellm call failed for {model_name} "
                f"({type(exc).__name__}: {str(exc)[:160]}); falling back to legacy backend"
            )

    if model_name.startswith("azure/"):
        # Legacy backend path for Azure OpenAI deployments.
        return _azure_legacy_completion(
            model=model_name,
            messages=messages_dict,
            max_tokens=max_tokens,
            api_key=api_key,
        )

    if base_url:
        # OpenAI-compatible path (covers Gemini, local models, etc.)
        key = (
            api_key
            or (os.environ.get("DEEPSEEK_API_KEY") if model_name.startswith("deepseek-") else None)
            or (os.environ.get("GEMINI_API_KEY") if model_name.startswith("gemini") else None)
            or os.environ.get("OPENAI_API_KEY", "")
        )
        budget = _effective_max_tokens(model_name, max_tokens)
        for attempt in range(2):
            data = _post_with_retry(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                body={"model": model_name, "messages": messages_dict, "max_tokens": budget},
            )
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                if attempt == 0:
                    budget = min(budget * 2, _MAX_COMPLETION_TOKENS_CAP)
                    continue
                raise RuntimeError(
                    f"LLM output truncated at {budget} completion tokens "
                    f"(finish_reason=length) for model {model_name}"
                )
            return choice["message"]["content"]

    # Native Anthropic path
    client = _get_anthropic_client(api_key)
    response = client.messages.create(
        model=model or DEFAULT_ORCHESTRATOR_MODEL,
        max_tokens=max_tokens,
        system=system or anthropic.NOT_GIVEN,  # type: ignore[arg-type]
        messages=[{"role": m.role, "content": m.content} for m in messages],
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    raise ValueError("No text content in LLM response")


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
            client = _get_anthropic_client(target.api_key)
            response = client.messages.create(
                model=target.model,
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
                except Exception:
                    if backend == "litellm":
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
        except Exception:
            if backend == "litellm":
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


