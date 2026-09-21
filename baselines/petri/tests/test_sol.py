import asyncio
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing

import httpx
import pytest
from inspect_ai.model import ChatMessageSystem, ChatMessageTool, ChatMessageUser, GenerateConfig, get_model
from inspect_ai.tool import ToolInfo, ToolParams
from openai import RateLimitError

from request_rate import wait_for_slot
import sol_api


def response_event(request, output=None, **overrides):
    response = dict(id="resp_test", object="response", created_at=0, status="completed",
                    model="gpt-5.6-sol", instructions=request["instructions"],
                    reasoning={"effort": "high"}, max_output_tokens=None,
                    output=output or [{"type": "message", "id": "msg_test", "role": "assistant",
                                      "status": "completed", "content": [{"type": "output_text",
                                      "text": "7", "annotations": []}]}],
                    usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                           "input_tokens_details": {"cached_tokens": 0},
                           "output_tokens_details": {"reasoning_tokens": 2}}, **overrides)
    event = {"type": "response.completed", "sequence_number": 1, "response": response}
    return httpx.Response(200, text="event: response.completed\ndata: " + json.dumps(event) + "\n\n",
                          headers={"content-type": "text/event-stream"})


def test_rate_limit_is_shared_between_processes(tmp_path):
    with ProcessPoolExecutor(4, mp_context=multiprocessing.get_context("fork")) as pool:
        futures = [pool.submit(wait_for_slot, tmp_path / "rate", 50) for _ in range(4)]
        starts = sorted(f.result(timeout=15) for f in futures)
    assert all(b - a >= 1.2 for a, b in zip(starts, starts[1:]))


@pytest.mark.asyncio
async def test_sol_tools_reasoning_history_and_every_attempt_are_limited(tmp_path, monkeypatch):
    monkeypatch.setenv("SOL_API_KEY", "sol-test")
    requests, slots = [], []
    monkeypatch.setattr(sol_api, "wait_for_slot", lambda path, rpm: slots.append((path, rpm)) or 1)

    def respond(request):
        assert request.headers["authorization"] == "Bearer sol-test"
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited", "type": "rate_limit"}})
        if len(requests) == 2:
            return response_event(body, [
                {"type": "reasoning", "id": "rs_test", "summary": [], "encrypted_content": "ciphertext"},
                {"type": "function_call", "id": "fc_test", "call_id": "call_test",
                 "name": "read_ledger", "arguments": "{}", "status": "completed"},
            ])
        return response_event(body)

    model = get_model("sol/gpt-5.6-sol", base_url="https://sol.invalid/v1", memoize=False,
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
                      rate_limit_file=str(tmp_path / "rate"), call_log=str(tmp_path / "calls.jsonl"),
                      config=GenerateConfig(max_tokens=300000, reasoning_effort="high", timeout=600))
    config = model.config
    messages = [ChatMessageSystem(content="Use the ledger."), ChatMessageUser(content="Read it.")]
    tools = [ToolInfo(name="read_ledger", description="Read integer", parameters=ToolParams())]
    # SDK retries are disabled; a framework retry re-enters the same HTTP hook.
    with pytest.raises(RateLimitError):
        await model.api.generate(messages, tools, "auto", config)
    assert len(requests) == 1
    first, _ = await model.api.generate(messages, tools, "auto", config)
    second, _ = await model.api.generate(messages + [first.message,
        ChatMessageTool(content="7", tool_call_id="call_test")], tools, "auto", config)
    assert second.completion == "7"
    assert len(slots) == len(requests) == 3
    assert all(rpm == 50 for _, rpm in slots)
    assert requests[-1]["input"][-2]["type"] == "function_call"
    assert requests[-1]["input"][-1] == {"type": "function_call_output", "call_id": "call_test", "output": "7"}
    reasoning = next(item for item in requests[-1]["input"] if item["type"] == "reasoning")
    assert reasoning["encrypted_content"] == "ciphertext"
    for body in requests:
        assert body["instructions"] == "Use the ledger."
        assert body["reasoning"]["effort"] == "high"
        assert body["max_output_tokens"] == 300000
        assert body["tools"][0]["name"] == "read_ledger"
        assert not {"seed", "thinking", "enable_thinking"} & body.keys()
    await model.api.aclose()


@pytest.mark.parametrize("field,value", [("model", "different-model"),
                                        ("reasoning", {"effort": "low"}),
                                        ("instructions", "changed system prompt")])
@pytest.mark.asyncio
async def test_sol_rejects_changed_model_effort_or_instructions(tmp_path, monkeypatch, field, value):
    monkeypatch.setenv("SOL_API_KEY", "sol-test")
    monkeypatch.setattr(sol_api, "wait_for_slot", lambda *args: 1)

    def respond(request):
        response = response_event(json.loads(request.content))
        event = json.loads(response.text.split("data: ", 1)[1])
        event["response"][field] = value
        return httpx.Response(200, text="data: " + json.dumps(event) + "\n\n",
                              headers={"content-type": "text/event-stream"})

    model = get_model("sol/gpt-5.6-sol", base_url="https://sol.invalid/v1", memoize=False,
                      rate_limit_file=str(tmp_path / "rate"), call_log=str(tmp_path / "calls.jsonl"),
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
                      config=GenerateConfig(reasoning_effort="high", max_tokens=300000))
    with pytest.raises(RuntimeError):
        await model.api.generate([ChatMessageUser(content="Hello")], [], "auto", model.config)
    rejected = json.loads((tmp_path / "calls.jsonl").read_text().splitlines()[-1])["rejected_response"][field]
    assert (rejected["effort"] == value["effort"] if field == "reasoning" else rejected == value)
    await model.api.aclose()
