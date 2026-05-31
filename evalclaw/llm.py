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


def _call_litellm(
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    import litellm

    litellm_model = model
    if base_url and not model.startswith(("openai/", "anthropic/", "gemini/")):
        litellm_model = f"openai/{model}"
    kwargs = {
        "model": litellm_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "timeout": 120,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    response = litellm.completion(**kwargs)
    return _extract_litellm_content(response)


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
        except Exception:
            if backend == "litellm":
                raise

    if base_url:
        # OpenAI-compatible path (covers Gemini, local models, etc.)
        key = (
            api_key
            or (os.environ.get("DEEPSEEK_API_KEY") if model_name.startswith("deepseek-") else None)
            or (os.environ.get("GEMINI_API_KEY") if model_name.startswith("gemini") else None)
            or os.environ.get("OPENAI_API_KEY", "")
        )
        data = _post_with_retry(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            body={"model": model_name, "messages": messages_dict, "max_tokens": max_tokens},
        )
        return data["choices"][0]["message"]["content"]

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

    data = _post_with_retry(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        body={"model": target.model, "messages": messages, "max_tokens": 4096},
    )
    return data["choices"][0]["message"]["content"]


