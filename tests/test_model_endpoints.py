import json
from types import SimpleNamespace

import pytest

from evalclaw.cli import _parse_target_configs
from evalclaw.models import llm
from evalclaw.models.providers import infer_provider, target_from_model
from evalclaw.protocols.tool import ToolSpec, object_schema
from evalclaw.types import Message, TargetModelConfig


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


def test_call_llm_does_not_fallback_to_legacy_after_truncation(monkeypatch) -> None:
    legacy_calls = 0

    def truncated(**kwargs):
        raise llm.LLMOutputTruncatedError("output truncated")

    def legacy(*args, **kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        return {}

    monkeypatch.setattr(llm, "_call_litellm", truncated)
    monkeypatch.setattr(llm, "_post_with_retry", legacy)

    with pytest.raises(llm.LLMOutputTruncatedError):
        llm.call_llm(
            [Message(role="user", content="build one task")],
            model="deepseek-v4-pro",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            backend="auto",
        )

    assert legacy_calls == 0


def test_call_llm_does_not_fallback_to_legacy_after_network_error(monkeypatch) -> None:
    legacy_calls = 0

    def disconnected(**kwargs):
        raise llm.httpx.ConnectError("disconnected")

    def legacy(*args, **kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        return {}

    monkeypatch.setattr(llm, "_call_litellm", disconnected)
    monkeypatch.setattr(llm, "_post_with_retry", legacy)

    with pytest.raises(llm.httpx.ConnectError):
        llm.call_llm(
            [Message(role="user", content="build one task")],
            model="deepseek-v4-pro",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            backend="auto",
        )

    assert legacy_calls == 0


def test_orchestrator_tool_truncation_does_not_fallback_to_legacy(monkeypatch) -> None:
    import litellm as _litellm

    completion_calls = 0
    legacy_calls = 0

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

    def legacy(*args, **kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        return {}

    monkeypatch.setattr(_litellm, "completion", truncated)
    monkeypatch.setattr(llm, "_post_with_retry", legacy)

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
    assert legacy_calls == 0


def test_call_llm_uses_legacy_for_litellm_adapter_failure(monkeypatch) -> None:
    import litellm as _litellm

    def unsupported(**kwargs):
        raise _litellm.UnsupportedParamsError(
            "unsupported parameter",
            llm_provider="openai",
            model="deepseek-v4-pro",
        )

    legacy_calls = 0

    def legacy(*args, **kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "legacy response"}}
            ]
        }

    monkeypatch.setattr(llm, "_call_litellm", unsupported)
    monkeypatch.setattr(llm, "_post_with_retry", legacy)

    result = llm.call_llm(
        [Message(role="user", content="hello")],
        model="deepseek-v4-pro",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        backend="auto",
    )

    assert result == "legacy response"
    assert legacy_calls == 1


def test_call_llm_uses_legacy_for_unadaptable_litellm_response(monkeypatch) -> None:
    import litellm as _litellm

    monkeypatch.setattr(
        _litellm,
        "completion",
        lambda **kwargs: SimpleNamespace(choices=[]),
    )
    legacy_calls = 0

    def legacy(*args, **kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "adapted directly"}}
            ]
        }

    monkeypatch.setattr(llm, "_post_with_retry", legacy)

    result = llm.call_llm(
        [Message(role="user", content="hello")],
        model="deepseek-v4-pro",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        backend="auto",
    )

    assert result == "adapted directly"
    assert legacy_calls == 1


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


def test_legacy_orchestrator_tool_call_retries_truncation_and_requests_json_object(monkeypatch) -> None:
    requests: list[dict] = []

    def fake_post(url, headers, body, **kwargs):
        requests.append(body)
        if len(requests) == 1:
            return {
                "choices": [
                    {"finish_reason": "length", "message": {"content": '[{"partial": true}]'}}
                ]
            }
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"tasks": []}'},
                }
            ]
        }

    monkeypatch.setattr(llm, "_post_with_retry", fake_post)

    response = llm.call_orchestrator_with_tools(
        [{"role": "user", "content": "Return one complete JSON object."}],
        model="deepseek-v4-pro",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        backend="legacy",
        tools=[],
        max_tokens=16384,
    )

    assert response.content == '{"tasks": []}'
    assert [request["max_tokens"] for request in requests] == [16384, 32768]
    assert all("tools" not in request for request in requests)
    assert all(request["response_format"] == {"type": "json_object"} for request in requests)
    assert all(request["thinking"] == {"type": "disabled"} for request in requests)


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
    openai_requests: list[tuple[str, dict]] = []

    def fake_post(url, headers, body, **kwargs):
        openai_requests.append((url, headers))
        return {"choices": [{"message": {"content": "openai response"}}]}

    anthropic_client = _FakeAnthropicClient()
    anthropic_clients: list[tuple[str | None, str | None]] = []

    def fake_anthropic_client(api_key=None, base_url=None):
        anthropic_clients.append((api_key, base_url))
        return anthropic_client

    monkeypatch.setattr(llm, "_post_with_retry", fake_post)
    monkeypatch.setattr(llm, "_get_anthropic_client", fake_anthropic_client)

    responses = [llm.call_target_model("hello", target, backend="legacy") for target in targets]

    assert responses == ["openai response", "anthropic response"]
    assert openai_requests == [
        (
            "https://relay.example/v1/chat/completions",
            {"Authorization": "Bearer relay-key", "Content-Type": "application/json"},
        )
    ]
    assert anthropic_clients == [("claude-key", "https://claude.example/v1")]


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
