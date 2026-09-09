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
            "goal": "",
            "done": True,
        }

    monkeypatch.setattr(analysis_module, "_call_analyser_json", fake_call)

    report = analysis_module.run_analysis(
        suite,
        run,
        _config(analysis_iterations=0),
        artifact_dir=tmp_path,
        log=lambda _message: None,
    )

    assert report.analysis == "The target overlooks explicit counterexamples."
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
            analysis="The target misses counterexamples.",
        ),
        report=EvalReport(title="Report", markdown="", summaries=[]),
    )

    restored = package.__class__.model_validate_json(package.model_dump_json())
    html = build_report_viewer_html(restored)

    assert restored.analysis is not None
    assert restored.analysis.analysis == "The target misses counterexamples."
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
                "task_designs": [_probe_design()],
                "done": False,
            }
        return {
            "analysis": "The probe supports a specific counterexample-handling weakness.",
            "task_designs": [],
            "done": True,
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
        _config(analysis_iterations=1, analysis_probe_mode="task_design"),
        artifact_dir=tmp_path,
        log=lambda _message: None,
    )

    assert report.analysis == "The probe supports a specific counterexample-handling weakness."
    assert len(report.iterations) == 1
    assert report.iterations[0].task_designs[0].task_design.id == "analysis_01_design_01"
    assert calls[1]["remaining_probe_iterations"] == 0
    assert calls[1]["verification_history"][0]["run"]["results"][0]["item_id"] == "analysis_probe_1"
    assert [item.id for item in suite.tasks] == original_task_ids


def test_review_probes_returns_review(monkeypatch) -> None:
    suite, _ = _suite_and_run()

    def fake_loop(payload, config, **kwargs):
        assert payload["hypothesis"] == "hypo"
        assert payload["tasks"][0]["id"] == "reasoning_1"
        return {
            "done": False,
            "update_items": [
                {"item_id": "reasoning_1", "dimension_id": "reasoning", "guidance": "fix"}
            ],
        }

    monkeypatch.setattr(analysis_module, "_run_analyser_tool_loop", fake_loop)
    review = analysis_module._review_probes(suite, "hypo", _config(), trace_dir=None)
    assert review["done"] is False
    assert review["update_items"][0]["item_id"] == "reasoning_1"


def test_review_probes_requires_done(monkeypatch) -> None:
    suite, _ = _suite_and_run()
    monkeypatch.setattr(
        analysis_module, "_run_analyser_tool_loop", lambda *args, **kwargs: {"update_items": []}
    )
    with pytest.raises(ValueError, match="done"):
        analysis_module._review_probes(suite, "hypo", _config(), trace_dir=None)


def test_build_and_run_probes_reviews_until_accepted(monkeypatch) -> None:
    suite, run = _suite_and_run()
    probe_suite, probe_run = _suite_and_run()
    probe_suite.tasks[0].id = "analysis_probe_1"
    probe_run.suite = probe_suite

    reviews = [
        {
            "done": False,
            "update_items": [
                {"item_id": "analysis_probe_1", "dimension_id": "reasoning", "guidance": "fix"}
            ],
        },
        {"done": True, "update_items": []},
    ]
    review_calls: list[dict] = []
    apply_calls: list[dict] = []

    def fake_review(suite_arg, analysis, config, *, trace_dir):
        review = reviews[len(review_calls)]
        review_calls.append(review)
        return review

    def fake_apply(suite_arg, review, qc, config, *, log=None, trace_dir=None):
        apply_calls.append(review)
        return suite_arg, qc

    class _Plan:
        suite = probe_suite

    monkeypatch.setattr(analysis_module, "_review_probes", fake_review)
    monkeypatch.setattr(
        analysis_module,
        "build_suite_from_spec_with_qc_loop",
        lambda spec, jobs, config, **kwargs: (probe_suite, probe_run.qc_report),
    )
    monkeypatch.setattr(analysis_module, "apply_review_to_suite", fake_apply)
    monkeypatch.setattr(
        analysis_module,
        "build_execution_plan",
        lambda suite_arg, qc: _Plan(),
    )
    monkeypatch.setattr(
        analysis_module,
        "run_environment_claw",
        lambda tasks, config: (
            config,
            type("R", (), {"blocking_errors": [], "as_dict": lambda self: {}})(),
        ),
    )
    monkeypatch.setattr(
        analysis_module, "run_eval", lambda suite_arg, qc, config, **kwargs: probe_run
    )

    design_payload = {key: value for key, value in _probe_design().items() if key != "dimension_id"}
    design = analysis_module.AnalysisProbeDesign(
        dimension_id="reasoning",
        task_design=analysis_module.TaskDesign(id="d", **design_payload),
    )
    out_suite, out_qc, out_run = analysis_module._build_and_run_probes(
        suite,
        _config(analysis_review_max_iterations=3),
        "hypo",
        "",
        [design],
        iteration=1,
        trace_dir=None,
        log=lambda _message: None,
    )

    assert len(review_calls) == 2
    assert len(apply_calls) == 1
    assert apply_calls[0]["done"] is False
    assert out_run is probe_run


def test_analysis_defaults_to_goal_probe(monkeypatch, tmp_path) -> None:
    suite, run = _suite_and_run()
    calls: list[dict] = []

    def fake_call(payload, config, **kwargs):
        calls.append(payload)
        if len(calls) == 1:
            return {
                "analysis": "The cause is uncertain; test counterexample handling.",
                "goal": "Evaluate whether the model rejects claims contradicted by one counterexample.",
                "done": False,
            }
        return {
            "analysis": "The probe confirms a counterexample-handling weakness.",
            "goal": "",
            "done": True,
        }

    captured: dict = {}

    def fake_build(main_suite, config, analysis, goal, task_designs, **kwargs):
        captured["goal"] = goal
        captured["task_designs"] = task_designs
        probe_suite, probe_run = _suite_and_run()
        return probe_suite, probe_run.qc_report, probe_run

    monkeypatch.setattr(analysis_module, "_call_analyser_json", fake_call)
    monkeypatch.setattr(analysis_module, "_build_and_run_probes", fake_build)

    report = analysis_module.run_analysis(
        suite,
        run,
        _config(analysis_iterations=1),
        artifact_dir=tmp_path,
        log=lambda _message: None,
    )

    assert captured["goal"] == (
        "Evaluate whether the model rejects claims contradicted by one counterexample."
    )
    assert captured["task_designs"] == []
    assert report.analysis == "The probe confirms a counterexample-handling weakness."
    assert (
        report.iterations[0].goal
        == "Evaluate whether the model rejects claims contradicted by one counterexample."
    )


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
                "task_designs": [design],
                "done": False,
            },
            suite,
            _config(analysis_max_tasks=max_tasks, analysis_probe_mode="task_design"),
            iteration=1,
            remaining_probe_iterations=remaining,
        )
