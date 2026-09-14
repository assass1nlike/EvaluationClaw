from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from evalclaw.cli import app
from evalclaw.quality import laaj as laaj_module
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
    QcReport,
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


def test_laaj_builder_reference_omits_environment_credentials() -> None:
    item = _suite().tasks[0]
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

    payload = laaj_module._item_payload(item)

    assert "expected answer" in json.dumps(payload)
    assert "secret-bridge-key" not in json.dumps(payload)
    assert "secret-vm-key" not in json.dumps(payload)


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
