from __future__ import annotations

import pytest

from evalclaw.quality import analysis as analysis_module
from evalclaw.reporting.viewer import build_report_viewer_html
from evalclaw.types import (
    AnalysisReport,
    BenchmarkConfig,
    BenchmarkItem,
    BenchmarkPackage,
    EvalDimension,
    EvalReport,
    EvalRun,
    EvalSpec,
    ItemResult,
    QcReport,
    TargetSummary,
    TaskSuite,
    TaskType,
)


def _suite_and_run() -> tuple[TaskSuite, EvalRun]:
    dimension = EvalDimension(
        id="reasoning",
        name="Reasoning",
        description="Evaluate evidence-based reasoning.",
        measurement_target="Reach supported conclusions.",
        boundary="Exclude unsupported claims.",
        approach="Use a concrete case.",
        task_types=[TaskType.generation],
        target_item_count=1,
    )
    spec = EvalSpec(
        id="analysis_test",
        objective="Evaluate evidence-based reasoning.",
        dimensions=[dimension],
        task_types=[TaskType.generation],
        scale=1,
    )
    item = BenchmarkItem(
        id="reasoning_1",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Assess the evidence and justify the conclusion.",
        rubric="Score correctness and justification.",
    )
    suite = TaskSuite(
        spec=spec,
        objective=spec.objective,
        dimensions=[dimension],
        tasks=[item],
    )
    qc_report = QcReport(passed_item_ids=[item.id])
    run = EvalRun(
        suite=suite,
        qc_report=qc_report,
        results=[
            ItemResult(
                item_id=item.id,
                target_id="target",
                raw_response="The evidence proves the claim.",
                score=0.25,
                judge_reasoning="The response ignored a counterexample.",
            )
        ],
        summaries=[
            TargetSummary(
                target_id="target",
                model="target-model",
                average_score=0.25,
                total_items=1,
            )
        ],
    )
    return suite, run


def _config(**updates) -> BenchmarkConfig:
    return BenchmarkConfig(
        analyser_model="analyser-model",
        analyser_provider="openai_compatible",
        analyser_api_key="analyser-key",
        analysis_timeout_s=5,
        **updates,
    )


def _probe_design(**updates) -> dict:
    design = {
        "dimension_id": "reasoning",
        "task_type": "generation",
        "task_count": 1,
        "challenge_effort": "E3",
        "content_design": {
            "purpose": "Distinguish counterexample blindness from general reasoning failure.",
            "description": "Require the target to test a claim against one explicit counterexample.",
        },
        "input_requirements": {},
        "interaction_requirements": {},
        "environment_requirements": {},
        "output_requirements": {},
        "scoring_contract": {},
        "source_plan": {"strategy": "generated"},
        "construction_requirements": [],
        "type_specific_requirements": {},
        "metadata": {},
    }
    design.update(updates)
    return design


def test_analysis_without_probes_returns_supported_conclusion(monkeypatch, tmp_path) -> None:
    suite, run = _suite_and_run()
    captured: list[dict] = []

    def fake_call(payload, config, **kwargs):
        captured.append(payload)
        return {
            "analysis": "The target overlooks explicit counterexamples.",
            "recommendations": ["Train on claim-testing tasks with salient counterexamples."],
            "task_designs": [],
        }

    monkeypatch.setattr(analysis_module, "_call_analyser_json", fake_call)

    report = analysis_module.run_analysis(
        suite,
        run,
        _config(analysis_iterations=0),
        artifact_dir=tmp_path,
        log=lambda _message: None,
    )

    assert report.conclusion == "The target overlooks explicit counterexamples."
    assert report.iterations == []
    assert captured[0]["main_run"]["results"][0]["raw_response"] == run.results[0].raw_response
    assert captured[0]["remaining_probe_iterations"] == 0


def test_analysis_round_trips_in_package_and_is_rendered_in_viewer() -> None:
    suite, run = _suite_and_run()
    package = BenchmarkPackage(
        goal=suite.objective,
        spec=suite.spec,
        suite=suite,
        qc_report=run.qc_report,
        run=run,
        analysis=AnalysisReport(
            conclusion="The target misses counterexamples.",
            recommendations=["Train explicit falsification checks."],
        ),
        report=EvalReport(title="Report", markdown="", summaries=[]),
    )

    restored = package.__class__.model_validate_json(package.model_dump_json())
    html = build_report_viewer_html(restored)

    assert restored.analysis is not None
    assert restored.analysis.conclusion == "The target misses counterexamples."
    assert "Model Performance Analysis" in html
    assert "The target misses counterexamples." in html


def test_analysis_runs_probe_then_analyses_new_evidence(monkeypatch, tmp_path) -> None:
    suite, run = _suite_and_run()
    original_task_ids = [item.id for item in suite.tasks]
    calls: list[dict] = []

    def fake_call(payload, config, **kwargs):
        calls.append(payload)
        if len(calls) == 1:
            return {
                "analysis": "The cause is uncertain; test counterexample handling directly.",
                "recommendations": [],
                "task_designs": [_probe_design()],
            }
        return {
            "analysis": "The probe supports a specific counterexample-handling weakness.",
            "recommendations": ["Strengthen explicit falsification checks."],
            "task_designs": [],
        }

    probe_suite, probe_run = _suite_and_run()
    probe_suite.tasks[0].id = "analysis_probe_1"
    probe_run.suite = probe_suite
    probe_run.results[0].item_id = "analysis_probe_1"

    monkeypatch.setattr(analysis_module, "_call_analyser_json", fake_call)
    monkeypatch.setattr(
        analysis_module,
        "_build_and_run_probes",
        lambda *args, **kwargs: (probe_suite, probe_run.qc_report, probe_run),
    )

    report = analysis_module.run_analysis(
        suite,
        run,
        _config(analysis_iterations=1),
        artifact_dir=tmp_path,
        log=lambda _message: None,
    )

    assert report.conclusion == "The probe supports a specific counterexample-handling weakness."
    assert len(report.iterations) == 1
    assert report.iterations[0].task_designs[0].task_design.id == "analysis_01_design_01"
    assert calls[1]["remaining_probe_iterations"] == 0
    assert calls[1]["verification_history"][0]["run"]["results"][0]["item_id"] == "analysis_probe_1"
    assert [item.id for item in suite.tasks] == original_task_ids


@pytest.mark.parametrize(
    ("design", "remaining", "max_tasks", "message"),
    [
        (_probe_design(id="model_assigned"), 1, 4, "must not assign"),
        (_probe_design(dimension_id="unknown"), 1, 4, "unknown dimension"),
        (_probe_design(task_count=2), 1, 1, "exceeding analysis_max_tasks"),
        (_probe_design(), 0, 4, "budget was exhausted"),
    ],
)
def test_analysis_rejects_invalid_probe_requests(
    design: dict,
    remaining: int,
    max_tasks: int,
    message: str,
) -> None:
    suite, _ = _suite_and_run()

    with pytest.raises(ValueError, match=message):
        analysis_module._parse_response(
            {
                "analysis": "More evidence is needed.",
                "recommendations": [],
                "task_designs": [design],
            },
            suite,
            _config(analysis_max_tasks=max_tasks),
            iteration=1,
            remaining_probe_iterations=remaining,
        )
