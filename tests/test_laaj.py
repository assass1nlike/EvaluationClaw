from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from evalclaw.cli import app
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.quality import laaj as laaj_module
from evalclaw.quality.laaj_tools import (
    inspect_agent_environment,
    read_task_file,
    view_benchmark_image,
)
from evalclaw.reporting.reporter import build_report
from evalclaw.reporting.viewer import build_report_viewer_html
from evalclaw.types import (
    AgentEnvironmentSpec,
    AnalysisReport,
    BenchmarkConfig,
    BenchmarkItem,
    BenchmarkPackage,
    EvalDimension,
    EvalRun,
    EvalSpec,
    ItemResult,
    QcReport,
    TaskAsset,
    TaskDefinition,
    TaskSuite,
    TaskType,
)


def _suite() -> TaskSuite:
    dimensions = [
        EvalDimension(id="d1", name="One", description="First skill", approach="Direct"),
        EvalDimension(id="d2", name="Two", description="Second skill", approach="Direct"),
    ]
    spec = EvalSpec(objective="Evaluate both skills.", dimensions=dimensions, scale=3)
    return TaskSuite(
        objective=spec.objective,
        spec=spec,
        dimensions=dimensions,
        tasks=[
            BenchmarkItem(
                id=f"item_{index}",
                dimension_id="d1" if index < 3 else "d2",
                task_type=TaskType.fill_blank,
                prompt=f"Return answer {index}.",
                expected_texts=[str(index)],
            )
            for index in range(1, 4)
        ],
    )


def _response(*, analyser: bool = False) -> str:
    data = {
        name: {"score": score, "reasoning": f"{name} evidence"}
        for name, score in (
            ("clarity", 5),
            ("correctness", 4),
            ("faithfulness", 5),
            ("diversity", 3),
        )
    }
    if analyser:
        data.update(
            {
                "systematicness": {"score": 4, "reasoning": "organized failures"},
                "credibility": {"score": 3, "reasoning": "partly verified"},
            }
        )
    return json.dumps(data)


def test_laaj_scores_benchmark_with_stratified_sample(monkeypatch) -> None:
    captured: dict = {}

    def fake_call(messages, **kwargs):
        captured["request"] = json.loads(messages[0].content)
        captured.update(kwargs)
        return _response()

    monkeypatch.setattr(laaj_module, "call_llm", fake_call)
    report = laaj_module.evaluate_with_laaj(
        "Evaluate both skills.",
        _suite(),
        None,
        BenchmarkConfig(
            laaj_model="judge-model",
            laaj_provider="openai_compatible",
            laaj_api_key="judge-key",
            laaj_sample_size=2,
        ),
    )

    assert report.model == "judge-model"
    assert report.clarity.score == 5
    assert report.systematicness is None
    assert report.evaluated_item_ids == ["item_1", "item_3"]
    assert report.total_item_count == 3
    assert captured["model"] == "judge-model"
    assert captured["request"]["benchmark"]["sampling"]["sample_size"] == 2
    assert "analyser_output" not in captured["request"]


def test_laaj_agent_overview_omits_file_contents_and_environment_credentials() -> None:
    suite = _suite()
    item = suite.tasks[0]
    item.source_definition = TaskDefinition(
        id=item.id,
        dimension_id=item.dimension_id,
        task_type=TaskType.agent,
        title="Agent task",
        prompt=item.prompt,
        environment=AgentEnvironmentSpec(
            bridge_url="https://bridge.example",
            bridge_api_key="secret-bridge-key",
            vm_provider_api_key="secret-vm-key",
            hidden_files={"answer.txt": "expected answer"},
        ),
    )
    item.task_type = TaskType.agent
    item.metadata["agent_env"] = item.source_definition.environment.model_dump(mode="json")

    payload = laaj_module._item_payload(item)
    encoded = json.dumps(payload)

    assert "answer.txt" in encoded
    assert "expected answer" not in encoded
    assert "secret-bridge-key" not in encoded
    assert "secret-vm-key" not in encoded


def test_laaj_agent_tools_expose_contract_and_declared_file_on_demand() -> None:
    suite = _suite()
    item = suite.tasks[0]
    item.task_type = TaskType.agent
    item.metadata["agent_env"] = {
        "type": "docker_workspace",
        "visible_files": {"brief.txt": "inspect this evidence"},
        "hidden_files": {"tests/check.py": "assert True"},
        "actors": [{
            "id": "reviewer",
            "description": "Reviews the work",
            "system_prompt": "Report defects precisely.",
            "toolset": "reader",
        }],
        "actor_toolsets": {"reader": {"tools": ["read_file"]}},
        "bridge_api_key": "secret-bridge-key",
    }

    inspected = inspect_agent_environment(
        ToolCall(
            id="inspect",
            name="inspect_agent_environment",
            arguments={"item_ids": [item.id]},
        ),
        suite,
    )
    inspection = json.loads(inspected.content)["content"]
    assert "Report defects precisely" in inspection
    assert "brief.txt" in inspection
    assert "inspect this evidence" not in inspection
    assert "secret-bridge-key" not in inspection

    read = read_task_file(
        ToolCall(
            id="read",
            name="read_task_file",
            arguments={"item_id": item.id, "area": "visible", "path": "brief.txt"},
        ),
        suite,
    )
    assert json.loads(read.content)["content"] == "inspect this evidence"


def test_laaj_agent_tools_cover_task_agent_session_files() -> None:
    suite = _suite()
    item = suite.tasks[0]
    item.task_type = TaskType.agent
    item.metadata["agent_env"] = {"type": "vm", "session": {}}
    item.metadata["task_agent"] = {
        "initial_content": {
            "files": {"brief.txt": "workspace brief"},
            "session": {
                "assets": [{"path": "input.txt", "content": "session evidence"}],
            },
        },
    }

    inspected = inspect_agent_environment(
        ToolCall(
            id="inspect",
            name="inspect_agent_environment",
            arguments={"item_ids": [item.id]},
        ),
        suite,
    )
    inspection = json.loads(inspected.content)["content"]
    assert "brief.txt" in inspection
    assert "input.txt" in inspection
    assert "workspace brief" not in inspection
    assert "session evidence" not in inspection

    for area, path, expected in (
        ("visible", "brief.txt", "workspace brief"),
        ("session", "input.txt", "session evidence"),
    ):
        result = read_task_file(
            ToolCall(
                id=path,
                name="read_task_file",
                arguments={"item_id": item.id, "area": area, "path": path},
            ),
            suite,
        )
        assert json.loads(result.content)["content"] == expected


def test_laaj_image_tool_limits_access_to_declared_assets_and_run(tmp_path) -> None:
    task_image = tmp_path / "task.png"
    task_image.write_bytes(b"\x89PNG\r\n\x1a\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_image = run_dir / "screen.png"
    run_image.write_bytes(b"\x89PNG\r\n\x1a\n")
    outside_image = tmp_path / "outside.png"
    outside_image.write_bytes(b"\x89PNG\r\n\x1a\n")
    suite = _suite()
    suite.tasks[0].assets = [TaskAsset(path=str(task_image))]

    task_result = view_benchmark_image(
        ToolCall(
            id="task-image",
            name="view_benchmark_image",
            arguments={
                "source": "task_asset",
                "item_id": suite.tasks[0].id,
                "path": "task.png",
            },
        ),
        suite,
        run_dir,
    )
    run_result = view_benchmark_image(
        ToolCall(
            id="run-image",
            name="view_benchmark_image",
            arguments={"source": "run_artifact", "path": "screen.png"},
        ),
        suite,
        run_dir,
    )
    blocked = view_benchmark_image(
        ToolCall(
            id="outside-image",
            name="view_benchmark_image",
            arguments={"source": "run_artifact", "path": "../outside.png"},
        ),
        suite,
        run_dir,
    )

    assert task_result.error is None
    assert run_result.error is None
    assert blocked.error == "image_unavailable"


def test_laaj_uses_tool_loop_for_agent_tasks(monkeypatch) -> None:
    suite = _suite()
    item = suite.tasks[0]
    item.task_type = TaskType.agent
    item.metadata["agent_env"] = {
        "type": "docker_workspace",
        "visible_files": {"brief.txt": "evidence"},
    }
    calls: list[dict] = []

    def fake_call(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        if len(calls) == 1:
            tool_call = ToolCall(
                id="inspect",
                name="inspect_agent_environment",
                arguments={"item_ids": [item.id]},
            )
            return TargetToolModelResponse(
                adapter="litellm",
                content="",
                tool_calls=[tool_call],
                assistant_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "inspect",
                        "type": "function",
                        "function": {
                            "name": "inspect_agent_environment",
                            "arguments": json.dumps({"item_ids": [item.id]}),
                        },
                    }],
                },
                raw_response={},
            )
        return TargetToolModelResponse(
            adapter="litellm",
            content=_response(),
            tool_calls=[],
            assistant_message={"role": "assistant", "content": _response()},
            raw_response={},
        )

    monkeypatch.setattr(laaj_module, "call_orchestrator_with_tools", fake_call)
    monkeypatch.setattr(
        laaj_module,
        "call_llm",
        lambda *args, **kwargs: pytest.fail("agent LaaJ should use the tool loop"),
    )

    report = laaj_module.evaluate_with_laaj(
        suite.objective,
        suite,
        None,
        BenchmarkConfig(laaj_model="judge", laaj_api_key="key"),
    )

    assert report.correctness.score == 4
    assert {tool.name for tool in calls[0]["tools"]} == {
        "inspect_agent_environment",
        "read_task_file",
        "view_benchmark_image",
    }
    assert "brief.txt" in calls[1]["messages"][-1]["content"]


def test_laaj_scores_analyser_and_renders_report(monkeypatch) -> None:
    monkeypatch.setattr(laaj_module, "call_llm", lambda *args, **kwargs: _response(analyser=True))
    suite = _suite()
    analysis = AnalysisReport(analysis="The model has two supported failure categories.")
    laaj = laaj_module.evaluate_with_laaj(
        suite.objective,
        suite,
        analysis,
        BenchmarkConfig(laaj_model="judge", laaj_api_key="key"),
    )
    run = EvalRun(suite=suite, qc_report=QcReport(passed_item_ids=[item.id for item in suite.tasks]))
    report = build_report(run, analysis=analysis, laaj=laaj)
    package = BenchmarkPackage(
        goal=suite.objective,
        spec=suite.spec,
        suite=suite,
        qc_report=run.qc_report,
        run=run,
        analysis=analysis,
        laaj=laaj,
        report=report,
    )

    assert laaj.systematicness is not None
    assert laaj.credibility is not None
    assert "LLM-as-a-Judge Quality Evaluation" in report.markdown
    assert "Analyser credibility" in report.markdown
    assert '"laaj"' in build_report_viewer_html(package)


def test_laaj_analyser_context_includes_main_run_and_qc_evidence() -> None:
    suite = _suite()
    qc = QcReport(passed_item_ids=[item.id for item in suite.tasks], summary="valid tasks")
    run = EvalRun(
        suite=suite,
        qc_report=qc,
        results=[
            ItemResult(
                item_id="item_1",
                target_id="target",
                raw_response="incorrect answer",
                score=0.0,
                judge_reasoning="The expected value was 1.",
                latency_ms=42,
            )
        ],
    )

    payload = laaj_module._analysis_payload(
        AnalysisReport(analysis="The model failed item_1."),
        run,
        qc,
    )

    assert payload["main_qc"]["summary"] == "valid tasks"
    assert payload["main_results"][0]["raw_response_excerpt"] == "incorrect answer"
    assert payload["main_results"][0]["latency_ms"] == 42


def test_laaj_analyser_with_artifacts_exposes_run_evidence_tools(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []

    def fake_call(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return TargetToolModelResponse(
            adapter="litellm",
            content=_response(analyser=True),
            tool_calls=[],
            assistant_message={"role": "assistant", "content": _response(analyser=True)},
            raw_response={},
        )

    monkeypatch.setattr(laaj_module, "call_orchestrator_with_tools", fake_call)
    suite = _suite()
    report = laaj_module.evaluate_with_laaj(
        suite.objective,
        suite,
        AnalysisReport(analysis="A supported conclusion."),
        BenchmarkConfig(laaj_model="judge", laaj_api_key="key"),
        artifact_dir=tmp_path,
    )

    assert report.credibility is not None
    assert {tool.name for tool in calls[0]["tools"]} == {
        "read_run_artifact",
        "list_run_artifacts",
        "read_item_evidence",
    }


def test_laaj_retries_invalid_judgments(monkeypatch) -> None:
    responses = iter(["{}", "not json", _response()])
    monkeypatch.setattr(laaj_module, "call_llm", lambda *args, **kwargs: next(responses))

    report = laaj_module.evaluate_with_laaj(
        "Evaluate both skills.",
        _suite(),
        None,
        BenchmarkConfig(laaj_model="judge", laaj_api_key="key"),
    )

    assert report.correctness.score == 4


def test_laaj_requires_analyser_metrics_when_analysis_is_present(monkeypatch) -> None:
    monkeypatch.setattr(laaj_module, "call_llm", lambda *args, **kwargs: _response())

    with pytest.raises(RuntimeError, match="systematicness and credibility"):
        laaj_module.evaluate_with_laaj(
            "Evaluate both skills.",
            _suite(),
            AnalysisReport(analysis="A conclusion."),
            BenchmarkConfig(laaj_model="judge", laaj_api_key="key"),
        )


def test_cli_configures_laaj_and_analyser_ablation(monkeypatch) -> None:
    captured: dict = {}
    suite = _suite()
    run = EvalRun(suite=suite, qc_report=QcReport(passed_item_ids=[]))

    def fake_pipeline(goal, config, **kwargs):
        captured["config"] = config
        return BenchmarkPackage(
            goal=goal,
            spec=suite.spec,
            suite=suite,
            qc_report=run.qc_report,
            run=run,
            report=build_report(run),
        )

    monkeypatch.setattr("evalclaw.cli.run_pipeline", fake_pipeline)
    result = CliRunner().invoke(
        app,
        [
            "generate",
            "--goal",
            "Evaluate both skills.",
            "--no-interactive",
            "--laaj-model",
            "judge",
            "--laaj-api-key",
            "key",
            "--laaj-sample-size",
            "7",
            "--ablation-analyser",
            "similar-tasks",
        ],
    )

    assert result.exit_code == 0
    assert captured["config"].laaj_model == "judge"
    assert captured["config"].laaj_sample_size == 7
    assert captured["config"].ablation_analyser == "similar_tasks"
