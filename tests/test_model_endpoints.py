import json
from types import SimpleNamespace

import pytest

from evalclaw.cli import _parse_target_configs
from evalclaw.models import llm
from evalclaw.models.providers import infer_provider, target_from_model
from evalclaw.protocols.tool import ToolSpec, object_schema
from evalclaw.types import BenchmarkConfig, Message, TargetModelConfig


@pytest.fixture(autouse=True)
def _clear_anthropic_client_cache():
    llm._anthropic_clients.clear()
    yield
    llm._anthropic_clients.clear()


def test_post_with_retry_bounds_transport_failures(monkeypatch) -> None:
    calls = 0
    waits: list[float] = []

    def fail_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise llm.httpx.ConnectError("offline")

    monkeypatch.setattr(llm.httpx, "post", fail_post)
    monkeypatch.setattr(llm.time, "sleep", waits.append)

    with pytest.raises(llm.httpx.ConnectError):
        llm._post_with_retry(
            "https://model.example/v1/chat/completions",
            {},
            {},
            max_retries=3,
        )

    assert calls == 3
    assert waits == [5.0, 10.0]


def test_post_with_retry_honors_retry_after(monkeypatch) -> None:
    responses = iter(
        [
            llm.httpx.Response(
                429,
                headers={"retry-after": "2"},
                request=llm.httpx.Request("POST", "https://model.example/v1"),
            ),
            llm.httpx.Response(
                200,
                json={"ok": True},
                request=llm.httpx.Request("POST", "https://model.example/v1"),
            ),
        ]
    )
    waits: list[float] = []
    monkeypatch.setattr(llm.httpx, "post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(llm.time, "sleep", waits.append)

    result = llm._post_with_retry("https://model.example/v1", {}, {})

    assert result == {"ok": True}
    assert waits == [2.0]


def test_post_with_retry_gives_one_generation_the_full_deadline(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(*args, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return llm.httpx.Response(
            200,
            json={"ok": True},
            request=llm.httpx.Request("POST", "https://model.example/v1"),
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)

    assert llm._post_with_retry("https://model.example/v1", {}, {}) == {"ok": True}
    assert captured["timeout"] == pytest.approx(300.0, abs=0.01)


def test_post_with_retry_enforces_total_deadline(monkeypatch) -> None:
    now = 0.0
    calls = 0
    request_timeouts: list[float] = []

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def fail_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        request_timeouts.append(kwargs["timeout"])
        raise llm.httpx.ReadTimeout("stalled")

    monkeypatch.setattr(llm.time, "monotonic", monotonic)
    monkeypatch.setattr(llm.time, "sleep", sleep)
    monkeypatch.setattr(llm.httpx, "post", fail_post)

    with pytest.raises(TimeoutError, match="overall deadline"):
        llm._post_with_retry(
            "https://model.example/v1",
            {},
            {},
            max_retries=5,
            request_timeout_s=120,
            total_timeout_s=6,
        )

    assert calls == 2
    assert request_timeouts == [6.0, 1.0]


def test_call_llm_does_not_switch_to_direct_http_after_truncation(monkeypatch) -> None:
    direct_calls = 0

    def truncated(**kwargs):
        raise llm.LLMOutputTruncatedError("output truncated")

    def direct(*args, **kwargs):
        nonlocal direct_calls
        direct_calls += 1
        return {}

    monkeypatch.setattr(llm, "_call_litellm", truncated)
    monkeypatch.setattr(llm, "_post_with_retry", direct)

    with pytest.raises(llm.LLMOutputTruncatedError):
        llm.call_llm(
            [Message(role="user", content="build one task")],
            model="deepseek-v4-pro",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            backend="auto",
        )

    assert direct_calls == 0


def test_call_llm_does_not_switch_to_direct_http_after_network_error(monkeypatch) -> None:
    direct_calls = 0

    def disconnected(**kwargs):
        raise llm.httpx.ConnectError("disconnected")

    def direct(*args, **kwargs):
        nonlocal direct_calls
        direct_calls += 1
        return {}

    monkeypatch.setattr(llm, "_call_litellm", disconnected)
    monkeypatch.setattr(llm, "_post_with_retry", direct)

    with pytest.raises(llm.httpx.ConnectError):
        llm.call_llm(
            [Message(role="user", content="build one task")],
            model="deepseek-v4-pro",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            backend="auto",
        )

    assert direct_calls == 0


def test_orchestrator_tool_truncation_does_not_switch_to_direct_http(monkeypatch) -> None:
    import litellm as _litellm

    completion_calls = 0
    direct_calls = 0

    def truncated(**kwargs):
        nonlocal completion_calls
        completion_calls += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content="partial"),
                )
            ]
        )

    def direct(*args, **kwargs):
        nonlocal direct_calls
        direct_calls += 1
        return {}

    monkeypatch.setattr(_litellm, "completion", truncated)
    monkeypatch.setattr(llm, "_post_with_retry", direct)

    with pytest.raises(llm.LLMOutputTruncatedError):
        llm.call_orchestrator_with_tools(
            [{"role": "user", "content": "build one task"}],
            model="deepseek-v4-pro",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            backend="auto",
            tools=[],
        )

    assert completion_calls == 2
    assert direct_calls == 0


def test_orchestrator_tool_adapter_failure_does_not_switch_to_direct_http(monkeypatch) -> None:
    import litellm as _litellm

    direct_calls = 0

    def direct(*args, **kwargs):
        nonlocal direct_calls
        direct_calls += 1
        return {}

    monkeypatch.setattr(
        _litellm,
        "completion",
        lambda **kwargs: SimpleNamespace(choices=[]),
    )
    monkeypatch.setattr(llm, "_post_with_retry", direct)

    with pytest.raises(llm.LLMProtocolAdapterError, match="no choices"):
        llm.call_orchestrator_with_tools(
            [{"role": "user", "content": "build one task"}],
            model="deepseek-v4-pro",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            tools=[],
        )

    assert direct_calls == 0


def test_orchestrator_uses_openai_litellm_route_for_custom_base_url(monkeypatch) -> None:
    import litellm as _litellm

    captured: dict = {}

    def complete(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "run_python",
                                    "arguments": '{"code":"print(4)"}',
                                },
                            }
                        ],
                    ),
                )
            ]
        )

    monkeypatch.setattr(_litellm, "completion", complete)

    response = llm.call_orchestrator_with_tools(
        [{"role": "user", "content": "Compute a value."}],
        model="deepseek-v4-flash",
        provider="openai_compatible",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        tools=[
            ToolSpec(
                name="run_python",
                parameters=object_schema(
                    {"code": {"type": "string"}},
                    required=["code"],
                ),
            )
        ],
    )

    assert captured["model"] == "openai/deepseek-v4-flash"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["tools"][0]["function"]["name"] == "run_python"
    assert response.tool_calls[0].name == "run_python"


def test_orchestrator_deepseek_json_recovery_disables_thinking(monkeypatch) -> None:
    import litellm as _litellm

    captured: dict = {}

    def complete(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content='{"tasks": []}', tool_calls=[]),
                )
            ]
        )

    monkeypatch.setattr(_litellm, "completion", complete)

    response = llm.call_orchestrator_with_tools(
        [{"role": "user", "content": "Return the final task JSON."}],
        model="deepseek-v4-flash",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        tools=[],
        expect_json=True,
    )

    assert response.content == '{"tasks": []}'
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_call_llm_propagates_litellm_adapter_failure(monkeypatch) -> None:
    import litellm as _litellm

    def unsupported(**kwargs):
        raise _litellm.UnsupportedParamsError(
            "unsupported parameter",
            llm_provider="openai",
            model="deepseek-v4-pro",
        )

    direct_calls = 0

    def direct(*args, **kwargs):
        nonlocal direct_calls
        direct_calls += 1
        return {}

    monkeypatch.setattr(llm, "_call_litellm", unsupported)
    monkeypatch.setattr(llm, "_post_with_retry", direct)

    with pytest.raises(_litellm.UnsupportedParamsError, match="unsupported parameter"):
        llm.call_llm(
            [Message(role="user", content="hello")],
            model="deepseek-v4-pro",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            backend="auto",
        )

    assert direct_calls == 0


def test_call_llm_propagates_unadaptable_litellm_response(monkeypatch) -> None:
    import litellm as _litellm

    monkeypatch.setattr(
        _litellm,
        "completion",
        lambda **kwargs: SimpleNamespace(choices=[]),
    )
    direct_calls = 0

    def direct(*args, **kwargs):
        nonlocal direct_calls
        direct_calls += 1
        return {}

    monkeypatch.setattr(llm, "_post_with_retry", direct)

    with pytest.raises(llm.LLMProtocolAdapterError, match="unsupported response shape"):
        llm.call_llm(
            [Message(role="user", content="hello")],
            model="deepseek-v4-pro",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            backend="auto",
        )

    assert direct_calls == 0


def test_legacy_llm_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="llm_backend"):
        BenchmarkConfig(llm_backend="legacy")

    with pytest.raises(ValueError, match="Unsupported LLM backend"):
        llm.call_llm([Message(role="user", content="hello")], backend="legacy")


def test_openai_responses_provider_uses_responses_api(monkeypatch) -> None:
    captured: dict = {}

    def fake_responses(url, headers, body, **kwargs):
        captured.update({"url": url, "headers": headers, "body": body})
        return {
            "status": "completed",
            "incomplete_details": None,
            "output_text": '{"ok":true}',
            "output": [],
        }

    monkeypatch.setattr(llm, "_post_streaming_responses", fake_responses)

    result = llm.call_llm(
        [Message(role="user", content="Return JSON.")],
        system="Follow the schema.",
        model="gpt-5.6-luna",
        api_key="test-key",
        base_url="https://model.example/v1",
        provider="openai_responses",
        backend="auto",
    )

    assert result == '{"ok":true}'
    assert captured["url"] == "https://model.example/v1/responses"
    assert captured["body"]["model"] == "gpt-5.6-luna"
    assert captured["body"]["instructions"] == "Follow the schema."
    assert captured["body"]["input"] == [{"role": "user", "content": "Return JSON."}]


def test_responses_stream_returns_completed_response(monkeypatch) -> None:
    completed = {"status": "completed", "output_text": "done", "output": []}
    stream_lines = [
        "data: " + json.dumps({"type": "response.created", "response": {"status": "in_progress"}}),
        "data: " + json.dumps({"type": "response.completed", "response": completed}),
        "data: [DONE]",
    ]

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(stream_lines)

    monkeypatch.setattr(llm.httpx, "stream", lambda *args, **kwargs: FakeStream())

    assert llm._post_streaming_responses("https://model.example/v1/responses", {}, {}) == completed


def test_responses_stream_returns_incomplete_response(monkeypatch) -> None:
    incomplete = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [],
    }

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(
                ["data: " + json.dumps({"type": "response.incomplete", "response": incomplete})]
            )

    monkeypatch.setattr(llm.httpx, "stream", lambda *args, **kwargs: FakeStream())

    assert llm._post_streaming_responses("https://model.example/v1/responses", {}, {}) == incomplete


def test_openai_responses_provider_preserves_tool_output(monkeypatch) -> None:
    raw_output = [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"query":"test"}',
        }
    ]
    monkeypatch.setattr(
        llm,
        "_post_streaming_responses",
        lambda *args, **kwargs: {
            "status": "completed",
            "incomplete_details": None,
            "output_text": "",
            "output": raw_output,
        },
    )
    tool = ToolSpec(
        name="lookup",
        description="Look up a query.",
        parameters=object_schema({"query": {"type": "string"}}, required=["query"]),
    )

    response = llm.call_orchestrator_with_tools(
        [{"role": "user", "content": "Look up test."}],
        model="gpt-5.6-luna",
        api_key="test-key",
        base_url="https://model.example/v1",
        provider="openai_responses",
        tools=[tool],
    )

    assert response.adapter == "openai_responses"
    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].arguments == {"query": "test"}
    assert response.assistant_message == {"responses_output": raw_output}


def test_openai_compatible_streaming_path_collects_chunks(monkeypatch) -> None:
    captured: dict = {}
    stream_lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "{\"ok\":"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "true}"}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ]

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(stream_lines)

    def fake_stream(method, url, headers, json, timeout):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        captured["timeout"] = timeout
        return FakeStream()

    def forbidden_post(*args, **kwargs):
        raise AssertionError("non-streaming POST should not be used")

    def forbidden_litellm(*args, **kwargs):
        raise AssertionError("LiteLLM should be skipped when streaming is enabled")

    monkeypatch.setenv("EVALCLAW_LLM_STREAMING", "1")
    monkeypatch.setattr(llm.httpx, "stream", fake_stream)
    monkeypatch.setattr(llm, "_post_with_retry", forbidden_post)
    monkeypatch.setattr(llm, "_call_litellm", forbidden_litellm)

    result = llm.call_llm(
        [Message(role="user", content="Return the run summary.")],
        model="gpt-5.6-luna",
        api_key="test-key",
        base_url="https://model.example/v1",
        provider="openai_compatible",
        backend="auto",
        expect_json=True,
    )

    assert result == '{"ok":true}'
    assert captured["method"] == "POST"
    assert captured["url"] == "https://model.example/v1/chat/completions"
    assert captured["body"]["stream"] is True
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_deepseek_streaming_preserves_thinking_until_json_recovery(monkeypatch) -> None:
    bodies: list[dict] = []

    def fake_stream(url, headers, body):
        bodies.append(body)
        return '{"tasks": []}', "stop"

    monkeypatch.setenv("EVALCLAW_LLM_STREAMING", "1")
    monkeypatch.setattr(llm, "_post_streaming_openai_compatible", fake_stream)

    llm.call_llm(
        [Message(role="user", content="Build the tasks.")],
        model="deepseek-v4-flash",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        provider="openai_compatible",
    )
    llm.call_llm(
        [Message(role="user", content="Return the final task JSON.")],
        model="deepseek-v4-flash",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        provider="openai_compatible",
        reduce_reasoning_effort=True,
        expect_json=True,
    )

    assert "thinking" not in bodies[0]
    assert bodies[1]["thinking"] == {"type": "disabled"}
    assert bodies[1]["response_format"] == {"type": "json_object"}


def test_openai_compatible_streaming_retries_upstream_error(monkeypatch) -> None:
    attempts = 0
    waits: list[float] = []

    class FakeStream:
        def __init__(self, lines):
            self.lines = lines

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(self.lines)

    def fake_stream(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return FakeStream(
                [
                    "data: "
                    + json.dumps(
                        {
                            "error": {
                                "message": "Upstream service temporarily unavailable",
                                "type": "upstream_error",
                            }
                        }
                    )
                ]
            )
        return FakeStream(
            [
                "data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}),
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr(llm.httpx, "stream", fake_stream)
    monkeypatch.setattr(llm.time, "sleep", waits.append)

    result = llm._post_streaming_openai_compatible(
        "https://model.example/v1/chat/completions",
        {},
        {},
    )

    assert result == ("ok", None)
    assert attempts == 2
    assert waits == [5.0]


class _FakeAnthropicMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="anthropic response")])


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = _FakeAnthropicMessages()


def test_claude_custom_base_url_infers_anthropic_protocol() -> None:
    endpoint = "https://claude-gateway.example/v1"

    assert infer_provider("claude-sonnet-4-6", endpoint) == ("anthropic", endpoint)
    assert infer_provider("claude-sonnet-4-6", endpoint, "openai_compatible") == (
        "openai_compatible",
        endpoint,
    )


def test_anthropic_client_cache_isolated_by_base_url(monkeypatch) -> None:
    created: list[dict] = []

    def fake_anthropic(**kwargs):
        created.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(llm.anthropic, "Anthropic", fake_anthropic)
    llm._anthropic_clients.clear()

    first = llm._get_anthropic_client("same-key", "https://claude-a.example/v1/")
    repeated = llm._get_anthropic_client("same-key", "https://claude-a.example/v1")
    second = llm._get_anthropic_client("same-key", "https://claude-b.example/v1")

    assert first is repeated
    assert first is not second
    assert created == [
        {"api_key": "same-key", "base_url": "https://claude-a.example/v1"},
        {"api_key": "same-key", "base_url": "https://claude-b.example/v1"},
    ]


def test_orchestrator_uses_native_anthropic_protocol_for_custom_base_url(monkeypatch) -> None:
    client = _FakeAnthropicClient()
    requested_clients: list[tuple[str | None, str | None]] = []

    def fake_client(api_key=None, base_url=None):
        requested_clients.append((api_key, base_url))
        return client

    monkeypatch.setattr(llm, "_get_anthropic_client", fake_client)

    result = llm.call_llm(
        [Message(role="user", content="hello")],
        system="system instruction",
        model="anthropic/claude-sonnet-4-6",
        provider="anthropic",
        api_key="claude-key",
        base_url="https://claude-code.example/v1",
    )

    assert result == "anthropic response"
    assert requested_clients == [("claude-key", "https://claude-code.example/v1")]
    assert client.messages.calls[0]["model"] == "claude-sonnet-4-6"
    assert client.messages.calls[0]["messages"] == [{"role": "user", "content": "hello"}]


def test_explicit_litellm_backend_does_not_use_native_anthropic_client(monkeypatch) -> None:
    import litellm as _litellm

    native_calls = 0

    def fail_native(*args, **kwargs):
        nonlocal native_calls
        native_calls += 1
        raise AssertionError("native Anthropic client should not run for backend=litellm")

    monkeypatch.setattr(llm, "_get_anthropic_client", fail_native)
    monkeypatch.setattr(
        _litellm,
        "completion",
        lambda **kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="litellm response"),
                )
            ]
        ),
    )

    result = llm.call_llm(
        [Message(role="user", content="hello")],
        model="anthropic/claude-sonnet-4-6",
        provider="anthropic",
        api_key="claude-key",
        base_url="https://claude-gateway.example/v1",
        backend="litellm",
    )

    assert result == "litellm response"
    assert native_calls == 0


def test_target_native_tools_use_target_specific_anthropic_endpoint(monkeypatch) -> None:
    client = _FakeAnthropicClient()
    requested_clients: list[tuple[str | None, str | None]] = []

    def fake_client(api_key=None, base_url=None):
        requested_clients.append((api_key, base_url))
        return client

    monkeypatch.setattr(llm, "_get_anthropic_client", fake_client)
    target = TargetModelConfig(
        id="claude_target",
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="target-key",
        base_url="https://target-claude.example/v1",
    )
    tool = ToolSpec(name="look", description="Inspect state.", parameters=object_schema())

    response = llm.call_target_model_with_tools(
        [{"role": "user", "content": "inspect"}],
        target,
        [tool],
        system_prompt="Use tools.",
    )

    assert response.adapter == "anthropic"
    assert response.content == "anthropic response"
    assert requested_clients == [("target-key", "https://target-claude.example/v1")]
    assert client.messages.calls[0]["tools"][0]["name"] == "look"


def test_orchestrator_native_tools_use_custom_anthropic_endpoint(monkeypatch) -> None:
    client = _FakeAnthropicClient()
    requested_clients: list[tuple[str | None, str | None]] = []

    def fake_client(api_key=None, base_url=None):
        requested_clients.append((api_key, base_url))
        return client

    monkeypatch.setattr(llm, "_get_anthropic_client", fake_client)
    tool = ToolSpec(name="search", description="Search sources.", parameters=object_schema())

    response = llm.call_orchestrator_with_tools(
        [{"role": "user", "content": "research"}],
        model="claude-sonnet-4-6",
        provider="anthropic",
        api_key="orchestrator-key",
        base_url="https://orchestrator-claude.example/v1",
        tools=[tool],
    )

    assert response.adapter == "anthropic"
    assert requested_clients == [
        ("orchestrator-key", "https://orchestrator-claude.example/v1")
    ]
    assert client.messages.calls[0]["tools"][0]["name"] == "search"


def test_repeated_target_configs_keep_protocol_url_and_key_independent(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_TARGET_KEY", "claude-secret")
    configs = [
        json.dumps(
            {
                "id": "openai_target",
                "model": "gpt-compatible-model",
                "provider": "openai_compatible",
                "base_url": "https://openai-gateway.example/v1",
                "api_key": "openai-secret",
            }
        ),
        json.dumps(
            {
                "id": "claude_target",
                "model": "claude-sonnet-4-6",
                "protocol": "claude_code",
                "base_url": "https://claude-gateway.example/v1",
                "api_key_env": "CLAUDE_TARGET_KEY",
            }
        ),
    ]

    targets = _parse_target_configs(configs, fallback_key=None)

    assert [target.id for target in targets] == ["openai_target", "claude_target"]
    assert targets[0].provider == "openai_compatible"
    assert targets[0].base_url == "https://openai-gateway.example/v1"
    assert targets[0].api_key == "openai-secret"
    assert targets[1].provider == "anthropic"
    assert targets[1].base_url == "https://claude-gateway.example/v1"
    assert targets[1].api_key == "claude-secret"


def test_multiple_targets_call_their_own_protocol_endpoint_and_key(monkeypatch) -> None:
    targets = _parse_target_configs(
        [
            json.dumps(
                {
                    "id": "openai_target",
                    "model": "relay-model",
                    "provider": "openai_compatible",
                    "base_url": "https://relay.example/v1",
                    "api_key": "relay-key",
                }
            ),
            json.dumps(
                {
                    "id": "claude_target",
                    "model": "claude-sonnet-4-6",
                    "provider": "anthropic",
                    "base_url": "https://claude.example/v1",
                    "api_key": "claude-key",
                }
            ),
        ],
        fallback_key=None,
    )
    openai_requests: list[tuple[str, str | None, str | None]] = []

    def fake_litellm(**kwargs):
        openai_requests.append(
            (kwargs["model"], kwargs.get("base_url"), kwargs.get("api_key"))
        )
        return "openai response"

    anthropic_client = _FakeAnthropicClient()
    anthropic_clients: list[tuple[str | None, str | None]] = []

    def fake_anthropic_client(api_key=None, base_url=None):
        anthropic_clients.append((api_key, base_url))
        return anthropic_client

    monkeypatch.setattr(llm, "_call_litellm", fake_litellm)
    monkeypatch.setattr(llm, "_get_anthropic_client", fake_anthropic_client)

    responses = [llm.call_target_model("hello", target) for target in targets]

    assert responses == ["openai response", "anthropic response"]
    assert openai_requests == [
        (
            "relay-model",
            "https://relay.example/v1",
            "relay-key",
        )
    ]
    assert anthropic_clients == [("claude-key", "https://claude.example/v1")]


def test_target_adapter_failure_does_not_switch_to_direct_http(monkeypatch) -> None:
    target = TargetModelConfig(
        provider="openai_compatible",
        model="relay-model",
        api_key="relay-key",
        base_url="https://relay.example/v1",
    )
    direct_calls = 0

    def fail_litellm(**kwargs):
        raise llm.LLMProtocolAdapterError("unsupported response")

    def direct(*args, **kwargs):
        nonlocal direct_calls
        direct_calls += 1
        return {}

    monkeypatch.setattr(llm, "_call_litellm", fail_litellm)
    monkeypatch.setattr(llm, "_post_with_retry", direct)

    with pytest.raises(llm.LLMProtocolAdapterError, match="unsupported response"):
        llm.call_target_model("hello", target)

    assert direct_calls == 0


def test_target_config_requires_unique_ids() -> None:
    configs = [
        json.dumps({"id": "same", "model": "model-a", "provider": "openai_compatible"}),
        json.dumps({"id": "same", "model": "model-b", "provider": "anthropic"}),
    ]

    with pytest.raises(ValueError, match="target id must be unique"):
        _parse_target_configs(configs, fallback_key=None)


def test_target_from_model_allows_explicit_openai_protocol_for_claude_gateway() -> None:
    target = target_from_model(
        "claude-served-by-relay",
        provider="openai_compatible",
        api_key="relay-key",
        base_url="https://relay.example/v1",
    )

    assert target.provider == "openai_compatible"
    assert target.base_url == "https://relay.example/v1"
