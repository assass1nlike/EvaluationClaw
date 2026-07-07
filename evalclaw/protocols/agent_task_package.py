"""ALE-style executable agent task package protocol."""
from __future__ import annotations

import copy
from typing import Any

from ..types import BenchmarkItem, TaskType
from .task_agent import TASK_AGENT_METADATA_KEY

AGENT_TASK_PACKAGE_SCHEMA_VERSION = "evalclaw.agent_task_package.v1"
AGENT_TASK_PACKAGE_METADATA_KEY = "agent_task_package"

AGENT_TASK_PACKAGE_SCHEMA: dict[str, Any] = {
    "schema_version": AGENT_TASK_PACKAGE_SCHEMA_VERSION,
    "style": "ale_executable_task",
    "capability_target": {
        "name": "Agent capability being measured, not a one-off task title.",
        "description": "What behavior this task is intended to test.",
    },
    "environment_requirements": {
        "type": "workspace | code_sandbox | docker_workspace | gui_desktop",
        "os": "linux | windows | macos | any",
        "requires_vm": False,
        "requires_gui": False,
        "required_software": ["Runtime, desktop app, browser, bridge, plugin, or package requirements."],
        "network": "none | restricted | internet",
        "resource_limits": {},
        "vm_provisioning": {
            "enabled": False,
            "strategy": "cloud_init.v1",
            "apt_packages": ["Ubuntu apt packages to install at VM first boot."],
            "pip_packages": ["Python packages to install at VM first boot."],
            "snap_packages": ["Snap packages to install at VM first boot."],
            "cran_packages": ["R/CRAN packages to install at VM first boot."],
            "bioconductor_packages": ["Bioconductor packages to install at VM first boot."],
            "julia_packages": ["Julia packages to install at VM first boot."],
            "conda_packages": ["Conda/mamba packages to install when the VM has conda/mamba/micromamba."],
            "cargo_packages": ["Rust cargo-install packages to install at VM first boot."],
            "go_packages": ["Go package specs such as module/cmd@version to install at VM first boot."],
            "gem_packages": ["Ruby gems to install at VM first boot."],
            "composer_packages": ["Composer packages to install globally at VM first boot."],
            "install_steps": [
                {
                    "manager": "apt | pip | snap | cran | bioconductor | julia | conda | cargo | go | gem | composer | apk | dnf | yum | pacman | shell",
                    "packages": ["Package specs for the selected manager."],
                    "command": "Shell command for manager=shell or custom setup.",
                }
            ],
            "commands": ["Additional guest shell commands for software setup or bridge startup."],
            "desktop_bridge_install_command": "Optional command to install the desktop bridge inside the guest.",
            "desktop_bridge_start_command": "Optional command to start the desktop bridge inside the guest.",
        },
        "image_build": {
            "enabled": False,
            "base_image": "Common base image, for example python:3.11-slim or ubuntu:22.04.",
            "system_packages": ["apt packages to install in the task image."],
            "python_packages": ["pip packages to install in the task image."],
            "node_packages": ["global npm packages to install in the task image."],
            "cran_packages": ["R/CRAN packages to install."],
            "bioconductor_packages": ["Bioconductor packages to install."],
            "julia_packages": ["Julia packages to install."],
            "conda_packages": ["Conda/mamba packages to install when the base image has conda/mamba/micromamba."],
            "cargo_packages": ["Rust cargo-install packages."],
            "go_packages": ["Go package specs such as module/cmd@version."],
            "gem_packages": ["Ruby gems to install."],
            "composer_packages": ["Composer packages to install globally."],
            "install_steps": [
                {
                    "manager": "apt | pip | npm | cran | bioconductor | julia | conda | cargo | go | gem | composer | apk | dnf | yum | pacman | shell",
                    "packages": ["Package specs for the selected manager."],
                    "command": "Shell command for manager=shell or custom setup.",
                }
            ],
            "commands": ["Additional Dockerfile RUN commands."],
            "dockerfile": "Complete custom Dockerfile content when package lists are insufficient.",
            "context_files": {"relative/build/path": "Build-time file content."},
            "tag": "Optional local image tag.",
            "rebuild": False,
        },
    },
    "visible_inputs": {
        "instructions": "User-visible task instructions.",
        "files": {"relative/or/guest/path.ext": "Full visible file content."},
        "assets": [
            "Visible datasets, documents, URLs, images, videos, project files, or inline path/content asset objects."
        ],
        "session": "Public GUI/browser/VM session state when applicable.",
    },
    "hidden_references": {
        "staging_phase": "post_agent_or_runner_private",
        "files": {"relative/private/path.ext": "Hidden reference or evaluator content."},
        "reference_artifacts": ["Hidden expected files, outputs, checksums, or reference states."],
        "notes": "Do not expose to the target agent.",
    },
    "output_contract": {
        "expected_artifacts": ["Paths or state values the target must produce."],
        "required_outputs": ["Structured outputs, final states, commands, or GUI artifacts."],
        "schema": {},
        "constraints": ["Format, location, reproducibility, and side-effect constraints."],
    },
    "execution": {
        "setup": ["Commands or bridge actions to prepare visible state."],
        "run": "How the target agent interacts with the task.",
        "evaluate": "Command, bridge evaluator, deterministic checker, or judge process.",
        "timeout_s": 0,
        "max_steps": 0,
    },
    "evaluation": {
        "method": "deterministic | artifact_check | bridge_state_check | judge",
        "checks": ["Named scoring checks with weights or exact assertions."],
        "score_range": [0, 1],
        "pass_criteria": "Full-credit standard.",
        "partial_criteria": "Partial-credit standard.",
        "fail_criteria": "Failure standard.",
    },
    "artifact_collection": {
        "collect_paths": ["Files, directories, logs, renders, notebooks, or exported artifacts to save."],
        "collect_trajectory": True,
        "logs": ["stdout", "stderr", "tool_trace", "screenshots"],
    },
    "trajectory_requirements": {
        "required_tools": ["read_file", "write_file", "run_command"],
        "forbidden_shortcuts": ["Direct access to hidden references or evaluator internals."],
        "audit_notes": "What the trace should prove about the agent's process.",
    },
    "resource_provenance": {
        "source_kind": "generated_fixture | imported | web | dataset | repo",
        "source_uris": ["https://..."],
        "license": "",
        "construction_notes": "",
    },
}

AGENT_TASK_PACKAGE_GENERATION_GUIDANCE = """\
For ALE-style executable agent tasks, add metadata.agent_task_package with
schema_version "evalclaw.agent_task_package.v1".

Use this package when a task is a professional workflow, long-horizon agent
task, docker_workspace task, GUI/browser/desktop-software task, VM-backed task,
or any task whose quality depends on executable setup, artifacts, hidden
references, and deterministic evaluation.

The package complements metadata.task_agent:
- metadata.task_agent defines the task-specific agent role, interaction rules,
  initial context summary, and scoring guidance.
- metadata.agent_task_package defines the executable task package: visible
  inputs, hidden references, output contract, setup/run/evaluate process,
  artifact collection, trajectory requirements, environment/software
  requirements, and provenance.

Package requirements:
- Keep visible_inputs and hidden_references separate. The target agent may see
  visible_inputs, but hidden_references are runner-private and should be staged
  only after the agent finishes or kept under a private evaluator path.
- Provide a concrete output_contract. Name expected files, exported artifacts,
  final GUI/page states, JSON schemas, numerical outputs, or other checkable
  products.
- Provide execution.setup, execution.run, and execution.evaluate at the right
  level of abstraction for the environment. For GUI/VM tasks, run/evaluate may
  point to a desktop bridge evaluator instead of a shell command.
- Provide evaluation.method, checks, and pass/partial/fail criteria. Prefer
  deterministic artifact/state checks; use judge scoring only for inherently
  subjective artifacts and still define score levels.
- Make evaluation reproducible. If a check uses pHash, SSIM, audio
  fingerprinting, ffprobe metadata, numerical tolerance, schema validation, or
  text/RCA matching, state the algorithm or tool, input paths, expected values,
  thresholds/tolerances, and partial-credit computation explicitly. Do not put
  concrete thresholds only in one field while leaving scoring.pass_criteria or
  pass_fail vague.
- Provide artifact_collection and trajectory_requirements so the runner can
  save outputs, logs, screenshots, command traces, and evidence that the agent
  used the intended tools rather than shortcuts.
- For proprietary or specialized software, put software/licensing assumptions
  in environment_requirements. Do not embed secrets or local provider URLs.
- For docker_workspace tasks where no common Hub image is sufficient, set
  environment_requirements.image_build and metadata.agent_env.image_build with
  enabled=true. Prefer base_image plus package lists for ordinary dependencies:
  apt/system, pip/python, npm/node, CRAN/R, Bioconductor, Julia, Conda,
  Cargo, Go, Ruby gems, Composer, apk/dnf/yum/pacman, and install_steps.
  Include required language/runtime system packages or choose a suitable
  base_image when a package manager is not present by default. Use dockerfile
  only when the package-list form cannot express the setup.
- For VM-backed tasks where a base OS image exists but task software is not yet
  installed, set environment_requirements.vm_provisioning and
  metadata.agent_env.vm_provisioning. EvaluationClaw can write apt/system,
  pip/python, snap, CRAN/R, Bioconductor, Julia, Conda, Cargo, Go, Ruby gems,
  Composer, apk/dnf/yum/pacman package fields, install_steps, setup commands,
  and desktop bridge commands into the per-task cloud-init seed ISO. This can
  install tools such as KiCad, FreeCAD, Blender, R/Julia analytics stacks,
  scientific CLIs, and other open/installable software at first boot when the
  image supports cloud-init.
"""


def _env_from_item(item: BenchmarkItem) -> dict[str, Any]:
    env = item.metadata.get("agent_env")
    if isinstance(env, dict):
        return env
    task_agent = item.metadata.get(TASK_AGENT_METADATA_KEY)
    if isinstance(task_agent, dict):
        execution = task_agent.get("execution")
        if isinstance(execution, dict):
            agent_env = execution.get("agent_env")
            if isinstance(agent_env, dict):
                return agent_env
    return {}


def get_agent_task_package(item: BenchmarkItem) -> dict[str, Any] | None:
    package = item.metadata.get(AGENT_TASK_PACKAGE_METADATA_KEY)
    return package if isinstance(package, dict) else None


def item_requires_agent_task_package(item: BenchmarkItem) -> bool:
    if item.task_type != TaskType.agent_interaction:
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
    for key in ("files", "assets", "resources"):
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


def _has_hidden_reference(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for key in ("files", "reference_artifacts", "checksums", "evaluator"):
        child = value.get(key)
        if isinstance(child, (dict, list)) and bool(child):
            return True
        if isinstance(child, str) and child.strip():
            return True
    return bool(str(value.get("notes") or "").strip())


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
                "ALE-style executable agent task is missing metadata.agent_task_package.",
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
    if required and not _has_hidden_reference(package.get("hidden_references")):
        issues.append("ALE-style executable task package must include runner-private hidden_references or evaluator notes.")
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
    if isinstance(visible_inputs, dict) and isinstance(visible_inputs.get("files"), dict):
        visible_files = {str(path) for path in visible_inputs["files"]}
    hidden_refs = package.get("hidden_references")
    if isinstance(hidden_refs, dict) and isinstance(hidden_refs.get("files"), dict):
        overlap = visible_files & {str(path) for path in hidden_refs["files"]}
        if overlap:
            issues.append(
                "metadata.agent_task_package exposes the same file path in visible_inputs.files and hidden_references.files: "
                + ", ".join(sorted(overlap)[:5])
            )
    return issues


def public_agent_task_package(package: dict[str, Any]) -> dict[str, Any]:
    """Return a target-visible package summary with hidden references redacted."""
    public = copy.deepcopy(package)
    hidden = public.get("hidden_references")
    if isinstance(hidden, dict):
        redacted = {
            "staging_phase": hidden.get("staging_phase") or "post_agent_or_runner_private",
            "reference_artifacts": hidden.get("reference_artifacts", []),
            "notes": "Hidden references are runner-private and are not exposed to the target agent.",
        }
        if isinstance(hidden.get("files"), dict):
            redacted["file_names"] = sorted(str(path) for path in hidden["files"].keys())
            redacted["file_count"] = len(hidden["files"])
        public["hidden_references"] = redacted
    return public


def compact_agent_task_package(package: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("schema_version", "style"):
        if key in package:
            compact[key] = package[key]
    capability = package.get("capability_target")
    if isinstance(capability, dict):
        compact["capability_target"] = {
            key: str(value)[:800]
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
            compact_visible["instructions"] = str(visible["instructions"])[:800]
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
