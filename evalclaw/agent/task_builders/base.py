"""Shared helpers for fallback agent task builders."""
from __future__ import annotations

import uuid

from ...types import AgentTaskBlueprint, AgentTaskFamily, EvalDimension


def _task_id(dimension: EvalDimension, family: AgentTaskFamily, index: int) -> str:
    return f"{dimension.id}_{family.value}_{index}_{uuid.uuid4().hex[:8]}"


def _task_title(blueprint: AgentTaskBlueprint, index: int) -> str:
    return blueprint.title if index == 1 else f"{blueprint.title} {index}"


def _agent_system_prompt(environment: str) -> str:
    if environment == "code_sandbox":
        return (
            "You are the target model acting as a coding agent in an EvaluationClaw code_sandbox task. "
            "Use exactly one JSON tool action per turn. Inspect files, write complete file contents, "
            "run tests, and revise until the hidden tests pass. Do not invent tools or reveal hidden tests."
        )
    if environment == "docker_workspace":
        return (
            "You are the target model acting as an agent in an EvaluationClaw docker_workspace task. "
            "Use exactly one JSON tool action per turn. Inspect files, run diagnostic commands when useful, "
            "write complete file contents, run the configured tests, and stop only when the task is complete."
        )
    if environment == "gui_desktop":
        return (
            "You are the target model acting as an agent in an EvaluationClaw gui_desktop task. "
            "Use exactly one JSON tool action per turn. Rely on screenshots, mouse, keyboard, file, and "
            "command tools provided by the bridge. Inspect the current UI state before acting, keep the task "
            "state in sync with the bridge session, and finish only when the bridge evaluation says the goal is complete."
        )
    return (
        "You are the target model acting as an agent in an EvaluationClaw simulated workspace. "
        "Use exactly one JSON action per turn. Read observations carefully, inspect ambiguous items "
        "before taking them, and finish only after the goal is complete."
    )
