import pytest

from evalclaw.benchmark import _merge_repaired_suite, build_benchmark_dataset_with_qc_loop
from evalclaw.quality.llm_checks import _stabilize_llm_issue
from evalclaw.types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    QcCategory,
    QcIssue,
    QcReport,
    QcSeverity,
    TaskDefinition,
    TaskResource,
    TaskScoringSpec,
    TaskSuite,
    TaskType,
)
from tests.blueprint_factory import make_blueprint, make_plan


def _task(
    task_id: str,
    dimension_id: str,
    blueprint_id: str,
    *,
    interactive: bool = False,
) -> TaskDefinition:
    return TaskDefinition(
        id=task_id,
        dimension_id=dimension_id,
        task_type=TaskType.agent_interaction if interactive else TaskType.short_answer,
        title=task_id,
        prompt=(
            "Inspect the workspace and place the requested item in the outgoing bin."
            if interactive
            else "State the requested result from the supplied evidence."
        ),
        answer=None if interactive else "result",
        environment=(
            AgentEnvironmentSpec(
                type=AgentEnvironmentType.workspace,
                workspace={
                    "start_room": "office",
                    "rooms": {"office": ["item"], "mailroom": []},
                    "goal": {"outgoing_bin": ["item"]},
                },
            )
            if interactive
            else None
        ),
        scoring=TaskScoringSpec(pass_criteria="The requested result is correct."),
        metadata={
            "builder_blueprint_id": blueprint_id,
            "task_design_id": f"{blueprint_id}_design",
        },
    )


def test_unified_qc_loop_repairs_only_rejected_blueprint(monkeypatch) -> None:
    dimensions = [
        EvalDimension(
            id="knowledge",
            name="Knowledge",
            description="Evaluate grounded knowledge.",
            approach="Use a short-answer task.",
            task_types=[TaskType.short_answer],
        ),
        EvalDimension(
            id="tool_use",
            name="Tool use",
            description="Evaluate stateful tool use.",
            approach="Use an executable task.",
            task_types=[TaskType.agent_interaction],
        ),
    ]
    spec = EvalSpec(
        objective="Evaluate knowledge and tool use.",
        dimensions=dimensions,
        task_types=[TaskType.short_answer, TaskType.agent_interaction],
    )
    blueprints = [
        make_blueprint(
            "knowledge_blueprint",
            "knowledge",
            "Knowledge",
            task_type=TaskType.short_answer,
            content="Grounded knowledge.",
        ),
        make_blueprint(
            "tool_blueprint",
            "tool_use",
            "Tool use",
            task_type=TaskType.agent_interaction,
            content="Stateful tool use.",
            environment_type=AgentEnvironmentType.workspace,
        ),
    ]
    initial_suite = TaskSuite(
        objective=spec.objective,
        dimensions=dimensions,
        blueprints=blueprints,
        tasks=[
            _task("knowledge_old", "knowledge", "knowledge_blueprint"),
            _task("tool_kept", "tool_use", "tool_blueprint", interactive=True),
        ],
    )
    repaired_suite = TaskSuite(
        objective=spec.objective,
        dimensions=dimensions,
        blueprints=[blueprints[0]],
        tasks=[_task("knowledge_old", "knowledge", "knowledge_blueprint")],
    )
    builder_calls: list[dict] = []

    monkeypatch.setattr(
        "evalclaw.benchmark.plan_benchmark",
        lambda goal, config, **kwargs: make_plan(spec, blueprints),
    )

    def fake_build(spec_arg, selected_blueprints, config, **kwargs):
        builder_calls.append(
            {
                "blueprints": [blueprint.id for blueprint in selected_blueprints],
                "revision": kwargs.get("revision_context_by_dimension"),
            }
        )
        return initial_suite if len(builder_calls) == 1 else repaired_suite

    monkeypatch.setattr("evalclaw.benchmark.build_task_suite", fake_build)
    qc_calls = 0

    def fake_qc(dataset, config):
        nonlocal qc_calls
        qc_calls += 1
        if qc_calls == 1:
            return QcReport(
                issues=[
                    QcIssue(
                        item_id="knowledge_old",
                        severity=QcSeverity.error,
                        category=QcCategory.scoring,
                        message="The reference answer is not supported by the evidence.",
                        suggested_action="Repair the answer and oracle.",
                    )
                ],
                passed_item_ids=["tool_kept"],
                rejected_item_ids=["knowledge_old"],
                quality_score=0.8,
                summary="One rejected item.",
            )
        return QcReport(
            issues=[],
            passed_item_ids=[item.id for item in dataset.items],
            rejected_item_ids=[],
            quality_score=1.0,
            summary="All items passed.",
        )

    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", fake_qc)

    _, dataset, qc_report = build_benchmark_dataset_with_qc_loop(
        spec.objective,
        BenchmarkConfig(max_qc_iterations=2),
        log=lambda message: None,
    )

    assert [item.id for item in dataset.items] == ["knowledge_old", "tool_kept"]
    assert qc_report.rejected_item_ids == []
    assert builder_calls[1]["blueprints"] == ["knowledge_blueprint"]
    revision = builder_calls[1]["revision"]["knowledge"]
    assert revision["previous_tasks"][0]["id"] == "knowledge_old"
    assert revision["qc_issues"][0]["message"] == (
        "The reference answer is not supported by the evidence."
    )
    assert "Do not return or modify any QC-passed task" in revision["instruction"]


def test_real_partial_credit_evaluator_error_is_not_demoted() -> None:
    item = BenchmarkItem(
        id="partial_task",
        dimension_id="first",
        task_type=TaskType.agent_interaction,
        prompt="Complete the task.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "hidden_files": {"evaluate.py": "raise SystemExit(0)"},
                "test_command": "python3 evaluate.py",
            }
        },
    )
    issue = QcIssue(
        item_id=item.id,
        severity=QcSeverity.error,
        category=QcCategory.scoring,
        message=(
            "The deterministic evaluator returns exit code 0 for partial credit 0.5, "
            "so partial and pass are indistinguishable."
        ),
        suggested_action="Use distinct evaluator results.",
    )

    stabilized = _stabilize_llm_issue(issue, {item.id: item})

    assert stabilized.severity == QcSeverity.error


def test_qc_repair_replaces_only_failed_task_inside_multi_task_blueprint(monkeypatch) -> None:
    dimension = EvalDimension(
        id="knowledge",
        name="Knowledge",
        description="Evaluate grounded knowledge.",
        approach="Use two short-answer tasks.",
        task_types=[TaskType.short_answer],
        target_item_count=2,
    )
    spec = EvalSpec(
        objective="Evaluate grounded knowledge.",
        dimensions=[dimension],
        task_types=[TaskType.short_answer],
        scale=2,
    )
    blueprint = make_blueprint(
        "knowledge_family",
        dimension.id,
        "Two knowledge tasks",
        task_type=TaskType.short_answer,
        count=2,
        content="Two distinct evidence questions.",
    )
    failed = _task("failed_task", dimension.id, blueprint.id)
    passed = _task("passed_task", dimension.id, blueprint.id)
    repaired = _task("failed_task", dimension.id, blueprint.id).model_copy(
        update={"answer": "supported result"}
    )
    initial_suite = TaskSuite(
        objective=spec.objective,
        dimensions=[dimension],
        blueprints=[blueprint],
        tasks=[failed, passed],
    )
    repaired_suite = TaskSuite(
        objective=spec.objective,
        dimensions=[dimension],
        blueprints=[blueprint],
        tasks=[repaired],
    )
    build_calls = 0

    monkeypatch.setattr(
        "evalclaw.benchmark.plan_benchmark",
        lambda *args, **kwargs: make_plan(spec, [blueprint]),
    )

    def fake_build(*args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        return initial_suite if build_calls == 1 else repaired_suite

    monkeypatch.setattr("evalclaw.benchmark.build_task_suite", fake_build)
    qc_calls = 0

    def fake_qc(dataset, config):
        nonlocal qc_calls
        qc_calls += 1
        if qc_calls == 1:
            return QcReport(
                issues=[
                    QcIssue(
                        item_id="failed_task",
                        severity=QcSeverity.error,
                        category=QcCategory.scoring,
                        message="The answer is unsupported.",
                    )
                ],
                passed_item_ids=["passed_task"],
                rejected_item_ids=["failed_task"],
                quality_score=0.8,
                summary="One failed task.",
            )
        return QcReport(
            passed_item_ids=[item.id for item in dataset.items],
            quality_score=1.0,
            summary="All tasks passed.",
        )

    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", fake_qc)
    _, dataset, _ = build_benchmark_dataset_with_qc_loop(
        spec.objective,
        BenchmarkConfig(max_qc_iterations=1),
        log=lambda _message: None,
    )

    assert [item.id for item in dataset.items] == ["failed_task", "passed_task"]
    assert dataset.items[0].answer == "supported result"
    assert dataset.items[1].prompt == passed.prompt


def test_qc_repair_preserves_task_order_and_replaces_resource_by_id() -> None:
    kept = _task("z_kept", "knowledge", "knowledge_family")
    failed = _task("a_failed", "knowledge", "knowledge_family").model_copy(
        update={"resource_ids": ["failed_evidence"]}
    )
    repaired = failed.model_copy(update={"answer": "supported result"})
    previous = TaskSuite(
        objective="Evaluate grounded knowledge.",
        tasks=[kept, failed],
        resources=[
            TaskResource(
                id="failed_evidence",
                kind="document",
                title="Evidence",
                content_summary="Unsupported evidence.",
            )
        ],
    )
    repair = TaskSuite(
        objective=previous.objective,
        tasks=[repaired],
        resources=[
            TaskResource(
                id="failed_evidence",
                kind="document",
                title="Evidence",
                content_summary="Corrected supporting evidence.",
            )
        ],
    )

    merged = _merge_repaired_suite(previous, repair)

    assert [task.id for task in merged.tasks] == ["z_kept", "a_failed"]
    assert merged.tasks[1].answer == "supported result"
    assert merged.resources[0].content_summary == "Corrected supporting evidence."


def _rejected_fixture():
    dimension = EvalDimension(
        id="core",
        name="Core",
        description="Core capability.",
        approach="Use a short-answer task.",
        task_types=[TaskType.short_answer],
    )
    spec = EvalSpec(
        objective="Evaluate core capability.",
        dimensions=[dimension],
        task_types=[TaskType.short_answer],
    )
    blueprint = make_blueprint(
        "core_blueprint",
        "core",
        "Core",
        task_type=TaskType.short_answer,
        content="Core capability.",
    )
    suite = TaskSuite(
        objective=spec.objective,
        dimensions=[dimension],
        blueprints=[blueprint],
        tasks=[_task("rejected_task", "core", "core_blueprint")],
    )
    rejected = QcReport(
        issues=[
            QcIssue(
                item_id="rejected_task",
                severity=QcSeverity.error,
                category=QcCategory.scoring,
                message="Evaluator is incomplete.",
            )
        ],
        passed_item_ids=[],
        rejected_item_ids=["rejected_task"],
        quality_score=0.0,
        summary="One item rejected.",
    )
    return spec, blueprint, suite, rejected


def test_unified_qc_loop_fails_closed_after_repair_exhaustion(monkeypatch) -> None:
    spec, blueprint, suite, rejected = _rejected_fixture()
    monkeypatch.setattr(
        "evalclaw.benchmark.plan_benchmark",
        lambda goal, config, **kwargs: make_plan(spec, [blueprint]),
    )
    monkeypatch.setattr("evalclaw.benchmark.build_task_suite", lambda *args, **kwargs: suite)
    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", lambda dataset, config: rejected)

    progress: list[str] = []
    with pytest.raises(RuntimeError, match="runner-ready dataset"):
        build_benchmark_dataset_with_qc_loop(
            spec.objective,
            BenchmarkConfig(max_qc_iterations=0),
            log=progress.append,
        )

    assert any("reviewing 1 constructed task" in message for message in progress)
    assert any(
        "rejected_task" in message and "Evaluator is incomplete" in message
        for message in progress
    )


def test_unified_qc_loop_allows_explicit_incomplete_draft(monkeypatch) -> None:
    spec, blueprint, suite, rejected = _rejected_fixture()
    monkeypatch.setattr(
        "evalclaw.benchmark.plan_benchmark",
        lambda goal, config, **kwargs: make_plan(spec, [blueprint]),
    )
    monkeypatch.setattr("evalclaw.benchmark.build_task_suite", lambda *args, **kwargs: suite)
    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", lambda dataset, config: rejected)

    _, dataset, qc_report = build_benchmark_dataset_with_qc_loop(
        spec.objective,
        BenchmarkConfig(max_qc_iterations=0, allow_incomplete_benchmark=True),
        log=lambda message: None,
    )

    assert [item.id for item in dataset.items] == ["rejected_task"]
    assert qc_report.rejected_item_ids == ["rejected_task"]
