from types import SimpleNamespace

from evalclaw.tool_adapters import (
    anthropic_tool_calls_from_response,
    anthropic_tool_spec,
    bedrock_tool_calls_from_response,
    bedrock_tool_spec,
    cohere_tool_calls_from_response,
    cohere_tool_spec,
    evalclaw_tool_result_to_anthropic,
    evalclaw_tool_result_to_bedrock,
    evalclaw_tool_result_to_cohere,
    evalclaw_tool_result_to_gemini,
    evalclaw_tool_result_to_mcp,
    evalclaw_tool_result_to_mistral,
    evalclaw_tool_result_to_openai,
    evalclaw_tool_result_to_openai_response_input,
    gemini_tool_calls_from_response,
    gemini_tools,
    mcp_tool_call_to_evalclaw,
    mcp_tool_spec,
    mcp_tools_list_result,
    mistral_tool_calls_from_response,
    mistral_tool_spec,
    openai_tool_call_to_evalclaw,
    openai_tool_calls_from_response,
    openai_tool_spec,
    tool_adapter_for_target,
)
from evalclaw.tool_protocol import ToolResult, ToolSpec, object_schema
from evalclaw.types import TargetModelConfig


def _read_file_spec() -> ToolSpec:
    return ToolSpec(
        name="read_file",
        description="Read a visible file by relative path.",
        parameters=object_schema(
            {"path": {"type": "string", "description": "Relative file path."}},
            required=["path"],
        ),
    )


def test_openai_tool_spec_uses_function_tool_shape() -> None:
    spec = _read_file_spec()

    native = openai_tool_spec(spec)

    assert native == {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a visible file by relative path.",
            "parameters": spec.parameters,
        },
    }


def test_anthropic_tool_spec_uses_input_schema_shape() -> None:
    spec = _read_file_spec()

    native = anthropic_tool_spec(spec)

    assert native == {
        "name": "read_file",
        "description": "Read a visible file by relative path.",
        "input_schema": spec.parameters,
    }


def test_mistral_and_cohere_specs_use_openai_like_shape() -> None:
    spec = _read_file_spec()

    assert mistral_tool_spec(spec) == openai_tool_spec(spec)
    assert cohere_tool_spec(spec) == openai_tool_spec(spec)


def test_gemini_tool_spec_uses_function_declarations() -> None:
    spec = _read_file_spec()

    assert gemini_tools([spec]) == [
        {
            "functionDeclarations": [
                {
                    "name": "read_file",
                    "description": "Read a visible file by relative path.",
                    "parameters": spec.parameters,
                }
            ]
        }
    ]


def test_bedrock_tool_spec_uses_converse_tool_spec_shape() -> None:
    spec = _read_file_spec()

    assert bedrock_tool_spec(spec) == {
        "toolSpec": {
            "name": "read_file",
            "description": "Read a visible file by relative path.",
            "inputSchema": {"json": spec.parameters},
        }
    }


def test_mcp_tool_spec_uses_input_schema_shape() -> None:
    spec = _read_file_spec()

    assert mcp_tool_spec(spec) == {
        "name": "read_file",
        "description": "Read a visible file by relative path.",
        "inputSchema": spec.parameters,
    }
    assert mcp_tools_list_result([spec]) == {"tools": [mcp_tool_spec(spec)]}


def test_openai_chat_tool_call_converts_to_evalclaw_tool_call() -> None:
    raw_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"solution.py"}'},
    }

    call = openai_tool_call_to_evalclaw(raw_call)

    assert call.id == "call_1"
    assert call.name == "read_file"
    assert call.arguments == {"path": "solution.py"}
    assert call.raw == raw_call


def test_openai_response_api_function_call_converts_to_evalclaw_tool_call() -> None:
    raw_response = {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Working..."}]},
            {
                "type": "function_call",
                "call_id": "call_2",
                "name": "run_tests",
                "arguments": "{}",
            },
        ]
    }

    calls = openai_tool_calls_from_response(raw_response)

    assert len(calls) == 1
    assert calls[0].id == "call_2"
    assert calls[0].name == "run_tests"
    assert calls[0].arguments == {}


def test_openai_sdk_object_response_extracts_tool_calls() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            id="call_3",
                            type="function",
                            function=SimpleNamespace(
                                name="write_file",
                                arguments='{"path":"solution.py","content":"print(1)"}',
                            ),
                        )
                    ]
                )
            )
        ]
    )

    calls = openai_tool_calls_from_response(response)

    assert len(calls) == 1
    assert calls[0].id == "call_3"
    assert calls[0].name == "write_file"
    assert calls[0].arguments == {"path": "solution.py", "content": "print(1)"}
    assert calls[0].raw["function"]["name"] == "write_file"


def test_mistral_and_cohere_extract_openai_like_tool_calls() -> None:
    mistral_response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "mistral_call_1",
                            "function": {"name": "read_file", "arguments": '{"path":"main.py"}'},
                        }
                    ]
                }
            }
        ]
    }
    cohere_response = {
        "message": {
            "tool_calls": [
                {
                    "id": "cohere_call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": {"path": "README.md"}},
                }
            ]
        }
    }

    mistral_calls = mistral_tool_calls_from_response(mistral_response)
    cohere_calls = cohere_tool_calls_from_response(cohere_response)

    assert mistral_calls[0].id == "mistral_call_1"
    assert mistral_calls[0].arguments == {"path": "main.py"}
    assert cohere_calls[0].id == "cohere_call_1"
    assert cohere_calls[0].arguments == {"path": "README.md"}


def test_gemini_response_extracts_function_calls() -> None:
    response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "I will inspect it."},
                        {
                            "functionCall": {
                                "name": "read_file",
                                "args": {"path": "solution.py"},
                            }
                        },
                    ]
                }
            }
        ]
    }

    calls = gemini_tool_calls_from_response(response)

    assert len(calls) == 1
    assert calls[0].id == "gemini_call_1"
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "solution.py"}


def test_bedrock_response_extracts_tool_use_blocks() -> None:
    response = {
        "output": {
            "message": {
                "content": [
                    {"text": "I will inspect it."},
                    {
                        "toolUse": {
                            "toolUseId": "bedrock_call_1",
                            "name": "read_file",
                            "input": {"path": "solution.py"},
                        }
                    },
                ]
            }
        }
    }

    calls = bedrock_tool_calls_from_response(response)

    assert len(calls) == 1
    assert calls[0].id == "bedrock_call_1"
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "solution.py"}


def test_mcp_tools_call_request_converts_to_evalclaw_tool_call() -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "read_file", "arguments": {"path": "solution.py"}},
    }

    call = mcp_tool_call_to_evalclaw(request)

    assert call.id == "7"
    assert call.name == "read_file"
    assert call.arguments == {"path": "solution.py"}


def test_anthropic_tool_use_converts_to_evalclaw_tool_call() -> None:
    response = {
        "content": [
            {"type": "text", "text": "I will inspect the file."},
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "solution.py"}},
        ]
    }

    calls = anthropic_tool_calls_from_response(response)

    assert len(calls) == 1
    assert calls[0].id == "toolu_1"
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "solution.py"}


def test_anthropic_sdk_object_response_extracts_tool_uses() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Checking tests."),
            SimpleNamespace(type="tool_use", id="toolu_2", name="run_tests", input={}),
        ]
    )

    calls = anthropic_tool_calls_from_response(response)

    assert len(calls) == 1
    assert calls[0].id == "toolu_2"
    assert calls[0].name == "run_tests"
    assert calls[0].arguments == {}


def test_evalclaw_tool_result_converts_to_openai_and_anthropic_outputs() -> None:
    result = ToolResult(tool_call_id="call_1", name="read_file", content="File solution.py:\npass\n")

    assert evalclaw_tool_result_to_openai(result) == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "File solution.py:\npass\n",
    }
    assert evalclaw_tool_result_to_openai_response_input(result) == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "File solution.py:\npass\n",
    }
    assert evalclaw_tool_result_to_anthropic(result) == {
        "type": "tool_result",
        "tool_use_id": "call_1",
        "content": "File solution.py:\npass\n",
        "is_error": False,
    }


def test_evalclaw_tool_result_preserves_error_flag_for_anthropic() -> None:
    result = ToolResult(tool_call_id="toolu_1", name="read_file", error="Missing path.")

    assert evalclaw_tool_result_to_openai(result)["content"] == "Error: Missing path."
    assert evalclaw_tool_result_to_anthropic(result) == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "Error: Missing path.",
        "is_error": True,
    }


def test_evalclaw_tool_result_converts_to_other_provider_outputs() -> None:
    result = ToolResult(tool_call_id="call_1", name="read_file", content="contents")

    assert evalclaw_tool_result_to_mistral(result) == evalclaw_tool_result_to_openai(result)
    assert evalclaw_tool_result_to_cohere(result) == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": [{"type": "document", "document": {"data": "contents"}}],
    }
    assert evalclaw_tool_result_to_gemini(result) == {
        "functionResponse": {
            "name": "read_file",
            "response": {"tool_call_id": "call_1", "content": "contents", "is_error": False},
        }
    }
    assert evalclaw_tool_result_to_bedrock(result) == {
        "toolResult": {"toolUseId": "call_1", "content": [{"text": "contents"}]}
    }
    assert evalclaw_tool_result_to_mcp(result, request_id=7) == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"content": [{"type": "text", "text": "contents"}], "isError": False},
    }


def test_tool_adapter_for_target_maps_deepseek_to_openai_adapter() -> None:
    assert tool_adapter_for_target(TargetModelConfig(provider="openai", model="gpt-5")) == "openai"
    assert (
        tool_adapter_for_target(TargetModelConfig(provider="openai_compatible", model="deepseek-chat"))
        == "openai"
    )
    assert tool_adapter_for_target(TargetModelConfig(provider="anthropic", model="claude-opus-4-6")) == "anthropic"
    assert tool_adapter_for_target(TargetModelConfig(provider="gemini", model="gemini-2.5-pro")) == "gemini"
    assert tool_adapter_for_target(TargetModelConfig(provider="mistral", model="mistral-large")) == "mistral"
    assert tool_adapter_for_target(TargetModelConfig(provider="cohere", model="command-r-plus")) == "cohere"
    assert tool_adapter_for_target(TargetModelConfig(provider="bedrock", model="anthropic.claude")) == "bedrock"
    assert tool_adapter_for_target(TargetModelConfig(provider="mcp", model="custom-agent")) == "mcp"
    assert tool_adapter_for_target(TargetModelConfig(provider="mock", model="mock-agent")) is None
