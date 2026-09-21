import json

import httpx
import pytest
from inspect_ai.model import (
    ChatMessageAssistant, ChatMessageTool, ChatMessageUser, ContentReasoning,
    ContentText, GenerateConfig, get_model,
)
from inspect_ai.tool import ToolInfo, ToolParams

import qwen_api


@pytest.mark.asyncio
async def test_qwen_partial_tools_and_reasoning_use_dashscope_wire_format(monkeypatch):
    requests = []
    monkeypatch.setenv("QWEN_API_KEY", "qwen-test")
    monkeypatch.setenv("OPENAI_API_KEY", "other-provider-test")

    def respond(request):
        assert request.headers["authorization"] == "Bearer qwen-test"
        requests.append(json.loads(request.content))
        message = ({"role": "assistant", "content": "", "tool_calls": [{
            "id": "ledger-1", "type": "function",
            "function": {"name": "read_ledger", "arguments": "{}"},
        }]} if len(requests) == 1 else {
            "role": "assistant", "content": "7", "reasoning_content": "The ledger says 7.",
        })
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "qwen3.8-27b",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if len(requests) == 1 else "stop",
                         "message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    model = get_model("qwen/qwen3.8-27b", base_url="https://example.invalid/v1",
                      http_client=client, memoize=False,
                      config=GenerateConfig(seed=42, max_tokens=300000, reasoning_effort="high",
                                            extra_body={"enable_thinking": True}))
    tool = ToolInfo(name="read_ledger", description="Read count.", parameters=ToolParams())
    messages = [ChatMessageUser(content="Read the ledger."),
                ChatMessageAssistant(content="I will read it.", metadata={"prefill": True})]
    first = await model.generate(messages, tools=[tool])
    assert first.message.tool_calls[0].function == "read_ledger"
    second = await model.generate([
        *messages, first.message,
        ChatMessageTool(content="7", tool_call_id="ledger-1"),
    ], tools=[tool])
    await model.generate([
        ChatMessageUser(content="Read the ledger."), second.message,
        ChatMessageUser(content="Repeat."),
        ChatMessageAssistant(content="The count is", metadata={"prefill": True}),
    ], tools=[tool])
    assert requests[0]["messages"][-1] == {"role": "assistant", "content": "I will read it.", "partial": True}
    assert all("partial" not in item for item in requests[1]["messages"])
    assert requests[2]["messages"][1]["reasoning_content"] == "The ledger says 7."
    assert requests[2]["messages"][-1]["partial"] is True
    for request in requests:
        assert request["tools"][0]["function"]["name"] == "read_ledger"
        assert request["max_completion_tokens"] == 300000
        assert request["enable_thinking"] is True
        assert request["reasoning_effort"] == "high"
        assert request["seed"] == 42
        assert "max_tokens" not in request and "thinking" not in request
        assert all("prefix" not in item for item in request["messages"])
    await client.aclose()
