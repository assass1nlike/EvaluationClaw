"""Parse framework-owned task definitions from Task Builder responses."""
from __future__ import annotations

from typing import Any

from ..core.identifiers import normalize_choice_data, remap_indexed_references
from ..types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    ChoiceOption,
    TaskDefinition,
    TaskScoringSpec,
    TaskType,
    safe_challenge_effort,
)


def _choice_data(raw: dict[str, Any]) -> tuple[list[ChoiceOption], list[str]]:
    choices, correct_ids = normalize_choice_data(
        raw.get("choices"),
        correct_choice_indices=raw.get("correct_choice_indices"),
        correct_choice_ids=raw.get("correct_choice_ids"),
    )
    return [ChoiceOption(**choice) for choice in choices], correct_ids


def _safe_environment_type(
    value: object,
    fallback: AgentEnvironmentType = AgentEnvironmentType.workspace,
) -> AgentEnvironmentType:
    try:
        return AgentEnvironmentType(str(value))
    except ValueError:
        return fallback


def _task_from_raw(
    raw: dict[str, Any],
    fallback_id: str,
    *,
    default_dimension_id: str,
    default_task_type: TaskType = TaskType.generation,
) -> TaskDefinition:
    """Normalize Builder content while keeping identity framework-owned."""
    environment = raw.get("environment") if isinstance(raw.get("environment"), dict) else {}
    scoring = raw.get("scoring") if isinstance(raw.get("scoring"), dict) else {}
    task_type = TaskType(str(raw.get("task_type") or default_task_type.value))
    choices, correct_choice_ids = _choice_data(raw)
    environment_spec = (
        AgentEnvironmentSpec(
            type=_safe_environment_type(environment.get("type")),
            tools=[tool for tool in environment.get("tools", []) if isinstance(tool, dict)],
            visible_files={
                str(path): str(content)
                for path, content in (environment.get("visible_files") or {}).items()
            }
            if isinstance(environment.get("visible_files"), dict)
            else {},
            runtime_files={
                str(path): str(content)
                for path, content in (environment.get("runtime_files") or {}).items()
            }
            if isinstance(environment.get("runtime_files"), dict)
            else {},
            hidden_files={
                str(path): str(content)
                for path, content in (environment.get("hidden_files") or {}).items()
            }
            if isinstance(environment.get("hidden_files"), dict)
            else {},
            image=str(environment.get("image") or ""),
            auto_select_image=bool(environment.get("auto_select_image", True)),
            image_selection=(
                environment.get("image_selection")
                if isinstance(environment.get("image_selection"), dict)
                else {}
            ),
            image_build=(
                environment.get("image_build")
                if isinstance(environment.get("image_build"), dict)
                else {}
            ),
            pull_image=bool(environment.get("pull_image", True)),
            pull_timeout=max(1, int(environment.get("pull_timeout") or 300)),
            setup_commands=[
                str(command)
                for command in environment.get("setup_commands", [])
                if str(command).strip()
            ]
            if isinstance(environment.get("setup_commands"), list)
            else [],
            test_command=str(environment.get("test_command") or ""),
            max_steps=max(1, int(environment.get("max_steps") or 8)),
            timeout=max(1, int(environment.get("timeout") or 20)),
            network=str(environment.get("network") or "none"),
            resource_limits=(
                environment.get("resource_limits")
                if isinstance(environment.get("resource_limits"), dict)
                else {}
            ),
            workdir=str(environment.get("workdir") or "/workspace"),
            workspace=(
                environment.get("workspace")
                if isinstance(environment.get("workspace"), dict)
                else {}
            ),
            browser=(
                environment.get("browser")
                if isinstance(environment.get("browser"), dict)
                else {}
            ),
            bridge_url=str(environment.get("bridge_url") or ""),
            bridge_api_key=str(environment.get("bridge_api_key") or "").strip() or None,
            requires_vm=bool(environment.get("requires_vm", False)),
            vm_provider_url=str(environment.get("vm_provider_url") or ""),
            vm_provider_api_key=(
                str(environment.get("vm_provider_api_key") or "").strip() or None
            ),
            vm=environment.get("vm") if isinstance(environment.get("vm"), dict) else {},
            vm_materialization=(
                environment.get("vm_materialization")
                if isinstance(environment.get("vm_materialization"), dict)
                else {}
            ),
            vm_provisioning=(
                environment.get("vm_provisioning")
                if isinstance(environment.get("vm_provisioning"), dict)
                else {}
            ),
            session=(
                environment.get("session")
                if isinstance(environment.get("session"), dict)
                else {}
            ),
            evaluation=(
                environment.get("evaluation")
                if isinstance(environment.get("evaluation"), dict)
                else {}
            ),
            notes=str(environment.get("notes") or ""),
        )
        if environment
        else None
    )
    pass_fail = scoring.get("pass_fail") if isinstance(scoring.get("pass_fail"), dict) else {}
    levels = scoring.get("score_levels") or scoring.get("levels")
    return TaskDefinition(
        id=fallback_id,
        dimension_id=default_dimension_id,
        task_type=task_type,
        title=str(raw.get("title") or fallback_id),
        content_summary=str(raw.get("content_summary") or ""),
        description=str(raw.get("description") or ""),
        prompt=str(raw.get("prompt") or ""),
        assets=raw.get("assets", []),
        choices=choices,
        correct_choice_ids=correct_choice_ids,
        expected_text=(
            str(raw["expected_text"]) if raw.get("expected_text") is not None else None
        ),
        rubric=str(raw["rubric"]) if raw.get("rubric") is not None else None,
        judge_tools=[
            value for value in raw.get("judge_tools", []) if isinstance(value, dict)
        ]
        if isinstance(raw.get("judge_tools"), list)
        else [],
        output_contract=(
            raw.get("output_contract")
            if isinstance(raw.get("output_contract"), dict)
            else {}
        ),
        system_prompt=str(raw.get("system_prompt") or ""),
        resource_ids=remap_indexed_references(raw.get("resource_ids"), {}),
        environment=environment_spec,
        interaction=(
            raw.get("interaction") if isinstance(raw.get("interaction"), dict) else {}
        ),
        scoring=TaskScoringSpec(
            method=str(scoring.get("method") or "deterministic"),
            instructions=str(scoring.get("instructions") or ""),
            pass_criteria=str(scoring.get("pass_criteria") or pass_fail.get("pass") or ""),
            partial_criteria=str(
                scoring.get("partial_criteria") or pass_fail.get("partial") or ""
            ),
            fail_criteria=str(scoring.get("fail_criteria") or pass_fail.get("fail") or ""),
            allows_partial_credit=bool(scoring.get("allows_partial_credit", False)),
            score_levels=(
                {str(key): str(value) for key, value in levels.items()}
                if isinstance(levels, dict)
                else {}
            ),
        ),
        challenge_effort=safe_challenge_effort(raw.get("challenge_effort")),
        tags=[str(tag) for tag in raw.get("tags", []) if tag],
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


__all__ = ["_task_from_raw"]
