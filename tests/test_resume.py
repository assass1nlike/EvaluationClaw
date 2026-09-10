from __future__ import annotations

import json

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
    ScaleBudget,
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
    assert calls == ["first", "second"]
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
        scale_budget=ScaleBudget.high,
    )
    plan = BenchmarkPlan(
        objective=spec.objective,
        subjects=spec.subjects,
        scale_budget=spec.scale_budget,
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
    assert resumed_plan.scale_budget == ScaleBudget.high
    assert resumed_suite is not None
    assert resumed_suite.tasks[0].source_definition == source


def test_pipeline_reuses_completed_run_checkpoint(monkeypatch, tmp_path) -> None:
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
                id="item",
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt="Solve the task.",
                rubric="Score correctness.",
            )
        ],
    )
    qc_report = QcReport(passed_item_ids=["item"])
    run = EvalRun(suite=suite, qc_report=qc_report)
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
        {"run_targets": False, "suite": suite.model_dump(mode="json"), "report": {"enabled": False}},
    )
    write_json(run_dir / "run.json", run.model_dump(mode="json"))

    monkeypatch.setattr(
        "evalclaw.pipeline.build_benchmark_suite_with_qc_loop",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("construction was rerun")),
    )
    monkeypatch.setattr(
        "evalclaw.pipeline.run_environment_claw",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("environment was rerun")),
    )
    monkeypatch.setattr(
        "evalclaw.pipeline.run_eval",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runner was rerun")),
    )
    monkeypatch.setattr(
        "evalclaw.pipeline.build_report",
        lambda run, research_brief=None, analysis=None: EvalReport(
            title="Report", markdown="", summaries=[]
        ),
    )
    monkeypatch.setattr("evalclaw.pipeline._persist_package", lambda *args, **kwargs: None)

    package = run_pipeline(
        None,
        BenchmarkConfig(output_dir=str(tmp_path), run_targets=False, analysis_iterations=0),
        resume_run=run_dir,
    )
    assert [item.id for item in package.suite.tasks] == ["item"]
