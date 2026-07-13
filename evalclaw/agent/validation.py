"""Structural validation for generated agent benchmark tasks."""
from __future__ import annotations

from pathlib import PurePosixPath

from ..protocols.agent_task_package import AGENT_TASK_PACKAGE_METADATA_KEY
from ..types import AgentEnvironmentType, AgentTask, AgentTaskBlueprint, EvalDimension

AGENT_STRUCTURE_VALIDATION_VERSION = "evalclaw.agent_task_structure.v1"
_COMPLETE_PROMPT_ENDINGS = (".", "!", "?", ")", "]", "}", '"', "'")
_DANGLING_PROMPT_ENDINGS = (
    " and",
    " or",
    " to",
    " with",
    " through",
    " across",
    " by",
    " for",
    " from",
    " into",
    " must",
    " must be",
    " must be carried",
    " should",
    " should be",
    " will",
    " will be",
)


def _has_text(value: object) -> bool:
    return bool(str(value or "").strip())


def _has_any_text(*values: object) -> bool:
    return any(_has_text(value) for value in values)


def _prompt_looks_truncated(prompt: str) -> bool:
    stripped = prompt.strip()
    if len(stripped) < 120 or stripped.endswith(_COMPLETE_PROMPT_ENDINGS):
        return False
    lower = stripped.lower()
    last_word = lower.rsplit(maxsplit=1)[-1] if lower.split() else ""
    return len(last_word) <= 2 or lower.endswith(_DANGLING_PROMPT_ENDINGS)


def agent_task_structure_issues(
    task: AgentTask,
    *,
    dimension: EvalDimension | None = None,
    blueprint: AgentTaskBlueprint | None = None,
    require_challenge_effort_self_assessment: bool = False,
) -> list[str]:
    """Return blocking structural issues that should be fixed before global QC.

    This is intentionally narrower than content QC. It checks whether the task
    has the fields needed to materialize and execute the intended environment.
    """
    issues: list[str] = []
    env = task.environment

    visible_paths = set(env.visible_files)
    runtime_paths = set(env.runtime_files)
    hidden_paths = set(env.hidden_files)
    collisions = (visible_paths & runtime_paths) | (visible_paths & hidden_paths) | (runtime_paths & hidden_paths)
    if collisions:
        issues.append(
            "Environment files must belong to exactly one lifecycle phase; duplicate paths: "
            + ", ".join(sorted(collisions))
        )
    setup_text = "\n".join(env.setup_commands)
    if "/tmp/hidden_files" in setup_text:
        issues.append(
            "setup_commands cannot use /tmp/hidden_files; put setup-only assets in runtime_files."
        )
    referenced_hidden = [
        path
        for path in hidden_paths
        if path in setup_text or PurePosixPath(path).name in setup_text
    ]
    if referenced_hidden:
        issues.append(
            "setup_commands reference evaluator-only hidden_files. Move setup assets to runtime_files: "
            + ", ".join(sorted(referenced_hidden))
        )

    if not _has_text(task.id):
        issues.append("Task id is empty.")
    if not _has_text(task.title):
        issues.append("Task title is empty.")
    if not _has_text(task.prompt):
        issues.append("Task prompt is empty.")
    elif _prompt_looks_truncated(task.prompt):
        issues.append("Task prompt appears truncated or ends with an incomplete instruction.")
    if dimension is not None and task.dimension_id != dimension.id:
        issues.append(f"Task dimension_id must be {dimension.id}.")
    if dimension is not None and task.challenge_effort != dimension.challenge_effort:
        issues.append(
            f"Task challenge_effort must be {dimension.challenge_effort.value}; "
            f"got {task.challenge_effort.value}."
        )
    if require_challenge_effort_self_assessment:
        assessment = task.metadata.get("challenge_effort_self_assessment")
        if not isinstance(assessment, dict):
            issues.append(
                "Task metadata.challenge_effort_self_assessment is required for LLM-built tasks."
            )
        else:
            requested = str(assessment.get("requested_effort") or "").strip()
            if dimension is not None and requested and requested != dimension.challenge_effort.value:
                issues.append(
                    "Task metadata.challenge_effort_self_assessment.requested_effort must match "
                    f"{dimension.challenge_effort.value}."
                )
            if assessment.get("meets_requested_effort") is not True:
                issues.append(
                    "Task metadata.challenge_effort_self_assessment.meets_requested_effort must be true; "
                    "revise the task until the builder judges it satisfies the requested challenge effort."
                )
            if not _has_text(assessment.get("rationale")):
                issues.append("Task metadata.challenge_effort_self_assessment.rationale must explain the self-check.")
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
        blueprint_text = ""
        if blueprint is not None:
            blueprint_text = " ".join(
                [
                    blueprint.title,
                    blueprint.description,
                    *blueprint.tool_requirements,
                    *blueprint.construction_requirements,
                ]
            ).lower()
        task_text = f"{task.prompt} {task.description} {' '.join(task.tags)}".lower()
        browser_required = "browser" in blueprint_text or "browser tool" in task_text
        browser_enabled = bool(env.browser.get("enabled"))
        if browser_required and not browser_enabled:
            issues.append(
                "Docker browser tasks must set environment.browser.enabled=true and configure "
                "the executable browser runtime."
            )
        if browser_enabled:
            if str(env.browser.get("runtime") or "") != "playwright_python":
                issues.append("Docker browser runtime must set browser.runtime=playwright_python.")
            if not _has_text(env.browser.get("start_url")):
                issues.append("Docker browser runtime must define browser.start_url.")
            if not isinstance(env.browser.get("allowed_origins"), list) or not env.browser.get("allowed_origins"):
                issues.append("Docker browser runtime must define at least one browser.allowed_origins entry.")
            image_build_enabled = bool(env.image_build.get("enabled"))
            if "playwright" not in env.image.lower() and not image_build_enabled:
                issues.append(
                    "Docker browser runtime requires a Playwright-ready image or enabled image_build."
                )
            if image_build_enabled:
                base_image = str(env.image_build.get("base_image") or "").lower()
                dockerfile = str(env.image_build.get("dockerfile") or "").lower()
                python_packages = {
                    str(package).lower()
                    for package in env.image_build.get("python_packages", [])
                    if str(package).strip()
                }
                system_packages = {
                    str(package).lower()
                    for package in env.image_build.get("system_packages", [])
                    if str(package).strip()
                }
                build_commands = "\n".join(
                    str(command).lower()
                    for command in env.image_build.get("commands", [])
                    if str(command).strip()
                )
                if "playwright" not in base_image and "playwright" not in dockerfile:
                    if not any(package.startswith("playwright") for package in python_packages):
                        issues.append(
                            "Docker browser image_build must install the Python Playwright package."
                        )
                    has_system_browser = any("chromium" in package for package in system_packages)
                    installs_browser_deps = (
                        "playwright install --with-deps" in build_commands
                        or "playwright install-deps" in build_commands
                        or has_system_browser
                    )
                    if not installs_browser_deps:
                        issues.append(
                            "Docker browser image_build must install Chromium OS dependencies via "
                            "a system browser package or playwright install --with-deps/install-deps."
                        )
            if env.tools:
                issues.append(
                    "Docker browser tasks must use EvaluationClaw's canonical browser runtime tools; "
                    "environment.tools cannot define executable browser behavior."
                )
            executable_path = str(env.browser.get("executable_path") or "")
            if any(marker in executable_path for marker in ("*", "?", "[", "]")):
                issues.append("browser.executable_path must be an exact guest path, not a wildcard pattern.")
            if "final_answer tool" in task_text or "final_answer_tool" in task_text:
                issues.append("The canonical completion tool is final; prompts must not name a final_answer tool.")

            package = task.metadata.get(AGENT_TASK_PACKAGE_METADATA_KEY)
            output_contract = package.get("output_contract") if isinstance(package, dict) else None
            expected_artifacts = (
                output_contract.get("expected_artifacts")
                if isinstance(output_contract, dict)
                and isinstance(output_contract.get("expected_artifacts"), list)
                else []
            )
            file_artifacts: list[str] = []
            for artifact in expected_artifacts:
                value = str(artifact or "").strip()
                if not value:
                    continue
                path = PurePosixPath(value)
                if path.is_absolute() or (" " not in value and bool(path.suffix)):
                    file_artifacts.append(value)
            configured_workspace_tools = env.browser.get("workspace_tools")
            workspace_tools = (
                {str(name) for name in configured_workspace_tools}
                if isinstance(configured_workspace_tools, list)
                else set()
            )
            if bool(env.browser.get("allow_workspace_tools")):
                workspace_tools.update({"list_files", "read_file", "write_file", "run_command"})
            if file_artifacts and "write_file" not in workspace_tools:
                issues.append(
                    "Browser tasks with file artifacts must expose write_file through "
                    "browser.workspace_tools."
                )
            workdir = PurePosixPath(env.workdir or "/workspace")
            for artifact in file_artifacts:
                artifact_path = PurePosixPath(artifact)
                if not artifact_path.is_absolute():
                    continue
                try:
                    artifact_path.relative_to(workdir)
                except ValueError:
                    issues.append(
                        f"Browser file artifact {artifact} must be inside environment.workdir={workdir}."
                    )

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
        if not env.workspace:
            issues.append(
                "workspace tasks must include environment.workspace state for the built-in "
                "room/inventory tools; environment.tools does not define executable custom behavior."
            )

    return issues


def agent_structure_validation_metadata(issues: list[str]) -> dict[str, object]:
    return {
        "schema_version": AGENT_STRUCTURE_VALIDATION_VERSION,
        "status": "passed" if not issues else "failed",
        "issues": issues,
    }
