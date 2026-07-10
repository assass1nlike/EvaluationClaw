"""Provider inference and credential helpers."""
from __future__ import annotations

import os
from typing import Optional

from ..types import TargetModelConfig

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def infer_provider(model: str, base_url: Optional[str] = None) -> tuple[str, Optional[str]]:
    """Infer provider and default base URL from a model name."""
    if model.startswith("azure/"):
        # Azure OpenAI deployments route through LiteLLM's native azure/ support,
        # which reads AZURE_API_BASE / AZURE_API_VERSION from the environment.
        # We intentionally keep base_url unset so the model string passes through
        # to LiteLLM unmangled.
        return "azure", None
    if base_url:
        return "openai_compatible", base_url
    if model.startswith("deepseek-"):
        return "openai_compatible", DEEPSEEK_BASE_URL
    if model.startswith("gemini"):
        return "openai_compatible", GEMINI_BASE_URL
    if model.startswith(("gpt-", "o1", "o3", "o4", "text-", "chatgpt-")):
        return "openai", None
    return "anthropic", None


def default_api_key(provider: str, model: str, fallback: Optional[str] = None) -> Optional[str]:
    """Return the conventional API key for a provider/model."""
    if provider == "openai_compatible" and model.startswith("deepseek-"):
        return os.environ.get("DEEPSEEK_API_KEY") or fallback
    if provider == "openai_compatible" and model.startswith("gemini"):
        return os.environ.get("GEMINI_API_KEY") or fallback
    if provider == "azure" or model.startswith("azure/"):
        return (
            os.environ.get("AZURE_API_KEY")
            or os.environ.get("AZURE_OPENAI_API_KEY")
            or fallback
        )
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY") or fallback
    return os.environ.get("ANTHROPIC_API_KEY") or fallback


def target_from_model(
    model: str,
    *,
    target_id: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    fallback_key: Optional[str] = None,
) -> TargetModelConfig:
    """Build a target config from a model name plus optional overrides."""
    provider, inferred_base = infer_provider(model, base_url)
    return TargetModelConfig(
        id=target_id or model.replace("/", "_").replace(":", "_"),
        provider=provider,
        model=model,
        api_key=api_key or default_api_key(provider, model, fallback_key),
        base_url=inferred_base,
    )


def orchestrator_defaults(
    model: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return effective orchestrator API key and base URL."""
    provider, inferred_base = infer_provider(model, base_url)
    effective_base_url = inferred_base if provider == "openai_compatible" else base_url
    return api_key or default_api_key(provider, model), effective_base_url
