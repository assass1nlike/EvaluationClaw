"""Agent-interaction runner logic."""
from __future__ import annotations

import json
import re
from typing import Any

from ..agent_envs import build_agent_environment
from ..llm import call_target_model, extract_json
from ..protocols.task_agent import task_agent_initial_content_text, task_agent_system_prompt
from ..protocols.tool import (
    TOOL_PROTOCOL_VERSION,
    ToolResult,
    action_to_tool_call,
    tool_call_to_action,
    validate_tool_call,
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


def run_agent_interaction(
    item: BenchmarkItem,
    target: TargetModelConfig,
    config: BenchmarkConfig,
) -> tuple[str, float, str]:
    env = build_agent_environment(item, config)
    try:
        system_prompt = task_agent_system_prompt(
            item,
            (
                "You are an agent being evaluated in a deterministic simulated environment. "
                "Choose one valid action per turn. Do not invent tools. Return JSON only."
            ),
        )
        history: list[Message] = []
        trace: list[dict[str, Any]] = []
        tool_specs = env.tool_specs() if hasattr(env, "tool_specs") else []
        initial_content = task_agent_initial_content_text(item)
        initial_block = f"\n\nInitial task content:\n{initial_content}\n" if initial_content else ""
        user_prompt = (
            f"Task:\n{item.prompt}\n\n"
            f"{initial_block}"
            f"Initial observation:\n{env.observation()}\n\n"
            f"{env.action_schema()}"
        )

        for step_index in range(env.max_steps):
            response = call_target_model(
                user_prompt,
                target,
                system_prompt=system_prompt,
                history=history,
                backend=config.llm_backend,
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
                validation_errors = validate_tool_call(tool_call, tool_specs) if tool_call else []
                if validation_errors:
                    env.invalid_actions += 1
                    env.steps += 1
                    error = " ".join(validation_errors)
                    observation = f"Error: {error}\n\n{env.observation()}"
                    done = env.steps >= env.max_steps
                    env.done = done
                    tool_result = ToolResult(
                        tool_call_id=tool_call.id if tool_call else f"call_{step_index + 1}",
                        name=tool_call.name if tool_call else "invalid",
                        content=observation,
                        error=error,
                    )
                else:
                    outcome = env.step(tool_call_to_action(tool_call) if tool_call else action)
                    observation = outcome.observation
                    done = outcome.done
                    error = outcome.error
                    tool_result = ToolResult(
                        tool_call_id=tool_call.id if tool_call else f"call_{step_index + 1}",
                        name=tool_call.name if tool_call else str(action.get("action") or action.get("tool") or ""),
                        content=observation,
                        error=error,
                    )
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
            if done:
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
        cleanup = getattr(env, "cleanup", None)
        if callable(cleanup):
            cleanup()
