from __future__ import annotations

import json

import pytest

from evalclaw.construction.suite import build_task_suite
from evalclaw.diagnostics import write_json
from evalclaw.execution.runner import run_eval
from evalclaw.pipeline import _load_construction_resume, run_pipeline
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    BenchmarkPlan,
    EvalDimension,
    EvalReport,
    EvalRun,
    EvalSpec,
    ItemResult,
    QcReport,
    TargetModelConfig,
    TaskDefinition,
    TaskSuite,
    TaskType,
)
from tests.blueprint_factory import make_blueprint
from tests.config_helpers import dummy_config_kwargs, patch_task_builder_model


def test_builder_reuses_completed_job_checkpoint(monkeypatch, tmp_path) -> None:
    calls = 0

    def responder(messages, *args, **kwargs):
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "tasks": [
                    {
                        "task_type": "fill_blank",
                        "title": "A task",
                        "prompt": "Return the exact value.",
                        "expected_texts": ["42"],
                        "metadata": {
                            "challenge_effort_self_assessment": {
                                "requested_effort": "E3",
                                "meets_requested_effort": True,
                                "rationale": "The task is sufficiently challenging.",
                            }
                        },
                    }
                ]
            }
        )

    patch_task_builder_model(monkeypatch, responder)
    dimension = EvalDimension(
        id="dimension",
        name="Dimension",
        description="Measure the capability.",
        approach="Use one task.",
        task_types=[TaskType.fill_blank],
    )
    spec = EvalSpec(
        objective="Evaluate the capability.",
        dimensions=[dimension],
        task_types=[TaskType.fill_blank],
    )
    blueprint = make_blueprint(
        "builder",
        dimension.id,
        "One task",
        task_type=TaskType.fill_blank,
    )
    config = BenchmarkConfig(
        **dummy_config_kwargs(),
        output_dir=str(tmp_path),
        task_builder_max_workers=1,
        use_web_research=False,
    )
    checkpoint_dir = tmp_path / "checkpoints"

    first = build_task_suite(spec, [blueprint], config, checkpoint_dir=checkpoint_dir)
    assert calls == 1
    assert len(list(checkpoint_dir.glob("*.json"))) == 1

    def fail_if_called(*args, **kwargs):
        raise AssertionError("completed Builder job was called again")

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", fail_if_called)
    second = build_task_suite(spec, [blueprint], config, checkpoint_dir=checkpoint_dir)
    assert [task.prompt for task in second.tasks] == [task.prompt for task in first.tasks]


def test_runner_reuses_successful_items_but_retries_failed_items(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def fake_run_item(item, config, target_id, **kwargs):
        calls.append(item.id)
        return ItemResult(item_id=item.id, target_id=target_id, raw_response="ok", score=1.0)

    monkeypatch.setattr("evalclaw.execution.runner._run_item", fake_run_item)
    dimension = EvalDimension(
        id="dimension",
        name="Dimension",
        description="Measure the capability.",
        approach="Use direct tasks.",
        target_item_count=2,
    )
    suite = TaskSuite(
        objective="Evaluate the capability.",
        spec=EvalSpec(objective="Evaluate the capability.", dimensions=[dimension]),
        tasks=[
            BenchmarkItem(
                id=item_id,
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt=f"Solve {item_id}.",
                rubric="Score correctness.",
            )
            for item_id in ("first", "second")
        ],
    )
    config = BenchmarkConfig(
        output_dir=str(tmp_path),
        targets=[TargetModelConfig(id="target", provider="openai", model="model")],
    )
    trace_dir = tmp_path / "runner"

    run_eval(suite, QcReport(passed_item_ids=["first", "second"]), config, trace_dir=trace_dir)
    assert sorted(calls) == ["first", "second"]
    calls.clear()
    run_eval(suite, QcReport(passed_item_ids=["first", "second"]), config, trace_dir=trace_dir)
    assert calls == []


def test_construction_resume_restores_builder_source_definitions(tmp_path) -> None:
    dimension = EvalDimension(
        id="dimension",
        name="Dimension",
        description="Measure the capability.",
        approach="Use one task.",
    )
    spec = EvalSpec(
        objective="Evaluate the capability.",
        subjects=["target"],
        dimensions=[dimension],
    )
    plan = BenchmarkPlan(
        objective=spec.objective,
        subjects=spec.subjects,
    )
    source = TaskDefinition(
        id="item",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        title="Builder task",
        prompt="Original Builder task.",
        rubric="Score correctness.",
    )
    suite = TaskSuite(
        objective=spec.objective,
        spec=spec,
        tasks=[
            BenchmarkItem(
                id=source.id,
                dimension_id=source.dimension_id,
                task_type=source.task_type,
                prompt="Packaged task.",
                rubric=source.rubric,
                source_definition=source,
            )
        ],
    )
    construction_dir = tmp_path / "construction"
    write_json(
        construction_dir / "plan.json",
        {"plan": plan.model_dump(mode="json"), "spec": spec.model_dump(mode="json")},
    )
    write_json(construction_dir / "initial-suite.json", suite.model_dump(mode="json"))
    write_json(construction_dir / "initial-qc.json", QcReport().model_dump(mode="json"))
    write_json(
        construction_dir / "builder-checkpoints" / "initial-0000-builder.json",
        {"tasks": [source.model_dump(mode="json")]},
    )

    resumed_plan, resumed_suite, _, _ = _load_construction_resume(construction_dir)

    assert resumed_plan is not None
    assert resumed_plan.subjects == ["target"]
    assert resumed_suite is not None
    assert resumed_suite.tasks[0].source_definition == source


def test_resumed_plan_restores_runtime_targets_before_builder(monkeypatch):
    from evalclaw.benchmark import build_benchmark_suite_with_qc_loop
    from evalclaw.construction.suite import _BlueprintBuildJob, _builder_checkpoint_digest
    from evalclaw.types import BenchmarkPlanDimension

    blueprint = make_blueprint("builder", "dimension", "One task", task_type=TaskType.fill_blank)
    original = BenchmarkPlan(
        objective="Evaluate", subjects=["target"],
        dimensions=[BenchmarkPlanDimension(
            id="dimension", name="Dimension", measurement_target="reasoning",
            boundary="reasoning", approach="direct", task_designs=blueprint.task_designs,
        )],
    )
    spec = original.to_eval_spec()
    expected = _builder_checkpoint_digest(
        spec, _BlueprintBuildJob(0, spec.dimensions[0], original.builder_jobs[0]), None, "initial",
    )
    restored = BenchmarkPlan.model_validate(original.model_dump(mode="json"))
    assert restored.subjects == []

    def build(spec, jobs, config, **kwargs):
        actual = _builder_checkpoint_digest(
            spec, _BlueprintBuildJob(0, spec.dimensions[0], jobs[0]), None, "initial",
        )
        assert actual == expected
        return TaskSuite(objective=spec.objective, spec=spec), QcReport()

    monkeypatch.setattr("evalclaw.benchmark.build_suite_from_spec_with_qc_loop", build)
    build_benchmark_suite_with_qc_loop(
        "Evaluate", BenchmarkConfig(targets=[TargetModelConfig(id="target", provider="openai", model="model")]),
        resume_plan=restored,
    )


def test_strict_resume_rejects_missing_tasks_even_when_saved_qc_passed(monkeypatch, tmp_path):
    dimension = EvalDimension(id="dimension", name="Dimension", description="Reason.", approach="Solve.")
    spec = EvalSpec(objective="Evaluate reasoning.", dimensions=[dimension])
    blueprint = make_blueprint("builder", dimension.id, "Tasks", task_type=TaskType.fill_blank, count=2)
    item = BenchmarkItem(
        id="builder_task_1", dimension_id=dimension.id, task_type=TaskType.fill_blank,
        prompt="Compute the requested value.", expected_texts=["42"],
        metadata={"builder_job_id": blueprint.id},
    )
    suite = TaskSuite(objective=spec.objective, spec=spec, blueprints=[blueprint], tasks=[item])
    run_dir = tmp_path / "debug" / "runs" / "partial"
    write_json(run_dir / "input.json", {"normalized_goal": spec.objective})
    write_json(run_dir / "construction" / "plan.json", {"spec": spec.model_dump(mode="json")})
    write_json(run_dir / "construction" / "final.json", {
        "suite": suite.model_dump(mode="json"),
        "qc_report": QcReport(passed_item_ids=[item.id]).model_dump(mode="json"),
    })

    def unexpected(*args, **kwargs):
        pytest.fail("Strict resume must reject the partial suite before building or running tasks.")

    monkeypatch.setattr("evalclaw.pipeline.build_benchmark_suite_with_qc_loop", unexpected)
    monkeypatch.setattr("evalclaw.pipeline.run_eval", unexpected)
    with pytest.raises(RuntimeError, match="every planned task"):
        run_pipeline(None, BenchmarkConfig(
            output_dir=str(tmp_path), allow_incomplete_benchmark=False, analysis_iterations=0,
        ), resume_run=run_dir)


@pytest.mark.parametrize("state", ["disabled", "complete", "failed", "missing", "duplicate", "wrong_target"])
def test_pipeline_resumes_run_checkpoint(monkeypatch, tmp_path, state) -> None:
    dimension = EvalDimension(
        id="dimension",
        name="Dimension",
        description="Measure the capability.",
        approach="Use direct tasks.",
        target_item_count=1,
    )
    spec = EvalSpec(objective="Evaluate the capability.", dimensions=[dimension])
    suite = TaskSuite(
        objective=spec.objective,
        spec=spec,
        tasks=[
            BenchmarkItem(
                id=item_id,
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt="Solve the task.",
                rubric="Score correctness.",
            )
            for item_id in ("first", "second", "excluded")
        ],
    )
    qc_report = QcReport(passed_item_ids=["first", "second"], rejected_item_ids=["excluded"])
    target = TargetModelConfig(id="target", provider="openai", model="model")
    # An incorrect answer with no execution error must be reused too.
    first = ItemResult(item_id="first", target_id=target.id, raw_response="incorrect answer", score=0)
    second = ItemResult(item_id="second", target_id=target.id, raw_response="answer", score=1)
    saved_results = {
        "disabled": [],
        "complete": [first, second],
        "failed": [first, second.model_copy(update={"error": "gateway failed", "score": 0})],
        "missing": [first],
        "duplicate": [first, first],
        "wrong_target": [first, second.model_copy(update={"target_id": "other-target"})],
    }[state]
    run = EvalRun(suite=suite, qc_report=qc_report, results=saved_results)
    run_dir = tmp_path / "debug" / "runs" / "saved-run"
    write_json(run_dir / "input.json", {"original_goal": "goal", "normalized_goal": "goal"})
    write_json(
        run_dir / "construction" / "plan.json",
        {"plan": None, "spec": spec.model_dump(mode="json")},
    )
    write_json(
        run_dir / "construction" / "final.json",
        {"suite": suite.model_dump(mode="json"), "qc_report": qc_report.model_dump(mode="json")},
    )
    write_json(
        run_dir / "environment-state.json",
        {"run_targets": state != "disabled", "suite": suite.model_dump(mode="json"), "report": {"enabled": False}},
    )
    write_json(run_dir / "run.json", run.model_dump(mode="json"))
    for result in saved_results:
        write_json(
            run_dir / "runner" / result.target_id / result.item_id / "result.json",
            result.model_dump(mode="json"),
        )

    monkeypatch.setattr(
        "evalclaw.pipeline.build_benchmark_suite_with_qc_loop",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("construction was rerun")),
    )
    monkeypatch.setattr(
        "evalclaw.pipeline.run_environment_claw",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("environment was rerun")),
    )
    calls = []

    def execute(item, config, target_id, **kwargs):
        calls.append((target_id, item.id))
        return ItemResult(item_id=item.id, target_id=target_id, raw_response="retried", score=1)

    monkeypatch.setattr("evalclaw.execution.runner._run_item", execute)
    if state in {"disabled", "complete"}:
        monkeypatch.setattr(
            "evalclaw.pipeline.run_eval",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("completed runner was rerun")),
        )
    monkeypatch.setattr(
        "evalclaw.pipeline.build_report",
        lambda run, research_brief=None, analysis=None, laaj=None: EvalReport(
            title="Report", markdown="", summaries=[]
        ),
    )
    monkeypatch.setattr("evalclaw.pipeline._persist_package", lambda *args, **kwargs: None)

    package = run_pipeline(
        None,
        BenchmarkConfig(
            output_dir=str(tmp_path), run_targets=state != "disabled", targets=[target],
            allow_incomplete_benchmark=True, analysis_iterations=0,
        ),
        resume_run=run_dir,
    )
    assert [item.id for item in package.suite.tasks] == ["first", "second", "excluded"]
    assert calls == ([] if state in {"disabled", "complete"} else [(target.id, "second")])
    saved_run = json.loads((run_dir / "run.json").read_text())
    results = saved_run["results"]
    assert not any(result["error"] for result in results)
    if state != "disabled":
        assert {result["item_id"] for result in results} == {"first", "second"}
        retained = next(result for result in results if result["item_id"] == "first")
        assert retained["raw_response"] == "incorrect answer"
        assert retained["score"] == 0
