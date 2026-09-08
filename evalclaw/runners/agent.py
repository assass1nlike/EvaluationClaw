"""Agent-interaction runner logic."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..diagnostics import error_record, write_json
from ..execution.agent_envs import build_agent_environment
from ..models.llm import (
    TargetToolModelResponse,
    call_target_model,
    call_target_model_with_tools,
    extract_json,
)
from ..protocols.task_agent import task_agent_initial_content_text, task_agent_system_prompt
from ..protocols.tool import (
    TOOL_PROTOCOL_VERSION,
    ToolCall,
    ToolResult,
    action_to_tool_call,
    tool_call_to_action,
    validate_tool_call,
)
from ..protocols.tool_adapters import (
    evalclaw_tool_result_to_anthropic,
    evalclaw_tool_result_to_openai,
    tool_adapter_for_target,
)
from ..types import BenchmarkConfig, BenchmarkItem, Message, TargetModelConfig


def parse_agent_action(response: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = extract_json(response)
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            parsed = parsed[0]
        if isinstance(parsed, dict):
            if "action" not in parsed and "tool" not in parsed:
                if "path" in parsed and "content" in parsed:
                    return {
                        "action": "write_file",
                        "args": {"path": parsed.get("path"), "content": parsed.get("content")},
                    }, None
                if "path" in parsed:
                    return {"action": "read_file", "args": {"path": parsed.get("path")}}, None
                if "answer" in parsed:
                    return {"action": "final", "args": {"answer": parsed.get("answer")}}, None
            if "action" not in parsed and "tool" in parsed:
                parsed["action"] = parsed["tool"]
            if "args" not in parsed:
                parsed["args"] = {
                    key: value
                    for key, value in parsed.items()
                    if key not in {"action", "tool", "thought", "reasoning"}
                }
            return parsed, None
    except Exception:
        pass

    stripped = response.strip()
    simple = re.search(
        r"\b(look|move|inspect|take|place|list_files|read_file|write_file|run_tests|run_test|"
        r"run_command|screenshot|cursor_position|key|key_down|key_up|type|hold_key|"
        r"mouse_move|click|drag|mouse_down|mouse_up|scroll|wait|evaluate|final)\b"
        r"\s*:?\s*([^\n\r{}]*)?",
        stripped,
        re.I,
    )
    if simple:
        action = simple.group(1).lower()
        value = (simple.group(2) or "").strip(" .")
        if action == "move":
            key = "room"
        elif action in {"read_file", "write_file", "list_files", "screenshot"}:
            key = "path"
        elif action in {"type", "key", "run_command"}:
            key = "text" if action == "type" else "keys" if action == "key" else "command"
        elif action in {"wait"}:
            key = "seconds"
        else:
            key = "item"
        args = {} if action in {"look", "final", "screenshot", "cursor_position", "evaluate"} or not value else {key: value}
        if action in {"key", "key_down", "key_up"} and value:
            args = {"keys": [part for part in re.split(r"[,+]", value) if part]}
        if action == "hold_key" and value:
            parts = [part for part in re.split(r"[,+]", value) if part]
            args = {"keys": parts}
        if action in {"click", "mouse_move"} and value:
            numbers = [float(part) for part in re.findall(r"-?\d+(?:\.\d+)?", value)]
            if len(numbers) >= 2:
                args = {"x": numbers[0], "y": numbers[1]}
        if action == "drag" and value:
            numbers = [float(part) for part in re.findall(r"-?\d+(?:\.\d+)?", value)]
            if len(numbers) >= 4:
                args = {"x1": numbers[0], "y1": numbers[1], "x2": numbers[2], "y2": numbers[3]}
        if action == "wait" and value:
            match = re.search(r"-?\d+(?:\.\d+)?", value)
            if match:
                args = {"seconds": float(match.group(0))}
        if action in {"list_files", "run_tests", "run_test"} and not value:
            args = {}
        if action == "final" and value:
            args = {"answer": stripped}
        return {"action": action, "args": args}, None
    return None, "Could not parse an agent action. Expected a JSON object with action and args."


def _initial_user_prompt(item: BenchmarkItem, env: Any, *, include_action_schema: bool) -> str:
    initial_content = task_agent_initial_content_text(item)
    initial_block = f"\n\nInitial task content:\n{initial_content}\n" if initial_content else ""
    prompt = (
        f"Task:\n{item.prompt}\n\n"
        f"{initial_block}"
        f"Initial observation:\n{env.observation()}"
    )
    if include_action_schema:
        prompt += f"\n\n{env.action_schema()}"
    else:
        prompt += "\n\nUse the provided native tools to inspect and modify the environment. Call final when the task is complete."
    return prompt


def _native_system_prompt(system_prompt: str) -> str:
    return (
        f"{system_prompt}\n\n"
        "Native tool protocol override: the API request exposes the valid tools as native tool definitions. "
        "Use those native tool calls instead of writing JSON actions in message text. "
        "Call exactly one environment tool at a time when possible, wait for the tool result, and call final when done."
    )


def _execute_tool_call(
    env: Any,
    tool_specs: list[Any],
    tool_call: ToolCall,
) -> tuple[dict[str, Any], ToolResult, str, str | None, bool]:
    validation_errors = validate_tool_call(tool_call, tool_specs)
    if validation_errors:
        env.invalid_actions += 1
        env.steps += 1
        error = " ".join(validation_errors)
        observation = f"Error: {error}\n\n{env.observation()}"
        done = env.steps >= env.max_steps
        env.done = done
        tool_result = ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            content=observation,
            error=error,
        )
    else:
        outcome = env.step(tool_call_to_action(tool_call))
        observation = outcome.observation
        done = outcome.done
        error = outcome.error
        tool_result = ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            content=observation,
            error=error,
        )
    return tool_call_to_action(tool_call), tool_result, observation, error, done


def _native_tool_result_messages(adapter: str, results: list[ToolResult]) -> list[dict[str, Any]]:
    if adapter == "anthropic":
        return [{"role": "user", "content": [evalclaw_tool_result_to_anthropic(result) for result in results]}]
    return [evalclaw_tool_result_to_openai(result) for result in results]


def _save_environment_artifacts(env: Any, artifact_dir: Path | None) -> None:
    if artifact_dir is None:
        return
    try:
        write_json(artifact_dir / "environment-state.json", env.state())
        export = getattr(env, "export_artifacts", None)
        if callable(export):
            write_json(artifact_dir / "artifacts.json", export(artifact_dir))
    except Exception as exc:
        write_json(artifact_dir / "artifact-error.json", error_record(exc))


def _save_interaction_progress(
    artifact_dir: Path | None,
    trace: list[dict[str, Any]],
    env: Any,
) -> None:
    if artifact_dir is not None:
        write_json(
            artifact_dir / "interaction.json",
            {"trace": trace, "current_state": env.state()},
        )


def _run_agent_interaction_native_tools(
    item: BenchmarkItem,
    target: TargetModelConfig,
    config: BenchmarkConfig,
    *,
    artifact_dir: Path | None = None,
    environment: Any = None,
    messages: list[dict[str, Any]] | None = None,
    max_tokens: int = 32768,
) -> tuple[str, float, str]:
    env = environment if environment is not None else build_agent_environment(item, config)
    try:
        system_prompt = task_agent_system_prompt(
            item,
            (
                "You are an agent being evaluated in a deterministic simulated environment. "
                "Choose one valid environment tool per turn. Do not invent tools."
            ),
        )
        native_system_prompt = _native_system_prompt(system_prompt)
        native_messages = messages if messages is not None else []
        native_messages.append(
            {"role": "user", "content": _initial_user_prompt(item, env, include_action_schema=False)}
        )
        trace: list[dict[str, Any]] = []
        tool_specs = env.tool_specs() if hasattr(env, "tool_specs") else []

        while env.steps < env.max_steps and not env.done:
            response: TargetToolModelResponse = call_target_model_with_tools(
                native_messages,
                target,
                tool_specs,
                system_prompt=native_system_prompt,
                backend=config.llm_backend,
                max_tokens=max_tokens,
                trace_dir=artifact_dir / "llm" if artifact_dir is not None else None,
                trace_name=f"agent-step-{len(trace) + 1:03d}",
            )
            native_messages.append(response.assistant_message)
            if not response.tool_calls:
                env.invalid_actions += 1
                env.steps += 1
                error = "Expected the target model to call one of the provided native tools."
                observation = f"Error: {error}\n\n{env.observation()}"
                done = env.steps >= env.max_steps
                env.done = done
                trace.append(
                    {
                        "step": len(trace) + 1,
                        "model_output": response.content,
                        "parsed_action": None,
                        "tool_call": None,
                        "tool_result": ToolResult(
                            tool_call_id=f"native_missing_{len(trace) + 1}",
                            name="missing_tool_call",
                            content=observation,
                            error=error,
                            raw=response.raw_response,
                        ).model_dump(mode="json"),
                        "observation": observation,
                        "error": error,
                        "score_after_step": env.score(),
                        "done": done,
                    }
                )
                _save_interaction_progress(artifact_dir, trace, env)
                break

            results: list[ToolResult] = []
            for tool_call in response.tool_calls:
                action, tool_result, observation, error, done = _execute_tool_call(env, tool_specs, tool_call)
                results.append(tool_result)
                trace.append(
                    {
                        "step": len(trace) + 1,
                        "model_output": response.content,
                        "parsed_action": action,
                        "tool_call": tool_call.model_dump(mode="json"),
                        "tool_result": tool_result.model_dump(mode="json"),
                        "observation": observation,
                        "error": error,
                        "score_after_step": env.score(),
                        "done": done,
                    }
                )
                _save_interaction_progress(artifact_dir, trace, env)
                if done or env.steps >= env.max_steps:
                    break
            native_messages.extend(_native_tool_result_messages(response.adapter, results))
            if done or env.steps >= env.max_steps:
                break

        raw = {
            "tool_protocol_version": TOOL_PROTOCOL_VERSION,
            "tool_message_protocol": "provider_native",
            "tool_adapter": tool_adapter_for_target(target),
            "environment": env.state().get("environment", env.__class__.__name__),
            "tool_specs": [spec.model_dump(mode="json") for spec in tool_specs],
            "trace": trace,
            "final_state": env.state(),
            "history": native_messages,
        }
        return json.dumps(raw, ensure_ascii=False), env.score(), env.summary()
    finally:
        _save_environment_artifacts(env, artifact_dir)
        cleanup = getattr(env, "cleanup", None)
        if environment is None and callable(cleanup):
            cleanup()


def _run_agent_interaction_json_actions(
    item: BenchmarkItem,
    target: TargetModelConfig,
    config: BenchmarkConfig,
    *,
    artifact_dir: Path | None = None,
    environment: Any = None,
    messages: list[Message] | None = None,
    max_tokens: int = 32768,
) -> tuple[str, float, str]:
    env = environment if environment is not None else build_agent_environment(item, config)
    try:
        system_prompt = task_agent_system_prompt(
            item,
            (
                "You are an agent being evaluated in a deterministic simulated environment. "
                "Choose one valid action per turn. Do not invent tools. Return JSON only."
            ),
        )
        history = messages if messages is not None else []
        trace: list[dict[str, Any]] = []
        tool_specs = env.tool_specs() if hasattr(env, "tool_specs") else []
        user_prompt = _initial_user_prompt(item, env, include_action_schema=True)

        for step_index in range(env.max_steps):
            response = call_target_model(
                user_prompt,
                target,
                system_prompt=system_prompt,
                history=history,
                backend=config.llm_backend,
                max_tokens=max_tokens,
                trace_dir=artifact_dir / "llm" if artifact_dir is not None else None,
                trace_name=f"agent-step-{step_index + 1:03d}",
            )
            history.extend([Message(role="user", content=user_prompt), Message(role="assistant", content=response)])
            action, parse_error = parse_agent_action(response)
            tool_call = action_to_tool_call(action, f"call_{step_index + 1}", raw=response) if action else None
            tool_result: ToolResult | None = None
            if action is None:
                env.invalid_actions += 1
                env.steps += 1
                observation = f"Error: {parse_error}\n\n{env.observation()}"
                done = env.steps >= env.max_steps
                env.done = done
                error = parse_error
                tool_result = ToolResult(
                    tool_call_id=f"call_{step_index + 1}",
                    name="parse_error",
                    content=observation,
                    error=parse_error,
                    raw=response,
                )
            else:
                action, tool_result, observation, error, done = _execute_tool_call(env, tool_specs, tool_call)
            trace.append(
                {
                    "step": step_index + 1,
                    "model_output": response,
                    "parsed_action": action,
                    "tool_call": tool_call.model_dump(mode="json") if tool_call else None,
                    "tool_result": tool_result.model_dump(mode="json") if tool_result else None,
                    "observation": observation,
                    "error": error,
                    "score_after_step": env.score(),
                    "done": done,
                }
            )
            _save_interaction_progress(artifact_dir, trace, env)
            if done:
                history.append(Message(role="user", content=f"Observation:\n{observation}"))
                break
            user_prompt = f"Observation:\n{observation}\n\nContinue with one JSON action."

        raw = {
            "tool_protocol_version": TOOL_PROTOCOL_VERSION,
            "environment": env.state().get("environment", env.__class__.__name__),
            "tool_specs": [spec.model_dump(mode="json") for spec in tool_specs],
            "trace": trace,
            "final_state": env.state(),
            "history": [message.model_dump() for message in history],
        }
        return json.dumps(raw, ensure_ascii=False), env.score(), env.summary()
    finally:
        _save_environment_artifacts(env, artifact_dir)
        cleanup = getattr(env, "cleanup", None)
        if environment is None and callable(cleanup):
            cleanup()


def run_agent_interaction(
    item: BenchmarkItem,
    target: TargetModelConfig,
    config: BenchmarkConfig,
    *,
    artifact_dir: str | Path | None = None,
) -> tuple[str, float, str]:
    artifact_path = Path(artifact_dir) if artifact_dir is not None else None
    if item.workflow is not None:
        from .workflow import run_workflow

        return run_workflow(item, target, config, artifact_dir=artifact_path)
    if target.harness:
        from .harness import get_harness

        return get_harness(target.harness).run(item, target, config, artifact_dir=artifact_path)
    adapter = tool_adapter_for_target(target)
    if adapter in {"openai", "anthropic"}:
        return _run_agent_interaction_native_tools(
            item,
            target,
            config,
            artifact_dir=artifact_path,
        )
    return _run_agent_interaction_json_actions(
        item,
        target,
        config,
        artifact_dir=artifact_path,
    )
