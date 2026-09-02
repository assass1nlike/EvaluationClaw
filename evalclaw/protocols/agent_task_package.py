"""Executable agent task package protocol."""
from __future__ import annotations

import copy
from typing import Any

from ..types import BenchmarkItem, TaskType

AGENT_TASK_PACKAGE_SCHEMA_VERSION = "evalclaw.agent_task_package.v1"
AGENT_TASK_PACKAGE_METADATA_KEY = "agent_task_package"

AGENT_TASK_PACKAGE_SCHEMA: dict[str, Any] = {
    "schema_version": AGENT_TASK_PACKAGE_SCHEMA_VERSION,
    "capability_target": {
        "name": "Agent capability being measured.",
        "content_summary": "Short report label.",
        "description": "Behavior tested by the task.",
    },
    "environment_requirements": {
        "environment_ref": "metadata.agent_env",
        "type": "workspace | code_sandbox | docker_workspace | gui_desktop",
        "os": "linux | windows | macos | any",
        "requires_vm": False,
        "requires_gui": False,
        "required_software": ["Runtime or application requirements, without secrets."],
        "required_capabilities": ["Provider image capabilities required at runtime."],
        "network": "none | restricted | internet",
    },
    "visible_inputs": {
        "instructions": "User-visible task instructions.",
        "file_names": ["Paths whose contents live only in metadata.agent_env.visible_files."],
        "assets": ["Public datasets, documents, URLs, images, or project files."],
    },
    "hidden_references": {
        "staging_phase": "evaluation_only",
        "file_names": ["Paths whose contents live only in metadata.agent_env.hidden_files."],
        "runtime_file_names": ["Setup-only paths from metadata.agent_env.runtime_files."],
        "reference_artifacts": ["Runner-private expected outputs or states."],
        "notes": "Never expose evaluator-only material to the target.",
    },
    "output_contract": {
        "expected_artifacts": ["Paths or states the target must produce."],
        "artifact_requirement": "all | any | exactly_one",
        "required_outputs": ["Structured outputs or final states."],
        "schema": {},
        "constraints": ["Format, location, and side-effect constraints."],
    },
    "execution": {
        "environment_ref": "metadata.agent_env",
        "setup_command_count": 0,
        "run": "How the target interacts with the environment.",
        "evaluate": "Evaluator command or bridge method.",
        "timeout_s": 0,
        "max_steps": 0,
    },
    "evaluation": {
        "method": "deterministic | artifact_check | bridge_state_check | judge",
        "checks": ["Named scoring checks."],
        "score_range": [0, 1],
        "pass_criteria": "Full-credit standard.",
        "partial_criteria": "Partial-credit standard.",
        "fail_criteria": "Failure standard.",
    },
    "artifact_collection": {
        "collect_paths": ["Artifacts to retain."],
        "collect_trajectory": True,
        "logs": ["stdout", "stderr", "tool_trace", "screenshots"],
    },
    "trajectory_requirements": {
        "required_tools": ["Tools required by the intended workflow."],
        "forbidden_shortcuts": ["Direct access to protected runtime or evaluator material."],
        "audit_notes": "What the trace should demonstrate.",
    },
    "resource_provenance": {
        "source_kind": "generated_fixture | imported | web | dataset | repo",
        "source_uris": ["https://..."],
        "license": "",
        "construction_notes": "",
    },
}

AGENT_TASK_PACKAGE_GENERATION_GUIDANCE = """\
For executable agent tasks, add metadata.agent_task_package with schema_version
"evalclaw.agent_task_package.v1".

metadata.agent_env is the sole executable environment definition. The package
must reference it with environment_ref="metadata.agent_env" and must not copy
file contents, VM configuration, image-build configuration, browser settings,
setup commands, or hidden evaluator content.

Keep three lifecycle phases distinct:
- visible_files: present before the target starts and available through tools.
- runtime_files: available to setup/runtime but protected from target file tools.
- hidden_files: injected only while the evaluator runs.

Raw shell access must not be exposed when runtime_files or hidden_files are
present, because it would bypass lifecycle protections or leave a background
process waiting for evaluator injection. Use structured workspace tools and the
runner-private evaluator instead.

The package describes capability intent, public input names, private reference
names, output contracts, evaluator semantics, artifact collection, trajectory
requirements, and provenance. Evaluators should write
{"score": 0.0-1.0, "passed": true|false, "details": "..."} to the configured
evaluation.result_path. Numeric score files are valid for simple evaluators.
Target-controlled stdout is not a trusted score source and is ignored by
default; enable evaluation.allow_stdout_score=true only when the evaluator's
stdout cannot be influenced by the target. Define explicit partial-credit
behavior and keep all scores within [0, 1].
"""


def _env_from_item(item: BenchmarkItem) -> dict[str, Any]:
    env = item.metadata.get("agent_env")
    if isinstance(env, dict):
        return env
    return {}


def get_agent_task_package(item: BenchmarkItem) -> dict[str, Any] | None:
    package = item.metadata.get(AGENT_TASK_PACKAGE_METADATA_KEY)
    return package if isinstance(package, dict) else None


def item_requires_agent_task_package(item: BenchmarkItem) -> bool:
    if item.task_type != TaskType.agent:
        return False
    env = _env_from_item(item)
    env_type = str(env.get("type") or "").lower()
    if env_type in {"docker_workspace", "gui_desktop"}:
        return True
    if bool(env.get("requires_vm") or env.get("vm")):
        return True
    tags = {str(tag).lower() for tag in item.tags}
    if tags & {"ale_style", "professional_workflow", "long_horizon", "executable_task_package"}:
        return True
    style = str(item.metadata.get("agent_benchmark_style") or "").lower()
    return style in {"ale", "ale_style", "executable_task_package"}


def _has_visible_inputs(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if str(value.get("instructions") or "").strip():
        return True
    for key in ("file_names", "assets", "resources"):
        child = value.get(key)
        if isinstance(child, (dict, list)) and bool(child):
            return True
    return bool(value.get("session"))


def _has_output_contract(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for key in ("expected_artifacts", "required_outputs", "schema", "constraints"):
        child = value.get(key)
        if isinstance(child, (dict, list)) and bool(child):
            return True
        if isinstance(child, str) and child.strip():
            return True
    return False


def _has_evaluation(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if str(value.get("method") or "").strip():
        return True
    if isinstance(value.get("checks"), list) and value["checks"]:
        return True
    return any(str(value.get(key) or "").strip() for key in ("pass_criteria", "partial_criteria", "fail_criteria"))


def agent_task_package_issues(item: BenchmarkItem) -> list[str]:
    """Return static validation issues for metadata.agent_task_package."""
    package = get_agent_task_package(item)
    required = item_requires_agent_task_package(item)
    if package is None:
        return (
            [
                "Executable agent task is missing metadata.agent_task_package.",
            ]
            if required
            else []
        )

    issues: list[str] = []
    if package.get("schema_version") != AGENT_TASK_PACKAGE_SCHEMA_VERSION:
        issues.append("metadata.agent_task_package schema_version is missing or invalid.")
    capability = package.get("capability_target")
    if not isinstance(capability, dict) or not str(capability.get("name") or capability.get("description") or "").strip():
        issues.append("metadata.agent_task_package.capability_target must name the evaluated capability.")
    if not _has_visible_inputs(package.get("visible_inputs")):
        issues.append("metadata.agent_task_package.visible_inputs must describe visible instructions/files/assets/session.")
    if not _has_output_contract(package.get("output_contract")):
        issues.append("metadata.agent_task_package.output_contract must define expected artifacts, outputs, or schema.")
    if not _has_evaluation(package.get("evaluation")):
        issues.append("metadata.agent_task_package.evaluation must define method, checks, or pass/partial/fail criteria.")

    env = _env_from_item(item)
    env_type = str(env.get("type") or "").lower()
    if env_type in {"docker_workspace", "gui_desktop"}:
        artifact_collection = package.get("artifact_collection")
        if not isinstance(artifact_collection, dict) or not (
            artifact_collection.get("collect_paths") or artifact_collection.get("collect_trajectory")
        ):
            issues.append("Docker/GUI agent task package must define artifact_collection paths or trajectory capture.")
        trajectory = package.get("trajectory_requirements")
        if not isinstance(trajectory, dict) or not trajectory.get("required_tools"):
            issues.append("Docker/GUI agent task package must define trajectory_requirements.required_tools.")

    visible_files = set()
    visible_inputs = package.get("visible_inputs")
    if isinstance(visible_inputs, dict) and isinstance(visible_inputs.get("file_names"), list):
        visible_files = {str(path) for path in visible_inputs["file_names"]}
    hidden_refs = package.get("hidden_references")
    if isinstance(hidden_refs, dict) and isinstance(hidden_refs.get("file_names"), list):
        overlap = visible_files & {str(path) for path in hidden_refs["file_names"]}
        if overlap:
            issues.append(
                "metadata.agent_task_package exposes the same path as visible and evaluator-only: "
                + ", ".join(sorted(overlap)[:5])
            )
    return issues


def public_agent_task_package(package: dict[str, Any]) -> dict[str, Any]:
    """Return a target-visible package summary with hidden references redacted."""
    public = copy.deepcopy(package)
    public.pop("evaluation", None)
    capability = public.get("capability_target")
    if isinstance(capability, dict):
        capability.pop("description", None)
    hidden = public.get("hidden_references")
    if isinstance(hidden, dict):
        redacted = {
            "staging_phase": hidden.get("staging_phase") or "post_agent_or_runner_private",
            "notes": "Hidden references are runner-private and are not exposed to the target agent.",
        }
        if isinstance(hidden.get("file_names"), list):
            redacted["file_count"] = len(hidden["file_names"])
        public["hidden_references"] = redacted
    execution = public.get("execution")
    if isinstance(execution, dict):
        execution.pop("evaluate", None)
    return public


def _compact_text(value: Any, *, limit: int) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return (
        text[:limit].rstrip()
        + "\n[QC summary clipped here; canonical metadata.agent_task_package contains the full field.]"
    )


def compact_agent_task_package(package: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("schema_version", "style"):
        if key in package:
            compact[key] = package[key]
    capability = package.get("capability_target")
    if isinstance(capability, dict):
        compact["capability_target"] = {
            key: _compact_text(value, limit=800)
            for key, value in capability.items()
            if isinstance(value, (str, int, float, bool))
        }
    for key in ("environment_requirements", "output_contract", "evaluation", "artifact_collection", "trajectory_requirements"):
        value = package.get(key)
        if isinstance(value, dict):
            compact[key] = {str(k): v for k, v in list(value.items())[:12]}
    visible = package.get("visible_inputs")
    if isinstance(visible, dict):
        compact_visible: dict[str, Any] = {}
        if "instructions" in visible:
            compact_visible["instructions"] = _compact_text(visible["instructions"], limit=2000)
        files = visible.get("files")
        if isinstance(files, dict):
            compact_visible["file_names"] = list(files.keys())[:20]
            compact_visible["file_count"] = len(files)
        assets = visible.get("assets")
        if isinstance(assets, list):
            compact_visible["assets"] = assets[:20]
        if compact_visible:
            compact["visible_inputs"] = compact_visible
    hidden = package.get("hidden_references")
    if isinstance(hidden, dict):
        compact_hidden: dict[str, Any] = {}
        files = hidden.get("files")
        if isinstance(files, dict):
            compact_hidden["file_names"] = list(files.keys())[:20]
            compact_hidden["file_count"] = len(files)
        refs = hidden.get("reference_artifacts")
        if isinstance(refs, list):
            compact_hidden["reference_artifacts"] = refs[:20]
        if hidden.get("staging_phase"):
            compact_hidden["staging_phase"] = hidden["staging_phase"]
        if compact_hidden:
            compact["hidden_references"] = compact_hidden
    return compact
