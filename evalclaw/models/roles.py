"""Resolve per-role model settings with orchestrator defaults."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..types import BenchmarkConfig

ModelRole = Literal["planner", "task_builder", "qc", "judge", "research", "loop3"]


@dataclass(frozen=True)
class RoleModelSettings:
    model: str
    provider: str | None
    api_key: str | None
    base_url: str | None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def call_kwargs(self) -> dict[str, str | None]:
        return {
            "model": self.model,
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
        }


def role_model_settings(config: BenchmarkConfig, role: ModelRole) -> RoleModelSettings:
    """Return one role's explicit settings, falling back field-wise to orchestrator."""
    return RoleModelSettings(
        model=getattr(config, f"{role}_model") or config.orchestrator_model,
        provider=getattr(config, f"{role}_provider") or config.orchestrator_provider,
        api_key=getattr(config, f"{role}_api_key") or config.orchestrator_api_key,
        base_url=getattr(config, f"{role}_base_url") or config.orchestrator_base_url,
    )


__all__ = ["ModelRole", "RoleModelSettings", "role_model_settings"]
