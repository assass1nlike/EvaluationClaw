"""Security checks for the model API egress gateway."""

import json

import pytest
from aiohttp import web

from evalclaw.execution.model_gateway import (
    _ALLOWED_PATHS,
    _configured_body,
    _upstream_headers,
    _validate_model,
)


def test_gateway_replaces_bearer_credential() -> None:
    headers = _upstream_headers(
        {"Authorization": "Bearer attacker-value", "Content-Type": "application/json"},
        "openai",
        "upstream-key",
    )

    assert headers["Authorization"] == "Bearer upstream-key"
    assert headers["Content-Type"] == "application/json"


def test_gateway_replaces_anthropic_credential() -> None:
    headers = _upstream_headers(
        {"x-api-key": "attacker-value", "anthropic-version": "2023-06-01"},
        "anthropic",
        "upstream-key",
    )

    assert headers["x-api-key"] == "upstream-key"
    assert headers["anthropic-version"] == "2023-06-01"


def test_gateway_allows_only_inference_paths() -> None:
    assert "/v1/chat/completions" in _ALLOWED_PATHS
    assert "/v1/responses" in _ALLOWED_PATHS
    assert "/v1/messages" in _ALLOWED_PATHS
    assert "/admin" not in _ALLOWED_PATHS


def test_gateway_pins_the_configured_model() -> None:
    _validate_model(b'{"model":"deepseek-flash","input":"hello"}', "deepseek-flash")

    with pytest.raises(web.HTTPForbidden):
        _validate_model(b'{"model":"another-model","input":"hello"}', "deepseek-flash")


def test_gateway_applies_experiment_parameters_and_preserves_tool_history():
    request = {'model': 'deepseek-flash', 'stream': True, 'reasoning_effort': 'low',
               'messages': [{'role': 'assistant', 'reasoning_content': 'plan', 'tool_calls': []}]}
    extra = {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'}
    forwarded = json.loads(_configured_body(json.dumps(request).encode(), 'deepseek-flash', extra))
    assert forwarded == {**request, **extra}
    with pytest.raises(web.HTTPForbidden):
        _configured_body(json.dumps(request).encode(), 'deepseek-flash', {'model': 'other'})


def test_explicit_reasoning_setting_is_not_lowered_for_helper_calls():
    from evalclaw.models.llm import _resolve_reasoning_effort

    assert _resolve_reasoning_effort('deepseek-flash', 'high', True) == 'high'
    assert _resolve_reasoning_effort('deepseek-flash', None, True) == 'low'


def test_gateway_retries_transient_status_before_forwarding_and_keeps_heartbeat_alive(tmp_path, monkeypatch):
    import asyncio

    import aiohttp
    from aiohttp.test_utils import TestClient, TestServer

    from evalclaw.execution import model_gateway
    waits, requests, timeouts = [], [], []
    original_sleep = asyncio.sleep
    original_session = aiohttp.ClientSession
    async def sleep(delay):
        waits.append(delay)
        await original_sleep(0)
    def session(*args, **kwargs):
        if "timeout" in kwargs:
            timeouts.append(kwargs["timeout"])
        return original_session(*args, **kwargs)
    monkeypatch.setattr(model_gateway.asyncio, "sleep", sleep)
    monkeypatch.setattr(model_gateway.aiohttp, "ClientSession", session)
    async def scenario():
        async def upstream(request):
            requests.append(await request.json())
            if len(requests) < 4:
                return web.json_response({"error":"busy"}, status=503)
            return web.Response(text=': keep-alive\n\ndata: {"choices":[{"finish_reason":"stop","delta":{"content":"OK"}}]}\n\ndata: [DONE]\n', content_type="text/event-stream")
        source = web.Application()
        source.router.add_post('/chat/completions', upstream)
        async with TestServer(source) as server:
            app = web.Application()
            app.update(upstream=str(server.make_url('')).rstrip('/'), model='test', api_key='key', provider='openai', evidence_path=str(tmp_path/'events.jsonl'))
            app.router.add_post('/chat/completions', model_gateway._forward)
            async with TestClient(TestServer(app)) as client:
                response = await client.post('/chat/completions', json={'model':'test','messages':[{'role':'user','content':'Hi'}]})
                assert response.status == 200
                assert '[DONE]' in await response.text()
    asyncio.run(scenario())
    assert [delay for delay in waits if delay] == [5, 10, 20]
    assert len(requests) == 4 and all(r == requests[0] for r in requests)
    assert timeouts[0].total is None and timeouts[0].sock_read == 300
    events = [json.loads(line) for line in (tmp_path/'events.jsonl').read_text().splitlines()]
    from evalclaw.execution.harness_evidence import terminal_model_error
    assert terminal_model_error(events) is None


@pytest.mark.parametrize("status,complete,body", [
    (503, True, '{"error":{"message":"Busy"}}'),
    (200, False, ': keep-alive\n'),
    (200, True, ': keep-alive\n'),
    (200, True, 'data: {"error":{"message":"Busy"}}\n'),
])
def test_terminal_provider_failure_cannot_be_masked_by_successful_cli(status, complete, body):
    from evalclaw.execution.harness_evidence import terminal_model_error
    events = [dict(kind="request", id="r"), dict(kind="response_start", id="r", status=status),
              dict(kind="response_chunk", id="r", body=body),
              dict(kind="response_end", id="r", complete=complete, body="")]
    assert terminal_model_error(events)
    events += [dict(kind="request", id="retry"),
               dict(kind="response", id="retry", status=200, complete=True,
                    body='{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}]}')]
    assert terminal_model_error(events) is None
