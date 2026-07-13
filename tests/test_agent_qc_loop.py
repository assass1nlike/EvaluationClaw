import pytest

from evalclaw.agent.qc_loop import build_agent_dataset_with_qc_loop
from evalclaw.quality.llm_checks import _stabilize_llm_issue
from evalclaw.types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    AgentScoringSpec,
    AgentTask,
    AgentTaskBlueprint,
    AgentTaskSuite,
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    QcCategory,
    QcIssue,
    QcReport,
    QcSeverity,
    TaskType,
)


def _workspace_task(task_id: str, dimension_id: str) -> AgentTask:
    return AgentTask(
        id=task_id,
        dimension_id=dimension_id,
        title=task_id,
        prompt="Inspect the workspace and place the requested item in the outgoing bin.",
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.workspace,
            workspace={
                "start_room": "office",
                "rooms": {"office": ["item"], "mailroom": []},
                "goal": {"outgoing_bin": ["item"]},
            },
        ),
        scoring=AgentScoringSpec(pass_criteria="The item is in the outgoing bin."),
    )


def test_agent_qc_loop_repairs_only_rejected_dimensions(monkeypatch) -> None:
    dimensions = [
        EvalDimension(
            id="first",
            name="First",
            description="First capability.",
            approach="Use an executable task.",
        ),
        EvalDimension(
            id="second",
            name="Second",
            description="Second capability.",
            approach="Use an executable task.",
        ),
    ]
    spec = EvalSpec(
        objective="Evaluate two agent capabilities.",
        dimensions=dimensions,
        task_types=[TaskType.agent_interaction],
    )
    blueprints = [
        AgentTaskBlueprint(id="first_blueprint", dimension_id="first", title="First"),
        AgentTaskBlueprint(id="second_blueprint", dimension_id="second", title="Second"),
    ]
    initial_suite = AgentTaskSuite(
        objective=spec.objective,
        dimensions=dimensions,
        blueprints=blueprints,
        tasks=[_workspace_task("first_old", "first"), _workspace_task("second_kept", "second")],
    )
    repaired_suite = AgentTaskSuite(
        objective=spec.objective,
        dimensions=dimensions,
        blueprints=[blueprints[0]],
        tasks=[_workspace_task("first_repaired", "first")],
    )
    builder_calls: list[dict] = []

    monkeypatch.setattr("evalclaw.agent.qc_loop.plan_agent_benchmark", lambda goal, config: (spec, blueprints))

    def fake_build(spec_arg, selected_blueprints, config, **kwargs):
        builder_calls.append(
            {
                "blueprints": [blueprint.id for blueprint in selected_blueprints],
                "revision": kwargs.get("revision_context_by_dimension"),
            }
        )
        return initial_suite if len(builder_calls) == 1 else repaired_suite

    monkeypatch.setattr("evalclaw.agent.qc_loop.build_agent_task_suite", fake_build)
    qc_calls = 0

    def fake_qc(dataset, config):
        nonlocal qc_calls
        qc_calls += 1
        if qc_calls == 1:
            return QcReport(
                issues=[
                    QcIssue(
                        item_id="first_old",
                        severity=QcSeverity.error,
                        category=QcCategory.scoring,
                        message="The evaluator does not check the requested final state.",
                        suggested_action="Repair the evaluator.",
                    )
                ],
                passed_item_ids=["second_kept"],
                rejected_item_ids=["first_old"],
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

    monkeypatch.setattr("evalclaw.agent.qc_loop.run_qc_gate", fake_qc)

    _, dataset, qc_report = build_agent_dataset_with_qc_loop(
        "Evaluate two agent capabilities.",
        BenchmarkConfig(max_qc_iterations=2),
        log=lambda message: None,
    )

    assert [item.id for item in dataset.items] == ["first_repaired", "second_kept"]
    assert qc_report.rejected_item_ids == []
    assert builder_calls[1]["blueprints"] == ["first_blueprint"]
    revision = builder_calls[1]["revision"]["first"]
    assert revision["previous_tasks"][0]["id"] == "first_old"
    assert revision["qc_issues"][0]["message"] == (
        "The evaluator does not check the requested final state."
    )


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


def test_agent_qc_loop_fails_closed_after_repair_exhaustion(monkeypatch) -> None:
    dimension = EvalDimension(
        id="core",
        name="Core",
        description="Core capability.",
        approach="Use an executable workspace task.",
    )
    spec = EvalSpec(
        objective="Evaluate core capability.",
        dimensions=[dimension],
        task_types=[TaskType.agent_interaction],
    )
    blueprint = AgentTaskBlueprint(id="core_blueprint", dimension_id="core", title="Core")
    suite = AgentTaskSuite(
        objective=spec.objective,
        dimensions=[dimension],
        blueprints=[blueprint],
        tasks=[_workspace_task("rejected_task", "core")],
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
    )

    monkeypatch.setattr("evalclaw.agent.qc_loop.plan_agent_benchmark", lambda goal, config: (spec, [blueprint]))
    monkeypatch.setattr("evalclaw.agent.qc_loop.build_agent_task_suite", lambda *args, **kwargs: suite)
    monkeypatch.setattr("evalclaw.agent.qc_loop.run_qc_gate", lambda dataset, config: rejected)

    with pytest.raises(RuntimeError, match="runner-ready dataset"):
        build_agent_dataset_with_qc_loop(
            "Evaluate core capability.",
            BenchmarkConfig(max_qc_iterations=0),
            log=lambda message: None,
        )


def test_agent_qc_loop_allows_explicit_incomplete_draft(monkeypatch) -> None:
    dimension = EvalDimension(
        id="core",
        name="Core",
        description="Core capability.",
        approach="Use an executable workspace task.",
    )
    spec = EvalSpec(
        objective="Evaluate core capability.",
        dimensions=[dimension],
        task_types=[TaskType.agent_interaction],
    )
    blueprint = AgentTaskBlueprint(id="core_blueprint", dimension_id="core", title="Core")
    suite = AgentTaskSuite(
        objective=spec.objective,
        dimensions=[dimension],
        blueprints=[blueprint],
        tasks=[_workspace_task("rejected_task", "core")],
    )
    rejected = QcReport(
        passed_item_ids=[],
        rejected_item_ids=["rejected_task"],
        quality_score=0.0,
    )

    monkeypatch.setattr("evalclaw.agent.qc_loop.plan_agent_benchmark", lambda goal, config: (spec, [blueprint]))
    monkeypatch.setattr("evalclaw.agent.qc_loop.build_agent_task_suite", lambda *args, **kwargs: suite)
    monkeypatch.setattr("evalclaw.agent.qc_loop.run_qc_gate", lambda dataset, config: rejected)

    _, dataset, qc_report = build_agent_dataset_with_qc_loop(
        "Evaluate core capability.",
        BenchmarkConfig(max_qc_iterations=0, allow_incomplete_benchmark=True),
        log=lambda message: None,
    )

    assert [item.id for item in dataset.items] == ["rejected_task"]
    assert qc_report.rejected_item_ids == ["rejected_task"]
