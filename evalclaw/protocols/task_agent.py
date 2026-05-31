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
    "agent_role": "dialogue_simulator | environment_controller | target_agent_executor | judge",
    "system_prompt": "System prompt for the task-specific agent.",
    "initial_content": {
        "scenario": "Initial scenario, state, persona, policy, repository brief, or other task context.",
        "files": {"relative/path.ext": "Initial file content when the task starts from a code/workspace state."},
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
        "environment_type": "dialogue | workspace | code_sandbox",
        "agent_env": "Optional environment config; may mirror metadata.agent_env.",
    },
}

TASK_AGENT_GENERATION_GUIDANCE = """\
For complex interactive items, write a standardized JSON object at
metadata.task_agent using schema_version "evalclaw.task_agent.v1".

Fields:
- agent_role: role of the task-specific agent, such as dialogue_simulator,
  environment_controller, target_agent_executor, or judge.
- system_prompt: concise system prompt for the task-specific agent. It should
  state the evaluation role, non-disclosure rules, and high-level turn policy.
  Do not encode repository files, test suites, command protocols, score tables,
  or large environment state in system_prompt; put those in structured fields.
- initial_content: initial scenario/state. For code or repository tasks, include
  initial files under initial_content.files using relative paths and full file
  contents. Do not use aliases such as file_preview, file_snippets, omitted_files,
  or truncated_files in place of initial_content.files. Do not put secret hidden-test
  answers in visible initial_content.
- interaction: max_turns, optional initial_user_message, optional deterministic
  user_turns, followup_instruction, and stop_condition for multi-turn execution.
- scoring: scoring method plus instructions. For agent_judge, define 1-5 score
  levels. For deterministic or simulated pass/fail tasks, define pass, partial,
  and fail standards.
- execution: environment_type and optional agent_env config. Keep legacy
  metadata.agent_env too for runner compatibility when using workspace or
  code_sandbox. When using a built-in environment, describe the tool/environment
  behavior with structured agent_env fields rather than a long custom command
  protocol in system_prompt.
  For iterative code-repair tasks, prefer environment_type="code_sandbox" with
  metadata.agent_env over a free-form environment_controller dialogue. In those
  tasks, the system_prompt should describe the target model as the coding agent
  who must inspect files, run tests, and revise code. Do not describe the helper
  as the environment itself or as an environment controller.
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
            initial_summary["file_preview"] = {
                name: str(content)[:500] for name, content in list(files.items())[:5]
            }
        for key, value in initial.items():
            if key == "files":
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                initial_summary[key] = value
        if initial_summary:
            compact["initial_content"] = initial_summary
    execution = spec.get("execution")
    if isinstance(execution, dict):
        compact["execution"] = {
            key: value
            for key, value in execution.items()
            if key in {"environment_type", "agent_env"}
        }
    return compact


def transcript_text(history: list[Message]) -> str:
    return "\n\n".join(f"[{message.role.upper()}] {message.content}" for message in history)
