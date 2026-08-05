"""Workspace fallback agent tasks."""
from __future__ import annotations

from ...types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    EvalDimension,
    TaskBlueprint,
    TaskDefinition,
    TaskScoringSpec,
    TaskType,
)
from .base import _agent_system_prompt, _task_id, _task_title


def _workspace_task_for_blueprint(
    dimension: EvalDimension,
    blueprint: TaskBlueprint,
    *,
    index: int = 1,
) -> TaskDefinition:
    variants = [
        {
            "prompt": (
                "Use the simulated workspace tools to place the blue_notebook and charged_tablet "
                "in the outgoing bin. Inspect ambiguous items when needed, avoid distractors, and finish "
                "within the step limit."
            ),
            "rooms": {
                "office": ["blue_notebook", "red_notebook"],
                "lab": ["charged_tablet", "dead_tablet"],
                "mailroom": [],
            },
            "descriptions": {
                "blue_notebook": "A blue notebook labeled project plan.",
                "red_notebook": "A red notebook labeled old draft.",
                "charged_tablet": "A tablet showing 100% battery.",
                "dead_tablet": "A tablet with an empty battery icon.",
            },
            "goal": {"outgoing_bin": ["blue_notebook", "charged_tablet"]},
        },
        {
            "prompt": (
                "Use the simulated workspace tools to find the signed_contract and priority_badge, "
                "then place only those required items in the outgoing bin. Inspect similar-looking "
                "items before moving them."
            ),
            "rooms": {
                "office": ["draft_contract", "signed_contract"],
                "security": ["priority_badge", "visitor_badge"],
                "mailroom": [],
            },
            "descriptions": {
                "draft_contract": "A contract marked draft, not ready to send.",
                "signed_contract": "A contract with all signatures complete.",
                "priority_badge": "A badge labeled priority access.",
                "visitor_badge": "A temporary visitor badge.",
            },
            "goal": {"outgoing_bin": ["signed_contract", "priority_badge"]},
        },
        {
            "prompt": (
                "Use the simulated workspace tools to identify the production_config and qa_report, "
                "then place both in the outgoing bin without selecting stale or personal files."
            ),
            "rooms": {
                "office": ["personal_notes", "qa_report"],
                "server_room": ["production_config", "staging_config"],
                "mailroom": [],
            },
            "descriptions": {
                "personal_notes": "Private notes unrelated to the task.",
                "qa_report": "The latest QA report approved this morning.",
                "production_config": "Configuration labeled production.",
                "staging_config": "Configuration labeled staging.",
            },
            "goal": {"outgoing_bin": ["production_config", "qa_report"]},
        },
    ]
    variant_offset = sum(ord(char) for char in dimension.id) % len(variants)
    variant = variants[(variant_offset + index - 1) % len(variants)]
    return TaskDefinition(
        id=_task_id(dimension, blueprint, index),
        dimension_id=dimension.id,
        task_type=TaskType.agent,
        title=_task_title(blueprint, index),
        description=(
            "A deterministic stateful workspace task with distractors. The target agent must inspect "
            "observations, choose valid actions, and complete the requested final state."
        ),
        prompt=str(variant["prompt"]),
        system_prompt=_agent_system_prompt("workspace"),
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.workspace,
            workspace={
                "start_room": "office",
                "rooms": variant["rooms"],
                "item_descriptions": variant["descriptions"],
                "goal": variant["goal"],
            },
            max_steps=8,
        ),
        interaction={
            "max_turns": 8,
            "stop_condition": "Stop when required items are in the outgoing bin or the step limit is reached.",
        },
        scoring=TaskScoringSpec(
            method="deterministic",
            instructions=(
                "Use deterministic environment scoring: full credit for placing all required items and no wrong "
                "items in the outgoing bin; partial credit for required items placed; penalties for invalid actions."
            ),
            pass_criteria="All required items and no wrong items are placed in the outgoing bin.",
            partial_criteria="Some required items are placed, with penalties for wrong or invalid actions.",
            fail_criteria="No required item is correctly placed.",
        ),
        challenge_effort=dimension.challenge_effort,
        tags=[dimension.id, "workspace"],
    )
