"""Public data contracts for the standalone EvalClaw Harness."""
from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evalclaw.models.providers import infer_provider
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkPlan,
    BenchmarkPlanDimension,
    FailoverEndpoint,
    QcReport,
    ResearchBrief,
    TargetModelConfig,
    TaskDesign,
    TaskSuite,
    utc_now,
)

REQUEST_SCHEMA_VERSION = "evalclaw.harness.request.v1"
RESULT_SCHEMA_VERSION = "evalclaw.harness.result.v1"


def _nonempty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be empty")
    return value


class ModelEndpoint(BaseModel):
    """One explicitly configured model endpoint used during construction."""

    model_config = ConfigDict(extra="forbid")

    model: str
    provider: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    api_key_env: str | None = None
    base_url: str | None = None
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)

    _validate_model = field_validator("model")(_nonempty)

    def resolved_api_key(self) -> str | None:
        if not self.api_key_env:
            return self.api_key
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ValueError(
                f"Model endpoint references unset or empty environment variable {self.api_key_env}."
            )
        return value


class ImageGenerationEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    api_key: str | None = Field(default=None, repr=False)
    api_key_env: str | None = None
    base_url: str

    _validate_model = field_validator("model")(_nonempty)
    _validate_base_url = field_validator("base_url")(_nonempty)

    @model_validator(mode="after")
    def validate_credential(self) -> "ImageGenerationEndpoint":
        if not self.api_key and not self.api_key_env:
            raise ValueError("Image generation requires api_key or api_key_env.")
        return self

    def resolved_api_key(self) -> str | None:
        if not self.api_key_env:
            return self.api_key
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ValueError(
                "Image-generation endpoint references unset or empty environment variable "
                f"{self.api_key_env}."
            )
        return value


class TaskModelEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    model: str
    provider: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    api_key_env: str | None = None
    base_url: str | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)

    _validate_model = field_validator("model")(_nonempty)

    def resolved_api_key(self) -> str | None:
        if not self.api_key_env:
            return self.api_key
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ValueError(
                f"Task model references unset or empty environment variable {self.api_key_env}."
            )
        return value


class HarnessDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    measurement_target: str
    boundary: str
    approach: str
    task_designs: list[TaskDesign] = Field(min_length=1)

    _validate_id = field_validator("id")(_nonempty)
    _validate_name = field_validator("name")(_nonempty)


class HarnessRequest(BaseModel):
    """Planner-independent request accepted by the Harness."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[REQUEST_SCHEMA_VERSION] = REQUEST_SCHEMA_VERSION
    id: str
    objective: str
    constraints: list[str] = Field(default_factory=list)
    dimensions: list[HarnessDimension] = Field(min_length=1)
    research_brief: ResearchBrief | None = None

    _validate_id = field_validator("id")(_nonempty)
    _validate_objective = field_validator("objective")(_nonempty)

    @model_validator(mode="after")
    def validate_ids(self) -> "HarnessRequest":
        dimension_ids = [dimension.id for dimension in self.dimensions]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("Dimension ids must be unique.")
        design_ids = [
            design.id
            for dimension in self.dimensions
            for design in dimension.task_designs
        ]
        if any(not design_id.strip() for design_id in design_ids):
            raise ValueError("TaskDesign ids must not be empty.")
        if len(design_ids) != len(set(design_ids)):
            raise ValueError("TaskDesign ids must be globally unique.")
        return self

    @property
    def planned_task_count(self) -> int:
        return sum(
            design.task_count
            for dimension in self.dimensions
            for design in dimension.task_designs
        )

    def to_plan(self) -> BenchmarkPlan:
        return BenchmarkPlan(
            id=self.id,
            objective=self.objective,
            constraints=self.constraints,
            dimensions=[
                BenchmarkPlanDimension(**dimension.model_dump())
                for dimension in self.dimensions
            ],
        )


class HarnessConfig(BaseModel):
    """Construction and QC settings, excluding planning and model evaluation."""

    model_config = ConfigDict(extra="forbid")

    task_builder: ModelEndpoint
    qc: ModelEndpoint | None = None
    image_generation: ImageGenerationEndpoint | None = None
    task_models: list[TaskModelEndpoint] = Field(default_factory=list)
    failover_endpoint: FailoverEndpoint | None = None
    max_qc_iterations: int = Field(default=5, ge=0)
    max_research_sources: int = Field(default=3, ge=0)
    large_scale_item_threshold: int = Field(default=1000, ge=1)
    large_scale_llm_qc_sample_size: int = Field(default=120, ge=1)
    use_llm_qc: bool = False
    use_web_research: bool = True
    search_backend: Literal["gemini", "ablation-keyless", "auto", "none"] = "gemini"
    task_builder_max_workers: int = Field(default=4, ge=1)
    task_builder_repair_attempts: int = Field(default=4, ge=0)
    task_builder_call_retries: int = Field(default=5, ge=0)
    task_builder_truncation_retries: int = Field(default=3, ge=0)
    task_builder_tool_max_calls: int = Field(default=50, ge=1, le=50)
    task_builder_tool_max_chars: int = Field(default=50_000, ge=1000, le=100_000)
    llm_backend: Literal["auto", "litellm"] = "auto"
    environment_preflight: bool = True
    allow_incomplete_benchmark: bool = False
    strict_qc_filter: bool = False
    docker_auto_select_image: bool = True
    docker_pull_timeout_s: int = Field(default=300, ge=1)
    docker_executable: str = "docker"
    container_sandbox_image: str = "python:3.11-slim"
    gui_bridge_url: str | None = None
    gui_bridge_api_key: str | None = Field(default=None, repr=False)
    vm_provider_url: str | None = None
    vm_provider_api_key: str | None = Field(default=None, repr=False)
    vm_provider_timeout_s: int = Field(default=600, ge=1)
    vm_provider_destroy_on_cleanup: bool = True

    @model_validator(mode="after")
    def validate_qc_endpoint(self) -> "HarnessConfig":
        if self.use_llm_qc and self.qc is None:
            raise ValueError("qc must be configured when use_llm_qc=true.")
        ids = [model.id or model.model.replace("/", "_").replace(":", "_") for model in self.task_models]
        if len(ids) != len(set(ids)):
            raise ValueError("Task model ids must be unique.")
        return self

    def to_benchmark_config(
        self,
        *,
        output_dir: str,
        research_brief: ResearchBrief | None = None,
    ) -> BenchmarkConfig:
        values: dict[str, Any] = {
            "failover_endpoint": self.failover_endpoint,
            "task_models": [self._task_model(model) for model in self.task_models],
            "max_qc_iterations": self.max_qc_iterations,
            "max_research_sources": self.max_research_sources,
            "large_scale_item_threshold": self.large_scale_item_threshold,
            "large_scale_llm_qc_sample_size": self.large_scale_llm_qc_sample_size,
            "use_llm_qc": self.use_llm_qc,
            "use_web_research": self.use_web_research,
            "search_backend": self.search_backend,
            "task_builder_max_workers": self.task_builder_max_workers,
            "task_builder_repair_attempts": self.task_builder_repair_attempts,
            "task_builder_call_retries": self.task_builder_call_retries,
            "task_builder_truncation_retries": self.task_builder_truncation_retries,
            "task_builder_tool_max_calls": self.task_builder_tool_max_calls,
            "task_builder_tool_max_chars": self.task_builder_tool_max_chars,
            "llm_backend": self.llm_backend,
            "environment_preflight": self.environment_preflight,
            "allow_incomplete_benchmark": self.allow_incomplete_benchmark,
            "strict_qc_filter": self.strict_qc_filter,
            "docker_auto_select_image": self.docker_auto_select_image,
            "docker_pull_timeout_s": self.docker_pull_timeout_s,
            "docker_executable": self.docker_executable,
            "container_sandbox_image": self.container_sandbox_image,
            "gui_bridge_url": self.gui_bridge_url,
            "gui_bridge_api_key": self.gui_bridge_api_key,
            "vm_provider_url": self.vm_provider_url,
            "vm_provider_api_key": self.vm_provider_api_key,
            "vm_provider_timeout_s": self.vm_provider_timeout_s,
            "vm_provider_destroy_on_cleanup": self.vm_provider_destroy_on_cleanup,
            "output_dir": output_dir,
            "task_builder_debug_dir": f"{output_dir}/traces/builder",
            "research_brief": research_brief,
            "run_targets": False,
        }
        self._apply_role(values, "task_builder", self.task_builder)
        self._apply_role(values, "qc", self.qc)
        if self.image_generation:
            values.update(
                image_generation_model=self.image_generation.model,
                image_generation_api_key=self.image_generation.resolved_api_key(),
                image_generation_base_url=self.image_generation.base_url,
            )
        return BenchmarkConfig(**values)

    @staticmethod
    def _apply_role(
        values: dict[str, Any],
        role: str,
        endpoint: ModelEndpoint | None,
    ) -> None:
        if endpoint is None:
            return
        values.update(
            {
                f"{role}_model": endpoint.model,
                f"{role}_provider": endpoint.provider,
                f"{role}_api_key": endpoint.resolved_api_key(),
                f"{role}_base_url": endpoint.base_url,
                f"{role}_reasoning_effort": endpoint.reasoning_effort,
                f"{role}_extra_body": endpoint.extra_body,
            }
        )

    @staticmethod
    def _task_model(endpoint: TaskModelEndpoint) -> TargetModelConfig:
        provider, base_url = infer_provider(
            endpoint.model,
            endpoint.base_url,
            endpoint.provider,
        )
        return TargetModelConfig(
            id=endpoint.id,
            provider=provider,
            model=endpoint.model,
            api_key=endpoint.resolved_api_key(),
            base_url=base_url,
            extra_body=endpoint.extra_body,
        )


class HarnessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[RESULT_SCHEMA_VERSION] = RESULT_SCHEMA_VERSION
    operation: Literal["build", "validate"]
    request_id: str
    status: Literal["ready", "incomplete"]
    suite: TaskSuite
    qc_report: QcReport
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


__all__ = [
    "HarnessConfig",
    "HarnessDimension",
    "HarnessRequest",
    "HarnessResult",
    "ImageGenerationEndpoint",
    "ModelEndpoint",
    "TaskModelEndpoint",
]
