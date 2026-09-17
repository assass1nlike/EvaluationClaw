import json

import pytest

from evalclaw import pipeline
from evalclaw.diagnostics import write_json
from evalclaw.reporting.viewer import build_report_viewer_html
from evalclaw.types import (
    AnalysisIteration,
    AnalysisReport,
    BenchmarkConfig,
    ContaminationReport,
    EvalRun,
    ItemResult,
    LaajReport,
    QcReport,
    TargetModelConfig,
)
from tests.test_laaj import _response, _suite


def _quality(suite):
    return LaajReport(
        model="judge", **json.loads(_response()),
        evaluated_item_ids=[item.id for item in suite.tasks], total_item_count=len(suite.tasks),
    )


def _contamination(suite):
    return ContaminationReport(
        model="judge", search_backend="gemini", total_item_count=len(suite.tasks),
        max_queries_per_item=20, max_sources_per_item=20, source_character_limit=1000,
    )


def _analysis(suite, strategy="hypothesis_driven"):
    return AnalysisReport(strategy=strategy, iterations=[
        AnalysisIteration(
            iteration=number, goal=f"Expand failure {number}",
            suite=suite.model_copy(update={"tasks": suite.tasks[:number]}),
            qc_report=QcReport(passed_item_ids=[item.id for item in suite.tasks[:number]]),
        )
        for number in (1, 2)
    ])


@pytest.mark.parametrize("ablation", ["none", "similar_tasks"])
def test_pipeline_adds_iteration_judgments_to_existing_main_report(monkeypatch, tmp_path, ablation):
    suite = _suite()
    qc = QcReport(passed_item_ids=[item.id for item in suite.tasks])
    run = EvalRun(suite=suite, qc_report=qc, results=[
        ItemResult(item_id=item.id, target_id="target", score=1, raw_response="answer")
        for item in suite.tasks
    ])
    analysis = _analysis(suite, "similar_tasks" if ablation == "similar_tasks" else "hypothesis_driven")
    root = tmp_path / "debug/runs/saved"
    write_json(root / "input.json", {"original_goal": "Original goal", "normalized_goal": "Original goal"})
    write_json(root / "construction/plan.json", {"plan": None, "spec": suite.spec.model_dump(mode="json")})
    write_json(root / "construction/final.json", {
        "suite": suite.model_dump(mode="json"), "qc_report": qc.model_dump(mode="json"),
    })
    write_json(root / "environment-state.json", {
        "run_targets": True, "suite": suite.model_dump(mode="json"), "report": {"enabled": False},
    })
    write_json(root / "run.json", run.model_dump(mode="json"))
    main = _quality(suite)
    main.contamination = _contamination(suite)
    write_json(root / "laaj.json", main.model_dump(mode="json"))
    monkeypatch.setattr(pipeline, "run_analysis", lambda *a, **k: analysis)
    monkeypatch.setattr(pipeline, "_persist_package", lambda *a, **k: None)

    def unexpected(*args, **kwargs):
        pytest.fail("A saved construction or target run was repeated")

    monkeypatch.setattr(pipeline, "build_benchmark_suite_with_qc_loop", unexpected)
    monkeypatch.setattr(pipeline, "run_eval", unexpected)
    calls = []

    def judge(goal, current, analyser, config, **kwargs):
        number = len(current.tasks)
        assert goal == "Original goal"
        assert analyser is None  # Do not score the entire Analyser again per iteration.
        assert kwargs["qc_report"] == analysis.iterations[number - 1].qc_report
        assert kwargs["artifact_dir"] == root / "analysis" / f"iteration-{number:02d}"
        assert kwargs["trace_dir"] == kwargs["artifact_dir"] / "laaj"
        calls.append(("quality", number))
        return _quality(current)

    def contamination(goal, current, config, **kwargs):
        number = len(current.tasks)
        assert goal == "Original goal"
        assert kwargs["trace_dir"] == root / "analysis" / f"iteration-{number:02d}" / "contamination"
        calls.append(("contamination", number))
        return _contamination(current)

    monkeypatch.setattr(pipeline, "evaluate_with_laaj", judge)
    monkeypatch.setattr(pipeline, "evaluate_contamination", contamination)
    config = BenchmarkConfig(
        output_dir=str(tmp_path), targets=[TargetModelConfig(id="target", provider="openai", model="model")],
        analyser_model="analyser", analyser_api_key="test", ablation_analyser=ablation,
        laaj_model="judge", laaj_api_key="test",
    )
    package = pipeline.run_pipeline(None, config, resume_run=root, log=lambda _: None)
    assert calls == [("quality", 1), ("contamination", 1), ("quality", 2), ("contamination", 2)]
    assert package.laaj.total_item_count == 3
    assert set(package.laaj.iteration_reports) == {1, 2}
    assert package.laaj.iteration_reports[2].total_item_count == 2
    assert package.laaj.iteration_reports[2].contamination.total_item_count == 2
    assert "#### Iteration 2" in package.report.markdown
    assert '"iteration_reports"' in build_report_viewer_html(package)
    restored = LaajReport.model_validate_json((root / "laaj.json").read_text())
    assert restored == package.laaj
    calls.clear()
    resumed = pipeline.run_pipeline(None, config, resume_run=root, log=lambda _: None)
    assert calls == []
    assert resumed.laaj == package.laaj


def test_iteration_resume_retains_quality_when_contamination_raises(monkeypatch, tmp_path):
    suite = _suite()
    analysis = _analysis(suite)
    main = _quality(suite)
    quality_calls, contamination_calls = [], []

    def judge(goal, current, *args, **kwargs):
        quality_calls.append(len(current.tasks))
        return _quality(current)

    def contamination(goal, current, *args, **kwargs):
        contamination_calls.append(len(current.tasks))
        if contamination_calls == [1, 2]:
            raise RuntimeError("Search unavailable")
        return _contamination(current)

    monkeypatch.setattr(pipeline, "evaluate_with_laaj", judge)
    monkeypatch.setattr(pipeline, "evaluate_contamination", contamination)
    config = BenchmarkConfig()
    with pytest.raises(RuntimeError, match="Search unavailable"):
        pipeline._evaluate_iteration_quality(
            "Goal", analysis, main, config, debug_run_dir=tmp_path, resuming=False, log=lambda _: None,
        )
    partial = LaajReport.model_validate_json((tmp_path / "laaj.json").read_text())
    assert partial.iteration_reports[1].contamination is not None
    assert partial.iteration_reports[2].contamination is None
    pipeline._evaluate_iteration_quality(
        "Goal", analysis, partial, config, debug_run_dir=tmp_path, resuming=True, log=lambda _: None,
    )
    assert quality_calls == [1, 2]
    assert contamination_calls == [1, 2, 2]
    assert partial.iteration_reports[2].contamination is not None


def test_iteration_quality_without_contamination_or_disk(monkeypatch):
    suite = _suite()
    analysis = _analysis(suite)
    analysis.iterations.extend([
        AnalysisIteration(iteration=3),
        AnalysisIteration(iteration=4, suite=suite.model_copy(update={"tasks": []})),
    ])
    main = _quality(suite)

    def judge(goal, current, *args, **kwargs):
        assert kwargs["artifact_dir"] is None
        assert kwargs["trace_dir"] is None
        return _quality(current)

    monkeypatch.setattr(pipeline, "evaluate_with_laaj", judge)
    monkeypatch.setattr(pipeline, "evaluate_contamination", lambda *a, **k: pytest.fail("Contamination disabled"))
    pipeline._evaluate_iteration_quality(
        "Goal", analysis, main, BenchmarkConfig(contamination_enabled=False),
        debug_run_dir=None, resuming=False, log=lambda _: None,
    )
    assert set(main.iteration_reports) == {1, 2}
    assert all(result.contamination is None for result in main.iteration_reports.values())
