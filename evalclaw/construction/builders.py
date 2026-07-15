"""Fallback dispatch for the general task builder."""
from __future__ import annotations

from ..agent.task_builders import (
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
from ..generation.fallback import fallback_items
from ..types import (
    AgentEnvironmentType,
    EvalDimension,
    EvalSpec,
    TaskBlueprint,
    TaskDefinition,
    TaskType,
)


def _fallback_task_for_blueprint(
    spec: EvalSpec,
    dimension: EvalDimension,
    blueprint: TaskBlueprint,
    *,
    index: int = 1,
    task_type: TaskType = TaskType.open_generation,
) -> TaskDefinition:
    if blueprint.environment_type is None:
        item_spec = spec.model_copy(update={"task_types": [task_type]})
        item_dimension = dimension.model_copy(update={"task_types": [task_type]})
        item = fallback_items(item_spec, item_dimension, 1)[0]
        return _task_from_item(item, title=blueprint.title)
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
    raise ValueError(f"Unsupported task environment: {blueprint.environment_type}")

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
