"""Parsing helpers for LLM-built and legacy agent tasks."""
from __future__ import annotations

from typing import Any

from ...types import (
    AgentEnvironmentSpec,
    AgentScoringSpec,
    AgentTask,
    BenchmarkItem,
    safe_challenge_effort,
)
from ..common import _safe_environment_type


def _task_from_raw(raw: dict[str, Any], fallback_id: str, *, default_dimension_id: str) -> AgentTask:
    environment = raw.get("environment") if isinstance(raw.get("environment"), dict) else {}
    scoring = raw.get("scoring") if isinstance(raw.get("scoring"), dict) else {}
    return AgentTask(
        id=str(raw.get("id") or fallback_id),
        dimension_id=str(raw.get("dimension_id") or default_dimension_id),
        title=str(raw.get("title") or fallback_id),
        content_summary=str(raw.get("content_summary") or ""),
        description=str(raw.get("description") or ""),
        prompt=str(raw.get("prompt") or ""),
        system_prompt=str(raw.get("system_prompt") or ""),
        resource_ids=[str(x) for x in raw.get("resource_ids", []) if x],
        environment=AgentEnvironmentSpec(
            type=_safe_environment_type(environment.get("type")),
            tools=[tool for tool in environment.get("tools", []) if isinstance(tool, dict)],
            visible_files={str(path): str(content) for path, content in (environment.get("visible_files") or {}).items()}
            if isinstance(environment.get("visible_files"), dict)
            else {},
            runtime_files={str(path): str(content) for path, content in (environment.get("runtime_files") or {}).items()}
            if isinstance(environment.get("runtime_files"), dict)
            else {},
            hidden_files={str(path): str(content) for path, content in (environment.get("hidden_files") or {}).items()}
            if isinstance(environment.get("hidden_files"), dict)
            else {},
            image=str(environment.get("image") or ""),
            auto_select_image=bool(environment.get("auto_select_image", True)),
            image_selection=environment.get("image_selection") if isinstance(environment.get("image_selection"), dict) else {},
            image_build=environment.get("image_build") if isinstance(environment.get("image_build"), dict) else {},
            pull_image=bool(environment.get("pull_image", True)),
            pull_timeout=max(1, int(environment.get("pull_timeout") or 300)),
            setup_commands=[str(cmd) for cmd in environment.get("setup_commands", []) if str(cmd).strip()]
            if isinstance(environment.get("setup_commands"), list)
            else [],
            test_command=str(environment.get("test_command") or ""),
            max_steps=max(1, int(environment.get("max_steps") or 8)),
            timeout=max(1, int(environment.get("timeout") or 20)),
            network=str(environment.get("network") or "none"),
            resource_limits=environment.get("resource_limits") if isinstance(environment.get("resource_limits"), dict) else {},
            workdir=str(environment.get("workdir") or "/workspace"),
            workspace=environment.get("workspace") if isinstance(environment.get("workspace"), dict) else {},
            browser=environment.get("browser") if isinstance(environment.get("browser"), dict) else {},
            bridge_url=str(environment.get("bridge_url") or ""),
            bridge_api_key=str(environment.get("bridge_api_key") or "").strip() or None,
            requires_vm=bool(environment.get("requires_vm", False)),
            vm_provider_url=str(environment.get("vm_provider_url") or ""),
            vm_provider_api_key=str(environment.get("vm_provider_api_key") or "").strip() or None,
            vm=environment.get("vm") if isinstance(environment.get("vm"), dict) else {},
            vm_materialization=environment.get("vm_materialization")
            if isinstance(environment.get("vm_materialization"), dict)
            else {},
            vm_provisioning=environment.get("vm_provisioning")
            if isinstance(environment.get("vm_provisioning"), dict)
            else {},
            session=environment.get("session") if isinstance(environment.get("session"), dict) else {},
            evaluation=environment.get("evaluation") if isinstance(environment.get("evaluation"), dict) else {},
            notes=str(environment.get("notes") or ""),
        ),
        interaction=raw.get("interaction") if isinstance(raw.get("interaction"), dict) else {},
        scoring=AgentScoringSpec(
            method=str(scoring.get("method") or "deterministic"),
            instructions=str(scoring.get("instructions") or ""),
            pass_criteria=str(scoring.get("pass_criteria") or scoring.get("pass_fail", {}).get("pass") or ""),
            partial_criteria=str(scoring.get("partial_criteria") or scoring.get("pass_fail", {}).get("partial") or ""),
            fail_criteria=str(scoring.get("fail_criteria") or scoring.get("pass_fail", {}).get("fail") or ""),
            score_levels={
                str(key): str(value)
                for key, value in (scoring.get("score_levels") or scoring.get("levels") or {}).items()
            }
            if isinstance(scoring.get("score_levels") or scoring.get("levels"), dict)
            else {},
            oracle_notes=str(scoring.get("oracle_notes") or ""),
        ),
        challenge_effort=safe_challenge_effort(raw.get("challenge_effort")),
        tags=[str(tag) for tag in raw.get("tags", []) if tag],
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def _task_from_item(item: BenchmarkItem, *, title: str) -> AgentTask:
    env = item.metadata.get("agent_env") if isinstance(item.metadata.get("agent_env"), dict) else {}
    task_agent = item.metadata.get("task_agent") if isinstance(item.metadata.get("task_agent"), dict) else {}
    scoring = task_agent.get("scoring") if isinstance(task_agent.get("scoring"), dict) else {}
    pass_fail = scoring.get("pass_fail") if isinstance(scoring.get("pass_fail"), dict) else {}
    env_type = _safe_environment_type(env.get("type"))
    workspace = {
        key: env[key]
        for key in ("start_room", "rooms", "item_descriptions", "goal")
        if key in env
    }
    return AgentTask(
        id=item.id,
        dimension_id=item.dimension_id,
        title=title,
        content_summary=str(item.metadata.get("task_content_summary") or item.source.title or ""),
        description=item.prompt,
        prompt=item.prompt,
        system_prompt=str(task_agent.get("system_prompt") or "You are the target agent. Return JSON only."),
        resource_ids=[],
        environment=AgentEnvironmentSpec(
            type=env_type,
            tools=[tool for tool in env.get("tools", []) if isinstance(tool, dict)]
            if isinstance(env.get("tools"), list)
            else [],
            visible_files={str(k): str(v) for k, v in (env.get("visible_files") or env.get("files") or {}).items()}
            if isinstance(env.get("visible_files") or env.get("files"), dict)
            else {},
            runtime_files={str(k): str(v) for k, v in (env.get("runtime_files") or {}).items()}
            if isinstance(env.get("runtime_files"), dict)
            else {},
            hidden_files={str(k): str(v) for k, v in (env.get("hidden_files") or {}).items()}
            if isinstance(env.get("hidden_files"), dict)
            else {},
            image=str(env.get("image") or ""),
            auto_select_image=bool(env.get("auto_select_image", True)),
            image_selection=env.get("image_selection") if isinstance(env.get("image_selection"), dict) else {},
            image_build=env.get("image_build") if isinstance(env.get("image_build"), dict) else {},
            pull_image=bool(env.get("pull_image", True)),
            pull_timeout=max(1, int(env.get("pull_timeout") or 300)),
            setup_commands=[str(cmd) for cmd in env.get("setup_commands", [])]
            if isinstance(env.get("setup_commands"), list)
            else [],
            test_command=str(env.get("test_command") or ""),
            max_steps=max(1, int(env.get("max_steps") or 8)),
            timeout=max(1, int(env.get("timeout") or 20)),
            network=str(env.get("network") or "none"),
            resource_limits=env.get("resource_limits") if isinstance(env.get("resource_limits"), dict) else {},
            workdir=str(env.get("workdir") or "/workspace"),
            workspace=workspace,
            browser=env.get("browser") if isinstance(env.get("browser"), dict) else {},
            bridge_url=str(env.get("bridge_url") or ""),
            bridge_api_key=str(env.get("bridge_api_key") or "").strip() or None,
            requires_vm=bool(env.get("requires_vm", False)),
            vm_provider_url=str(env.get("vm_provider_url") or ""),
            vm_provider_api_key=str(env.get("vm_provider_api_key") or "").strip() or None,
            vm=env.get("vm") if isinstance(env.get("vm"), dict) else {},
            vm_materialization=env.get("vm_materialization") if isinstance(env.get("vm_materialization"), dict) else {},
            vm_provisioning=env.get("vm_provisioning") if isinstance(env.get("vm_provisioning"), dict) else {},
            session=env.get("session") if isinstance(env.get("session"), dict) else {},
            evaluation=env.get("evaluation") if isinstance(env.get("evaluation"), dict) else {},
            notes="Converted from EvaluationClaw fallback agent item.",
        ),
        interaction=task_agent.get("interaction") if isinstance(task_agent.get("interaction"), dict) else {},
        scoring=AgentScoringSpec(
            method=str(scoring.get("method") or "deterministic"),
            instructions=item.rubric or str(scoring.get("instructions") or ""),
            pass_criteria=str(pass_fail.get("pass") or ""),
            partial_criteria=str(pass_fail.get("partial") or ""),
            fail_criteria=str(pass_fail.get("fail") or ""),
            score_levels={str(k): str(v) for k, v in (scoring.get("levels") or {}).items()}
            if isinstance(scoring.get("levels"), dict)
            else {},
        ),
        challenge_effort=item.challenge_effort,
        tags=item.tags,
        metadata=dict(item.metadata),
    )
