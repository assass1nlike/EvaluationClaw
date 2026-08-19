"""Tests for Azure OpenAI provider support and the pluggable search backends.

Follows the monkeypatch style of tests/test_core_smoke.py: no real network.
"""
from __future__ import annotations

import pytest

from evalclaw.models import llm
from evalclaw.models.providers import default_api_key, infer_provider, target_from_model
from evalclaw.research import backends
from evalclaw.research.backends import (
    GeminiBackend,
    KeylessBackend,
    NoneBackend,
    SearchResult,
    get_backend,
    resolve_backend_name,
)
from evalclaw.types import Message, TargetModelConfig


@pytest.fixture(autouse=True)
def _isolate_research_network_state():
    backends._reset_network_state_for_tests()
    yield
    backends._reset_network_state_for_tests()


# ---------------------------------------------------------------------------
# Azure provider inference / credentials
# ---------------------------------------------------------------------------
def test_infer_provider_azure_name() -> None:
    provider, base = infer_provider("azure/my-gpt4o-deployment")
    assert provider == "azure"
    assert base is None


def test_infer_provider_azure_ignores_base_url() -> None:
    # Azure routing must win even if a base_url is passed, so the model string
    # stays unmangled for LiteLLM's native azure/ support.
    provider, base = infer_provider("azure/dep", base_url="https://x.example.com")
    assert provider == "azure"
    assert base is None


def test_default_api_key_azure(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_API_KEY", "azkey")
    assert default_api_key("azure", "azure/dep") == "azkey"


def test_default_api_key_azure_alias(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "aliaskey")
    assert default_api_key("azure", "azure/dep") == "aliaskey"


def test_default_api_key_generic_openai_compatible(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "relay-key")

    assert default_api_key("openai_compatible", "gpt-5.6-luna") == "relay-key"


def test_target_from_model_azure(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_API_KEY", "azkey")
    target = target_from_model("azure/my-dep")
    assert target.provider == "azure"
    assert target.model == "azure/my-dep"  # unmangled
    assert target.api_key == "azkey"
    assert target.base_url is None


# ---------------------------------------------------------------------------
# Azure legacy (non-litellm) backend behaviour
# ---------------------------------------------------------------------------
def test_azure_legacy_completion_builds_url(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_API_BASE", "https://res.openai.azure.com")
    monkeypatch.setenv("AZURE_API_VERSION", "2024-06-01")
    monkeypatch.setenv("AZURE_API_KEY", "azkey")

    captured: dict = {}

    def fake_post(url, headers, body, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        return {"choices": [{"message": {"content": "hi from azure"}}]}

    monkeypatch.setattr(llm, "_post_with_retry", fake_post)

    out = llm.call_llm(
        [Message(role="user", content="hello")],
        model="azure/my-dep",
        backend="legacy",
    )
    assert out == "hi from azure"
    assert captured["url"] == (
        "https://res.openai.azure.com/openai/deployments/my-dep"
        "/chat/completions?api-version=2024-06-01"
    )
    assert captured["headers"]["api-key"] == "azkey"


def test_is_reasoning_model() -> None:
    assert llm._is_reasoning_model("azure/gpt-5.5")
    assert llm._is_reasoning_model("gpt-5.5")
    assert llm._is_reasoning_model("o3-mini")
    assert llm._is_reasoning_model("deepseek-reasoner")
    assert not llm._is_reasoning_model("azure/gpt-4o")
    assert not llm._is_reasoning_model("gpt-4o-mini")
    assert not llm._is_reasoning_model("claude-opus-4-6")


def test_effective_max_tokens_floors_reasoning_models() -> None:
    assert llm._effective_max_tokens("azure/gpt-5.5", 4096) == llm._REASONING_MAX_TOKENS_FLOOR
    assert llm._effective_max_tokens("azure/gpt-5.5", 32000) == 32000
    assert llm._effective_max_tokens("azure/gpt-4o", 4096) == 4096


def test_effective_max_tokens_respects_explicit_low_effort(monkeypatch) -> None:
    monkeypatch.setenv("EVALCLAW_REASONING_EFFORT", "low")

    assert llm._effective_max_tokens("gpt-5.6-luna", 1024) == 1024


def test_legacy_orchestrator_tools_forward_reasoning_effort(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, headers, body, **kwargs):
        captured.update(body)
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "ok", "tool_calls": []}}
            ]
        }

    monkeypatch.setenv("EVALCLAW_REASONING_EFFORT", "low")
    monkeypatch.setattr(llm, "_post_with_retry", fake_post)

    llm.call_orchestrator_with_tools(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-luna",
        api_key="test-key",
        base_url="https://model.example/v1",
        backend="legacy",
        tools=[],
    )

    assert captured["reasoning_effort"] == "low"


def test_azure_legacy_reasoning_model_uses_max_completion_tokens(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_API_BASE", "https://res.openai.azure.com")
    monkeypatch.setenv("AZURE_API_VERSION", "2024-06-01")
    monkeypatch.setenv("AZURE_API_KEY", "azkey")

    captured: dict = {}

    def fake_post(url, headers, body, **kwargs):
        captured["body"] = body
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(llm, "_post_with_retry", fake_post)

    llm.call_llm(
        [Message(role="user", content="hello")],
        model="azure/gpt-5.5",
        backend="legacy",
    )
    assert "max_tokens" not in captured["body"]
    assert captured["body"]["max_completion_tokens"] == llm._REASONING_MAX_TOKENS_FLOOR


class _FakeChoice:
    def __init__(self, finish_reason: str, text: str) -> None:
        self.finish_reason = finish_reason
        self.message = type("M", (), {"content": text})()


class _FakeLitellmResponse:
    def __init__(self, finish_reason: str, text: str) -> None:
        self.choices = [_FakeChoice(finish_reason, text)]


def test_call_litellm_retries_on_truncation(monkeypatch) -> None:
    import litellm as _litellm

    budgets: list[int] = []

    def fake_completion(**kwargs):
        budgets.append(kwargs["max_tokens"])
        if len(budgets) == 1:
            return _FakeLitellmResponse("length", "partial")
        return _FakeLitellmResponse("stop", "full text")

    monkeypatch.setattr(_litellm, "completion", fake_completion)
    out = llm._call_litellm(
        model="azure/gpt-5.5",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=4096,
    )
    assert out == "full text"
    assert budgets == [llm._REASONING_MAX_TOKENS_FLOOR, llm._REASONING_MAX_TOKENS_FLOOR * 2]


def test_call_litellm_raises_when_still_truncated(monkeypatch) -> None:
    import litellm as _litellm

    monkeypatch.setattr(
        _litellm, "completion", lambda **kw: _FakeLitellmResponse("length", "partial")
    )
    with pytest.raises(RuntimeError, match="truncated"):
        llm._call_litellm(
            model="azure/gpt-4o",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=1024,
        )


def test_call_litellm_reduced_effort_disables_deepseek_thinking(monkeypatch) -> None:
    import litellm as _litellm

    requests: list[dict] = []

    def fake_completion(**kwargs):
        requests.append(kwargs)
        return _FakeLitellmResponse("stop", "complete task")

    monkeypatch.setattr(_litellm, "completion", fake_completion)

    result = llm._call_litellm(
        model="deepseek-v4-pro",
        messages=[{"role": "user", "content": "build one task"}],
        max_tokens=16384,
        reduce_reasoning_effort=True,
    )

    assert result == "complete task"
    assert requests[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_call_litellm_deepseek_json_matches_direct_structured_mode(monkeypatch) -> None:
    import litellm as _litellm

    requests: list[dict] = []

    def fake_completion(**kwargs):
        requests.append(kwargs)
        return _FakeLitellmResponse("stop", '{"plan": {}}')

    monkeypatch.setattr(_litellm, "completion", fake_completion)

    result = llm._call_litellm(
        model="deepseek-v4-pro",
        messages=[{"role": "user", "content": "Return pure JSON only."}],
        max_tokens=16384,
    )

    assert result == '{"plan": {}}'
    assert requests[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert requests[0]["response_format"] == {"type": "json_object"}


def test_call_litellm_custom_openai_endpoint_uses_json_mode(monkeypatch) -> None:
    import litellm as _litellm

    requests: list[dict] = []

    def fake_completion(**kwargs):
        requests.append(kwargs)
        return _FakeLitellmResponse("stop", '{"tasks": []}')

    monkeypatch.setattr(_litellm, "completion", fake_completion)

    result = llm._call_litellm(
        model="gpt-5.6-luna",
        messages=[{"role": "user", "content": "Return one JSON object."}],
        max_tokens=16384,
        base_url="https://openai-compatible.example/v1",
    )

    assert result == '{"tasks": []}'
    assert requests[0]["response_format"] == {"type": "json_object"}


def test_azure_legacy_retries_then_raises_on_truncation(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_API_BASE", "https://res.openai.azure.com")
    monkeypatch.setenv("AZURE_API_VERSION", "2024-06-01")
    monkeypatch.setenv("AZURE_API_KEY", "azkey")

    budgets: list[int] = []

    def fake_post(url, headers, body, **kwargs):
        budgets.append(body["max_completion_tokens"])
        return {
            "choices": [
                {"finish_reason": "length", "message": {"content": "partial"}}
            ]
        }

    monkeypatch.setattr(llm, "_post_with_retry", fake_post)

    with pytest.raises(RuntimeError, match="truncated"):
        llm.call_llm(
            [Message(role="user", content="hello")],
            model="azure/gpt-5.5",
            backend="legacy",
        )
    assert budgets == [llm._REASONING_MAX_TOKENS_FLOOR, llm._REASONING_MAX_TOKENS_FLOOR * 2]


def test_azure_legacy_completion_missing_env_raises(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_API_BASE", raising=False)
    monkeypatch.delenv("AZURE_API_VERSION", raising=False)
    with pytest.raises(RuntimeError, match="Azure OpenAI models require"):
        llm.call_llm(
            [Message(role="user", content="hello")],
            model="azure/my-dep",
            backend="legacy",
        )


def test_call_target_model_azure_legacy(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_API_BASE", "https://res.openai.azure.com")
    monkeypatch.setenv("AZURE_API_VERSION", "2024-06-01")
    monkeypatch.setenv("AZURE_API_KEY", "azkey")

    def fake_post(url, headers, body, **kwargs):
        assert "deployments/dep2" in url
        return {"choices": [{"message": {"content": "target azure"}}]}

    monkeypatch.setattr(llm, "_post_with_retry", fake_post)
    target = TargetModelConfig(provider="azure", model="azure/dep2", api_key="azkey")
    out = llm.call_target_model("q", target, backend="legacy")
    assert out == "target azure"


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
def test_resolve_backend_name_explicit_wins(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    assert resolve_backend_name("keyless") == "keyless"
    assert resolve_backend_name("none") == "none"
    assert resolve_backend_name("gemini") == "gemini"


def test_resolve_backend_name_auto_prefers_gemini_when_key(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    assert resolve_backend_name("auto") == "gemini"


def test_resolve_backend_name_auto_keyless_without_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert resolve_backend_name("auto") == "keyless"
    assert resolve_backend_name(None) == "keyless"


def test_resolve_backend_name_invalid_falls_back_to_auto(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert resolve_backend_name("bogus") == "keyless"


def test_get_backend_types(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(get_backend("none"), NoneBackend)
    assert isinstance(get_backend("keyless"), KeylessBackend)
    assert isinstance(get_backend("gemini"), GeminiBackend)
    assert isinstance(get_backend("auto"), KeylessBackend)  # no key -> keyless


def test_none_backend_returns_none() -> None:
    assert NoneBackend().search("anything") is None


# ---------------------------------------------------------------------------
# Keyless backend parsing (monkeypatched httpx)
# ---------------------------------------------------------------------------
ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678v1</id>
    <title>Tax Law Reasoning in Language Models</title>
    <summary>We study how models reason
    about tax law and deductions.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2222.1111v1</id>
    <title>Second Paper</title>
    <summary>Another abstract.</summary>
  </entry>
</feed>"""

WIKI_OPENSEARCH = [
    "tax law",
    ["Tax law"],
    ["Overview of taxation law."],
    ["https://en.wikipedia.org/wiki/Tax_law"],
]

DDG_HTML = (
    '<div><a class="result__a" href="https://example.com/tax">'
    "Tax Guide &amp; Tips</a>"
    '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2F'
    'www.irs.gov%2Ftax-code&amp;rut=abc123">IRS Tax Code</a></div>'
)


class _FakeResponse:
    def __init__(self, *, text: str = "", json_data=None) -> None:
        self._text = text
        self._json = json_data

    @property
    def text(self) -> str:
        return self._text

    def json(self):
        return self._json

    def raise_for_status(self) -> None:
        return None


def _fake_get_factory(*, fail: set[str] | None = None):
    fail = fail or set()

    def fake_get(url, *args, **kwargs):
        if "export.arxiv.org" in url:
            if "arxiv" in fail:
                raise RuntimeError("arxiv down")
            return _FakeResponse(text=ARXIV_ATOM)
        if "wikipedia.org/w/api.php" in url:
            if "wiki" in fail:
                raise RuntimeError("wiki down")
            return _FakeResponse(json_data=WIKI_OPENSEARCH)
        if "duckduckgo" in url:
            if "ddg" in fail:
                raise RuntimeError("ddg down")
            return _FakeResponse(text=DDG_HTML)
        raise AssertionError(f"unexpected url {url}")

    return fake_get


def test_keyless_backend_parses_all_sources(monkeypatch) -> None:
    monkeypatch.setattr(backends.httpx, "get", _fake_get_factory())
    result = KeylessBackend().search("tax law reasoning")
    assert isinstance(result, SearchResult)
    urls = [c["url"] for c in result.citations]
    assert "http://arxiv.org/abs/1234.5678v1" in urls
    assert "https://en.wikipedia.org/wiki/Tax_law" in urls
    assert "https://example.com/tax" in urls
    # arXiv summary whitespace collapsed into content
    assert "reason about tax law" in result.content
    # DuckDuckGo title HTML entities decoded/stripped
    ddg = next(c for c in result.citations if c["url"] == "https://example.com/tax")
    assert ddg["title"] == "Tax Guide & Tips"
    # DuckDuckGo protocol-relative redirect links resolved to the real target
    assert "https://www.irs.gov/tax-code" in urls


def test_resolve_ddg_url() -> None:
    resolve = KeylessBackend._resolve_ddg_url
    assert (
        resolve("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=xyz")
        == "https://example.com/a"
    )
    # Non-redirect URLs pass through untouched
    assert resolve("https://example.com/direct") == "https://example.com/direct"
    # Protocol-relative non-DDG URL gains a scheme
    assert resolve("//example.com/x") == "https://example.com/x"
    # Malformed uddg (not an http URL) falls back to the normalized link
    assert resolve("//duckduckgo.com/l/?uddg=javascript%3Aalert(1)").startswith(
        "https://duckduckgo.com/l/"
    )


def test_keyless_backend_degrades_when_one_source_fails(monkeypatch) -> None:
    monkeypatch.setattr(backends.httpx, "get", _fake_get_factory(fail={"ddg", "wiki"}))
    result = KeylessBackend().search("tax law")
    assert result is not None
    urls = [c["url"] for c in result.citations]
    assert urls == ["http://arxiv.org/abs/1234.5678v1", "http://arxiv.org/abs/2222.1111v1"]


def test_keyless_backend_returns_none_when_all_fail(monkeypatch) -> None:
    monkeypatch.setattr(
        backends.httpx, "get", _fake_get_factory(fail={"arxiv", "wiki", "ddg"})
    )
    assert KeylessBackend().search("tax law") is None


def test_keyless_backend_caches_repeated_queries(monkeypatch) -> None:
    calls: list[str] = []
    fake_get = _fake_get_factory()

    def counted_get(url, *args, **kwargs):
        calls.append(url)
        return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(backends.httpx, "get", counted_get)
    backend = KeylessBackend(min_source_interval_s=0)

    first = backend.search("tax law")
    second = backend.search("  TAX   law ")

    assert first == second
    assert len(calls) == 3


def test_keyless_backend_disables_forbidden_source_for_run(monkeypatch) -> None:
    calls: list[str] = []
    fake_get = _fake_get_factory()

    def wikipedia_forbidden(url, *args, **kwargs):
        calls.append(url)
        if "wikipedia.org" in url:
            return backends.httpx.Response(
                403,
                request=backends.httpx.Request("GET", url),
            )
        return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(backends.httpx, "get", wikipedia_forbidden)
    backend = KeylessBackend(min_source_interval_s=0)

    assert backend.search("first query") is not None
    assert backend.search("second query") is not None
    wikipedia_calls = [url for url in calls if "wikipedia.org" in url]
    assert len(wikipedia_calls) == 1


def test_keyless_backend_disables_timed_out_source_for_run(monkeypatch) -> None:
    wikipedia_calls = 0
    fake_get = _fake_get_factory()

    def wikipedia_timeout(url, *args, **kwargs):
        nonlocal wikipedia_calls
        if "wikipedia.org" in url:
            wikipedia_calls += 1
            raise backends.httpx.ConnectTimeout(
                "timed out",
                request=backends.httpx.Request("GET", url),
            )
        return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(backends.httpx, "get", wikipedia_timeout)
    backend = KeylessBackend(min_source_interval_s=0)

    assert backend.search("first query") is not None
    assert backend.search("second query") is not None
    assert wikipedia_calls == 1

    assert backend.search_or_raise("strict query") is not None
    assert wikipedia_calls == 2


def test_process_keyless_backend_shares_query_cache(monkeypatch) -> None:
    calls: list[str] = []
    fake_get = _fake_get_factory()

    def counted_get(url, *args, **kwargs):
        calls.append(url)
        return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(backends.httpx, "get", counted_get)

    assert backends.web_search("shared query", backend="keyless") is not None
    assert backends.web_search("shared query", backend="keyless") is not None
    assert len(calls) == 3


def test_reset_network_state_reenables_source_for_next_run(monkeypatch) -> None:
    wikipedia_blocked = True
    wikipedia_calls = 0
    fake_get = _fake_get_factory()

    def toggle_wikipedia(url, *args, **kwargs):
        nonlocal wikipedia_calls
        if "wikipedia.org" in url:
            wikipedia_calls += 1
            if wikipedia_blocked:
                return backends.httpx.Response(
                    403,
                    request=backends.httpx.Request("GET", url),
                )
        return fake_get(url, *args, **kwargs)

    monkeypatch.setattr(backends.httpx, "get", toggle_wikipedia)

    assert backends.web_search("first run", backend="keyless") is not None
    wikipedia_blocked = False
    backends.reset_network_state()
    second = backends.web_search("second run", backend="keyless")

    assert second is not None
    assert wikipedia_calls == 2
    assert any("wikipedia.org" in citation["url"] for citation in second.citations)


# ---------------------------------------------------------------------------
# search.py shim compatibility + web_search routing
# ---------------------------------------------------------------------------
def test_fetch_url_text_skips_non_http_urls() -> None:
    assert backends.fetch_url_text("hf://datasets/foo/bar") is None
    assert backends.fetch_url_text("ftp://example.com/x") is None


def test_fetch_url_text_caches_success(monkeypatch) -> None:
    calls = 0

    def fake_get(url, **kwargs):
        nonlocal calls
        calls += 1
        return backends.httpx.Response(
            200,
            text="<html><body>Stable source text</body></html>",
            headers={"content-type": "text/html"},
            request=backends.httpx.Request("GET", url),
        )

    monkeypatch.setattr(backends.httpx, "get", fake_get)

    assert backends.fetch_url_text("https://docs.example/source") == "Stable source text"
    assert backends.fetch_url_text("https://docs.example/source") == "Stable source text"
    assert calls == 1


def test_fetch_url_text_disables_forbidden_origin_for_run(monkeypatch) -> None:
    calls = 0

    def fake_get(url, **kwargs):
        nonlocal calls
        calls += 1
        return backends.httpx.Response(
            403,
            request=backends.httpx.Request("GET", url),
        )

    monkeypatch.setattr(backends.httpx, "get", fake_get)

    assert backends.fetch_url_text("https://blocked.example/first") is None
    assert backends.fetch_url_text("https://blocked.example/second") is None
    assert calls == 1


def test_fetch_url_text_disables_timed_out_origin_for_run(monkeypatch) -> None:
    calls = 0

    def fake_get(url, **kwargs):
        nonlocal calls
        calls += 1
        raise backends.httpx.ConnectTimeout(
            "timed out",
            request=backends.httpx.Request("GET", url),
        )

    monkeypatch.setattr(backends.httpx, "get", fake_get)

    assert backends.fetch_url_text("https://slow.example/first") is None
    assert backends.fetch_url_text("https://slow.example/second") is None
    assert calls == 1


def test_search_backend_public_exports() -> None:
    assert backends.web_search
    assert backends.fetch_url_text
    assert backends.format_search_result
    assert backends.SearchResult is SearchResult


def test_web_search_none_backend_returns_none() -> None:
    assert backends.web_search("q", backend="none") is None


def test_web_search_keyless_routing(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(backends.httpx, "get", _fake_get_factory())
    # auto with no gemini key -> keyless
    result = backends.web_search("tax law", backend="auto")
    assert result is not None
    assert any("arxiv.org" in c["url"] for c in result.citations)


def test_web_search_does_not_forward_non_gemini_key_to_gemini(monkeypatch) -> None:
    # Azure orchestrator key + azure model must not clobber the GEMINI_API_KEY
    # env fallback used by the gemini backend.
    monkeypatch.setenv("GEMINI_API_KEY", "real-gemini-key")
    captured: dict = {}

    def fake_search(self, query):
        captured["api_key"] = self.api_key
        captured["model"] = self.model
        return SearchResult(content="ok", citations=[])

    monkeypatch.setattr(GeminiBackend, "search", fake_search)
    backends.web_search(
        "q",
        api_key="azure-secret",
        model="azure/dep",
        backend="gemini",
    )
    assert captured["api_key"] is None  # azure key not forwarded
    assert captured["model"] == backends.DEFAULT_SEARCH_MODEL


def test_web_search_forwards_gemini_key_for_gemini_model(monkeypatch) -> None:
    captured: dict = {}

    def fake_search(self, query):
        captured["api_key"] = self.api_key
        captured["model"] = self.model
        return SearchResult(content="ok", citations=[])

    monkeypatch.setattr(GeminiBackend, "search", fake_search)
    backends.web_search(
        "q",
        api_key="gemini-secret",
        model="gemini-2.0-flash",
        backend="gemini",
    )
    assert captured["api_key"] == "gemini-secret"
    assert captured["model"] == "gemini-2.0-flash"


def test_gemini_backend_no_key_returns_none(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiBackend(api_key=None).search("q") is None


def test_web_search_graceful_without_any_key(monkeypatch) -> None:
    # No keys, keyless sources all fail -> None, no exception.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        backends.httpx, "get", _fake_get_factory(fail={"arxiv", "wiki", "ddg"})
    )
    assert backends.web_search("q", backend="auto") is None
