import asyncio
import json

import httpx
import litellm
from openai import OpenAI, AsyncOpenAI

from local.model_runtime import configure, configured_calls, request_parameters
from local.run_with_usage import UsageRecorder, observe_calls
from utils import core, llm_caller, native_responses
from utils.agent_utils import Agent


def test_async_agent_wire_preserves_thinking_across_tool_turns(monkeypatch, tmp_path):
    requests = []
    reasoning = "Use the lookup result before computing the answer."

    def server(request):
        requests.append(json.loads(request.content))
        message = {"role": "assistant", "content": "done", "reasoning_content": reasoning}
        if len(requests) == 1:
            message.update(content=None, tool_calls=[{"id": "call_1", "type": "function",
                           "function": {"name": "lookup", "arguments": "{}"}}])
        return httpx.Response(200, json={"id": "test", "created": 1, "model": "deepseek-flash",
            "object": "chat.completion", "choices": [{"index": 0, "message": message,
            "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    async def run():
        async with AsyncOpenAI(api_key="test", base_url="https://example.org/v1", max_retries=0,
                               http_client=httpx.AsyncClient(transport=httpx.MockTransport(server))) as client:
            async def call(**kwargs):
                return await litellm.acompletion(**kwargs, client=client)
            monkeypatch.setattr(core, "acompletion", call)
            chain = core.MetaChain()
            def lookup():
                """Return a value."""
                return "17"
            agent = Agent(model="openai/deepseek-flash", instructions="Use the tool", functions=[lookup])
            kwargs = dict(agent=agent, context_variables={}, model_override=None, stream=False, debug=False)
            recorder = UsageRecorder(tmp_path)
            with observe_calls(recorder), configured_calls():
                first = await chain.get_chat_completion_async(history=[{"role": "user", "content": "task"}], **kwargs)
                history = [{"role": "user", "content": "task"}, json.loads(first.choices[0].message.model_dump_json()),
                           {"role": "tool", "tool_call_id": "call_1", "content": "17"}]
                second = await chain.get_chat_completion_async(history=history, **kwargs)
            assert first.choices[0].message.reasoning_content == reasoning
            assert second.choices[0].message.content == "done"
            events = [json.loads(line) for line in (recorder.directory / "calls.jsonl").read_text().splitlines()]
            assert all(e["request_settings"]["thinking"] == {"type": "enabled"} for e in events)
            assert all(e["request_settings"]["reasoning_effort"] == "high" for e in events)
    asyncio.run(run())
    assert len(requests) == 2
    assert all(r["thinking"] == {"type": "enabled"} and r["reasoning_effort"] == "high" for r in requests)
    assert requests[1]["messages"][2]["reasoning_content"] == reasoning
    assert requests[1]["messages"][-1] == {"role": "tool", "tool_call_id": "call_1", "content": "17"}


def test_search_native_request_gets_high_and_keeps_payload(monkeypatch):
    seen = []
    reply = object()
    monkeypatch.setattr(native_responses, "request_response", lambda **kw: seen.append(kw) or reply)
    payload = {"model": "openai/responses/gpt-5.6-luna", "input": "original question",
               "tools": [{"type": "web_search"}], "tool_choice": "required"}
    with configured_calls():
        assert native_responses.request_response(**payload) is reply
    assert seen == [{**payload, "reasoning": {"effort": "high"}}]


def test_qwen_settings_and_other_models():
    assert request_parameters("qwen3.8-27b") == {"reasoning_effort": "high", "extra_body": {"enable_thinking": True}}
    assert request_parameters("gpt-5.6-sol") == {}
    seen = []
    call = configure(lambda **kw: seen.append(kw))
    call(model="openai/deepseek-flash", messages=[], extra_body={"thinking": {"type": "disabled"}, "other": 7})
    assert seen[0]["extra_body"] == {"thinking": {"type": "enabled"}, "reasoning_effort": "high", "other": 7}
