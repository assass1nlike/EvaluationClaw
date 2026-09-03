"""Resolve per-role model settings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..types import BenchmarkConfig, TargetModelConfig

ModelRole = Literal["planner", "task_builder", "qc", "research", "analyser"]


@dataclass(frozen=True)
class RoleModelSettings:
    model: str
    provider: str | None
    api_key: str | None
    base_url: str | None
    reasoning_effort: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def call_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": self.model,
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
        }
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs


def role_model_settings(config: BenchmarkConfig, role: ModelRole) -> RoleModelSettings:
    """Return one role's explicit settings. Each role must be configured individually."""
    return RoleModelSettings(
        model=getattr(config, f"{role}_model"),
        provider=getattr(config, f"{role}_provider"),
        api_key=getattr(config, f"{role}_api_key"),
        base_url=getattr(config, f"{role}_base_url"),
        reasoning_effort=getattr(config, f"{role}_reasoning_effort"),
    )


def _resolve_model_from_list(
    models: list[TargetModelConfig],
    metadata: dict[str, object] | None,
    key: str,
) -> TargetModelConfig | None:
    """Pick the per-task-selected model from a list, falling back to the first entry."""
    if not models:
        return None
    selected_id = str((metadata or {}).get(key) or "").strip()
    if selected_id:
        for model in models:
            if model.id == selected_id:
                return model
    return models[0]


def resolve_task_model(
    config: BenchmarkConfig,
    item: object | None = None,
) -> TargetModelConfig | None:
    """Resolve the per-item task model (judge, dialogue simulator, etc.) from ``config.task_models``."""
    metadata = getattr(item, "metadata", None) if item is not None else None
    return _resolve_model_from_list(config.task_models, metadata, "task_model_id")


__all__ = [
    "ModelRole",
    "RoleModelSettings",
    "resolve_task_model",
    "role_model_settings",
]
