"""Security checks for the model API egress gateway."""

import pytest
import json
from aiohttp import web

from evalclaw.execution.model_gateway import _ALLOWED_PATHS, _configured_body, _upstream_headers, _validate_model


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
