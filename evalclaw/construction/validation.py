"""Structural validation for tasks built by the general constructor."""
from __future__ import annotations

from pathlib import PurePosixPath

from ..protocols.agent_task_package import AGENT_TASK_PACKAGE_METADATA_KEY
from ..types import (
    AgentEnvironmentType,
    EvalDimension,
    TaskBlueprint,
    TaskDefinition,
    TaskDesign,
    TaskType,
)

TASK_STRUCTURE_VALIDATION_VERSION = "evalclaw.task_structure.v1"
CHALLENGE_EFFORT_FIDELITY_METADATA_KEY = "challenge_effort_fidelity"
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


def _has_scoring_guidance(task: TaskDefinition) -> bool:
    return bool(
        _has_any_text(
            task.rubric,
            task.scoring.instructions,
            task.scoring.pass_criteria,
            task.scoring.partial_criteria,
            task.scoring.fail_criteria,
            task.scoring.oracle_notes,
        )
        or task.scoring.score_levels
    )


def _has_environment_evaluator(task: TaskDefinition) -> bool:
    env = task.environment
    if env is None:
        return False
    if env.type in {AgentEnvironmentType.code_sandbox, AgentEnvironmentType.docker_workspace}:
        return _has_text(env.test_command)
    if env.type == AgentEnvironmentType.workspace:
        goal = env.workspace.get("goal") if isinstance(env.workspace, dict) else None
        return isinstance(goal, dict) and bool(goal.get("outgoing_bin"))
    if env.type == AgentEnvironmentType.gui_desktop:
        evaluation = env.evaluation
        return bool(
            isinstance(evaluation.get("checks"), list)
            and evaluation["checks"]
        ) or _has_any_text(
            evaluation.get("method"),
            evaluation.get("evaluator"),
            evaluation.get("command"),
            evaluation.get("pass_criteria"),
            evaluation.get("fail_criteria"),
        )
    return False


def _prompt_looks_truncated(prompt: str) -> bool:
    stripped = prompt.strip()
    if len(stripped) < 120 or stripped.endswith(_COMPLETE_PROMPT_ENDINGS):
        return False
    lower = stripped.lower()
    last_word = lower.rsplit(maxsplit=1)[-1] if lower.split() else ""
    return len(last_word) <= 2 or lower.endswith(_DANGLING_PROMPT_ENDINGS)


def _declared_vm_guest_os(env: object) -> str:
    vm = getattr(env, "vm", {})
    materialization = getattr(env, "vm_materialization", {})
    candidates = []
    if isinstance(materialization, dict):
        candidates.extend((materialization.get("guest_os"), materialization.get("os")))
    if isinstance(vm, dict):
        candidates.extend((vm.get("guest_os"), vm.get("os"), vm.get("os_type"), vm.get("platform")))
    raw = next((str(value).strip().lower() for value in candidates if _has_text(value)), "")
    normalized = raw.replace("_", "-")
    if normalized == "win" or normalized.startswith("windows"):
        return "windows"
    if normalized.startswith("linux") or normalized in {
        "ubuntu",
        "debian",
        "fedora",
        "rhel",
        "centos",
        "alpine",
        "arch",
    }:
        return "linux"
    return raw


def _vm_provisioning_platform_issues(env: object) -> list[str]:
    provisioning = getattr(env, "vm_provisioning", {})
    if not isinstance(provisioning, dict) or not provisioning:
        return []
    guest_os = _declared_vm_guest_os(env)
    windows_fields = {
        "winget_packages",
        "choco_packages",
        "chocolatey_packages",
        "windows_features",
        "powershell_commands",
        "powershell_script",
    }
    linux_fields = {
        "apt_packages",
        "apk_packages",
        "dnf_packages",
        "yum_packages",
        "pacman_packages",
        "snap_packages",
        "cran_packages",
        "r_packages",
        "bioconductor_packages",
        "bioc_packages",
        "julia_packages",
        "conda_packages",
        "cargo_packages",
        "go_packages",
        "gem_packages",
        "ruby_gems",
        "composer_packages",
    }
    used_windows = sorted(key for key in windows_fields if provisioning.get(key))
    used_linux = sorted(key for key in linux_fields if provisioning.get(key))
    raw_steps = (
        provisioning.get("install_steps")
        or provisioning.get("package_manager_steps")
        or provisioning.get("software_install_steps")
    )
    steps = [raw_steps] if isinstance(raw_steps, dict) else raw_steps
    step_managers = {
        str(step.get("manager") or step.get("type") or "").strip().lower().replace("_", "-")
        for step in steps or []
        if isinstance(step, dict)
    }
    linux_step_managers = step_managers & {
        "apt",
        "apt-get",
        "apk",
        "dnf",
        "yum",
        "pacman",
        "snap",
        "cran",
        "bioconductor",
        "julia",
        "conda",
        "cargo",
        "go",
        "gem",
        "composer",
    }
    windows_step_managers = step_managers & {
        "winget",
        "choco",
        "chocolatey",
        "windows-feature",
        "windows-features",
    }
    if guest_os and guest_os not in {"linux", "windows"}:
        return ["VM guest_os must be linux or windows for built-in task materialization."]
    if used_windows and not guest_os:
        return ["Windows VM provisioning fields require vm.guest_os=windows."]
    if guest_os == "windows" and used_linux:
        return [
            "Windows VM provisioning cannot use Linux-only package fields: "
            + ", ".join(used_linux)
            + ". Use winget/choco, Windows features, pip/npm, or PowerShell commands."
        ]
    if guest_os == "windows" and linux_step_managers:
        return [
            "Windows VM provisioning cannot use Linux-only install-step managers: "
            + ", ".join(sorted(linux_step_managers))
            + "."
        ]
    if guest_os == "linux" and used_windows:
        return [
            "Linux VM provisioning cannot use Windows-only fields: " + ", ".join(used_windows) + "."
        ]
    if guest_os == "linux" and windows_step_managers:
        return [
            "Linux VM provisioning cannot use Windows-only install-step managers: "
            + ", ".join(sorted(windows_step_managers))
            + "."
        ]
    return []


def _vm_provisioning_needs_state_check(env: object) -> bool:
    provisioning = getattr(env, "vm_provisioning", {})
    if not isinstance(provisioning, dict):
        return False
    command_fields = (
        "commands",
        "run_commands",
        "bootstrap_commands",
        "runcmd",
        "powershell_commands",
        "powershell_script",
    )
    if any(provisioning.get(key) for key in command_fields):
        return True
    steps = (
        provisioning.get("install_steps")
        or provisioning.get("package_manager_steps")
        or provisioning.get("software_install_steps")
    )
    steps = [steps] if isinstance(steps, dict) else steps
    return any(
        str(step.get("manager") or step.get("type") or "").strip().lower()
        in {"command", "shell", "sh", "bash", "powershell", "pwsh", "ps1"}
        for step in steps or []
        if isinstance(step, dict)
    )


def task_structure_issues(
    task: TaskDefinition,
    *,
    dimension: EvalDimension | None = None,
    blueprint: TaskBlueprint | None = None,
    task_design: TaskDesign | None = None,
    require_challenge_effort_self_assessment: bool = False,
) -> list[str]:
    """Return blocking structural issues that should be fixed before global QC.

    This is intentionally narrower than content QC. It checks whether the task
    has the fields needed for its task type and optional execution capabilities.
    """
    issues: list[str] = []
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
    expected_effort = (
        task_design.challenge_effort
        if task_design is not None
        else (dimension.challenge_effort if dimension is not None else None)
    )
    if expected_effort is not None and task.challenge_effort != expected_effort:
        issues.append(
            f"Task challenge_effort must be {expected_effort.value}; "
            f"got {task.challenge_effort.value}."
        )
    if require_challenge_effort_self_assessment:
        fidelity = task.metadata.get(CHALLENGE_EFFORT_FIDELITY_METADATA_KEY)
        effort_fidelity_uncertain = (
            isinstance(fidelity, dict)
            and fidelity.get("status") == "uncertain"
            and fidelity.get("recovery_strategy") == "reduced_effort_litellm_retry"
        )
        assessment = task.metadata.get("challenge_effort_self_assessment")
        if not isinstance(assessment, dict):
            issues.append(
                "Task metadata.challenge_effort_self_assessment is required for LLM-built tasks."
            )
        else:
            requested = str(assessment.get("requested_effort") or "").strip()
            if expected_effort is not None and requested and requested != expected_effort.value:
                issues.append(
                    "Task metadata.challenge_effort_self_assessment.requested_effort must match "
                    f"{expected_effort.value}."
                )
            if (
                assessment.get("meets_requested_effort") is not True
                and not effort_fidelity_uncertain
            ):
                issues.append(
                    "Task metadata.challenge_effort_self_assessment.meets_requested_effort must be true; "
                    "revise the task until the builder judges it satisfies the requested challenge effort."
                )
            if not _has_text(assessment.get("rationale")):
                issues.append("Task metadata.challenge_effort_self_assessment.rationale must explain the self-check.")

    if task.task_type == TaskType.multiple_choice:
        if len(task.choices) < 2:
            issues.append("multiple_choice tasks must provide at least two choices.")
        if not _has_text(task.answer):
            issues.append("multiple_choice tasks must provide the correct answer.")
    elif task.task_type == TaskType.yes_no and not _has_text(task.answer):
        issues.append("yes_no tasks must provide a reference answer.")
    elif (
        task.task_type == TaskType.short_answer
        and not _has_text(task.answer)
        and not _has_scoring_guidance(task)
    ):
        issues.append("short_answer tasks must provide a reference answer or scoring guidance.")
    elif task.task_type == TaskType.code_execution:
        if not _has_text(task.test_code):
            issues.append("code_execution tasks must provide test_code used by the runner.")
        elif "{model_output}" not in str(task.test_code):
            issues.append("code_execution test_code must consume the response through {model_output}.")
    elif task.task_type == TaskType.pairwise_preference and not _has_scoring_guidance(task):
        issues.append("pairwise_preference tasks must define comparison criteria for the judge.")

    if not _has_scoring_guidance(task) and not _has_any_text(task.answer, task.test_code):
        if not _has_environment_evaluator(task):
            issues.append(
                "Task scoring must define an answer, rubric, executable evaluator, instructions, criteria, "
                "oracle notes, or levels."
            )

    if task.task_type == TaskType.agent_interaction and task.environment is None:
        issues.append("agent_interaction tasks must provide an executable environment.")

    expected_environment = blueprint.environment_type if blueprint is not None else None
    if blueprint is not None:
        if expected_environment is None:
            if task.environment is not None:
                issues.append("Task must omit environment because the blueprint does not request one.")
            return issues
        if task.environment is None:
            issues.append(
                f"Task must provide environment because blueprint.environment_type={expected_environment.value}."
            )
            return issues
    elif task.environment is None:
        return issues
    else:
        expected_environment = task.environment.type

    env = task.environment
    if env.type != expected_environment:
        issues.append(
            f"Task environment.type must match blueprint.environment_type={expected_environment.value}."
        )
    if env.type == AgentEnvironmentType.dialogue and task.task_type != TaskType.multi_turn:
        issues.append("dialogue environments are executable only for multi_turn tasks.")
    if env.type != AgentEnvironmentType.dialogue and task.task_type != TaskType.agent_interaction:
        issues.append(
            f"{env.type.value} environments are executable only for agent_interaction tasks."
        )
    if env.max_steps < 1:
        issues.append("Executable environments must set max_steps to a positive bound.")
    if env.timeout < 1:
        issues.append("Executable environments must set timeout to a positive bound.")
    if env.tools:
        issues.append(
            "environment.tools does not define executable custom behavior; use only tools exposed by "
            "the selected runtime and its structured configuration."
        )

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

    if env.type == AgentEnvironmentType.code_sandbox:
        if not _has_text(env.test_command):
            issues.append("code_sandbox tasks must include a deterministic test_command.")

    elif env.type == AgentEnvironmentType.docker_workspace:
        if not _has_text(env.test_command):
            issues.append("docker_workspace tasks must include a deterministic test_command.")
        task_text = f"{task.prompt} {task.description} {' '.join(task.tags)}".lower()
        browser_enabled = bool(env.browser.get("enabled"))
        planned_designs = (
            [task_design]
            if task_design is not None
            else (blueprint.task_designs if blueprint is not None else [])
        )
        requested_capabilities = [
            str(capability).strip().lower()
            for design in planned_designs
            for capability in (
                list(design.interaction_requirements.get("allowed_action_or_tool_categories", []))
                + list(design.environment_requirements.get("required_capabilities", []))
            )
            if str(capability).strip()
        ]
        browser_required = any("browser" in capability for capability in requested_capabilities)
        if browser_required and not browser_enabled:
            issues.append(
                "TaskDesign requires browser actions, so environment.browser.enabled=true and an "
                "executable browser runtime are required."
            )
        if browser_enabled:
            if str(env.browser.get("runtime") or "") != "playwright_python":
                issues.append("Docker browser runtime must set browser.runtime=playwright_python.")
            if not _has_text(env.browser.get("start_url")):
                issues.append("Docker browser runtime must define browser.start_url.")
            if not isinstance(env.browser.get("allowed_origins"), list) or not env.browser.get("allowed_origins"):
                issues.append("Docker browser runtime must define at least one browser.allowed_origins entry.")
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
        else:
            has_application = _has_any_text(
                env.session.get("application"),
                env.session.get("kind"),
            ) or bool(env.session.get("applications"))
            has_start_state = _has_any_text(
                env.session.get("launch_state"),
                env.session.get("start_state"),
                env.session.get("start_url"),
                env.session.get("entrypoint"),
            )
            if not has_application:
                issues.append("gui_desktop session must identify the application or desktop surface.")
            if not has_start_state:
                issues.append("gui_desktop session must define a launch or start state.")
        if not _has_environment_evaluator(task):
            issues.append("gui_desktop tasks must include an executable evaluation method or checks.")
        if env.requires_vm:
            if not env.vm:
                issues.append("gui_desktop tasks with requires_vm=true must include environment.vm.")
            elif not _has_any_text(
                env.vm.get("template"),
                env.vm.get("template_name"),
                env.vm.get("image"),
                env.vm.get("disk_image"),
                env.vm.get("disk_path"),
            ):
                issues.append(
                    "VM-backed gui_desktop tasks must provide a runner-resolvable template, image, or disk identifier."
                )
            issues.extend(_vm_provisioning_platform_issues(env))
            if _vm_provisioning_needs_state_check(env) and not (
                isinstance(env.session.get("baseline_checks"), list)
                and env.session["baseline_checks"]
            ):
                issues.append(
                    "VM provisioning with state-building commands must define executable "
                    "session.baseline_checks for the bridge to verify before the target starts."
                )

    elif env.type == AgentEnvironmentType.dialogue:
        if not task.interaction:
            issues.append("dialogue tasks must include interaction rules such as max_turns and stop_condition.")
        else:
            try:
                max_turns = int(task.interaction.get("max_turns", 0))
            except (TypeError, ValueError):
                max_turns = 0
            if max_turns < 1:
                issues.append("multi_turn dialogue tasks must define a positive interaction.max_turns.")
            scripted_turns = task.interaction.get("user_turns")
            if not (
                isinstance(scripted_turns, list)
                and any(_has_text(turn) for turn in scripted_turns)
            ) and not _has_text(task.interaction.get("followup_instruction")):
                issues.append(
                    "multi_turn dialogue tasks must provide scripted user_turns or a followup_instruction."
                )
        if any(
            (
                env.visible_files,
                env.runtime_files,
                env.hidden_files,
                env.setup_commands,
                env.test_command,
                env.workspace,
                env.browser,
                env.vm,
                env.requires_vm,
            )
        ):
            issues.append("dialogue environments cannot execute files, setup commands, browser state, or VM state.")

    elif env.type == AgentEnvironmentType.workspace:
        if not env.workspace:
            issues.append(
                "workspace tasks must include environment.workspace state for the built-in "
                "room/inventory tools; environment.tools does not define executable custom behavior."
            )
        else:
            rooms = env.workspace.get("rooms")
            goal = env.workspace.get("goal")
            required_items = goal.get("outgoing_bin") if isinstance(goal, dict) else None
            if not isinstance(rooms, dict) or not rooms:
                issues.append("workspace tasks must define non-empty workspace.rooms.")
            elif "mailroom" not in rooms:
                issues.append("workspace tasks must include a mailroom for the built-in place action.")
            if not isinstance(required_items, list) or not required_items:
                issues.append("workspace tasks must define a non-empty goal.outgoing_bin.")
            elif isinstance(rooms, dict):
                available_items = {
                    str(item)
                    for room_items in rooms.values()
                    if isinstance(room_items, list)
                    for item in room_items
                }
                missing_items = sorted(
                    str(item) for item in required_items if str(item) not in available_items
                )
                if missing_items:
                    issues.append(
                        "workspace goal items must exist in workspace.rooms: "
                        + ", ".join(missing_items)
                    )
        if any(
            (
                env.visible_files,
                env.runtime_files,
                env.hidden_files,
                env.setup_commands,
                env.test_command,
                env.browser,
                env.vm,
                env.requires_vm,
            )
        ):
            issues.append(
                "workspace is the built-in room/inventory runtime and cannot execute files, shell setup, "
                "browser state, or VM state; use code_sandbox, docker_workspace, or gui_desktop instead."
            )

    return issues


def task_structure_validation_metadata(issues: list[str]) -> dict[str, object]:
    return {
        "schema_version": TASK_STRUCTURE_VALIDATION_VERSION,
        "status": "passed" if not issues else "failed",
        "issues": issues,
    }
