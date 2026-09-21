"""Frozen settings for direct frontier-model benchmark authoring."""
import os
import random

from pydantic import Field, model_validator

from ..protocols.task_definition import Contract
from ..types import BenchmarkConfig, TargetModelConfig


class Job(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    goal: str = Field(min_length=1)
    count: int = Field(gt=0)


class Settings(Contract):
    jobs: list[Job] = Field(min_length=1)
    author_model: str = "gpt-6-astra"
    author_base_url: str = "https://api.sudorelay.com/v1"
    author_key_env: str = "FRONTIER_API_KEY"
    author_image: str = "evalclaw-harness-runtime:latest"
    author_effort: str = "high"
    author_workers: int = Field(default=4, gt=0)
    evaluation_workers: int = Field(default=4, gt=0)
    author_timeout_seconds: int = Field(default=5400, gt=0)
    author_memory_gib: int = Field(default=4, gt=0)
    author_cpus: int = Field(default=2, gt=0)
    request_spacing_seconds: float = Field(default=2.1, gt=0)
    key_pools: dict[str, list[str]] = Field(default_factory=dict)
    model_identity_attempts: int = Field(default=3, ge=1)
    gateway_host: str = "10.253.240.1"
    proxy: str | None = "http://127.0.0.1:17891"
    direct_hosts: list[str] = Field(default_factory=list)
    seed: int = 42
    evaluation_key_env: str = "DEEPSEEK_API_KEY"
    evaluation_model: TargetModelConfig
    task_model: TargetModelConfig | None = None
    task_key_env: str = "FRONTIER_API_KEY"
    laaj_model: TargetModelConfig | None = None
    laaj_key_env: str = "FRONTIER_API_KEY"
    contamination_enabled: bool = False
    laaj_sample_size: int | None = Field(default=None, ge=1)
    memory_budget_gib: int = 600
    memory_job_gib: int = 1
    memory_headroom_gib: int = 16

    @model_validator(mode="after")
    def validate_experiment(self):
        if len({j.id for j in self.jobs}) != len(self.jobs):
            raise ValueError("Job IDs must be unique")
        if any(not pool or len(pool) != len(set(pool)) for pool in self.key_pools.values()):
            raise ValueError("Credential pools must contain distinct environment variable names")
        if any(model.api_key for model in (self.evaluation_model, self.task_model, self.laaj_model) if model):
            raise ValueError("Credentials must be supplied through the configured environment variable")
        if self.evaluation_model.supported_message_roles is None:
            raise ValueError("Declare evaluation_model.supported_message_roles before freezing the experiment")
        return self


def seed_everything(seed):
    random.seed(seed)
    # Effective for newly spawned Python processes; launcher sets it before re-exec.
    os.environ["PYTHONHASHSEED"] = str(seed)


def evaluation_config(settings, output, *, credentials=True, bindings=None):
    # Absent auxiliary bindings retain the explicit legacy single-model setting.
    def bind(role, model, key_env):
        update = {"api_key": os.environ[key_env] if credentials else None}
        if credentials and bindings and role in bindings:
            update = bindings[role]
        return model.model_copy(update=update)
    model = bind("target", settings.evaluation_model, settings.evaluation_key_env)
    task = bind("task", settings.task_model or settings.evaluation_model,
                settings.task_key_env if settings.task_model else settings.evaluation_key_env)
    laaj = bind("laaj", settings.laaj_model or settings.evaluation_model,
                settings.laaj_key_env if settings.laaj_model else settings.evaluation_key_env)
    return BenchmarkConfig(seed=settings.seed, targets=[model],
        task_models=[task.model_copy(update={"id": "judge"})],
        actor_model=task.model, actor_provider=task.provider, actor_api_key=task.api_key,
        actor_base_url=task.base_url, actor_extra_body=task.extra_body,
        laaj_model=laaj.model, laaj_provider=laaj.provider, laaj_api_key=laaj.api_key,
        laaj_base_url=laaj.base_url, laaj_extra_body=laaj.extra_body,
        laaj_reasoning_effort=laaj.extra_body.get("reasoning_effort") or laaj.extra_body.get("reasoning", {}).get("effort"),
        contamination_enabled=settings.contamination_enabled, laaj_evaluate_analyser=False,
        runner_max_workers=0, memory_budget_gib=settings.memory_budget_gib,
        memory_job_gib=settings.memory_job_gib, memory_headroom_gib=settings.memory_headroom_gib,
        output_dir=str(output))
