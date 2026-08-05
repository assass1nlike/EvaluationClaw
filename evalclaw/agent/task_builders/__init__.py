"""Fallback implementations for tasks that request interaction environments."""
from __future__ import annotations

from .base import _agent_system_prompt, _task_id, _task_title
from .code import _code_repair_task_for_blueprint, _repo_issue_task_for_blueprint
from .data import _data_analysis_task_for_blueprint
from .gui import _gui_desktop_task_for_blueprint
from .parsing import _task_from_item, _task_from_raw
from .shell import _shell_debugging_task_for_blueprint
from .tools import (
    _api_tool_task_for_blueprint,
    _safety_tool_task_for_blueprint,
    _web_research_task_for_blueprint,
)
from .workspace import _workspace_task_for_blueprint

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
    "_safety_tool_task_for_blueprint",
    "_gui_desktop_task_for_blueprint",
]
