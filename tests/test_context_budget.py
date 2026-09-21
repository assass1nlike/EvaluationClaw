import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from evalclaw.models import llm
from evalclaw.models.context_budget import LLMContextWindowError, context_window_error


def overflow(inputs, output, *, limit=1048576):
    return {"error": {"type": "invalid_request_error", "code": "invalid_request_error", "message":
        f"This model's maximum context length is {limit} tokens. However, you requested "
        f"{inputs + output} tokens ({inputs} in the messages, {output} in the completion). "
        "Please reduce the length of the messages or completion."}}


def http_error(payload, status=400):
    response = httpx.Response(status, json=payload, request=httpx.Request("POST", "https://model.example/v1"))
    return httpx.HTTPStatusError("request failed", request=response.request, response=response)


@pytest.mark.parametrize("inputs", [944637, 704140, 666463])
def test_exact_provider_counts_adjust_output_without_altering_input(monkeypatch, tmp_path, inputs):
    calls = []
    @contextmanager
    def stream(method, url, **kwargs):
        body = kwargs["json"]
        calls.append(json.loads(json.dumps(body)))
        request = httpx.Request(method, url)
        if len(calls) == 1:
            yield httpx.Response(400, json=overflow(inputs, body["max_tokens"]), request=request)
        else:
            chunk = {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
            yield httpx.Response(200, text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n", request=request)
    monkeypatch.setattr(llm.httpx, "stream", stream)
    body = {"model": "deepseek-flash", "messages": [{"role": "user", "content": "Evidence"}], "max_tokens": 393216}
    result = llm._post_streaming_openai_compatible("https://model.example/v1", {}, body, max_retries=1, trace_dir=tmp_path)
    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 2
    assert calls[1]["messages"] == calls[0]["messages"]
    assert calls[1]["max_tokens"] == 1048576 - inputs - 1024
    assert body["max_tokens"] == calls[1]["max_tokens"]
    traces = [json.loads(p.read_text()) for p in tmp_path.glob("*.json")]
    assert sorted(t["status"] for t in traces) == ["completed", "failed"]


def test_sdk_route_obeys_the_same_remaining_window(monkeypatch):
    calls = []
    def completion(**kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise http_error(overflow(944637, kwargs["max_tokens"]))
        return iter([{"choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}]}])
    kwargs = {"model": "deepseek-flash", "messages": [], "max_tokens": 393216}
    result, _ = llm._stream_litellm_response(SimpleNamespace(completion=completion), kwargs)
    assert result["choices"][0]["message"]["content"] == "ok"
    assert calls[1]["max_tokens"] == 102915


def test_insufficient_room_is_typed_and_does_not_fail_over():
    error = context_window_error(http_error(overflow(1040000, 393216)), 393216)
    with pytest.raises(LLMContextWindowError):
        llm.remaining_output(error, 393216)
    assert not llm._is_failover_eligible(error)


@pytest.mark.parametrize("payload,status", [
    ({"error": {"message": "context token error", "code": "invalid_request_error"}}, 400),
    (overflow(944637, 393216), 429),
    ({"error": {"type": "invalid_request_error", "code": "invalid_request_error", "message":
      "This model's maximum context length is 1048576 tokens. However, you requested 2000000 tokens "
      "(944637 in the messages, 393216 in the completion). Please reduce the length of the messages or completion."}}, 400),
])
def test_unrelated_or_inconsistent_errors_are_not_reclassified(payload, status):
    assert context_window_error(http_error(payload, status), 393216) is None


def test_provider_typed_error_without_counts_requests_context_reduction():
    error = context_window_error(http_error({"error": {"code": "context_length_exceeded", "message": "Too large"}}), 100)
    with pytest.raises(LLMContextWindowError):
        llm.remaining_output(error, 100)


def test_responses_context_error_is_available_to_caller_and_saved(monkeypatch, tmp_path):
    @contextmanager
    def stream(method, url, **kwargs):
        yield httpx.Response(400, json={"error": {"code": "context_length_exceeded", "message": "Too large"}},
                             request=httpx.Request(method, url))
    monkeypatch.setattr(llm.httpx, "stream", stream)
    with pytest.raises(LLMContextWindowError):
        llm._post_streaming_responses("https://model.example/v1/responses", {}, {"max_output_tokens": 32768}, trace_dir=tmp_path)
    traces = list(tmp_path.glob("*.json"))
    assert len(traces) == 1
    assert json.loads(traces[0].read_text())["response"]["status_code"] == 400


def test_output_truncation_does_not_restore_a_rejected_reservation(monkeypatch):
    calls = []
    def stream(url, headers, body, **kwargs):
        calls.append(dict(body))
        body["max_tokens"] = 102915
        return {"choices": [{"message": {"role": "assistant", "content": "partial"}, "finish_reason": "length"}]}
    monkeypatch.setattr(llm, "_post_streaming_openai_compatible", stream)
    with pytest.raises(llm.LLMOutputTruncatedError):
        llm.call_orchestrator_with_tools([{"role": "user", "content": "Evidence"}],
            model="deepseek-flash", provider="openai_compatible", base_url="https://model.example/v1", api_key="test")
    assert len(calls) == 1
