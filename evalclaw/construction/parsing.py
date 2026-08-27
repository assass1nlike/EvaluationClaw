"""Parse framework-owned task definitions from Task Builder responses."""
from __future__ import annotations

from typing import Any

from ..core.identifiers import normalize_choice_data, remap_indexed_references
from ..types import (
    AgentEnvironmentSpec,
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


def _environment_from_raw(raw: dict[str, Any]) -> AgentEnvironmentSpec | None:
    if "environment" not in raw or raw["environment"] == {}:
        return None
    environment = raw["environment"]
    if not isinstance(environment, dict):
        raise ValueError("environment must be a JSON object.")
    if "type" not in environment:
        raise ValueError("environment.type is required.")
    return AgentEnvironmentSpec.model_validate(environment)


def _task_from_raw(
    raw: dict[str, Any],
    fallback_id: str,
    *,
    default_dimension_id: str,
    default_task_type: TaskType = TaskType.generation,
) -> TaskDefinition:
    """Normalize Builder content while keeping identity framework-owned."""
    scoring = raw.get("scoring") if isinstance(raw.get("scoring"), dict) else {}
    task_type = TaskType(str(raw.get("task_type") or default_task_type.value))
    choices, correct_choice_ids = _choice_data(raw)
    environment_spec = _environment_from_raw(raw)
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
