import itertools
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, RateLimitError

from local.run_with_usage import UsageRecorder, observe_calls
from local.test_native_responses import response
from utils import llm_caller, native_responses as native


def limited(headers=None, code="rate_limit_exceeded"):
    http = httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://example.org/responses"))
    return RateLimitError("limited", response=http, body={"code": code, "message": "limited"})


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 0, "waits": []}

    def sleep(seconds):
        state["waits"].append(seconds)
        state["now"] += seconds

    monkeypatch.setattr(native.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(native.time, "sleep", sleep)
    monkeypatch.setattr(native.random, "uniform", lambda a, b: 0.25)
    monkeypatch.setattr(native, "_key_sequence", itertools.count())
    return state


def call(**overrides):
    arguments = dict(model="openai/responses/gpt-5.6-luna", messages=[{"role": "user", "content": "query"}],
                     api_key="key-one", api_keys=["key-one", "key-two", "key-three", "key-four"],
                     base_url="https://example.org", timeout=180, max_tokens=12000,
                     tools=[{"type": "web_search"}], tool_choice="required", temperature=0.3)
    return native.responses_completion(**(arguments | overrides))


def test_rotation_backoff_and_per_attempt_accounting(monkeypatch, tmp_path, clock):
    requests = []
    replies = iter([limited({"retry-after": "7"}), limited(), response()])

    def request(**kwargs):
        requests.append(kwargs)
        result = next(replies)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(native, "request_response", request)
    recorder = UsageRecorder(tmp_path)
    with observe_calls(recorder):
        assert call().status == "completed"
    assert clock["waits"] == [7.25, 4.25]
    assert [r["api_key"] for r in requests] == ["key-one", "key-two", "key-three"]
    assert all({k: v for k, v in r.items() if k not in ("api_key", "timeout")} ==
               {k: v for k, v in requests[0].items() if k not in ("api_key", "timeout")}
               for r in requests)
    assert recorder.summary["finished_calls"] == 3
    assert recorder.summary["failed_calls"] == recorder.summary["calls_with_incomplete_usage"] == 2
    assert recorder.summary["reported_tokens"]["total_tokens"] == 25
    records = [json.loads(line) for line in (recorder.directory / "calls.jsonl").read_text().splitlines()]
    assert len({r["credential_id"] for r in records}) == 3
    assert records[0]["rate_limit_headers"] == {"retry-after": "7"}
    assert records[0]["http_status"] == 429
    assert all(r["usage"] is None for r in records[:2])


@pytest.mark.parametrize("headers,expected", [
    ({"retry-after-ms": "1500"}, 1.75),
    ({"x-ms-retry-after-ms": "2500", "retry-after": "1"}, 2.75),
    ({"retry-after": "bad"}, 2.25),
    ({"retry-after": "nan"}, 2.25),
    ({"retry-after": "-1"}, 2.25),
])
def test_retry_headers(clock, headers, expected):
    assert native.retry_delay(limited(headers), 0, 2, 60) == expected


def test_http_date_and_server_delay_are_not_capped(clock, monkeypatch):
    monkeypatch.setattr(native.time, "time", lambda: 100)
    date = format_datetime(datetime.fromtimestamp(190, tz=timezone.utc), usegmt=True)
    assert native.retry_delay(limited({"retry-after": date}), 0, 2, 60) == 90.25


def test_delay_exceeding_total_budget_does_not_retry_early(clock, monkeypatch):
    requests = []
    error = limited({"retry-after": "181"})

    def request(**kwargs):
        requests.append(kwargs)
        raise error

    monkeypatch.setattr(native, "request_response", request)
    with pytest.raises(RateLimitError) as caught:
        call()
    assert caught.value is error
    assert len(requests) == 1 and clock["waits"] == []


def test_retry_exhaustion_not_multiplied_by_outer_json_loop(clock, monkeypatch):
    requests = []

    def request(**kwargs):
        requests.append(kwargs)
        raise limited()

    monkeypatch.setattr(native, "request_response", request)
    result = llm_caller.llm_call_json(
        model="openai/responses/gpt-5.6-luna", system_prompt="test", user_prompt="test",
        extra_create_params={"tools": [{"type": "web_search"}], "tool_choice": "required",
                             "api_key": "key-one", "api_keys": ["key-one", "key-two"],
                             "retry_config": {"rate_limit_attempts": 6, "retry_budget_seconds": 180}})
    assert not result["ok"]
    assert len(requests) == 6
    assert clock["waits"] == [2.25, 4.25, 8.25, 16.25, 32.25]


@pytest.mark.parametrize("error", [limited(code="insufficient_quota"), AuthenticationError(
    "invalid key", response=httpx.Response(401, request=httpx.Request("POST", "https://example.org")), body=None)])
def test_nontransient_errors_not_retried_by_transport(clock, monkeypatch, error):
    requests = []

    def request(**kwargs):
        requests.append(kwargs)
        raise error

    monkeypatch.setattr(native, "request_response", request)
    with pytest.raises(type(error)):
        call()
    assert len(requests) == 1 and clock["waits"] == []


def test_concurrent_requests_spread_across_keys(clock, monkeypatch):
    used = []

    def request(**kwargs):
        used.append(kwargs["api_key"])
        return response()

    monkeypatch.setattr(native, "request_response", request)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call(), range(40)))
    assert len(results) == 40
    assert {key: used.count(key) for key in set(used)} == dict.fromkeys(
        ["key-one", "key-two", "key-three", "key-four"], 10)
    assert clock["waits"] == []


def test_timeout_retries_then_uses_fallback_endpoint(clock, monkeypatch):
    requests = []

    def request(**kwargs):
        requests.append(kwargs)
        if kwargs["base_url"] == "https://primary.example":
            raise APITimeoutError("timed out")
        return response()

    monkeypatch.setattr(native, "request_response", request)
    result = call(
        base_url="https://primary.example",
        api_keys=["primary-key"],
        retry_config={"rate_limit_attempts": 2, "timeout_attempts": 2,
                      "retry_budget_seconds": 180, "global_concurrency": 0},
        fallback={"base_url": "https://fallback.example", "api_key": "fallback-key",
                  "retry_config": {"rate_limit_attempts": 2, "timeout_attempts": 2,
                                    "retry_budget_seconds": 180, "global_concurrency": 0}},
    )
    assert result.status == "completed"
    assert [request["base_url"] for request in requests] == [
        "https://primary.example", "https://primary.example", "https://fallback.example"
    ]
    assert [request["api_key"] for request in requests] == [
        "primary-key", "primary-key", "fallback-key"
    ]
