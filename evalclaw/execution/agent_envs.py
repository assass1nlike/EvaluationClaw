"""Build executable agent environments."""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from ..protocols.assets import environment_asset_sources
from ..types import BenchmarkConfig, BenchmarkItem
from .desktop_agent_env import DesktopBridgeAgentEnvironment
from .docker_agent_env import DockerWorkspaceAgentEnvironment
from .docker_images import apply_docker_image_selection
from .evaluation import require_valid_evaluator_execution


def _resolve_builder_image_context(
    item: BenchmarkItem,
    env_config: dict[str, Any],
    config: BenchmarkConfig | None,
) -> dict[str, Any]:
    image_build = env_config.get("image_build")
    if not isinstance(image_build, dict):
        return env_config
    context_dir = str(image_build.get("context_dir") or "").strip()
    if not context_dir or Path(context_dir).is_absolute() or config is None:
        return env_config
    builder_job_id = str(item.metadata.get("builder_job_id") or "").strip()
    if not builder_job_id or not str(config.output_dir).strip():
        raise ValueError(
            "A relative image_build.context_dir requires the task's builder_job_id and output_dir."
        )
    safe_job_id = re.sub(r"[^A-Za-z0-9._-]+", "_", builder_job_id).strip("._")
    root = (
        Path(config.output_dir).expanduser().resolve()
        / "assets"
        / "task-builder"
        / (safe_job_id or "task-builder")
    )
    resolved = (root / context_dir).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("image_build.context_dir must stay inside the Builder job directory.")
    updated = dict(env_config)
    updated["image_build"] = {**image_build, "context_dir": str(resolved)}
    return updated


def build_agent_environment(
    item: BenchmarkItem,
    config: BenchmarkConfig | None = None,
) -> DockerWorkspaceAgentEnvironment | DesktopBridgeAgentEnvironment:
    from .evidence import validate_environment_files

    validate_environment_files(item)
    env_config = item.metadata.get("agent_env")
    if not isinstance(env_config, dict):
        raise ValueError("Agent task is missing metadata.agent_env.")
    env_config = copy.deepcopy(env_config)
    if env_config.get("budget"):
        raise ValueError("Episode wall-clock budgets currently require an external shell harness.")
    env_type = str(env_config.get("type") or "docker_workspace")
    if env_config.get("judge"):
        from .agent_judge import judge_spec

        judge_spec(item)
        if config is None:
            raise ValueError("Judge-agent scoring requires BenchmarkConfig.")
    if env_type == "docker_workspace":
        env_config = _resolve_builder_image_context(item, env_config, config)
        task_text = "\n".join(
            value
            for value in (
                item.prompt,
                item.rubric or "",
                " ".join(item.tags),
                str(item.metadata.get("task_agent") or ""),
            )
            if value
        )
        if config is not None and not config.docker_auto_select_image:
            env_config["auto_select_image"] = False
        env_config, _ = apply_docker_image_selection(env_config, task_text=task_text)
        if config is not None:
            env_config.setdefault("pull_timeout", config.docker_pull_timeout_s)
            env_config.setdefault("docker_executable", config.docker_executable)
            image_build = env_config.get("image_build") if isinstance(env_config.get("image_build"), dict) else {}
            env_config["build_timeout"] = max(
                config.docker_build_timeout_s,
                int(env_config.get("build_timeout") or env_config.get("image_build_timeout")
                    or image_build.get("build_timeout") or 0),
            )
    if env_type == "vm" and config is not None:
        requires_vm = bool(env_config.get("requires_vm") or env_config.get("vm"))
        env_config = {
            **env_config,
            "bridge_url": env_config.get("bridge_url") or ("" if requires_vm else config.gui_bridge_url or ""),
            "bridge_api_key": env_config.get("bridge_api_key") or config.gui_bridge_api_key,
            "timeout": env_config.get("timeout") or config.gui_bridge_timeout_s,
            "vm_provider_url": env_config.get("vm_provider_url") or config.vm_provider_url or ("local://auto" if requires_vm else ""),
            "vm_provider_api_key": env_config.get("vm_provider_api_key") or config.vm_provider_api_key,
            "vm_provider_timeout": env_config.get("vm_provider_timeout") or config.vm_provider_timeout_s,
            "destroy_vm_on_cleanup": env_config.get("destroy_vm_on_cleanup", config.vm_provider_destroy_on_cleanup),
        }
    if env_type == "docker_workspace":
        if env_config.get("judge"):
            env_config.update(expose_test_tool=False, auto_evaluate_on_final=False)
        environment = DockerWorkspaceAgentEnvironment.from_config(
            env_config,
            input_assets=environment_asset_sources(item.assets),
        )
        if env_config.get("judge"):
            from .agent_judge import score_with_agent

            def judge(evidence):
                from .evidence import EVALUATOR_EVIDENCE_SCHEMA

                evidence = {"schema_version": EVALUATOR_EVIDENCE_SCHEMA, "item_id": item.id, **evidence}

                def deterministic():
                    details = environment._evaluate_script_with_evidence(evidence)
                    result = environment.last_test
                    require_valid_evaluator_execution(result, environment.evaluation)
                    return environment.score(), details

                score, details = score_with_agent(
                    item, config, environment._container_name, evidence, deterministic,
                    artifact_dir=environment.judge_artifact_dir,
                )
                environment.last_test = {
                    "score": score, "passed": score >= 1, "returncode": 0,
                    "stdout": details, "stderr": "", "evaluator": {
                        "score": score, "passed": score >= 1, "returncode": 0,
                        "structured": True, "source": "judge_agent", "details": details,
                    },
                }
                environment.evaluator_runs.append(environment.last_test.copy())
                return details

            environment.judge_evaluator = judge
        return environment
    if env_type == "vm":
        return DesktopBridgeAgentEnvironment.from_config(env_config)
    raise ValueError(f"Unsupported agent environment type: {env_type}")
