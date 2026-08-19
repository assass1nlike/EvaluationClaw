import pytest

from evalclaw.benchmark import (
    _affected_builder_job_ids,
    _merge_repaired_suite,
    build_benchmark_suite_with_qc_loop,
    build_suite_from_spec_with_qc_loop,
)
from evalclaw.quality.llm_checks import _stabilize_llm_issue
from evalclaw.types import (
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
) -> BenchmarkItem:
    metadata: dict[str, object] = {
        "builder_job_id": blueprint_id,
        "task_design_id": f"{blueprint_id}_design",
    }
    if interactive:
        metadata["agent_env"] = {
            "type": "workspace",
            "workspace": {
                "start_room": "office",
                "rooms": {"office": ["item"], "mailroom": []},
                "goal": {"outgoing_bin": ["item"]},
            },
        }
    return BenchmarkItem(
        id=task_id,
        dimension_id=dimension_id,
        task_type=TaskType.agent if interactive else TaskType.fill_blank,
        prompt=(
            "Inspect the workspace and place the requested item in the outgoing bin."
            if interactive
            else "State the requested result from the supplied evidence."
        ),
        expected_text=None if interactive else "result",
        rubric="The requested result is correct.",
        metadata=metadata,
    )


def test_full_suite_rejects_dimension_without_builder_job() -> None:
    dimensions = [
        EvalDimension(id="covered", name="Covered", description="Covered", approach="Build it."),
        EvalDimension(id="missing", name="Missing", description="Missing", approach="Build it."),
    ]
    spec = EvalSpec(objective="Evaluate coverage.", dimensions=dimensions)
    blueprint = make_blueprint(
        "covered_blueprint",
        "covered",
        "Covered",
        task_type=TaskType.fill_blank,
        content="Build one covered task.",
    )

    with pytest.raises(ValueError, match=r"Missing TaskDesign Builder jobs.*missing"):
        build_suite_from_spec_with_qc_loop(
            spec,
            [blueprint],
            BenchmarkConfig(),
            log=lambda _: None,
        )


def test_dataset_level_qc_issue_is_warning_and_does_not_trigger_repair() -> None:
    dimension = EvalDimension(
        id="coverage",
        name="Coverage",
        description="Evaluate coverage.",
        approach="Use representative tasks.",
    )
    blueprint = make_blueprint(
        "coverage_blueprint",
        dimension.id,
        "Coverage",
        task_type=TaskType.fill_blank,
        content="Build one coverage task.",
    )
    suite = TaskSuite(
        spec=EvalSpec(objective="Evaluate coverage.", dimensions=[dimension]),
        objective="Evaluate coverage.",
        blueprints=[blueprint],
    )
    issue = QcIssue(
        severity=QcSeverity.error,
        category=QcCategory.coverage,
        message="The dimension design is too broad.",
    )

    assert issue.severity == QcSeverity.warning
    assert _affected_builder_job_ids(suite, QcReport(issues=[issue])) == set()


def test_unified_qc_loop_repairs_only_rejected_blueprint(monkeypatch) -> None:
    dimensions = [
        EvalDimension(
            id="knowledge",
            name="Knowledge",
            description="Evaluate grounded knowledge.",
            approach="Use a short-answer task.",
            task_types=[TaskType.fill_blank],
        ),
        EvalDimension(
            id="tool_use",
            name="Tool use",
            description="Evaluate stateful tool use.",
            approach="Use an executable task.",
            task_types=[TaskType.agent],
        ),
    ]
    spec = EvalSpec(
        objective="Evaluate knowledge and tool use.",
        dimensions=dimensions,
        task_types=[TaskType.fill_blank, TaskType.agent],
    )
    blueprints = [
        make_blueprint(
            "knowledge_blueprint",
            "knowledge",
            "Knowledge",
            task_type=TaskType.fill_blank,
            content="Grounded knowledge.",
        ),
        make_blueprint(
            "tool_blueprint",
            "tool_use",
            "Tool use",
            task_type=TaskType.agent,
            content="Stateful tool use.",
            environment_type=AgentEnvironmentType.workspace,
        ),
    ]
    plan = make_plan(spec, blueprints)
    builder_jobs = plan.builder_jobs
    knowledge_job_id = builder_jobs[0].id
    tool_job_id = builder_jobs[1].id
    initial_suite = TaskSuite(
        spec=spec,
        objective=spec.objective,
        dimensions=dimensions,
        blueprints=builder_jobs,
        tasks=[
            _task("knowledge_old", "knowledge", knowledge_job_id),
            _task("tool_kept", "tool_use", tool_job_id, interactive=True),
        ],
    )
    repaired_suite = TaskSuite(
        spec=spec,
        objective=spec.objective,
        dimensions=dimensions,
        blueprints=[builder_jobs[0]],
        tasks=[_task("knowledge_old", "knowledge", knowledge_job_id)],
    )
    builder_calls: list[dict] = []

    monkeypatch.setattr(
        "evalclaw.benchmark.plan_benchmark",
        lambda goal, config, **kwargs: plan,
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

    def fake_qc(suite, config):
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
            passed_item_ids=[item.id for item in suite.tasks],
            rejected_item_ids=[],
            quality_score=1.0,
            summary="All items passed.",
        )

    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", fake_qc)

    _, run_ready_suite, qc_report = build_benchmark_suite_with_qc_loop(
        spec.objective,
        BenchmarkConfig(max_qc_iterations=2),
        log=lambda message: None,
    )

    assert [item.id for item in run_ready_suite.tasks] == ["knowledge_old", "tool_kept"]
    assert qc_report.rejected_item_ids == []
    assert builder_calls[1]["blueprints"] == [knowledge_job_id]
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
        task_type=TaskType.agent,
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


def test_valid_vm_provider_request_false_positive_is_demoted() -> None:
    item = BenchmarkItem(
        id="vm_task",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Repair the prepared workstation.",
        metadata={
            "agent_env": {
                "type": "gui_desktop",
                "requires_vm": True,
                "vm": {
                    "guest_os": "windows",
                    "required_capabilities": ["desktop_bridge", "cloudbase_init_nocloud"],
                },
            }
        },
    )
    issue = QcIssue(
        item_id=item.id,
        severity=QcSeverity.error,
        category=QcCategory.schema,
        message=(
            "The task has no concrete boot source or externally managed desktop bridge "
            "endpoint, so there is no resolvable Windows desktop."
        ),
        suggested_action="Hard-code a template.",
    )

    stabilized = _stabilize_llm_issue(issue, {item.id: item})

    assert stabilized.severity == QcSeverity.warning
    assert "VM Provider resolution request" in stabilized.message


def test_qc_repair_replaces_only_failed_task_inside_multi_task_blueprint(monkeypatch) -> None:
    dimension = EvalDimension(
        id="knowledge",
        name="Knowledge",
        description="Evaluate grounded knowledge.",
        approach="Use two short-answer tasks.",
        task_types=[TaskType.fill_blank],
        target_item_count=2,
    )
    spec = EvalSpec(
        objective="Evaluate grounded knowledge.",
        dimensions=[dimension],
        task_types=[TaskType.fill_blank],
        scale=2,
    )
    blueprint = make_blueprint(
        "knowledge_family",
        dimension.id,
        "Two knowledge tasks",
        task_type=TaskType.fill_blank,
        count=2,
        content="Two distinct evidence questions.",
    )
    failed = _task("failed_task", dimension.id, blueprint.id)
    passed = _task("passed_task", dimension.id, blueprint.id)
    repaired = _task("failed_task", dimension.id, blueprint.id).model_copy(
        update={"expected_text": "supported result"}
    )
    initial_suite = TaskSuite(
        spec=spec,
        objective=spec.objective,
        dimensions=[dimension],
        blueprints=[blueprint],
        tasks=[failed, passed],
    )
    repaired_suite = TaskSuite(
        spec=spec,
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

    def fake_qc(suite, config):
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
            passed_item_ids=[item.id for item in suite.tasks],
            quality_score=1.0,
            summary="All tasks passed.",
        )

    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", fake_qc)
    _, run_ready_suite, _ = build_benchmark_suite_with_qc_loop(
        spec.objective,
        BenchmarkConfig(max_qc_iterations=1),
        log=lambda _message: None,
    )

    assert [item.id for item in run_ready_suite.tasks] == ["failed_task", "passed_task"]
    assert run_ready_suite.tasks[0].expected_text == "supported result"
    assert run_ready_suite.tasks[1].prompt == passed.prompt


def test_qc_loop_discards_regressive_repair_and_retries_from_best(monkeypatch) -> None:
    dimension = EvalDimension(
        id="knowledge",
        name="Knowledge",
        description="Evaluate grounded knowledge.",
        approach="Use one short-answer task.",
        task_types=[TaskType.fill_blank],
        target_item_count=1,
    )
    spec = EvalSpec(
        objective="Evaluate grounded knowledge.",
        dimensions=[dimension],
        task_types=[TaskType.fill_blank],
        scale=1,
    )
    blueprint = make_blueprint(
        "knowledge_family",
        dimension.id,
        "One knowledge task",
        task_type=TaskType.fill_blank,
        content="One evidence question.",
    )

    def suite(answer: str) -> TaskSuite:
        task = _task("knowledge_task", dimension.id, blueprint.id).model_copy(
            update={"expected_text": answer}
        )
        return TaskSuite(
            spec=spec,
            objective=spec.objective,
            dimensions=[dimension],
            blueprints=[blueprint],
            tasks=[task],
        )

    monkeypatch.setattr(
        "evalclaw.benchmark.plan_benchmark",
        lambda *args, **kwargs: make_plan(spec, [blueprint]),
    )
    answers = iter(("initial", "best", "worse", "fixed"))
    build_calls = 0

    def fake_build(*args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        revision = kwargs.get("revision_context_by_dimension")
        if build_calls in {3, 4}:
            assert revision[dimension.id]["previous_tasks"][0]["expected_text"] == "best"
        return suite(next(answers))

    def fake_qc(candidate_suite, config):
        answer = candidate_suite.tasks[0].expected_text
        issue_count = {"initial": 2, "best": 1, "worse": 2, "fixed": 0}[answer]
        issues = [
            QcIssue(
                item_id="knowledge_task",
                severity=QcSeverity.error,
                category=QcCategory.scoring,
                message=f"Blocking issue {index} for {answer}.",
            )
            for index in range(issue_count)
        ]
        return QcReport(
            issues=issues,
            passed_item_ids=[] if issues else ["knowledge_task"],
            rejected_item_ids=["knowledge_task"] if issues else [],
            quality_score=1.0 if not issues else 0.0,
            summary=f"{issue_count} blocking issue(s).",
        )

    monkeypatch.setattr("evalclaw.benchmark.build_task_suite", fake_build)
    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", fake_qc)
    logs: list[str] = []

    _, run_ready_suite, qc_report = build_benchmark_suite_with_qc_loop(
        spec.objective,
        BenchmarkConfig(max_qc_iterations=3),
        log=logs.append,
    )

    assert run_ready_suite.tasks[0].expected_text == "fixed"
    assert qc_report.rejected_item_ids == []
    assert any("discarded non-improving replacement" in message for message in logs)


def test_qc_loop_keeps_only_items_with_fewer_blocking_errors(monkeypatch) -> None:
    dimension = EvalDimension(
        id="knowledge",
        name="Knowledge",
        description="Evaluate grounded knowledge.",
        approach="Use short-answer tasks.",
        task_types=[TaskType.fill_blank],
        target_item_count=2,
    )
    spec = EvalSpec(
        objective="Evaluate grounded knowledge.",
        dimensions=[dimension],
        task_types=[TaskType.fill_blank],
        scale=2,
    )
    blueprints = [
        make_blueprint(
            "knowledge_a",
            dimension.id,
            "Knowledge A",
            task_type=TaskType.fill_blank,
            content="Evidence question A.",
        ),
        make_blueprint(
            "knowledge_b",
            dimension.id,
            "Knowledge B",
            task_type=TaskType.fill_blank,
            content="Evidence question B.",
        ),
    ]
    original_a = _task("task_a", dimension.id, blueprints[0].id).model_copy(
        update={"expected_text": "a-original"}
    )
    original_b = _task("task_b", dimension.id, blueprints[1].id).model_copy(
        update={"expected_text": "b-original"}
    )
    repaired_a = original_a.model_copy(update={"expected_text": "a-fixed"})
    repaired_b = original_b.model_copy(update={"expected_text": "b-regressed"})
    initial_suite = TaskSuite(
        spec=spec,
        objective=spec.objective,
        dimensions=[dimension],
        blueprints=blueprints,
        tasks=[original_a, original_b],
    )
    repaired_suite = initial_suite.model_copy(update={"tasks": [repaired_a, repaired_b]})

    monkeypatch.setattr(
        "evalclaw.benchmark.plan_benchmark",
        lambda *args, **kwargs: make_plan(spec, blueprints),
    )
    build_calls = 0

    def fake_build(*args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        return initial_suite if build_calls == 1 else repaired_suite

    def report(*counts: tuple[str, int]) -> QcReport:
        issues = [
            QcIssue(
                item_id=item_id,
                severity=QcSeverity.error,
                category=QcCategory.scoring,
                message=f"Blocking issue {index} for {item_id}.",
            )
            for item_id, count in counts
            for index in range(count)
        ]
        rejected = sorted({issue.item_id for issue in issues if issue.item_id})
        return QcReport(
            issues=issues,
            passed_item_ids=[item.id for item in initial_suite.tasks if item.id not in rejected],
            rejected_item_ids=rejected,
            summary=f"{len(issues)} blocking issue(s).",
        )

    def fake_qc(candidate, config):
        answers = [item.expected_text for item in candidate.tasks]
        if answers == ["a-original", "b-original"]:
            return report(("task_a", 1), ("task_b", 1))
        if answers == ["a-fixed", "b-regressed"]:
            return report(("task_b", 2))
        assert answers == ["a-fixed", "b-original"]
        return report(("task_b", 1))

    monkeypatch.setattr("evalclaw.benchmark.build_task_suite", fake_build)
    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", fake_qc)
    logs: list[str] = []

    _, result, qc_report = build_benchmark_suite_with_qc_loop(
        spec.objective,
        BenchmarkConfig(max_qc_iterations=1, allow_incomplete_benchmark=True),
        log=logs.append,
    )

    assert [item.expected_text for item in result.tasks] == ["a-fixed", "b-original"]
    assert [issue.item_id for issue in qc_report.issues] == ["task_b"]
    assert any("kept 1 improved item repair(s), rolled back 1" in message for message in logs)


def test_qc_repair_preserves_task_order_and_replaces_resource_by_id() -> None:
    spec = EvalSpec(objective="Evaluate grounded knowledge.")
    kept = _task("z_kept", "knowledge", "knowledge_family")
    failed = _task("a_failed", "knowledge", "knowledge_family").model_copy(
        update={"resource_ids": ["failed_evidence"]}
    )
    repaired = failed.model_copy(update={"expected_text": "supported result"})
    previous = TaskSuite(
        spec=spec,
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
        spec=spec,
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
    assert merged.tasks[1].expected_text == "supported result"
    assert merged.resources[0].content_summary == "Corrected supporting evidence."


def test_partial_qc_repair_merges_only_resources_used_by_kept_items() -> None:
    spec = EvalSpec(objective="Evaluate grounded knowledge.")

    def item_with_resource(item_id: str, resource_id: str, answer: str) -> BenchmarkItem:
        item = _task(item_id, "knowledge", "knowledge_family").model_copy(
            update={"expected_text": answer}
        )
        definition = TaskDefinition(
            id=item_id,
            dimension_id="knowledge",
            task_type=TaskType.fill_blank,
            title=item_id,
            prompt=item.prompt,
            expected_text=answer,
            resource_ids=[resource_id],
        )
        return item.model_copy(update={"source_definition": definition})

    previous = TaskSuite(
        spec=spec,
        objective=spec.objective,
        tasks=[
            item_with_resource("task_a", "resource_a", "a-original"),
            item_with_resource("task_b", "resource_b", "b-original"),
        ],
        resources=[
            TaskResource(id="resource_a", content_summary="A original"),
            TaskResource(id="resource_b", content_summary="B original"),
        ],
    )
    repaired = TaskSuite(
        spec=spec,
        objective=spec.objective,
        tasks=[
            item_with_resource("task_a", "resource_a", "a-fixed"),
            item_with_resource("task_b", "resource_b", "b-regressed"),
        ],
        resources=[
            TaskResource(id="resource_a", content_summary="A repaired"),
            TaskResource(id="resource_b", content_summary="B repaired"),
        ],
    )

    merged = _merge_repaired_suite(previous, repaired, item_ids={"task_a"})

    assert [item.expected_text for item in merged.tasks] == ["a-fixed", "b-original"]
    assert [resource.content_summary for resource in merged.resources] == [
        "A repaired",
        "B original",
    ]


def _rejected_fixture():
    dimension = EvalDimension(
        id="core",
        name="Core",
        description="Core capability.",
        approach="Use a short-answer task.",
        task_types=[TaskType.fill_blank],
    )
    spec = EvalSpec(
        objective="Evaluate core capability.",
        dimensions=[dimension],
        task_types=[TaskType.fill_blank],
    )
    blueprint = make_blueprint(
        "core_blueprint",
        "core",
        "Core",
        task_type=TaskType.fill_blank,
        content="Core capability.",
    )
    suite = TaskSuite(
        spec=spec,
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
    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", lambda candidate_suite, config: rejected)

    progress: list[str] = []
    with pytest.raises(RuntimeError, match="runner-ready suite"):
        build_benchmark_suite_with_qc_loop(
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
    monkeypatch.setattr("evalclaw.benchmark.run_qc_gate", lambda candidate_suite, config: rejected)

    _, run_ready_suite, qc_report = build_benchmark_suite_with_qc_loop(
        spec.objective,
        BenchmarkConfig(max_qc_iterations=0, allow_incomplete_benchmark=True),
        log=lambda message: None,
    )

    assert [item.id for item in run_ready_suite.tasks] == ["rejected_task"]
    assert qc_report.rejected_item_ids == ["rejected_task"]
