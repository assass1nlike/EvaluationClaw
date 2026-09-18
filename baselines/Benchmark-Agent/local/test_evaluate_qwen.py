from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError, AuthenticationError

from local.evaluate_qwen import request_with_retry, score, empty_answer, EmptyAnswerError


def test_retry_preserves_request(monkeypatch):
    monkeypatch.setattr("local.evaluate_qwen.time.sleep", lambda _: None)
    requests = []
    messages = [{"role": "user", "content": "task"}]

    def call(**kwargs):
        requests.append(kwargs)
        if len(requests) < 3:
            raise RateLimitError("limited", response=httpx.Response(429,
                request=httpx.Request("POST", "https://example.org")), body=None)
        return "success"

    assert request_with_retry(call, model="qwen3.8-27b", messages=messages, seed=42) == "success"
    assert requests == [dict(model="qwen3.8-27b", messages=messages, seed=42)] * 3


def test_authentication_error_is_not_retried():
    calls = []

    def call(**kwargs):
        calls.append(kwargs)
        raise AuthenticationError("invalid", response=httpx.Response(401,
            request=httpx.Request("POST", "https://example.org")), body=None)

    with pytest.raises(AuthenticationError):
        request_with_retry(call, model="qwen3.8-27b")
    assert len(calls) == 1


def test_empty_answer_retries_unchanged_then_succeeds(monkeypatch):
    monkeypatch.setattr("local.evaluate_qwen.time.sleep", lambda _: None)
    requests = []
    def call(**kwargs):
        requests.append(kwargs)
        if len(requests) < 3:
            raise EmptyAnswerError()
        return "answer"
    payload = {"model": "gpt-5.6-sol", "messages": [{"role": "user", "content": "task"}]}
    assert request_with_retry(call, **payload) == "answer"
    assert requests == [payload] * 3


def test_empty_answer_exhaustion_is_failure(monkeypatch):
    monkeypatch.setattr("local.evaluate_qwen.time.sleep", lambda _: None)
    calls = []
    def call(**kwargs):
        calls.append(kwargs)
        raise EmptyAnswerError()
    with pytest.raises(EmptyAnswerError):
        request_with_retry(call, model="gpt-5.6-sol")
    assert len(calls) == 6


@pytest.mark.parametrize("content,finish,refusal,expected", [
    (None, "stop", None, True), ("  ", "stop", None, True),
    ("A", "stop", None, False), (None, "length", None, False),
    (None, "stop", "refused", False), (None, "content_filter", None, False),
])
def test_empty_response_detection_preserves_truncation_and_refusal(content, finish, refusal, expected):
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
        message=SimpleNamespace(content=content, refusal=refusal, tool_calls=None))])
    assert empty_answer(response) is expected


def test_usage_preserves_chat_counts_when_gateway_also_sends_zero_response_counts(tmp_path):
    from local.run_with_usage import UsageRecorder
    recorder = UsageRecorder(tmp_path)
    response = SimpleNamespace(usage={"prompt_tokens": 55, "completion_tokens": 0,
                                     "total_tokens": 55, "input_tokens": 0, "output_tokens": 0})
    recorder.record("test", "gpt-5.6-sol", response=response)
    assert recorder.summary["reported_tokens"] == {"prompt_tokens": 55, "completion_tokens": 0, "total_tokens": 55}


def test_scoring_preserves_strict_choice_and_incomplete_handling():
    def judge(**kwargs):
        pytest.fail("Choice and incomplete answers must not call the judge")
    item = {"sample": {"input": {"question": "task"}, "output": {"answer": "A"}}}
    result = score(item, {"answer_type": "choice"}, {"prediction": "Answer: A", "finish_reason": "stop"}, judge)
    assert result["status"] == "scored" and result["correct"] is False
    result = score(item, {"answer_type": "choice"}, {"prediction": "A", "finish_reason": "length"}, judge)
    assert result["status"] == "incomplete_response" and "correct" not in result


def test_judge_receives_original_reference_and_candidate():
    import json
    seen = []
    class Response:
        choices = [SimpleNamespace(message=SimpleNamespace(content='{"correct": true, "reason": "matches"}'), finish_reason="stop")]
        def model_dump(self, **kwargs):
            return {}
    def judge(**kwargs):
        seen.append(kwargs)
        return Response()
    item = {"sample": {"input": {"question": "task"}, "output": {"answer": "reference"}}}
    result = score(item, {"answer_type": "free_form"}, {"prediction": "candidate", "finish_reason": "stop"}, judge)
    assert result["correct"] is True
    payload = json.loads(seen[0]["messages"][1]["content"])
    assert payload == {"task_input": item["sample"]["input"], "reference_output": item["sample"]["output"], "candidate_response": "candidate"}
