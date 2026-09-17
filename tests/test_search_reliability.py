from __future__ import annotations

import json
import ssl

import httpx
import pytest

from evalclaw.construction import research as builder
from evalclaw.planning import task_planner as planner
from evalclaw.protocols.tool import ToolCall
from evalclaw.quality import contamination, contamination_tools
from evalclaw.research import backends
from evalclaw.types import BenchmarkConfig, ContaminationItemResult
from tests.test_contamination import _call, _config, _done, _model, _task_suite


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_http_failure_is_not_retried(monkeypatch, status):
    attempts = []
    monkeypatch.setattr(backends.time, "sleep", lambda _: pytest.fail("unexpected retry"))

    def post(client, url, **kwargs):
        attempts.append(client)
        return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(backends.SearchBackendError) as raised:
        backends.GeminiBackend(api_key="test").search_or_raise("query")
    assert raised.value.retryable is False
    assert raised.value.attempts == 1
    assert len(attempts) == 1
    assert attempts[0].is_closed


@pytest.mark.parametrize("failure", ["ssl_eof", "timeout", 429, 500, 502, 503, 504])
def test_retry_recovers_after_old_limit_with_same_client(monkeypatch, failure):
    attempts, delays = [], []
    monkeypatch.setattr(backends.time, "sleep", delays.append)

    def post(client, url, **kwargs):
        attempts.append(client)
        if len(attempts) <= 4:
            if failure == "ssl_eof":
                raise httpx.ConnectError("TLS peer closed during handshake")
            if failure == "timeout":
                raise httpx.ReadTimeout("read timed out")
            return httpx.Response(failure, request=httpx.Request("POST", url))
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "candidates": [{"content": {"parts": [{"text": "grounded answer"}]}}],
        })

    monkeypatch.setattr(httpx.Client, "post", post)
    result = backends.GeminiBackend(api_key="test").search_or_raise("query")
    assert result.content == "grounded answer"
    assert len(attempts) == 5
    assert all(client is attempts[0] for client in attempts)
    assert attempts[0].is_closed
    assert len(delays) == 4
    assert all(cap / 2 <= delay <= cap for delay, cap in zip(delays, [2, 4, 8, 16]))


def test_exhaustion_respects_configured_attempts_and_jitter_cap(monkeypatch):
    monkeypatch.setenv("GEMINI_SEARCH_MAX_ATTEMPTS", "10")
    monkeypatch.setenv("GEMINI_SEARCH_RETRY_MAX_DELAY_S", "3")
    attempts, delays = [], []
    monkeypatch.setattr(backends.time, "sleep", delays.append)

    def post(client, url, **kwargs):
        attempts.append(client)
        raise httpx.ConnectError("TLS EOF")

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(backends.SearchBackendError) as raised:
        backends.GeminiBackend(api_key="test").search_or_raise("query")
    assert len(attempts) == raised.value.attempts == 10
    assert raised.value.retryable is True
    assert isinstance(raised.value.__cause__, httpx.ConnectError)
    assert len(delays) == 9
    assert 1 <= delays[0] <= 2
    assert all(1.5 <= delay <= 3 for delay in delays[1:])
    assert attempts[0].is_closed


def test_certificate_verification_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(backends.time, "sleep", lambda _: pytest.fail("unexpected retry"))

    def post(client, url, **kwargs):
        try:
            raise ssl.SSLCertVerificationError("untrusted certificate")
        except ssl.SSLCertVerificationError as cause:
            raise httpx.ConnectError("TLS handshake failed") from cause

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(backends.SearchBackendError) as raised:
        backends.GeminiBackend(api_key="test").search_or_raise("query")
    assert raised.value.retryable is False
    assert raised.value.attempts == 1


@pytest.mark.parametrize("name,value", [
    ("GEMINI_SEARCH_MAX_ATTEMPTS", "0"),
    ("GEMINI_SEARCH_MAX_ATTEMPTS", "wrong"),
    ("GEMINI_SEARCH_RETRY_MAX_DELAY_S", "nan"),
    ("GEMINI_SEARCH_RETRY_MAX_DELAY_S", "inf"),
    ("GEMINI_SEARCH_RETRY_MAX_DELAY_S", "-1"),
])
def test_invalid_retry_configuration_is_explicit(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(backends.SearchConfigurationError):
        backends.GeminiBackend(api_key="test")


@pytest.mark.parametrize("consumer", ["planner", "builder", "contamination"])
@pytest.mark.parametrize("outcome", ["network_failure", "missing_key", "empty", "success"])
def test_search_tools_distinguish_failure_from_empty_results(monkeypatch, tmp_path, consumer, outcome):
    def search(query, **kwargs):
        assert kwargs["raise_on_error"] is True
        if outcome == "network_failure":
            raise backends.SearchBackendError("TLS EOF", retryable=True, attempts=8)
        if outcome == "missing_key":
            raise backends.SearchConfigurationError("Missing API key")
        if outcome == "success":
            return backends.SearchResult(content="Evidence", citations=[])
        return None

    modules = {"planner": planner, "builder": builder, "contamination": contamination_tools}
    monkeypatch.setattr(modules[consumer], "web_search", search)
    call = ToolCall(id="query-1", name="search_web", arguments={"query": "original query"})
    config = BenchmarkConfig(use_web_research=True)
    if consumer == "planner":
        result = planner._execute_planner_tool(call, config, max_chars=1000, source_materials={})
    elif consumer == "builder":
        result = builder._execute_task_builder_tool(call, config, max_chars=1000)
    else:
        item = _task_suite().tasks[0]
        record = ContaminationItemResult(item_id=item.id, status="no_confirmed_match")
        tools = contamination_tools.ContaminationResearchTools(item, config, record, tmp_path)
        result = tools.dispatch(call)

    if outcome in ("network_failure", "missing_key"):
        assert result.error == "search_failed"
        payload = json.loads(result.content)
        assert payload == result.raw
        assert payload["query"] == "original query"
        assert payload["retryable"] is (outcome == "network_failure")
        assert payload["attempts"] == (8 if outcome == "network_failure" else None)
    elif outcome == "empty":
        assert result.error in (None, "no_search_result")
    else:
        assert result.error is None
        assert json.loads(result.content)["content"] == "Evidence"


def test_exhausted_search_is_preserved_in_contamination_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(backends.time, "sleep", lambda _: None)

    def post(client, url, **kwargs):
        raise httpx.ConnectError("TLS EOF")

    monkeypatch.setattr(httpx.Client, "post", post)
    _model(monkeypatch, [[_call("search_web", query="original query")], _done()])
    report = contamination.evaluate_contamination(
        "Goal", _task_suite(), _config(), trace_dir=tmp_path, log=lambda _: None,
    )
    assert report.items[0].status == "failed"
    assert report.items[0].queries == ["original query"]
    assert report.conditional_score is None
    evidence = json.loads((tmp_path / "item-0001/research.json").read_text())
    result = evidence["tool_trace"][0]["result"]
    assert result["error"] == "search_failed"
    assert result["raw"]["query"] == "original query"
    assert result["raw"]["attempts"] == 8
    assert result["raw"]["retryable"] is True
