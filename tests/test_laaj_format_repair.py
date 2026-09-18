import json
from copy import deepcopy

import pytest

from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall, ToolResult, ToolSpec
from evalclaw.quality import laaj
from evalclaw.types import BenchmarkConfig
from tests.test_laaj import _response, _suite


@pytest.mark.parametrize("invalid", [
    _response()[:-1],
    _response().replace('"reasoning"', '"reason"'),
    _response().replace('"score": 4', '"score": "bad"'),
])
def test_text_format_repair_retains_previous_response(monkeypatch, tmp_path, invalid):
    calls = []

    def model(messages, **kwargs):
        calls.append(deepcopy(messages))
        return invalid if len(calls) == 1 else _response()

    monkeypatch.setattr(laaj, "call_llm", model)
    suite = _suite()
    suite.tasks = suite.tasks[:1]
    result = laaj._evaluate_laaj_item(
        "goal", suite, BenchmarkConfig(laaj_model="judge", laaj_api_key="test"), trace_dir=tmp_path,
    )
    assert result.correctness.score == 4
    assert len(calls) == 2
    assert [m.role for m in calls[1]] == ["user", "assistant", "user"]
    assert calls[1][1].content == invalid
    assert calls[1][2].content


@pytest.mark.parametrize("exhaust", [False, True])
def test_agent_repairs_final_json_without_repeating_tools(monkeypatch, exhaust):
    calls, executed = [], []
    tool = ToolSpec(name="observe", description="Observe", parameters={"type": "object", "properties": {}})
    tc = ToolCall(id="observation", name="observe", arguments={})

    def model(messages, **kwargs):
        calls.append((deepcopy(messages), kwargs["tools"]))
        if len(calls) == 1:
            return TargetToolModelResponse(
                adapter="openai_compatible", content="", tool_calls=[tc],
                assistant_message={"role": "assistant", "content": None, "tool_calls": [{
                    "id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": "{}"},
                }]}, raw_response={},
            )
        raw = _response()[:-1] if len(calls) == 2 or exhaust else _response()
        return TargetToolModelResponse(adapter="openai_compatible", content=raw, tool_calls=[],
                                       assistant_message={"role": "assistant", "content": raw}, raw_response={})

    def observe(call):
        executed.append(call.id)
        return ToolResult(tool_call_id=call.id, name=call.name, content="verified environment evidence")

    monkeypatch.setattr(laaj, "call_orchestrator_with_tools", model)
    kwargs = dict(
        trace_dir=None, artifact_dir=None, trace_name="test", include_agent_tools=False,
        additional_tools=[tool], tool_handlers={"observe": observe},
        validate_response=laaj._judgment_json,
    )
    config = BenchmarkConfig(laaj_model="judge", laaj_api_key="test")
    if exhaust:
        with pytest.raises(laaj.LaajOutputError):
            laaj._run_laaj_tool_loop({}, _suite(), config, **kwargs)
        assert len(calls) == 5
    else:
        raw = laaj._run_laaj_tool_loop({}, _suite(), config, **kwargs)
        assert json.loads(raw)["correctness"]["score"] == 4
        assert len(calls) == 3
    assert executed == ["observation"]
    assert all(tools == [] for _, tools in calls[2:])
    assert any(m.get("content") == "verified environment evidence" for m in calls[-1][0])
