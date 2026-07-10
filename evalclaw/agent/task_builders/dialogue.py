"""Dialogue fallback agent tasks."""
from __future__ import annotations

from ...types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    AgentScoringSpec,
    AgentTask,
    AgentTaskBlueprint,
    EvalDimension,
)
from .base import _task_id, _task_title


def _multi_turn_delegation_task_for_blueprint(
    dimension: EvalDimension,
    blueprint: AgentTaskBlueprint,
    *,
    index: int = 1,
) -> AgentTask:
    return AgentTask(
        id=_task_id(dimension, blueprint.task_family, index),
        dimension_id=dimension.id,
        title=_task_title(blueprint, index),
        description=(
            "A scripted multi-turn delegation task. The target must preserve constraints while adapting to "
            "new user requirements across turns."
        ),
        task_family=blueprint.task_family,
        prompt=(
            "Draft a three-step rollout plan for a documentation migration. Keep it concise and include one "
            "risk mitigation step."
        ),
        system_prompt=(
            "You are a task-specific user simulator for an EvaluationClaw multi-turn evaluation. "
            "Keep follow-up turns concise, reveal only the scripted requirement changes, and return JSON only "
            "when asked for the next turn or score."
        ),
        environment=AgentEnvironmentSpec(type=AgentEnvironmentType.dialogue, max_steps=3),
        interaction={
            "max_turns": 3,
            "initial_user_message": (
                "Draft a three-step rollout plan for a documentation migration. Keep it concise and include "
                "one risk mitigation step."
            ),
            "user_turns": [
                "Revise the plan so the migration has no weekend work.",
                "Now add a rollback trigger, but keep the answer to three steps.",
            ],
            "stop_condition": "Stop after the scripted follow-up turns are answered.",
        },
        scoring=AgentScoringSpec(
            method="agent_judge",
            instructions=(
                "Score the full transcript for constraint tracking across turns: 5 for satisfying the original "
                "plan request, no-weekend revision, rollback trigger, and three-step limit; 3 for one missed "
                "constraint; 1 for ignoring follow-ups or contradicting earlier constraints."
            ),
            pass_criteria="The final answer satisfies all accumulated constraints.",
            partial_criteria="The final answer satisfies the main task but misses one constraint.",
            fail_criteria="The target ignores follow-ups or loses the task objective.",
            score_levels={"5": "complete", "3": "partial", "1": "failed"},
        ),
        difficulty=dimension.target_difficulty,
        tags=[dimension.id, blueprint.task_family.value, "multi_turn"],
    )
