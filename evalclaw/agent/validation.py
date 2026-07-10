"""Structural validation for generated agent benchmark tasks."""
from __future__ import annotations

from ..types import AgentEnvironmentType, AgentTask, AgentTaskBlueprint, EvalDimension

AGENT_STRUCTURE_VALIDATION_VERSION = "evalclaw.agent_task_structure.v1"


def _has_text(value: object) -> bool:
    return bool(str(value or "").strip())


def _has_any_text(*values: object) -> bool:
    return any(_has_text(value) for value in values)


def agent_task_structure_issues(
    task: AgentTask,
    *,
    dimension: EvalDimension | None = None,
    blueprint: AgentTaskBlueprint | None = None,
) -> list[str]:
    """Return blocking structural issues that should be fixed before global QC.

    This is intentionally narrower than content QC. It checks whether the task
    has the fields needed to materialize and execute the intended environment.
    """
    issues: list[str] = []
    env = task.environment

    if not _has_text(task.id):
        issues.append("Task id is empty.")
    if not _has_text(task.title):
        issues.append("Task title is empty.")
    if not _has_text(task.prompt):
        issues.append("Task prompt is empty.")
    if dimension is not None and task.dimension_id != dimension.id:
        issues.append(f"Task dimension_id must be {dimension.id}.")
    if blueprint is not None and env.type != blueprint.environment_type:
        issues.append(
            f"Task environment.type must match blueprint.environment_type={blueprint.environment_type.value}."
        )

    if not _has_any_text(
        task.scoring.instructions,
        task.scoring.pass_criteria,
        task.scoring.partial_criteria,
        task.scoring.fail_criteria,
        task.scoring.oracle_notes,
    ) and not task.scoring.score_levels:
        issues.append("Task scoring must define instructions, pass/fail criteria, oracle notes, or score levels.")

    if env.type == AgentEnvironmentType.code_sandbox:
        if not env.visible_files:
            issues.append("code_sandbox tasks must include environment.visible_files.")
        if not env.hidden_files and not _has_text(env.test_command):
            issues.append("code_sandbox tasks must include hidden_files or a deterministic test_command.")

    elif env.type == AgentEnvironmentType.docker_workspace:
        if not (env.visible_files or env.setup_commands or env.image or env.image_build):
            issues.append(
                "docker_workspace tasks must include visible_files, setup_commands, image, or image_build."
            )
        if not _has_text(env.test_command) and not env.evaluation:
            issues.append("docker_workspace tasks must include test_command or environment.evaluation.")

    elif env.type == AgentEnvironmentType.gui_desktop:
        if not env.session:
            issues.append(
                "gui_desktop tasks must include environment.session with application, launch/start state, "
                "input assets, expected artifacts, or task restrictions."
            )
        if not env.evaluation:
            issues.append("gui_desktop tasks must include environment.evaluation with reproducible checks.")
        if env.requires_vm and not env.vm:
            issues.append("gui_desktop tasks with requires_vm=true must include environment.vm.")

    elif env.type == AgentEnvironmentType.dialogue:
        if not task.interaction:
            issues.append("dialogue tasks must include interaction rules such as max_turns and stop_condition.")

    elif env.type == AgentEnvironmentType.workspace:
        if not (env.workspace or env.tools):
            issues.append("workspace tasks must include environment.workspace state or tool definitions.")

    return issues


def agent_structure_validation_metadata(issues: list[str]) -> dict[str, object]:
    return {
        "schema_version": AGENT_STRUCTURE_VALIDATION_VERSION,
        "status": "passed" if not issues else "failed",
        "issues": issues,
    }

