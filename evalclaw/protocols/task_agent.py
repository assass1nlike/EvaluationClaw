"""Task-level agent specification helpers.

Complex interactive items can provide ``metadata.task_agent`` as a structured
JSON object. The runner uses it to create a task-specific helper agent for
multi-turn simulations, to override target-agent system prompts for simulated
environments, and to pass item-specific scoring guidance to judges.
"""
from __future__ import annotations

import json
from typing import Any

from ..types import BenchmarkConfig, BenchmarkItem, Message

TASK_AGENT_SCHEMA_VERSION = "evalclaw.task_agent.v1"
TASK_AGENT_METADATA_KEY = "task_agent"

TASK_AGENT_SCHEMA: dict[str, Any] = {
    "schema_version": TASK_AGENT_SCHEMA_VERSION,
    "agent_role": "dialogue_simulator | environment_controller | target_agent_executor | judge | api_oracle | research_synthesizer",
    "system_prompt": "System prompt for the task-specific agent.",
    "initial_content": {
        "scenario": "Initial scenario, state, persona, policy, repository brief, or other task context.",
        "files": {"relative/path.ext": "Initial file content when the task starts from a code/workspace state."},
        "session": {
            "application": "GUI/browser/desktop application to launch, when applicable.",
            "start_state": "Initial desktop/browser/software state.",
            "assets": [
                "Input files, URLs, documents, or resources loaded into the session. "
                "Inline file assets may be objects with path/content."
            ],
            "asset_files": {"relative/or/guest/path.ext": "Inline file content to materialize into a VM session."},
            "expected_artifacts": ["Files, page states, or other artifacts expected after completion."],
        },
        "vm": {
            "isolation": "fresh_snapshot | persistent_session | none",
            "image": "VM image/template name, if a VM is required.",
            "snapshot": "Snapshot/reset point to use before the task.",
            "display": {"width": 1280, "height": 900, "scale": 1.0},
            "required_software": ["Desktop applications, browsers, fonts, plugins, or bridge services."],
            "network": "none | restricted | internet",
            "locale": "Locale/language assumptions.",
        },
        "evaluation": {
            "method": "Bridge, deterministic, judge, artifact, or state-check method.",
            "checks": ["Named scoring checks or artifact/state assertions."],
            "pass_criteria": "Full-credit completion standard.",
            "partial_criteria": "Partial-credit standard.",
            "fail_criteria": "Failure standard.",
        },
        "notes": "Any non-secret setup detail needed to run the task.",
    },
    "interaction": {
        "max_turns": 3,
        "initial_user_message": "Optional first user message; defaults to BenchmarkItem.prompt.",
        "user_turns": ["Optional scripted follow-up turns for deterministic multi-turn tasks."],
        "followup_instruction": "How the helper agent should choose the next user turn from the transcript.",
        "stop_condition": "When the helper agent should stop the dialogue.",
    },
    "scoring": {
        "method": "agent_judge | runner_judge | deterministic",
        "instructions": "How to score the transcript or trace.",
        "levels": {
            "5": "Excellent / pass",
            "3": "Partial credit",
            "1": "Fail",
        },
        "pass_fail": {
            "pass": "Full-credit completion standard.",
            "partial": "Partial-credit standard, if applicable.",
            "fail": "Failure standard.",
        },
    },
    "execution": {
        "environment_type": "dialogue | workspace | code_sandbox | docker_workspace | gui_desktop",
        "agent_env": "Optional environment config; may mirror metadata.agent_env.",
    },
    "agent_task_package": "Optional summary pointer; full executable task package should live at metadata.agent_task_package.",
}

TASK_AGENT_GENERATION_GUIDANCE = """\
For complex interactive items, write a standardized JSON object at
metadata.task_agent using schema_version "evalclaw.task_agent.v1".

Fields:
- agent_role: role of the task-specific agent, such as dialogue_simulator,
  environment_controller, target_agent_executor, judge, api_oracle, or
  research_synthesizer.
- system_prompt: concise system prompt for the task-specific agent. It should
  state the evaluation role, non-disclosure rules, and high-level turn policy.
  Do not encode repository files, test suites, command protocols, score tables,
  or large environment state in system_prompt; put those in structured fields.
- initial_content: initial scenario/state. For code or repository tasks, include
  initial files under initial_content.files using relative paths and full file
  contents. Do not use aliases such as file_preview, file_snippets, omitted_files,
  or truncated_files in place of initial_content.files. Do not put secret hidden-test
  answers in visible initial_content. For any task that requires a VM, use
  initial_content.files, metadata.agent_env.visible_files, and/or
  metadata.agent_env.session.asset_files/assets with path/content objects to
  describe task-specific guest files. EvaluationClaw materializes these into a
  per-task cloud-init seed ISO before VM startup when no explicit seed ISO is
  supplied. For GUI/browser/desktop-software tasks,
  include initial_content.session, initial_content.vm, and
  initial_content.evaluation summaries: application/window, start state,
  assets/input files/URLs, expected artifacts, VM isolation/image/snapshot,
  required software/display/network, oracle checks, and pass/partial/fail
  standards.
  For VM-backed tasks that can start from a base OS image, metadata.agent_env may
  include vm_provisioning.enabled=true with apt_packages/system_packages,
  pip_packages/python_packages, snap_packages, cran_packages/r_packages,
  bioconductor_packages/bioc_packages, julia_packages, conda_packages with
  conda_channels, cargo_packages, go_packages, gem_packages,
  composer_packages, apk/dnf/yum/pacman package fields for non-Ubuntu bases,
  install_steps, commands, and optional desktop_bridge_install_command/
  desktop_bridge_start_command. EvaluationClaw writes these into cloud-init so
  the VM installs task software at first boot.
- interaction: max_turns, optional initial_user_message, optional deterministic
  user_turns, followup_instruction, and stop_condition for multi-turn execution.
- scoring: scoring method plus instructions. For agent_judge, define 1-5 score
  levels. For deterministic or simulated pass/fail tasks, define pass, partial,
  and fail standards.
- execution: environment_type and optional agent_env config. Keep legacy
  metadata.agent_env too for runner compatibility when using workspace or
  code_sandbox or docker_workspace. When using a built-in environment, describe the tool/environment
  behavior with structured agent_env fields rather than a long custom command
  protocol in system_prompt.
  For iterative code-repair tasks, prefer environment_type="code_sandbox" with
  metadata.agent_env over a free-form environment_controller dialogue. In those
  tasks, the system_prompt should describe the target model as the coding agent
  who must inspect files, run tests, and revise code. Do not describe the helper
  as the environment itself or as an environment controller.
  Use environment_type="docker_workspace" only when the task needs realistic
  OS dependencies, non-Python runtimes, package installation, command-line
  diagnostics, native builds, or container isolation that the lightweight
  code_sandbox cannot provide. Provide image, visible_files, hidden_files,
  setup_commands, test_command, timeout, and resource_limits in agent_env.
  Choose a common official runtime image when the requirement is clear, or set
  image to "auto" / leave it empty so EvaluationClaw can select a suitable
  Docker image from task files and commands before execution.
  If no common Hub image is sufficient, set image="build://auto" or
  agent_env.image_build.enabled=true. image_build can include base_image,
  system_packages/apt_packages, python_packages/pip_packages,
  node_packages/npm_packages, cran_packages/r_packages,
  bioconductor_packages/bioc_packages, julia_packages, conda_packages with
  conda_channels, cargo_packages, go_packages, gem_packages,
  composer_packages, apk_packages/dnf_packages/yum_packages/pacman_packages,
  install_steps, commands, dockerfile, context_files, tag, rebuild, and
  build_timeout. EvaluationClaw will build a local task image before starting
  the container, then run the workspace in that image.
  Use environment_type="gui_desktop" when the task requires screenshot-driven
  browser or desktop software operation. Provide max_steps, timeout, session,
  evaluation, and usually requires_vm=true plus vm in agent_env. Put task files
  that should exist in the guest under agent_env.visible_files or
  initial_content.files; put session-specific documents/data under
  agent_env.session.asset_files or assets with path/content objects. The session
  should describe application type, launch/start state, assets/input files/URLs,
  and expected artifacts. The vm object should describe image/template,
  snapshot/reset behavior, display, required software, network policy, and
  locale. Optional agent_env.vm_materialization can set guest_user, guest_root,
  enabled=false, or overwrite_seed_iso=true. The evaluation should describe artifact, UI-state, page-state, and
  trace checks with pass/partial/fail criteria. Do not put bridge or VM-provider
  secrets in task metadata; bridge_url, bridge_api_key, vm_provider_url, and
  vm_provider_api_key can be supplied by runtime config.
  For multi-industrial-software collaboration, do not collapse the task into a
  single CAD/EDA/rendering application. Use a VM-backed desktop_software
  agent_env with session.applications, workflow_stages, handoff_artifacts,
  expected_artifacts, and a workflow_manifest.json requirement. Default to a
  reproducible KiCad + FreeCAD + Blender stack when the request does not supply
  licensed software, and make the evaluator check intermediate artifacts,
  final artifacts, units, provenance, and trace evidence of multi-app use. Add
  vm_provisioning package lists or install_steps for kicad/freecad/blender when
  using a clean base image rather than a prebuilt industrial-software template.
  Keep hidden_files secret; the runner injects them only during run_tests.
  For multi-turn delegation tasks, keep the system_prompt focused on the helper
  role and the interaction.turn policy. Store any scripted turns in interaction.
  For API/tool/research/data-analysis tasks, use structured files or tool client
  stubs in initial_content.files rather than embedding large narratives in the
  system prompt.
- For professional, VM-backed, GUI/desktop-software, docker_workspace, or
  long-horizon executable tasks, also provide metadata.agent_task_package using
  schema_version "evalclaw.agent_task_package.v1". metadata.task_agent remains
  the interaction/scoring prompt contract; metadata.agent_task_package is the
  executable package contract with visible inputs, hidden references, output
  contract, setup/run/evaluate steps, artifact collection, trajectory
  requirements, and provenance.
"""


def get_task_agent_spec(item: BenchmarkItem) -> dict[str, Any] | None:
    spec = item.metadata.get(TASK_AGENT_METADATA_KEY)
    return spec if isinstance(spec, dict) else None


def task_agent_initial_user_message(item: BenchmarkItem) -> str:
    spec = get_task_agent_spec(item)
    interaction = spec.get("interaction") if spec else None
    if isinstance(interaction, dict):
        initial = interaction.get("initial_user_message")
        if isinstance(initial, str) and initial.strip():
            return initial.strip()
    return item.prompt


def task_agent_scripted_turns(item: BenchmarkItem) -> list[str]:
    spec = get_task_agent_spec(item)
    interaction = spec.get("interaction") if spec else None
    if isinstance(interaction, dict):
        turns = interaction.get("user_turns")
        if isinstance(turns, list) and all(isinstance(turn, str) for turn in turns):
            return [turn for turn in turns if turn.strip()][:5]
    legacy_turns = item.metadata.get("turns")
    if isinstance(legacy_turns, list) and all(isinstance(turn, str) for turn in legacy_turns):
        return [turn for turn in legacy_turns if turn.strip()][:5]
    return []


def task_agent_max_turns(item: BenchmarkItem, default: int = 3) -> int:
    spec = get_task_agent_spec(item)
    interaction = spec.get("interaction") if spec else None
    if isinstance(interaction, dict):
        try:
            parsed = int(interaction.get("max_turns", default))
        except (TypeError, ValueError):
            parsed = default
        return max(1, min(parsed, 5))
    return default


def task_agent_system_prompt(item: BenchmarkItem, fallback: str) -> str:
    spec = get_task_agent_spec(item)
    system_prompt = spec.get("system_prompt") if spec else None
    return system_prompt.strip() if isinstance(system_prompt, str) and system_prompt.strip() else fallback


def task_agent_scoring(item: BenchmarkItem) -> dict[str, Any]:
    spec = get_task_agent_spec(item)
    scoring = spec.get("scoring") if spec else None
    return scoring if isinstance(scoring, dict) else {}


def task_agent_initial_content_text(item: BenchmarkItem, limit: int = 6000) -> str:
    spec = get_task_agent_spec(item)
    initial = spec.get("initial_content") if spec else None
    if not initial:
        return ""
    if isinstance(initial, str):
        text = initial
    else:
        text = json.dumps(initial, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    half = max(1, limit // 2)
    return text[:half] + "\n...\n" + text[-half:]


def task_agent_model_settings(config: BenchmarkConfig) -> dict[str, str | None]:
    return {
        "model": config.task_agent_model or config.orchestrator_model,
        "api_key": config.task_agent_api_key or config.orchestrator_api_key,
        "base_url": config.task_agent_base_url or config.orchestrator_base_url,
    }


def task_agent_available(config: BenchmarkConfig) -> bool:
    settings = task_agent_model_settings(config)
    return bool(settings["api_key"])


def compact_task_agent_for_qc(spec: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("schema_version", "agent_role", "system_prompt"):
        value = spec.get(key)
        if isinstance(value, str):
            compact[key] = value[:800]
    interaction = spec.get("interaction")
    if isinstance(interaction, dict):
        compact["interaction"] = {
            key: value
            for key, value in interaction.items()
            if key in {"max_turns", "user_turns", "followup_instruction", "stop_condition"}
        }
    scoring = spec.get("scoring")
    if isinstance(scoring, dict):
        compact["scoring"] = {
            key: value
            for key, value in scoring.items()
            if key in {"method", "instructions", "levels", "pass_fail"}
        }
    initial = spec.get("initial_content")
    if isinstance(initial, dict):
        initial_summary: dict[str, Any] = {}
        files = initial.get("files")
        if isinstance(files, dict):
            initial_summary["file_names"] = list(files.keys())[:20]
            initial_summary["file_count"] = len(files)
            initial_summary["file_content_note"] = (
                "Full file contents are omitted from the LLM QC sample to avoid "
                "confusing compact excerpts with task truncation."
            )
        session = initial.get("session")
        if isinstance(session, dict):
            initial_summary["session_keys"] = list(session.keys())[:20]
            for key in ("kind", "application", "entrypoint", "start_url"):
                if key in session:
                    initial_summary[f"session_{key}"] = session[key]
            assets = session.get("assets")
            if isinstance(assets, list):
                initial_summary["session_assets"] = assets[:20]
            expected_artifacts = session.get("expected_artifacts")
            if isinstance(expected_artifacts, list):
                initial_summary["session_expected_artifacts"] = expected_artifacts[:20]
        vm = initial.get("vm")
        if isinstance(vm, dict):
            initial_summary["vm_keys"] = list(vm.keys())[:20]
            for key in ("isolation", "image", "snapshot", "network", "locale"):
                if key in vm:
                    initial_summary[f"vm_{key}"] = vm[key]
            required_software = vm.get("required_software")
            if isinstance(required_software, list):
                initial_summary["vm_required_software"] = required_software[:20]
            display = vm.get("display")
            if isinstance(display, dict):
                initial_summary["vm_display"] = display
        evaluation = initial.get("evaluation")
        if isinstance(evaluation, dict):
            initial_summary["evaluation_keys"] = list(evaluation.keys())[:20]
            for key in ("method", "pass_criteria", "partial_criteria", "fail_criteria"):
                if key in evaluation:
                    initial_summary[f"evaluation_{key}"] = str(evaluation[key])[:800]
        for key, value in initial.items():
            if key == "files":
                continue
            if key in {"session", "vm", "evaluation"}:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                initial_summary[key] = value
        if initial_summary:
            compact["initial_content"] = initial_summary
    execution = spec.get("execution")
    if isinstance(execution, dict):
        compact_execution: dict[str, Any] = {}
        environment_type = execution.get("environment_type")
        if isinstance(environment_type, str):
            compact_execution["environment_type"] = environment_type
        agent_env = execution.get("agent_env")
        if isinstance(agent_env, dict):
            env_summary: dict[str, Any] = {}
            for key in ("type", "max_steps", "test_command", "timeout", "network", "image"):
                if key in agent_env:
                    env_summary[key] = agent_env[key]
            for key in ("visible_files", "files", "hidden_files"):
                files = agent_env.get(key)
                if isinstance(files, dict):
                    env_summary[f"{key}_count"] = len(files)
                    env_summary[f"{key}_names"] = list(files.keys())[:20]
                    env_summary[f"{key}_content_note"] = (
                        "Full file contents are omitted from the LLM QC sample to avoid "
                        "confusing compact excerpts with task truncation."
                    )
            compact_execution["agent_env"] = env_summary
        if compact_execution:
            compact["execution"] = compact_execution
    return compact


def transcript_text(history: list[Message]) -> str:
    return "\n\n".join(f"[{message.role.upper()}] {message.content}" for message in history)
