import json

import httpx
import pytest
from inspect_ai.model import (
    ChatMessageAssistant, ChatMessageTool, ChatMessageUser, ContentReasoning,
    ContentText, GenerateConfig, get_model,
)
from inspect_ai.tool import ToolCall

from deepseek_api import deepseek_messages


@pytest.mark.asyncio
async def test_reasoning_and_prefill_serialization():
    assistant = ChatMessageAssistant(content=[
        ContentReasoning(reasoning="Check the ledger."), ContentText(text="Checking."),
    ], tool_calls=[ToolCall(id="a", function="lookup", arguments={})])
    wire = await deepseek_messages([
        assistant, ChatMessageTool(content="7", tool_call_id="a"),
        ChatMessageAssistant(content="The answer is", metadata={"prefill": True}),
    ])
    assert wire[0] == {
        "role": "assistant", "content": "Checking.", "reasoning_content": "Check the ledger.",
        "tool_calls": [{"id": "a", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
    }
    assert wire[2] == {"role": "assistant", "content": "The answer is", "prefix": True, "reasoning_content": ""}
    assert "prefix" not in wire[0]


@pytest.mark.asyncio
async def test_provider_preserves_reasoning_in_actual_request():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "deepseek-flash",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "7", "reasoning_content": "The ledger says 7.",
            }}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    model = get_model("deepseek/deepseek-flash", base_url="https://api.deepseek.com/beta",
                      api_key="test", http_client=client, memoize=False,
                      config=GenerateConfig(max_tokens=300000, reasoning_effort="high",
                                            extra_body={"thinking": {"type": "enabled"}}))
    first = await model.generate([ChatMessageUser(content="Read the ledger.")])
    await model.generate([
        ChatMessageUser(content="Read the ledger."), first.message,
        ChatMessageUser(content="Repeat the result."),
        ChatMessageAssistant(content="The value is", metadata={"prefill": True}),
    ])
    assert requests[1]["messages"][1] == {
        "role": "assistant", "content": "7", "reasoning_content": "The ledger says 7.",
    }
    assert requests[1]["messages"][-1]["prefix"] is True
    assert requests[1]["max_tokens"] == 300000
    assert requests[1]["thinking"] == {"type": "enabled"}
    await client.aclose()
