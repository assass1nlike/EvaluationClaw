from __future__ import annotations

import json

from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.quality import analysis
from evalclaw.quality.analysis_tools import read_run_artifact
from evalclaw.types import BenchmarkConfig


def _config() -> BenchmarkConfig:
    return BenchmarkConfig(
        analyser_model="analyser-model",
        analyser_provider="openai_compatible",
        analyser_api_key="analyser-key",
        analyser_base_url="https://analyser.example",
    )


def test_read_run_artifact_is_bounded_and_relative(tmp_path) -> None:
    artifact = tmp_path / "qc_report.json"
    artifact.write_text(json.dumps({"issues": []}), encoding="utf-8")

    result = read_run_artifact(
        ToolCall(id="call-1", name="read_run_artifact", arguments={"path": "qc_report.json"}),
        tmp_path,
    )

    assert result.error is None
    assert json.loads(result.content)["path"] == "qc_report.json"
    assert json.loads(json.loads(result.content)["content"]) == {"issues": []}

    traversal = read_run_artifact(
        ToolCall(id="call-2", name="read_run_artifact", arguments={"path": "../secret.txt"}),
        tmp_path,
    )
    assert traversal.error == "artifact_read_failed"


def test_analyser_tool_round_preserves_artifact_context(monkeypatch, tmp_path) -> None:
    (tmp_path / "qc_report.json").write_text('{"issues": []}', encoding="utf-8")
    calls: list[dict] = []

    def fake_call(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        if len(calls) == 1:
            tool_call = ToolCall(
                id="call-1",
                name="read_run_artifact",
                arguments={"path": "qc_report.json"},
            )
            return TargetToolModelResponse(
                adapter="litellm",
                content="",
                tool_calls=[tool_call],
                assistant_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "read_run_artifact",
                            "arguments": '{"path":"qc_report.json"}',
                        },
                    }],
                },
                raw_response={},
            )
        return TargetToolModelResponse(
            adapter="litellm",
            content='{"analysis":"Supported conclusion.","recommendations":[],"task_designs":[]}',
            tool_calls=[],
            assistant_message={
                "role": "assistant",
                "content": '{"analysis":"Supported conclusion.","recommendations":[],"task_designs":[]}',
            },
            raw_response={},
        )

    monkeypatch.setattr(analysis, "call_orchestrator_with_tools", fake_call)

    result = analysis._run_analyser_tool_loop(
        {"available_artifacts": {"qc_report": "qc_report.json"}},
        _config(),
        trace_dir=None,
        artifact_dir=tmp_path,
    )

    assert result["analysis"] == "Supported conclusion."
    assert calls[0]["tools"][0].name == "read_run_artifact"
    assert calls[1]["messages"][-1]["role"] == "tool"
    assert "issues" in calls[1]["messages"][-1]["content"]
