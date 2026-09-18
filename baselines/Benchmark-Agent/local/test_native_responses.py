import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from openai.types.responses import Response

from local.run_with_usage import UsageRecorder, observe_calls
from utils import llm_caller, native_responses


def response(status="completed", searched=True):
    output = [{"type": "message", "id": "msg_test", "role": "assistant", "status": status,
               "content": [{"type": "output_text", "text": '{"answer":"Evidence-based summary"}',
                            "annotations": []}]}]
    if searched:
        output.insert(0, {"type": "web_search_call", "id": "ws_test", "status": "completed",
                          "action": {"type": "search", "query": "test",
                                     "sources": [{"type": "url", "url": "https://example.org"}]}})
    return Response.model_validate({
        "id": "resp_test", "object": "response", "created_at": 1,
        "model": "gpt-5.6-luna", "status": status, "error": None,
        "incomplete_details": {"reason": "content_filter"} if status != "completed" else None,
        "instructions": None, "metadata": {}, "output": output,
        "parallel_tool_calls": True, "temperature": 0.3, "tool_choice": "required",
        "tools": [], "top_p": 1.0,
        "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25,
                  "input_tokens_details": {"cached_tokens": 10},
                  "output_tokens_details": {"reasoning_tokens": 2}},
        "tool_usage": {"web_search": {"num_requests": 1 if searched else 0}},
    })


def test_transport_preserves_prompts_images_and_native_tool(monkeypatch):
    seen = {}
    result = response()

    def create(**kwargs):
        seen["request"] = kwargs
        return result

    def client(**kwargs):
        seen["client"] = kwargs
        return nullcontext(SimpleNamespace(responses=SimpleNamespace(create=create)))

    monkeypatch.setattr(native_responses, "OpenAI", client)
    original = [{"role": "system", "content": "Keep the original prompt."},
                {"role": "user", "content": [{"type": "text", "text": "Question"},
                  {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]}]
    tools = [{"type": "web_search", "search_context_size": "medium"}]
    returned = native_responses.responses_completion(
        model="openai/responses/gpt-5.6-luna", messages=original,
        api_key="search-secret", base_url="https://search.example/v1", max_tokens=12000,
        timeout=180, request_timeout=180, tools=tools, tool_choice="required", temperature=0.3)
    assert returned is result
    assert 0 < seen["client"].pop("timeout") <= 180
    assert seen["client"] == {"api_key": "search-secret", "base_url": "https://search.example/v1",
                              "max_retries": 0}
    request = seen["request"]
    assert request["model"] == "gpt-5.6-luna"
    assert request["input"][0] == original[0]
    assert request["input"][1]["content"] == [
        {"type": "input_text", "text": "Question"},
        {"type": "input_image", "image_url": "data:image/png;base64,abc", "detail": "auto"},
    ]
    assert original[1]["content"][1]["type"] == "image_url"
    assert request["tools"] is tools and request["tool_choice"] == "required"
    assert request["max_output_tokens"] == 12000 and "temperature" not in request


@pytest.mark.parametrize("first", [response(status="incomplete"), response(searched=False)])
def test_incomplete_or_missing_search_retries_and_keeps_all_usage(monkeypatch, tmp_path, first):
    seen = []
    replies = iter([first, response()])

    def create(**kwargs):
        seen.append(kwargs)
        return next(replies)

    monkeypatch.setattr(native_responses, "request_response", create)
    recorder = UsageRecorder(tmp_path)
    with observe_calls(recorder):
        result = llm_caller.llm_call_json(
            model="openai/responses/gpt-5.6-luna", system_prompt="test", user_prompt="test",
            extra_create_params={"api_key": "search-secret", "base_url": "https://search.example/v1",
                                 "timeout": 180, "request_timeout": 180,
                                 "tools": [{"type": "web_search"}], "tool_choice": "required"})
    assert result["ok"] and result["json"] == {"answer": "Evidence-based summary"}
    assert len(seen) == 2
    assert all(call["api_key"] == "search-secret" for call in seen)
    assert all(call["max_output_tokens"] == 12000 for call in seen)
    assert all(0 < call["timeout"] <= 180 for call in seen)
    assert recorder.summary["reported_tokens"] == {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}
    assert recorder.summary["calls_with_incomplete_usage"] == 0
    events = [json.loads(line) for line in (recorder.directory / "calls.jsonl").read_text().splitlines()]
    assert events[0]["response_status"] == first.status
    assert events[1]["usage"]["input_tokens_details"]["cached_tokens"] == 10
    assert events[1]["web_search_calls"][0]["action"]["sources"][0]["url"] == "https://example.org"
    assert events[1]["tool_usage"]["web_search"]["num_requests"] == 1


def test_original_chat_route_and_credentials_stay_separate(monkeypatch):
    seen = []
    monkeypatch.setattr(llm_caller, "get_api_key", lambda path: "deepseek-secret")
    monkeypatch.setattr(llm_caller, "get_api_base_url", lambda path: "https://api.deepseek.com")

    def completion(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])

    def unexpected(**kwargs):
        pytest.fail("DeepSeek must not use the Responses transport")

    monkeypatch.setattr(llm_caller, "completion", completion)
    monkeypatch.setattr(llm_caller, "responses_completion", unexpected)
    assert llm_caller.llm_call_json(model="openai/deepseek-flash", system_prompt="test", user_prompt="test",
                                  max_tokens=1500, extra_create_params={"max_tokens": 12000,
                                  "timeout": 90, "request_timeout": 90})["ok"]
    assert seen[0]["api_key"] == "deepseek-secret"
    assert seen[0]["base_url"] == "https://api.deepseek.com"
    assert seen[0]["max_tokens"] == 300000
    assert seen[0]["timeout"] == seen[0]["request_timeout"] == 7200
