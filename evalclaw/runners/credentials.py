"""Credential checks for runner model calls."""
from __future__ import annotations

import os

from ..types import BenchmarkConfig, TargetModelConfig


def target_config_has_credentials(target: TargetModelConfig) -> tuple[bool, str | None]:
    if target.api_key:
        return True, None
    if target.provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY"
    if target.model.startswith("deepseek-"):
        return bool(os.environ.get("DEEPSEEK_API_KEY")), "DEEPSEEK_API_KEY"
    if target.model.startswith("gemini"):
        return bool(os.environ.get("GEMINI_API_KEY")), "GEMINI_API_KEY"
    if target.provider in {"openai", "openai_compatible"}:
        return bool(os.environ.get("OPENAI_API_KEY")), "OPENAI_API_KEY"
    return True, None


def target_has_credentials(target_id: str, config: BenchmarkConfig) -> tuple[bool, str | None]:
    target = next(target for target in config.targets if target.id == target_id)
    return target_config_has_credentials(target)
