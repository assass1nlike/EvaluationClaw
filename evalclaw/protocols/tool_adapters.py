"""Provider-native adapters for EvaluationClaw's canonical tool protocol."""
from __future__ import annotations

import json
from typing import Any, Literal

from ..types import TargetModelConfig
from .tool import ToolCall, ToolResult, ToolSpec

ToolAdapterName = Literal["openai", "anthropic", "gemini", "mistral", "cohere", "bedrock", "mcp"]


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _get_any(value: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        found = _get(value, key, None)
        if found is not None:
            return found
    return default


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(inner) for inner in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    if hasattr(value, "__dict__"):
        return {
            key: _jsonable(inner)
            for key, inner in vars(value).items()
            if not key.startswith("_")
        }
    return repr(value)


def _parse_arguments(raw_arguments: Any) -> dict[str, Any]:
    if raw_arguments is None or raw_arguments == "":
        return {}
    if isinstance(raw_arguments, dict):
        return dict(raw_arguments)
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _ensure_tool_call_id(raw_id: Any, fallback_prefix: str, index: int = 0) -> str:
    if raw_id:
        return str(raw_id)
    suffix = index + 1 if index >= 0 else 1
    return f"{fallback_prefix}_{suffix}"


def _result_content(result: ToolResult) -> str:
    if not result.error:
        return result.content
    if result.content:
        return f"Error: {result.error}\n\n{result.content}"
    return f"Error: {result.error}"


def openai_tool_spec(spec: ToolSpec) -> dict[str, Any]:
    """Convert an EvaluationClaw ToolSpec to OpenAI/DeepSeek tools format."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def openai_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [openai_tool_spec(spec) for spec in specs]


def openai_tool_call_to_evalclaw(raw_call: Any) -> ToolCall:
    """Convert an OpenAI-compatible tool call to a canonical ToolCall.

    Supports both Chat Completions tool_calls and Responses API function_call
    output items. DeepSeek's tool-call format is OpenAI-compatible and should
    use this adapter.
    """
    function = _get(raw_call, "function", {}) or {}
    call_id = _get(raw_call, "id") or _get(raw_call, "call_id") or ""
    name = _get(function, "name") or _get(raw_call, "name") or ""
    raw_arguments = _get(function, "arguments")
    if raw_arguments is None:
        raw_arguments = _get(raw_call, "arguments")
    return ToolCall(
        id=str(call_id),
        name=str(name),
        arguments=_parse_arguments(raw_arguments),
        raw=_jsonable(raw_call),
    )


def openai_tool_calls_from_message(message: Any) -> list[ToolCall]:
    """Extract tool calls from an OpenAI-compatible assistant message."""
    raw_calls = _get(message, "tool_calls", []) or []
    return [openai_tool_call_to_evalclaw(raw_call) for raw_call in raw_calls]


def openai_tool_calls_from_response(response: Any) -> list[ToolCall]:
    """Extract tool calls from Chat Completions or Responses API responses."""
    choices = _get(response, "choices", []) or []
    if choices:
        first_choice = choices[0]
        message = _get(first_choice, "message", {}) or {}
        return openai_tool_calls_from_message(message)

    output = _get(response, "output", []) or []
    return [
        openai_tool_call_to_evalclaw(item)
        for item in output
        if _get(item, "type") == "function_call"
    ]


def evalclaw_tool_result_to_openai(result: ToolResult) -> dict[str, Any]:
    """Convert a canonical ToolResult to a Chat Completions tool message."""
    return {
        "role": "tool",
        "tool_call_id": result.tool_call_id,
        "content": _result_content(result),
    }


def evalclaw_tool_result_to_openai_response_input(result: ToolResult) -> dict[str, Any]:
    """Convert a canonical ToolResult to a Responses API function output item."""
    return {
        "type": "function_call_output",
        "call_id": result.tool_call_id,
        "output": _result_content(result),
    }


def mistral_tool_spec(spec: ToolSpec) -> dict[str, Any]:
    """Convert an EvaluationClaw ToolSpec to Mistral's OpenAI-like tools format."""
    return openai_tool_spec(spec)


def mistral_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return openai_tools(specs)


def mistral_tool_call_to_evalclaw(raw_call: Any) -> ToolCall:
    """Convert a Mistral tool call to a canonical ToolCall."""
    return openai_tool_call_to_evalclaw(raw_call)


def mistral_tool_calls_from_response(response: Any) -> list[ToolCall]:
    return openai_tool_calls_from_response(response)


def evalclaw_tool_result_to_mistral(result: ToolResult) -> dict[str, Any]:
    return evalclaw_tool_result_to_openai(result)


def cohere_tool_spec(spec: ToolSpec) -> dict[str, Any]:
    """Convert an EvaluationClaw ToolSpec to Cohere v2's OpenAI-like tools format."""
    return openai_tool_spec(spec)


def cohere_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return openai_tools(specs)


def cohere_tool_call_to_evalclaw(raw_call: Any) -> ToolCall:
    """Convert a Cohere v2 tool call to a canonical ToolCall."""
    return openai_tool_call_to_evalclaw(raw_call)


def cohere_tool_calls_from_response(response: Any) -> list[ToolCall]:
    """Extract tool calls from a Cohere v2 response.

    Cohere v2 places tool calls on response.message.tool_calls. The individual
    call format is OpenAI-like.
    """
    message = _get(response, "message", None)
    if message is not None:
        return openai_tool_calls_from_message(message)
    return openai_tool_calls_from_response(response)


def evalclaw_tool_result_to_cohere(result: ToolResult) -> dict[str, Any]:
    """Convert a canonical ToolResult to a Cohere v2 tool message."""
    return {
        "role": "tool",
        "tool_call_id": result.tool_call_id,
        "content": [{"type": "document", "document": {"data": _result_content(result)}}],
    }


def gemini_function_declaration(spec: ToolSpec) -> dict[str, Any]:
    """Convert an EvaluationClaw ToolSpec to a Gemini function declaration."""
    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.parameters,
    }


def gemini_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """Convert ToolSpecs to Gemini native tools format.

    The REST API uses camelCase functionDeclarations; several SDKs accept the
    same structure as plain dictionaries.
    """
    return [{"functionDeclarations": [gemini_function_declaration(spec) for spec in specs]}]


def gemini_function_call_to_evalclaw(raw_call: Any, *, index: int = 0) -> ToolCall:
    """Convert a Gemini functionCall object to a canonical ToolCall."""
    call = _get_any(raw_call, "functionCall", "function_call", default=raw_call)
    name = _get(call, "name", "")
    raw_args = _get_any(call, "args", "arguments", default={})
    raw_id = _get_any(call, "id", "call_id", default="")
    return ToolCall(
        id=_ensure_tool_call_id(raw_id, "gemini_call", index),
        name=str(name),
        arguments=_parse_arguments(raw_args),
        raw=_jsonable(raw_call),
    )


def gemini_tool_calls_from_response(response: Any) -> list[ToolCall]:
    """Extract function calls from a Gemini native response."""
    calls = _get_any(response, "function_calls", "functionCalls", default=None)
    if calls:
        return [gemini_function_call_to_evalclaw(call, index=index) for index, call in enumerate(calls)]

    candidates = _get(response, "candidates", []) or []
    if not candidates:
        return []
    content = _get(candidates[0], "content", {}) or {}
    parts = _get(content, "parts", []) or []
    result: list[ToolCall] = []
    for part in parts:
        if _get_any(part, "functionCall", "function_call", default=None) is None:
            continue
        result.append(gemini_function_call_to_evalclaw(part, index=len(result)))
    return result


def evalclaw_tool_result_to_gemini(result: ToolResult) -> dict[str, Any]:
    """Convert a canonical ToolResult to a Gemini functionResponse part."""
    return {
        "functionResponse": {
            "name": result.name,
            "response": {
                "tool_call_id": result.tool_call_id,
                "content": _result_content(result),
                "is_error": bool(result.error),
            },
        }
    }


def bedrock_tool_spec(spec: ToolSpec) -> dict[str, Any]:
    """Convert an EvaluationClaw ToolSpec to Bedrock Converse toolSpec format."""
    return {
        "toolSpec": {
            "name": spec.name,
            "description": spec.description,
            "inputSchema": {"json": spec.parameters},
        }
    }


def bedrock_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [bedrock_tool_spec(spec) for spec in specs]


def bedrock_tool_use_to_evalclaw(raw_block: Any) -> ToolCall:
    """Convert a Bedrock Converse toolUse block to a canonical ToolCall."""
    tool_use = _get_any(raw_block, "toolUse", "tool_use", default=raw_block) or {}
    return ToolCall(
        id=str(_get_any(tool_use, "toolUseId", "tool_use_id", "id", default="")),
        name=str(_get(tool_use, "name", "")),
        arguments=_parse_arguments(_get(tool_use, "input", {})),
        raw=_jsonable(raw_block),
    )


def bedrock_tool_calls_from_response(response: Any) -> list[ToolCall]:
    """Extract toolUse blocks from a Bedrock Converse response."""
    output = _get(response, "output", {}) or {}
    message = _get(output, "message", {}) or {}
    content = _get(message, "content", []) or []
    return [
        bedrock_tool_use_to_evalclaw(block)
        for block in content
        if _get_any(block, "toolUse", "tool_use", default=None) is not None
    ]


def evalclaw_tool_result_to_bedrock(result: ToolResult) -> dict[str, Any]:
    """Convert a canonical ToolResult to Bedrock Converse toolResult format."""
    tool_result: dict[str, Any] = {
        "toolUseId": result.tool_call_id,
        "content": [{"text": _result_content(result)}],
    }
    if result.error:
        tool_result["status"] = "error"
    return {"toolResult": tool_result}


def mcp_tool_spec(spec: ToolSpec) -> dict[str, Any]:
    """Convert an EvaluationClaw ToolSpec to an MCP tool descriptor."""
    return {
        "name": spec.name,
        "description": spec.description,
        "inputSchema": spec.parameters,
    }


def mcp_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [mcp_tool_spec(spec) for spec in specs]


def mcp_tools_list_result(specs: list[ToolSpec]) -> dict[str, Any]:
    """Convert ToolSpecs to the payload returned by MCP tools/list."""
    return {"tools": mcp_tools(specs)}


def mcp_tool_call_to_evalclaw(raw_request: Any) -> ToolCall:
    """Convert an MCP tools/call request or params object to a canonical ToolCall."""
    request_id = _get(raw_request, "id", "")
    params = _get(raw_request, "params", None)
    payload = params if params is not None else raw_request
    return ToolCall(
        id=str(request_id),
        name=str(_get(payload, "name", "")),
        arguments=_parse_arguments(_get(payload, "arguments", {})),
        raw=_jsonable(raw_request),
    )


def evalclaw_tool_result_to_mcp(result: ToolResult, *, request_id: str | int | None = None) -> dict[str, Any]:
    """Convert a canonical ToolResult to an MCP tools/call JSON-RPC result."""
    payload = {
        "content": [{"type": "text", "text": _result_content(result)}],
        "isError": bool(result.error),
    }
    if request_id is None:
        return payload
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def anthropic_tool_spec(spec: ToolSpec) -> dict[str, Any]:
    """Convert an EvaluationClaw ToolSpec to Claude/Anthropic tools format."""
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.parameters,
    }


def anthropic_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [anthropic_tool_spec(spec) for spec in specs]


def anthropic_tool_use_to_evalclaw(raw_block: Any) -> ToolCall:
    """Convert an Anthropic tool_use content block to a canonical ToolCall."""
    raw_input = _get(raw_block, "input", {}) or {}
    arguments = dict(raw_input) if isinstance(raw_input, dict) else {}
    return ToolCall(
        id=str(_get(raw_block, "id", "")),
        name=str(_get(raw_block, "name", "")),
        arguments=arguments,
        raw=_jsonable(raw_block),
    )


def anthropic_tool_calls_from_response(response: Any) -> list[ToolCall]:
    """Extract canonical ToolCalls from a Claude Messages API response."""
    content = _get(response, "content", []) or []
    return [
        anthropic_tool_use_to_evalclaw(block)
        for block in content
        if _get(block, "type") == "tool_use"
    ]


def evalclaw_tool_result_to_anthropic(result: ToolResult) -> dict[str, Any]:
    """Convert a canonical ToolResult to an Anthropic tool_result block."""
    return {
        "type": "tool_result",
        "tool_use_id": result.tool_call_id,
        "content": _result_content(result),
        "is_error": bool(result.error),
    }


def tool_adapter_for_target(target: TargetModelConfig) -> ToolAdapterName | None:
    """Return the native tool adapter family for a configured target model."""
    provider = target.provider.lower()
    model = target.model.lower()
    if provider in {"openai", "openai_compatible", "deepseek"}:
        return "openai"
    if model.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-", "deepseek-")):
        return "openai"
    if provider in {"anthropic", "claude"} or model.startswith("claude"):
        return "anthropic"
    if provider in {"gemini", "google"} or model.startswith("gemini"):
        return "gemini"
    if provider == "mistral" or model.startswith(("mistral-", "codestral-")):
        return "mistral"
    if provider == "cohere" or model.startswith(("command-", "c4ai-")):
        return "cohere"
    if provider in {"bedrock", "aws_bedrock"}:
        return "bedrock"
    if provider == "mcp":
        return "mcp"
    return None
