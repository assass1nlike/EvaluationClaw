"""Canonical tool-call protocol for EvaluationClaw agent runners.

Provider-native adapters and EvaluationClaw's JSON-action runner should convert
their native events into these structures before scoring/reporting.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

TOOL_PROTOCOL_VERSION = "evalclaw.tool_protocol.v1"


class ToolSpec(BaseModel):
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw: Any = None


class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    content: str = ""
    error: str | None = None
    raw: Any = None


class AgentTraceTurn(BaseModel):
    role: str
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_result: ToolResult | None = None
    raw: Any = None


class AgentTrace(BaseModel):
    protocol_version: str = TOOL_PROTOCOL_VERSION
    turns: list[AgentTraceTurn] = Field(default_factory=list)
    final_answer: str = ""
    final_state: dict[str, Any] = Field(default_factory=dict)
    raw_native_trace: Any = None
    adapter_notes: str = ""


def object_schema(
    properties: dict[str, dict[str, Any]] | None = None,
    *,
    required: list[str] | None = None,
    additional_properties: bool = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": additional_properties,
    }


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True


def validate_tool_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> list[str]:
    """Validate a tool call against a small JSON Schema subset.

    The goal is deterministic runner-side guardrails, not full JSON Schema
    coverage. It supports object type, required fields, primitive property
    types, enum, and additionalProperties=false.
    """
    schema = spec.parameters or {}
    errors: list[str] = []
    if schema.get("type", "object") != "object":
        return errors
    if not isinstance(arguments, dict):
        return [f"{spec.name} arguments must be an object."]
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    for key in required:
        if key not in arguments:
            errors.append(f"Missing required argument: {key}.")
    if schema.get("additionalProperties") is False:
        extras = sorted(set(arguments) - set(properties))
        if extras:
            errors.append(f"Unexpected argument(s): {', '.join(extras)}.")
    for key, value in arguments.items():
        prop = properties.get(key)
        if not isinstance(prop, dict):
            continue
        expected_type = prop.get("type")
        if isinstance(expected_type, str) and not _type_matches(value, expected_type):
            errors.append(f"Argument {key} must be {expected_type}.")
        enum = prop.get("enum")
        if isinstance(enum, list) and value not in enum:
            errors.append(f"Argument {key} must be one of: {', '.join(str(x) for x in enum)}.")
    return errors


def validate_tool_call(call: ToolCall, specs: list[ToolSpec]) -> list[str]:
    spec_by_name = {spec.name: spec for spec in specs}
    spec = spec_by_name.get(call.name)
    if spec is None:
        return [f"Unknown tool/action: {call.name or '<missing>'}."]
    return validate_tool_arguments(spec, call.arguments)


def action_to_tool_call(action: dict[str, Any], call_id: str, *, raw: Any = None) -> ToolCall:
    name = str(action.get("action") or action.get("tool") or "").strip().lower()
    if name == "run_test":
        name = "run_tests"
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    return ToolCall(id=call_id, name=name, arguments=args, raw=raw if raw is not None else action)


def tool_call_to_action(call: ToolCall) -> dict[str, Any]:
    return {"action": call.name, "args": call.arguments}


def format_tool_specs_for_prompt(specs: list[ToolSpec]) -> str:
    lines = [
        "Return exactly one JSON object per turn.",
        "Use this shape: {\"action\":\"tool_name\",\"args\":{...}}",
        "Valid tools:",
    ]
    for spec in specs:
        lines.append(
            "- "
            + json.dumps(
                {
                    "action": spec.name,
                    "description": spec.description,
                    "args_schema": spec.parameters,
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)
