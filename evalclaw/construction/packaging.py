"""Conversion of constructed TaskDefinitions into runner-ready BenchmarkItems."""
from __future__ import annotations

from typing import Any

from ..core.task_summary import TASK_CONTENT_SUMMARY_METADATA_KEY, compact_task_content_summary
from ..execution.docker_browser import docker_browser_tool_specs
from ..execution.docker_images import apply_docker_image_selection
from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_METADATA_KEY,
    AGENT_TASK_PACKAGE_SCHEMA_VERSION,
)
from ..protocols.task_agent import public_task_agent_initial_content
from ..types import (
    AgentEnvironmentType,
    BenchmarkItem,
    BenchmarkSource,
    EvalDimension,
    SourceKind,
    TaskBlueprint,
    TaskDefinition,
    TaskDesign,
    TaskResource,
    TaskType,
)
from .validation import task_structure_issues, task_structure_validation_metadata


def _environment_for_runner(task: TaskDefinition) -> dict[str, Any]:
    if task.environment is None:
        return {}
    env = task.environment.model_dump(mode="json")
    env_type = str(env.get("type") or "workspace")
    env["type"] = env_type
    if env_type == "workspace":
        workspace = env.get("workspace") if isinstance(env.get("workspace"), dict) else {}
        for key in ("start_room", "rooms", "item_descriptions", "goal", "max_steps"):
            if key in workspace and key not in env:
                env[key] = workspace[key]
        if "rooms" not in env:
            env["start_room"] = "office"
            env["rooms"] = {"office": ["blue_notebook"], "mailroom": []}
            env["goal"] = {"outgoing_bin": ["blue_notebook"]}
            env["max_steps"] = env.get("max_steps") or 6
    if env_type == "code_sandbox":
        if not env.get("test_command"):
            env["test_command"] = "python3 tests.py"
        env.pop("workspace", None)
    if env_type == "docker_workspace":
        task_text = "\n".join(
            value
            for value in (
                task.prompt,
                task.description,
                task.scoring.instructions,
                " ".join(task.tags),
            )
            if value
        )
        env, _ = apply_docker_image_selection(env, task_text=task_text)
        if not env.get("test_command"):
            env["test_command"] = "pytest -q"
        env.pop("workspace", None)
    if env_type == "gui_desktop":
        if not isinstance(env.get("session"), dict):
            env["session"] = {}
        if not isinstance(env.get("evaluation"), dict):
            env["evaluation"] = {}
        if not isinstance(env.get("vm"), dict):
            env["vm"] = {}
        env["requires_vm"] = bool(env.get("requires_vm") or env.get("vm"))
        env["max_steps"] = env.get("max_steps") or 24
        env["timeout"] = env.get("timeout") or 30
        env.pop("workspace", None)
    return env


def _task_agent_metadata_for_task(task: TaskDefinition, agent_env: dict[str, Any]) -> dict[str, Any]:
    existing = task.metadata.get("task_agent") if isinstance(task.metadata.get("task_agent"), dict) else {}
    initial_content: dict[str, Any] = {}
    if isinstance(existing.get("initial_content"), dict):
        initial_content.update(public_task_agent_initial_content(existing["initial_content"]))
    if task.description and "scenario" not in initial_content:
        initial_content["scenario"] = task.description
    public_environment = public_task_agent_initial_content(
        {
            key: agent_env[key]
            for key in ("workspace", "visible_files", "image", "session", "vm", "browser", "notes")
            if agent_env.get(key)
        }
    )
    if "visible_files" in public_environment:
        public_environment["files"] = public_environment.pop("visible_files")
    for key, value in public_environment.items():
        initial_content.setdefault(key, value)

    scoring = task.scoring.model_dump(mode="json")
    pass_criteria = scoring.get("pass_criteria") or task.scoring.pass_criteria
    partial_criteria = scoring.get("partial_criteria") or task.scoring.partial_criteria
    fail_criteria = scoring.get("fail_criteria") or task.scoring.fail_criteria
    levels = scoring.get("score_levels") or task.scoring.score_levels
    if not isinstance(levels, dict):
        levels = {}
    levels = {str(key): str(value) for key, value in levels.items()}
    if task.scoring.allows_partial_credit and not levels:
        levels = {"0": "fail", "0.5": "partial", "1": "pass"}
    scoring.update(
        {
            "method": scoring.get("method") or "deterministic",
            "instructions": scoring.get("instructions") or task.description,
            "pass_fail": {
                "pass": pass_criteria,
                "partial": partial_criteria,
                "fail": fail_criteria,
            },
            "levels": levels,
        }
    )
    is_dialogue = task.task_type == TaskType.multi_turn
    metadata = {
        "schema_version": existing.get("schema_version") or "evalclaw.task_agent.v1",
        "agent_role": (
            "dialogue_simulator"
            if is_dialogue
            else existing.get("agent_role") or "target_agent_executor"
        ),
        "system_prompt": task.system_prompt or existing.get("system_prompt") or (
            "You are a task-specific dialogue simulator. Use the transcript to produce the next "
            "user turn and return JSON only."
            if is_dialogue
            else "You are the target agent. Return JSON only."
        ),
        "initial_content": initial_content,
        "interaction": existing.get("interaction") if isinstance(existing.get("interaction"), dict) else task.interaction,
        "scoring": scoring,
        "execution": (
            {"interaction_type": "multi_turn"}
            if is_dialogue
            else {
                "environment_type": agent_env.get("type", task.environment.type.value),
                "environment_ref": "metadata.agent_env",
            }
        ),
    }
    for key, value in existing.items():
        if key not in metadata:
            metadata[key] = value
    return metadata


def _artifact_path(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        path = value.get("path")
        return path.strip() if isinstance(path, str) else ""
    return ""


def _artifact_paths(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(path for value in values if (path := _artifact_path(value))))


def _expected_artifacts(agent_env: dict[str, Any]) -> list[str]:
    artifacts: list[str] = []
    session = agent_env.get("session")
    if isinstance(session, dict):
        artifacts.extend(_artifact_paths(session.get("expected_artifacts")))
    evaluation = agent_env.get("evaluation")
    if isinstance(evaluation, dict):
        artifacts.extend(_artifact_paths(evaluation.get("expected_artifacts")))
    return list(dict.fromkeys(artifacts))


def _artifact_requirement(agent_env: dict[str, Any]) -> str:
    for section_name in ("evaluation", "session"):
        section = agent_env.get(section_name)
        if not isinstance(section, dict):
            continue
        value = str(section.get("artifact_requirement") or "").strip().lower()
        if value in {"all", "any", "exactly_one"}:
            return value
    return "all"


def _required_tools_for_env(agent_env: dict[str, Any]) -> list[str]:
    env_type = str(agent_env.get("type") or "workspace")
    tools = [str(tool.get("name") or tool.get("type") or "") for tool in agent_env.get("tools", []) if isinstance(tool, dict)]
    tools = [tool for tool in tools if tool]
    if tools:
        return tools
    if env_type == "gui_desktop":
        return ["screenshot", "mouse_move", "click", "key", "type", "read_file", "write_file", "run_command", "evaluate"]
    if env_type == "docker_workspace":
        protected_material = bool(agent_env.get("runtime_files") or agent_env.get("hidden_files"))
        browser = agent_env.get("browser")
        if isinstance(browser, dict) and browser.get("enabled"):
            browser_tools = [tool.name for tool in docker_browser_tool_specs()]
            configured_workspace_tools = browser.get("workspace_tools")
            workspace_tools = (
                [str(name) for name in configured_workspace_tools]
                if isinstance(configured_workspace_tools, list)
                else []
            )
            if browser.get("allow_workspace_tools"):
                workspace_tools = ["list_files", "read_file", "write_file", "run_command"]
            if protected_material:
                workspace_tools = [name for name in workspace_tools if name != "run_command"]
            return [*browser_tools, *workspace_tools, "final"]
        workspace_tools = ["list_files", "read_file", "write_file"]
        if not protected_material:
            workspace_tools.append("run_command")
        return [*workspace_tools, "run_tests"]
    if env_type == "code_sandbox":
        return ["read_file", "write_file", "run_tests"]
    return ["look", "move", "inspect", "take", "place", "final"]


def _agent_task_package_for_task(task: TaskDefinition, agent_env: dict[str, Any]) -> dict[str, Any]:
    existing = task.metadata.get(AGENT_TASK_PACKAGE_METADATA_KEY)

    env_type = str(agent_env.get("type") or task.environment.type.value)
    vm = agent_env.get("vm") if isinstance(agent_env.get("vm"), dict) else {}
    session = agent_env.get("session") if isinstance(agent_env.get("session"), dict) else {}
    evaluation = agent_env.get("evaluation") if isinstance(agent_env.get("evaluation"), dict) else {}
    visible_files = agent_env.get("visible_files") if isinstance(agent_env.get("visible_files"), dict) else {}
    runtime_files = agent_env.get("runtime_files") if isinstance(agent_env.get("runtime_files"), dict) else {}
    hidden_files = agent_env.get("hidden_files") if isinstance(agent_env.get("hidden_files"), dict) else {}
    expected_artifacts = _expected_artifacts(agent_env)
    declared_output = (
        task.metadata.get("output_contract")
        if isinstance(task.metadata.get("output_contract"), dict)
        else {}
    )
    if not expected_artifacts:
        declared_artifacts = declared_output.get("expected_artifacts")
        if not isinstance(declared_artifacts, list):
            declared_artifacts = task.metadata.get("expected_artifacts")
        if isinstance(declared_artifacts, list):
            expected_artifacts = _artifact_paths(declared_artifacts)
    artifact_requirement = str(
        declared_output.get("artifact_requirement")
        or task.metadata.get("artifact_requirement")
        or _artifact_requirement(agent_env)
    ).strip().lower()
    if artifact_requirement not in {"all", "any", "exactly_one"}:
        artifact_requirement = "all"
    declared_required_outputs = declared_output.get("required_outputs")
    if not isinstance(declared_required_outputs, list):
        declared_required_outputs = []
    declared_required_outputs = [
        str(value) for value in declared_required_outputs if str(value).strip()
    ]
    if expected_artifacts and artifact_requirement != "all":
        quantifier = "Any one of" if artifact_requirement == "any" else "Exactly one of"
        required_outputs = [f"{quantifier}: " + "; ".join(expected_artifacts)]
    elif expected_artifacts:
        required_outputs = expected_artifacts
    elif declared_required_outputs:
        required_outputs = declared_required_outputs
    else:
        required_outputs = [task.scoring.pass_criteria or "Task-specific completion state."]
    declared_constraints = declared_output.get("constraints")
    if not isinstance(declared_constraints, list):
        declared_constraints = []
    setup_commands = agent_env.get("setup_commands") if isinstance(agent_env.get("setup_commands"), list) else []
    required_software = vm.get("required_software") if isinstance(vm.get("required_software"), list) else []
    vm_requirements = vm.get("requirements") if isinstance(vm.get("requirements"), dict) else {}
    required_capabilities = vm.get("required_capabilities")
    if not isinstance(required_capabilities, list):
        required_capabilities = vm_requirements.get("capabilities")
    required_capabilities = (
        list(dict.fromkeys(str(value) for value in required_capabilities if str(value).strip()))
        if isinstance(required_capabilities, list)
        else []
    )
    if env_type in {"code_sandbox", "docker_workspace"} and agent_env.get("image"):
        required_software = list(dict.fromkeys([*required_software, str(agent_env["image"])]))
    hidden_reference_artifacts = list(expected_artifacts) if env_type == "gui_desktop" else []
    if hidden_files:
        hidden_reference_artifacts.extend(sorted(str(path) for path in hidden_files.keys()))
    if not hidden_reference_artifacts and evaluation:
        hidden_reference_artifacts.append("runner-private evaluation contract")
    declared_os = str(
        vm.get("guest_os")
        or vm.get("os")
        or vm.get("os_type")
        or vm.get("platform")
        or ""
    ).strip().lower()
    if declared_os == "win" or declared_os.startswith("windows"):
        environment_os = "windows"
    elif declared_os.startswith("linux") or declared_os in {
        "ubuntu",
        "debian",
        "fedora",
        "rhel",
        "centos",
        "alpine",
        "arch",
    }:
        environment_os = "linux"
    elif env_type in {"code_sandbox", "docker_workspace"}:
        environment_os = "linux"
    elif declared_os:
        environment_os = declared_os
    else:
        environment_os = "any"

    generated = {
        "schema_version": AGENT_TASK_PACKAGE_SCHEMA_VERSION,
        "style": "executable_agent_task",
        "capability_target": {
            "name": task.title,
            "content_summary": _task_content_summary(task),
            "description": task.description or task.prompt,
            "dimension_id": task.dimension_id,
        },
        "environment_requirements": {
            "environment_ref": "metadata.agent_env",
            "type": env_type,
            "os": environment_os,
            "requires_vm": bool(agent_env.get("requires_vm") or vm),
            "requires_gui": env_type == "gui_desktop",
            "required_software": required_software,
            "required_capabilities": required_capabilities,
            "network": str(agent_env.get("network") or vm.get("network") or "none"),
        },
        "visible_inputs": {
            "instructions": task.prompt,
            "file_names": sorted(str(path) for path in visible_files),
            "assets": session.get("assets", []) if isinstance(session.get("assets"), list) else [],
        },
        "hidden_references": {
            "staging_phase": "post_agent_or_runner_private",
            "file_names": sorted(str(path) for path in hidden_files),
            "runtime_file_names": sorted(str(path) for path in runtime_files),
            "reference_artifacts": list(dict.fromkeys(hidden_reference_artifacts)),
            "notes": "Hidden references and evaluator internals are runner-private and must not be exposed to the target agent.",
        },
        "output_contract": {
            "expected_artifacts": expected_artifacts,
            "artifact_requirement": artifact_requirement,
            "required_outputs": required_outputs,
            "schema": (
                declared_output.get("schema")
                if isinstance(declared_output.get("schema"), dict)
                else {}
            ),
            "constraints": [
                "The final answer or artifacts must be produced inside the configured environment.",
                "Hidden references and evaluator files must not be read by the target agent.",
                *(
                    str(value)
                    for value in declared_constraints
                    if str(value).strip()
                ),
            ],
        },
        "execution": {
            "environment_ref": "metadata.agent_env",
            "setup_command_count": len(setup_commands),
            "run": f"Target agent acts through the EvaluationClaw {env_type} tool environment.",
            "evaluate": str(agent_env.get("test_command") or evaluation.get("method") or task.scoring.method),
            "timeout_s": int(agent_env.get("timeout") or 0),
            "max_steps": int(agent_env.get("max_steps") or task.interaction.get("max_turns") or 0),
        },
        "evaluation": {
            "method": str(evaluation.get("method") or task.scoring.method or "deterministic"),
            "checks": evaluation.get("checks", []) if isinstance(evaluation.get("checks"), list) else [],
            "score_range": [0, 1],
            "pass_criteria": str(evaluation.get("pass_criteria") or task.scoring.pass_criteria),
            "partial_criteria": str(evaluation.get("partial_criteria") or task.scoring.partial_criteria),
            "fail_criteria": str(evaluation.get("fail_criteria") or task.scoring.fail_criteria),
        },
        "artifact_collection": {
            "collect_paths": expected_artifacts,
            "collect_trajectory": True,
            "logs": ["tool_trace", "stdout", "stderr"] + (["screenshots"] if env_type == "gui_desktop" else []),
        },
        "trajectory_requirements": {
            "required_tools": _required_tools_for_env(agent_env),
            "forbidden_shortcuts": [
                "Do not read runner-private hidden references.",
                "Do not bypass the intended GUI/VM/workspace workflow when the task requires it.",
            ],
            "audit_notes": "The saved trajectory should show meaningful environment inspection and task-directed actions.",
        },
        "resource_provenance": {
            "source_kind": "generated_fixture" if not task.resource_ids else "imported",
            "source_uris": list(task.resource_ids),
            "license": "",
            "construction_notes": "Generated or normalized by the EvaluationClaw task builder.",
        },
    }
    if not isinstance(existing, dict):
        return generated
    if existing.get("schema_version") != AGENT_TASK_PACKAGE_SCHEMA_VERSION:
        generated["resource_provenance"]["construction_notes"] = (
            "Generated by EvaluationClaw because the builder supplied an incomplete or invalid "
            "metadata.agent_task_package."
        )
        return generated

    merged = dict(generated)
    for key, value in existing.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        elif value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _task_content_summary(task: TaskDefinition) -> str:
    return compact_task_content_summary(
        task.content_summary,
        task.metadata.get(TASK_CONTENT_SUMMARY_METADATA_KEY) if isinstance(task.metadata, dict) else "",
        task.title,
        task.description,
        task.prompt,
    )


def _resource_source_kind(kind: str) -> SourceKind:
    normalized = str(kind or "").strip().lower()
    if normalized in {"generated_fixture", "self_generated", "synthetic"}:
        return SourceKind.self_generated
    if normalized == "web":
        return SourceKind.web
    if normalized in {"hf_dataset", "dataset"}:
        return SourceKind.hf_dataset
    if normalized == "lm_eval":
        return SourceKind.lm_eval
    return SourceKind.imported


def _has_real_source_uri(uri: str) -> bool:
    normalized = str(uri or "").strip().lower()
    return bool(normalized) and normalized not in {"self_generated", "generated", "none", "n/a"}


def _item_source_for_task(task: TaskDefinition, package: dict[str, Any] | None = None) -> BenchmarkSource:
    package = package or {}
    provenance = package.get("resource_provenance") if isinstance(package.get("resource_provenance"), dict) else {}
    provenance_kind = str(provenance.get("source_kind") or "")
    source_kind = _resource_source_kind(provenance_kind)
    source_uris = [str(uri) for uri in provenance.get("source_uris", []) if _has_real_source_uri(str(uri))]
    if source_kind == SourceKind.self_generated or not source_uris:
        return BenchmarkSource(
            kind=SourceKind.self_generated,
            uri="",
            title=task.title,
            notes=task.description or str(provenance.get("construction_notes") or ""),
        )
    return BenchmarkSource(
        kind=source_kind,
        uri=source_uris[0],
        title=task.title,
        notes=task.description or str(provenance.get("construction_notes") or ""),
    )


def pack_task_item(
    task: TaskDefinition,
    dimension: EvalDimension,
    *,
    resource_by_id: dict[str, TaskResource],
    blueprint: TaskBlueprint | None = None,
    task_design: TaskDesign | None = None,
) -> BenchmarkItem:
    """Convert one constructed TaskDefinition into a runner-ready BenchmarkItem.

    This is the single point where a TaskDefinition (the TaskBuilder's output
    shape) becomes the runnable BenchmarkItem stored in the TaskSuite. It is pure
    code: it attaches structural-validation metadata, a stable content summary,
    a normalized rubric, runtime task_agent/agent_env/agent_task_package metadata
    for interactive tasks, and a standard provenance source. The original
    TaskDefinition is preserved on item.source_definition so repair loops can
    hand it back to the TaskBuilder as previous_tasks.
    """
    metadata = dict(task.metadata)
    validation_blueprint = (
        blueprint.model_copy(
            update={
                "task_design_ids": [task_design.id],
                "task_designs": [task_design],
            }
        )
        if blueprint is not None and task_design is not None
        else blueprint
    )
    structure_issues = task_structure_issues(
        task,
        dimension=dimension,
        blueprint=validation_blueprint,
        task_design=task_design,
    )
    metadata["task_structure_validation"] = task_structure_validation_metadata(structure_issues)
    metadata[TASK_CONTENT_SUMMARY_METADATA_KEY] = _task_content_summary(task)
    metadata.setdefault("builder_job_id", task.metadata.get("builder_job_id") or "")
    task_package: dict[str, Any] | None = None
    if task.task_type == TaskType.multi_turn:
        metadata["task_agent"] = _task_agent_metadata_for_task(task, {})
    elif task.environment is not None:
        agent_env = _environment_for_runner(task)
        metadata["task_agent"] = _task_agent_metadata_for_task(task, agent_env)
        metadata["agent_env"] = agent_env
        task_package = _agent_task_package_for_task(task, agent_env)
        metadata[AGENT_TASK_PACKAGE_METADATA_KEY] = task_package
    item_source = _item_source_for_task(task, task_package)
    if task_package is None and task.resource_ids:
        resource = resource_by_id.get(task.resource_ids[0])
        if resource is not None:
            item_source = BenchmarkSource(
                kind=_resource_source_kind(resource.kind),
                uri=resource.uri if _has_real_source_uri(resource.uri) else "",
                title=resource.title or task.title,
                notes=resource.content_summary,
            )
    return BenchmarkItem(
        id=task.id,
        dimension_id=task.dimension_id,
        task_type=task.task_type,
        prompt=task.prompt,
        assets=task.assets,
        choices=task.choices,
        correct_choice_ids=task.correct_choice_ids,
        expected_text=task.expected_text,
        rubric=task.rubric or task.scoring.instructions or (
            f"{task.scoring.pass_criteria} {task.scoring.partial_criteria} {task.scoring.fail_criteria}".strip()
            or None
        ),
        judge_tools=task.judge_tools,
        output_contract=task.output_contract,
        challenge_effort=task.challenge_effort,
        source=item_source,
        tags=task.tags,
        metadata=metadata,
        source_definition=task,
    )
