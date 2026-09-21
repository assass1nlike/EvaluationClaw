from __future__ import annotations

import json

import pytest

from evalclaw.quality import analysis as analysis_module
from evalclaw.reporting.viewer import build_report_viewer_html
from evalclaw.types import (
    AnalysisIteration,
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


def _benchmark(*references: dict) -> list[dict]:
    return [{
        "name": "Counterexample neglect",
        "description": "Accepts a claim despite explicit contradicting evidence.",
        "items": list(references) or [{"iteration": 0, "item_id": "reasoning_1", "target_id": "target"}],
    }]


def test_evidence_defect_survives_iterations_and_blocks_final_selection():
    suite, run = _suite_and_run()
    finding = {"iteration": 0, "item_id": "reasoning_1", "target_id": "target",
               "status": "confirmed_task_defect", "components": ["accuracy"],
               "reason": "The scorer reads a different path than the public requirement.",
               "evidence": ["grader.py: report path; item.json: public path"]}
    parsed = analysis_module._parse_evidence_assessments({"evidence_assessments": [finding]}, suite, run, [])
    prior = [AnalysisIteration(iteration=1, evidence_assessments=parsed)]
    assert analysis_module._parse_evidence_assessments({}, suite, run, prior) == parsed
    with pytest.raises(ValueError, match="unresolved evidence defect"):
        analysis_module._parse_benchmark({"benchmark": _benchmark()}, suite, run, prior)
    assert analysis_module._parse_benchmark({"benchmark": []}, suite, run, prior) == []
    cleared = {**finding, "status": "model_failure", "reason": "The full input and trace resolve the path concern.",
               "evidence": ["complete input and episode: correct path, wrong contents"]}
    data = {"benchmark": _benchmark(), "evidence_assessments": [cleared]}
    assert len(analysis_module._parse_benchmark(data, suite, run, prior)) == 1
    with pytest.raises(ValueError, match="no demonstrated model failure"):
        analysis_module._parse_benchmark({"benchmark": _benchmark(), "evidence_assessments": [
            {**cleared, "status": "no_model_failure"}]}, suite, run, prior)
    with pytest.raises(ValueError, match="Unknown or duplicate"):
        analysis_module._parse_evidence_assessments({"evidence_assessments": [{**finding, "item_id": "missing"}]}, suite, run, [])


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


def test_similar_tasks_ablation_replaces_hypothesis_method() -> None:
    prompt = analysis_module._analyser_system_prompt("goal", "similar_tasks")
    task_design_prompt = analysis_module._analyser_system_prompt(
        "task_design", "similar_tasks"
    )

    assert "maximizes the target model's error rate by creating tasks" in prompt
    assert "Similarity may involve subject matter" in prompt
    assert "Do not infer a latent capability weakness" in prompt
    assert "Group failed tasks" not in prompt
    assert "serves as an instruction for the Planner" in prompt
    assert "maximizes the target model's error rate by creating tasks" in task_design_prompt
    assert "Return TaskDesigns" in task_design_prompt


def test_removed_analyser_ablation_is_rejected() -> None:
    with pytest.raises(ValueError, match="ablation_analyser"):
        _config(ablation_analyser="error_commonality")


def test_default_analyser_strategy_keeps_hypothesis_prompt() -> None:
    assert analysis_module._analyser_system_prompt("goal") == analysis_module.ANALYSER_SYSTEM_PROMPT


def test_analyser_ablation_does_not_use_hypothesis_probe_review() -> None:
    assert analysis_module._probe_review_iterations(_config()) == 3
    assert (
        analysis_module._probe_review_iterations(
            _config(ablation_analyser="similar_tasks")
        )
        == 0
    )


def test_analysis_without_probes_returns_supported_conclusion(monkeypatch, tmp_path) -> None:
    suite, run = _suite_and_run()
    captured: list[dict] = []

    def fake_call(payload, config, **kwargs):
        captured.append(payload)
        return {
            "analysis": "The target overlooks explicit counterexamples.",
            "benchmark": _benchmark(),
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
    assert report.benchmark[0].items[0].iteration == 0
    saved = AnalysisReport.model_validate_json((tmp_path / "analysis/report.json").read_text())
    assert saved.benchmark == report.benchmark
    assert captured[0]["main_run"]["results"][0]["raw_response"] == run.results[0].raw_response
    assert captured[0]["remaining_probe_iterations"] == 0


def test_analysis_agent_context_describes_contract_without_hidden_payload() -> None:
    suite, run = _suite_and_run()
    item = suite.tasks[0].model_copy(
        update={
            "task_type": TaskType.agent,
            "metadata": {
                "agent_env": {
                    "type": "docker_workspace",
                    "image": "python:3.11",
                    "visible_files": {"README.md": "task instructions"},
                    "hidden_files": {"tests/test_secret.py": "expected = 42"},
                    "test_command": "pytest -q",
                }
            },
        }
    )
    context = analysis_module._task_context(suite.model_copy(update={"tasks": [item]}))[0]
    assert context["agent_environment"]["type"] == "docker_workspace"
    assert context["agent_task_contract"]["visible_file_paths"] == ["README.md"]
    assert "expected = 42" not in str(context)


def test_analysis_raw_response_excerpt_keeps_response_tail() -> None:
    value = "a" * 3000 + "FINAL FAILURE DETAILS"
    excerpt = analysis_module._truncate(value, limit=2000)
    assert excerpt.startswith("a")
    assert "FINAL FAILURE DETAILS" in excerpt
    assert "truncated" in excerpt


def test_analysis_context_prioritizes_failures_and_includes_latency() -> None:
    suite, run = _suite_and_run()
    run.results = [
        ItemResult(
            item_id="passed",
            target_id="target",
            raw_response="ok",
            score=1.0,
            latency_ms=10,
        ),
        ItemResult(
            item_id="low-score",
            target_id="target",
            raw_response="wrong",
            score=0.25,
            latency_ms=20,
        ),
        ItemResult(
            item_id="harness-error",
            target_id="target",
            error="runner failed",
            latency_ms=30,
        ),
    ]

    context = analysis_module._run_context(run)

    assert [item["item_id"] for item in context["results"]] == [
        "harness-error",
        "low-score",
        "passed",
    ]
    assert context["results"][0]["latency_ms"] == 30


def test_analysis_payload_advertises_artifact_discovery(tmp_path) -> None:
    suite, run = _suite_and_run()

    payload = analysis_module._analysis_payload(
        suite,
        run,
        [],
        _config(),
        artifact_dir=tmp_path,
    )

    assert payload["available_artifacts"]["index_tool"] == "list_run_artifacts"
    assert "probe_item_evidence" in payload["available_artifacts"]


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
            benchmark=_benchmark(),
        ),
        report=EvalReport(title="Report", markdown="", summaries=[]),
    )

    restored = package.__class__.model_validate_json(package.model_dump_json())
    html = build_report_viewer_html(restored)

    assert restored.analysis is not None
    assert restored.analysis.analysis == "The target misses counterexamples."
    assert restored.analysis.benchmark == package.analysis.benchmark
    assert "Model Performance Analysis" in html
    assert "The target misses counterexamples." in html
    from evalclaw.reporting.reporter import build_report

    markdown = build_report(run, analysis=restored.analysis).markdown
    assert restored.analysis.benchmark[0].name in markdown
    assert restored.analysis.benchmark[0].description in markdown
    assert restored.analysis.benchmark[0].name in html


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
            "benchmark": _benchmark(
                {"iteration": 0, "item_id": "reasoning_1", "target_id": "target"},
                {"iteration": 1, "item_id": "analysis_probe_1", "target_id": "target"},
            ),
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
        _config(
            analysis_iterations=1,
            analysis_probe_mode="task_design",
            analysis_max_tasks=4,
        ),
        artifact_dir=tmp_path,
        log=lambda _message: None,
    )

    assert report.analysis == "The probe supports a specific counterexample-handling weakness."
    assert len(report.iterations) == 1
    assert [ref.iteration for ref in report.benchmark[0].items] == [0, 1]
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

    def fake_apply(suite_arg, review, qc, config, *, log=None, trace_dir=None, max_task_count=None):
        apply_calls.append(review)
        return suite_arg.spec, suite_arg, qc

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
            type("R", (), {"blocking_errors": [], "blocked_item_ids": [], "as_dict": lambda self: {}})(),
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
            "benchmark": _benchmark(),
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
        _config(analysis_iterations=1, analysis_max_tasks=1),
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


def test_parse_response_converges_on_budget_exhaustion() -> None:
    suite, _ = _suite_and_run()
    analysis, goal, done, designs = analysis_module._parse_response(
        {
            "analysis": "More evidence is needed.",
            "task_designs": [_probe_design()],
            "done": False,
        },
        suite,
        _config(analysis_probe_mode="task_design"),
        iteration=1,
        remaining_probe_iterations=0,
    )
    assert done is True
    assert goal == ""
    assert designs == []
    assert analysis == "More evidence is needed."


@pytest.mark.parametrize("mode", ["goal", "task_design"])
@pytest.mark.parametrize("remaining,max_tasks", [(0, 3), (2, 0)])
def test_exhausted_budget_does_not_require_a_new_probe(mode, remaining, max_tasks) -> None:
    suite, _ = _suite_and_run()
    parsed = analysis_module._parse_response(
        {"analysis": "Evidence is limited.", "done": False},
        suite, _config(analysis_probe_mode=mode, analysis_max_tasks=max_tasks),
        iteration=3, remaining_probe_iterations=remaining,
    )
    assert parsed == ("Evidence is limited.", "", True, [])


def test_analysis_failure_preserves_completed_iterations_and_can_resume(monkeypatch, tmp_path) -> None:
    suite, run = _suite_and_run()
    iteration = analysis_module.AnalysisIteration(iteration=1, suite=suite, run=run, qc_report=run.qc_report)
    analysis_module.write_json(tmp_path / "analysis/iteration-01.json", iteration.model_dump(mode="json"))

    def fail(*args, **kwargs):
        raise ValueError("Invalid analyser output")

    monkeypatch.setattr(analysis_module, "_call_analyser_json", fail)
    report = analysis_module.run_analysis(suite, run, _config(), artifact_dir=tmp_path, log=lambda _: None)
    assert report.status == "failed"
    assert len(report.iterations) == 1
    assert report.analysis == ""
    assert (tmp_path / "analysis/failed-report.json").is_file()
    from evalclaw.reporting.reporter import build_report

    markdown = build_report(run, analysis=report).markdown
    assert "Invalid analyser output" in markdown
    assert "Analysis status: failed" in markdown
    monkeypatch.setattr(analysis_module, "_call_analyser_json", lambda *a, **k: {"analysis": "Concluded.", "done": True, "benchmark": []})
    resumed = analysis_module.run_analysis(suite, run, _config(), artifact_dir=tmp_path, log=lambda _: None)
    assert resumed.status == "completed"
    assert resumed.analysis == "Concluded."


def test_goal_probe_planning_receives_its_own_budget(monkeypatch) -> None:
    suite, _ = _suite_and_run()
    config = _config(item_count=20, analysis_max_tasks=3, challenge_effort_distribution={"E2": 0.8, "E3": 0.2})

    class ReachedPlanner(Exception):
        pass

    def build(goal, scoped, **kwargs):
        assert scoped.item_count is None
        assert scoped.challenge_effort_distribution == {}
        assert kwargs["max_task_count"] == 3
        assert scoped.analysis_max_tasks == 3
        raise ReachedPlanner

    monkeypatch.setattr(analysis_module, "build_benchmark_suite_with_qc_loop", build)
    with pytest.raises(ReachedPlanner):
        analysis_module._build_and_run_probes(suite, config, "Hypothesis", "Make one E1 task", [], iteration=1, trace_dir=None, log=lambda _: None)
    assert config.item_count == 20
    assert config.challenge_effort_distribution


def test_probe_review_rejects_budget_expansion_before_construction(monkeypatch) -> None:
    suite, _ = _suite_and_run()

    def loop(payload, config, **kwargs):
        kwargs["validate"]({"done": False, "needs_more_items": [{"dimension_id": "reasoning", "count": 4, "guidance": "Add counterexamples."}]})

    monkeypatch.setattr(analysis_module, "_run_analyser_tool_loop", loop)
    with pytest.raises(ValueError, match="exceed"):
        analysis_module._review_probes(suite, "Hypothesis", _config(analysis_max_tasks=2), trace_dir=None)


def test_probe_review_repairs_foreign_dimension_reference(monkeypatch) -> None:
    from evalclaw.models.llm import TargetToolModelResponse

    suite, _ = _suite_and_run()
    calls = []
    corrected = {"done": False, "update_items": [{
        "item_id": "reasoning_1", "dimension_id": "reasoning", "guidance": "Add conflicting evidence.",
    }]}

    def model(messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            payload = json.loads(messages[0]["content"])
            assert payload["dimensions"][0]["measurement_target"] == "Reach supported conclusions."
            result = {"done": False, "needs_more_items": [{
                "dimension_id": "main_suite_dimension", "count": 1, "guidance": "Replace the probe.",
            }]}
        else:
            result = corrected
        content = json.dumps(result)
        return TargetToolModelResponse(adapter="openai", raw_response={}, content=content, tool_calls=[],
            assistant_message={"role": "assistant", "content": content})

    monkeypatch.setattr(analysis_module, "call_orchestrator_with_tools", model)
    assert analysis_module._review_probes(suite, "Original dimension differs.", _config(), trace_dir=None) == corrected
    assert len(calls) == 2
    assert "needs_more_items[0].dimension_id" in calls[1][-1]["content"]


@pytest.mark.parametrize("save_trace", [False, True])
def test_probe_review_can_read_full_current_task(monkeypatch, tmp_path, save_trace) -> None:
    from evalclaw.protocols.tool import ToolCall

    suite, _ = _suite_and_run()
    suite.tasks[0].metadata["agent_env"] = {
        "actors": [{"id": "colleague", "system_prompt": "State your own uncertain observations."}],
        "hidden_files": {"grade.py": "print(0)"},
    }
    roots = []

    def loop(payload, config, **kwargs):
        root = kwargs["artifact_dir"]
        roots.append(root)
        result = analysis_module.read_run_artifact(ToolCall(id="read", name="read_run_artifact",
            arguments={"path": payload["task_evidence_path"]}), root)
        assert not result.error
        saved = json.loads(json.loads(result.content)["content"])
        assert saved["suite"]["tasks"][0]["metadata"]["agent_env"] == suite.tasks[0].metadata["agent_env"]
        return {"done": True}

    monkeypatch.setattr(analysis_module, "_run_analyser_tool_loop", loop)
    analysis_module._review_probes(suite, "Hypothesis", _config(), trace_dir=tmp_path if save_trace else None)
    assert roots[0].exists() == save_trace


@pytest.mark.parametrize("review", [
    {"done": False, "delete_item_ids": ["absent"]},
    {"done": False, "update_items": [{"item_id": "absent", "dimension_id": "reasoning", "guidance": "fix"}]},
    {"done": False, "needs_more_items": [{"dimension_id": [], "count": 1, "guidance": "fix"}]},
    {"done": False, "needs_more_items": [{"dimension_id": "reasoning", "count": True, "guidance": "fix"}]},
    {"done": False, "update_items": {}},
    {"done": True, "delete_item_ids": ["reasoning_1"]},
    {"done": False},
])
def test_probe_review_rejects_invalid_actions(monkeypatch, review) -> None:
    suite, _ = _suite_and_run()

    def loop(payload, config, **kwargs):
        kwargs["validate"](review)

    monkeypatch.setattr(analysis_module, "_run_analyser_tool_loop", loop)
    with pytest.raises(ValueError):
        analysis_module._review_probes(suite, "Hypothesis", _config(), trace_dir=None)


def test_final_benchmark_resolves_colliding_ids_by_iteration_and_target() -> None:
    suite, run = _suite_and_run()
    probe_suite, probe_run = _suite_and_run()
    probe_run.results[0].target_id = "second-target"
    history = [AnalysisIteration(iteration=1, suite=probe_suite, run=probe_run)]
    refs = [
        {"iteration": 0, "item_id": "reasoning_1", "target_id": "target"},
        {"iteration": 1, "item_id": "reasoning_1", "target_id": "second-target"},
    ]
    groups = analysis_module._parse_benchmark({"benchmark": _benchmark(*refs)}, suite, run, history)
    assert [item.model_dump() for item in groups[0].items] == refs
    refs[1]["target_id"] = "target"
    with pytest.raises(ValueError, match="existing task"):
        analysis_module._parse_benchmark({"benchmark": _benchmark(*refs)}, suite, run, history)


@pytest.mark.parametrize("problem", ["unknown_task", "unrun", "runner_error", "qc_rejected", "duplicate"])
def test_final_benchmark_rejects_invalid_evidence(problem) -> None:
    suite, run = _suite_and_run()
    groups = _benchmark()
    if problem == "unknown_task":
        groups[0]["items"][0]["item_id"] = "invented"
    elif problem == "unrun":
        run.results = []
    elif problem == "runner_error":
        run.results[0].error = "Environment setup failed."
    elif problem == "qc_rejected":
        run.qc_report.rejected_item_ids = ["reasoning_1"]
    else:
        groups[0]["items"] *= 2
    with pytest.raises(ValueError):
        analysis_module._parse_benchmark({"benchmark": groups}, suite, run, [])


@pytest.mark.parametrize("groups", [None, {}, [{"name": "", "description": "Failure", "items": []}]])
def test_final_benchmark_requires_a_valid_group_list(groups) -> None:
    suite, run = _suite_and_run()
    with pytest.raises(ValueError):
        analysis_module._parse_benchmark({"benchmark": groups}, suite, run, [])
    assert analysis_module._parse_benchmark({"benchmark": []}, suite, run, []) == []


@pytest.mark.parametrize("mode", ["goal", "task_design"])
@pytest.mark.parametrize("ablation", ["none", "similar_tasks"])
@pytest.mark.parametrize("stop", ["voluntary", "iterations", "tasks"])
def test_terminal_analysis_repairs_missing_benchmark(monkeypatch, tmp_path, mode, ablation, stop) -> None:
    suite, run = _suite_and_run()
    calls = []

    def model(messages, **kwargs):
        calls.append(messages)
        data = {
            "analysis": "No trustworthy weakness classification can be established.",
            "done": stop == "voluntary",
        }
        if len(calls) > 1:
            data["benchmark"] = []
        content = json.dumps(data)
        return analysis_module.TargetToolModelResponse(
            adapter="openai_compatible", content=content, tool_calls=[],
            assistant_message={"role": "assistant", "content": content}, raw_response={},
        )

    monkeypatch.setattr(analysis_module, "call_orchestrator_with_tools", model)
    report = analysis_module.run_analysis(
        suite, run,
        _config(
            analysis_probe_mode=mode, ablation_analyser=ablation,
            analysis_iterations=0 if stop == "iterations" else 3,
            analysis_max_tasks=0 if stop == "tasks" else 1,
        ),
        artifact_dir=tmp_path, log=lambda _: None,
    )
    assert len(calls) == 2
    assert report.status == "completed"
    assert report.benchmark == []
    assert report.iterations == []
