"""Fallback executable task-builder dispatch for agent benchmarks."""
from __future__ import annotations

import uuid

from ..generation.fallback import fallback_items
from ..types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    AgentScoringSpec,
    AgentTask,
    AgentTaskBlueprint,
    EvalDimension,
    EvalSpec,
    TaskType,
)
from .task_builders import (
    _agent_system_prompt,
    _api_tool_task_for_blueprint,
    _code_repair_task_for_blueprint,
    _data_analysis_task_for_blueprint,
    _gui_desktop_task_for_blueprint,
    _multi_turn_delegation_task_for_blueprint,
    _repo_issue_task_for_blueprint,
    _safety_tool_task_for_blueprint,
    _shell_debugging_task_for_blueprint,
    _task_from_item,
    _task_from_raw,
    _task_id,
    _task_title,
    _web_research_task_for_blueprint,
    _workspace_task_for_blueprint,
)


def _fallback_task_for_blueprint(
    spec: EvalSpec,
    dimension: EvalDimension,
    blueprint: AgentTaskBlueprint,
    *,
    index: int = 1,
) -> AgentTask:
    if blueprint.environment_type == AgentEnvironmentType.code_sandbox:
        return _code_repair_task_for_blueprint(dimension, blueprint, index=index)
    if blueprint.environment_type == AgentEnvironmentType.docker_workspace:
        return _shell_debugging_task_for_blueprint(dimension, blueprint, index=index)
    if blueprint.environment_type == AgentEnvironmentType.gui_desktop:
        return _gui_desktop_task_for_blueprint(dimension, blueprint, index=index)
    if blueprint.environment_type == AgentEnvironmentType.dialogue:
        return _multi_turn_delegation_task_for_blueprint(dimension, blueprint, index=index)
    if blueprint.environment_type == AgentEnvironmentType.workspace:
        return _workspace_task_for_blueprint(dimension, blueprint, index=index)
    item_spec = spec.model_copy(update={"task_types": [TaskType.agent_interaction]})
    item_dimension = dimension.model_copy(update={"task_types": [TaskType.agent_interaction]})
    legacy_items = fallback_items(item_spec, item_dimension, 1)
    if legacy_items:
        task = _task_from_item(
            legacy_items[0],
            title=blueprint.title,
        )
        if index > 1:
            task.id = f"{task.id}_{index}"
            task.title = f"{task.title} {index}"
        return task
    return AgentTask(
        id=f"{blueprint.id}_{index}_{uuid.uuid4().hex[:8]}",
        dimension_id=dimension.id,
        title=blueprint.title,
        description=blueprint.description,
        prompt=f"Use the simulated workspace tools to complete this task: {dimension.description}",
        system_prompt="You are the target agent. Return exactly one JSON tool action per turn.",
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.workspace,
            workspace={
                "start_room": "office",
                "rooms": {"office": ["blue_notebook"], "mailroom": []},
                "goal": {"outgoing_bin": ["blue_notebook"]},
            },
            max_steps=6,
        ),
        interaction={"max_turns": 6, "stop_condition": "Stop when the workspace goal is complete."},
        scoring=AgentScoringSpec(
            method="deterministic",
            instructions="Score from the final environment state.",
            pass_criteria="The required item is placed in the outgoing bin.",
            partial_criteria="The agent takes a useful intermediate action.",
            fail_criteria="The agent does not make progress toward the goal.",
        ),
        challenge_effort=dimension.challenge_effort,
        tags=[dimension.id, blueprint.environment_type.value],
    )

__all__ = [
    "_agent_system_prompt",
    "_task_id",
    "_task_title",
    "_task_from_raw",
    "_task_from_item",
    "_workspace_task_for_blueprint",
    "_code_repair_task_for_blueprint",
    "_repo_issue_task_for_blueprint",
    "_shell_debugging_task_for_blueprint",
    "_api_tool_task_for_blueprint",
    "_web_research_task_for_blueprint",
    "_data_analysis_task_for_blueprint",
    "_multi_turn_delegation_task_for_blueprint",
    "_safety_tool_task_for_blueprint",
    "_gui_desktop_task_for_blueprint",
    "_fallback_task_for_blueprint",
]
