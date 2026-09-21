from __future__ import annotations

import json

from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.quality import analysis
from evalclaw.quality.analysis_tools import (
    list_run_artifacts,
    read_item_evidence,
    read_run_artifact,
)
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


def test_read_run_artifact_supports_character_pagination(tmp_path) -> None:
    content = "αβγδε" * 50
    (tmp_path / "trace.txt").write_text(content, encoding="utf-8")

    first = read_run_artifact(
        ToolCall(
            id="call-1",
            name="read_run_artifact",
            arguments={"path": "trace.txt", "max_chars": 100},
        ),
        tmp_path,
    )
    first_payload = json.loads(first.content)
    second = read_run_artifact(
        ToolCall(
            id="call-2",
            name="read_run_artifact",
            arguments={
                "path": "trace.txt",
                "max_chars": 100,
                "offset": first_payload["next_offset"],
            },
        ),
        tmp_path,
    )
    second_payload = json.loads(second.content)

    assert first_payload["content"] == content[:100]
    assert first_payload["next_offset"] == 100
    assert second_payload["content"] == content[100:200]
    assert second_payload["next_offset"] == 200


def test_list_run_artifacts_is_paginated_and_confined(tmp_path) -> None:
    (tmp_path / "runner" / "target" / "item").mkdir(parents=True)
    (tmp_path / "runner" / "target" / "item" / "item.json").write_text("{}")
    (tmp_path / "runner" / "target" / "item" / "result.json").write_text("{}")

    result = list_run_artifacts(
        ToolCall(
            id="call-1",
            name="list_run_artifacts",
            arguments={"prefix": "runner", "max_entries": 1},
        ),
        tmp_path,
    )
    payload = json.loads(result.content)

    assert result.error is None
    assert len(payload["files"]) == 1
    assert payload["next_offset"] == 1
    traversal = list_run_artifacts(
        ToolCall(
            id="call-2",
            name="list_run_artifacts",
            arguments={"prefix": "../"},
        ),
        tmp_path,
    )
    assert traversal.error == "artifact_list_failed"


def test_read_item_evidence_supports_probe_task_qc_and_pagination(tmp_path) -> None:
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir()
    payload = {
        "suite": {
            "tasks": [{
                "id": "probe-item",
                "prompt": "Inspect the workspace.",
                "metadata": {
                    "task_design_id": "probe-design",
                    "agent_env": {"bridge_api_key": "secret", "actors": []},
                },
            }],
            "blueprints": [{
                "task_designs": [{
                    "id": "probe-design",
                    "content_design": {"purpose": "Test recovery."},
                }],
            }],
        },
        "qc_report": {
            "passed_item_ids": ["probe-item"],
            "rejected_item_ids": [],
            "issues": [],
            "summary": "valid",
        },
        "run": {
            "results": [{
                "item_id": "probe-item",
                "target_id": "target",
                "raw_response": "a" * 250,
                "judge_reasoning": "incorrect attribution",
                "score": 0.25,
                "latency_ms": 123,
            }],
        },
    }
    (analysis_dir / "iteration-01.json").write_text(json.dumps(payload), encoding="utf-8")

    response = read_item_evidence(
        ToolCall(
            id="call-1",
            name="read_item_evidence",
            arguments={
                "target_id": "target",
                "item_id": "probe-item",
                "scope": "probe",
                "iteration": 1,
                "kind": "all",
                "max_chars": 100,
                "offset": 20,
            },
        ),
        tmp_path,
    )
    evidence = json.loads(response.content)

    assert response.error is None
    assert evidence["raw_response"] == "a" * 100
    assert evidence["raw_response_next_offset"] == 120
    assert evidence["latency_ms"] == 123
    assert evidence["qc"]["passed"] is True
    assert evidence["artifact_prefix"] == "analysis/iteration-01/runner/target/probe-item"

    task_response = read_item_evidence(
        ToolCall(
            id="call-2",
            name="read_item_evidence",
            arguments={
                "target_id": "target",
                "item_id": "probe-item",
                "scope": "probe",
                "iteration": 1,
                "kind": "task",
                "max_chars": 10_000,
            },
        ),
        tmp_path,
    )
    task_evidence = json.loads(task_response.content)
    assert "Test recovery" in task_evidence["task"]
    assert "secret" not in task_evidence["task"]


def test_read_item_evidence_keeps_main_run_defaults(tmp_path) -> None:
    (tmp_path / "run.json").write_text(
        json.dumps({
            "results": [{
                "item_id": "main-item",
                "target_id": "target",
                "raw_response": "full response",
                "judge_reasoning": "judge reason",
                "score": 0.5,
            }],
        }),
        encoding="utf-8",
    )

    result = read_item_evidence(
        ToolCall(
            id="call-1",
            name="read_item_evidence",
            arguments={"target_id": "target", "item_id": "main-item"},
        ),
        tmp_path,
    )
    evidence = json.loads(result.content)

    assert result.error is None
    assert evidence["scope"] == "main"
    assert evidence["raw_response"] == "full response"
    assert evidence["judge_reasoning"] == "judge reason"


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
    assert {tool.name for tool in calls[0]["tools"]} == {
        "read_run_artifact",
        "list_run_artifacts",
        "read_item_evidence",
        "read_analysis_context",
    }
    assert calls[1]["messages"][-1]["role"] == "tool"
    assert "issues" in calls[1]["messages"][-1]["content"]


def test_analyser_answers_every_call_when_a_batch_exceeds_budget(monkeypatch, tmp_path) -> None:
    (tmp_path / "qc_report.json").write_text('{"issues": []}', encoding="utf-8")
    calls = [ToolCall(id=f"call-{i}", name="read_run_artifact", arguments={"path": "qc_report.json"}) for i in range(3)]
    turns = 0

    def model(messages, **kwargs):
        nonlocal turns
        turns += 1
        if turns == 1:
            return TargetToolModelResponse(adapter="openai_compatible", content="", tool_calls=calls,
                assistant_message={"role": "assistant", "tool_calls": [{"id": c.id} for c in calls]}, raw_response={})
        results = [m for m in messages if m.get("role") == "tool"]
        assert [m["tool_call_id"] for m in results] == [c.id for c in calls]
        assert "issues" in results[0]["content"]
        assert all("exhausted" in m["content"] for m in results[1:])
        assert kwargs["tools"] == []
        return TargetToolModelResponse(adapter="openai_compatible", content='{"analysis":"Done","done":true}',
            tool_calls=[], assistant_message={"role": "assistant"}, raw_response={})

    monkeypatch.setattr(analysis, "call_orchestrator_with_tools", model)
    config = _config().model_copy(update={"analyser_tool_max_calls": 1})
    assert analysis._run_analyser_tool_loop({}, config, trace_dir=None, artifact_dir=tmp_path)["done"] is True


def test_analyser_retries_missing_content_without_using_reasoning_as_answer(monkeypatch) -> None:
    attempts = 0

    def model(messages, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise analysis.LLMFinalContentMissingError("No final content")
        return TargetToolModelResponse(adapter="openai_compatible", content='{"analysis":"Insufficient evidence","done":true}',
            tool_calls=[], assistant_message={"role": "assistant"}, raw_response={})

    monkeypatch.setattr(analysis, "call_orchestrator_with_tools", model)
    result = analysis._run_analyser_tool_loop({}, _config(), trace_dir=None, artifact_dir=None)
    assert attempts == 2
    assert result["analysis"] == "Insufficient evidence"
