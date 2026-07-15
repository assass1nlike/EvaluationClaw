from __future__ import annotations

from evalclaw.construction.packaging import task_suite_to_dataset
from evalclaw.construction.suite import build_task_suite
from evalclaw.planning.task_planner import plan_benchmark
from evalclaw.quality.improver import _replace_or_expand_items
from evalclaw.types import (
    AgentEnvironmentType,
    BenchmarkConfig,
    EvalDimension,
    EvalSpec,
    ImprovementAction,
    TaskBlueprint,
    TaskDefinition,
    TaskScoringSpec,
    TaskSuite,
    TaskType,
)


def _mixed_spec() -> EvalSpec:
    dimension = EvalDimension(
        id="mixed",
        name="Mixed capability",
        description="Evaluate factual analysis and stateful tool use.",
        approach="Use both direct questions and executable tasks.",
        task_types=[TaskType.multiple_choice, TaskType.agent_interaction],
        target_item_count=2,
    )
    return EvalSpec(
        objective="Evaluate factual analysis and tool use.",
        task_types=[TaskType.multiple_choice, TaskType.agent_interaction],
        dimensions=[dimension],
        scale=2,
    )


def test_one_planner_call_creates_generic_blueprints_with_optional_capabilities(monkeypatch) -> None:
    spec = _mixed_spec().model_copy(
        update={
            "dimensions": [
                _mixed_spec().dimensions[0].model_copy(update={"target_item_count": 5})
            ]
        }
    )
    calls = 0

    def fake_plan(*args, **kwargs):
        nonlocal calls
        calls += 1
        return spec

    monkeypatch.setattr("evalclaw.planning.task_planner.plan_eval_spec", fake_plan)

    planned, blueprints = plan_benchmark(spec.objective, BenchmarkConfig())

    assert calls == 1
    assert planned is spec
    assert [blueprint.expected_task_count for blueprint in blueprints] == [3, 2]
    assert [blueprint.task_types for blueprint in blueprints] == [
        [TaskType.multiple_choice],
        [TaskType.agent_interaction],
    ]
    assert blueprints[0].environment_type is None
    assert blueprints[0].tool_requirements == []
    assert blueprints[1].environment_type == AgentEnvironmentType.workspace


def test_one_task_builder_constructs_static_and_interactive_tasks_together() -> None:
    spec = _mixed_spec()
    blueprints = [
        TaskBlueprint(
            id="mixed_mcq",
            dimension_id="mixed",
            title="Mixed MCQ",
            task_types=[TaskType.multiple_choice],
            expected_task_count=1,
        ),
        TaskBlueprint(
            id="mixed_interaction",
            dimension_id="mixed",
            title="Mixed interaction",
            task_types=[TaskType.agent_interaction],
            expected_task_count=1,
            environment_type=AgentEnvironmentType.workspace,
            tool_requirements=["look", "read_file", "write_file"],
        ),
    ]

    suite = build_task_suite(
        spec,
        blueprints,
        BenchmarkConfig(task_builder="local", task_builder_max_workers=1),
    )
    dataset = task_suite_to_dataset(suite, spec, BenchmarkConfig())

    assert [task.task_type for task in suite.tasks] == [
        TaskType.multiple_choice,
        TaskType.agent_interaction,
    ]
    assert suite.tasks[0].environment is None
    assert suite.tasks[1].environment is not None
    assert [item.task_type for item in dataset.items] == [
        TaskType.multiple_choice,
        TaskType.agent_interaction,
    ]
    assert "agent_env" not in dataset.items[0].metadata
    assert dataset.items[1].metadata["agent_env"]["type"] == "workspace"
    assert dataset.task_suite is suite
    assert len(dataset.task_suite.tasks) == 2


def test_loop3_rebuilds_through_the_same_task_builder(monkeypatch) -> None:
    dimension = EvalDimension(
        id="analysis",
        name="Analysis",
        description="Evaluate analysis.",
        approach="Use open-generation tasks.",
        task_types=[TaskType.open_generation],
        target_item_count=1,
    )
    spec = EvalSpec(
        objective="Evaluate analysis.",
        task_types=[TaskType.open_generation],
        dimensions=[dimension],
        scale=1,
    )
    blueprint = TaskBlueprint(
        id="analysis_blueprint",
        dimension_id=dimension.id,
        title="Analysis",
        task_types=[TaskType.open_generation],
    )
    original = TaskDefinition(
        id="analysis_original",
        dimension_id=dimension.id,
        task_type=TaskType.open_generation,
        title="Original",
        prompt="Analyze the original case and justify the conclusion.",
        rubric="Score correctness and justification.",
        scoring=TaskScoringSpec(instructions="Score correctness and justification."),
        metadata={"builder_blueprint_id": blueprint.id, "builder_task_index": 1},
    )
    dataset = task_suite_to_dataset(
        TaskSuite(
            objective=spec.objective,
            dimensions=[dimension],
            blueprints=[blueprint],
            tasks=[original],
        ),
        spec,
        BenchmarkConfig(),
    )
    calls = 0

    def fake_build(scoped_spec, blueprints, config, **kwargs):
        nonlocal calls
        calls += 1
        assert "Loop 3 guidance" in " ".join(blueprints[0].construction_requirements)
        task = TaskDefinition(
            id="temporary",
            dimension_id=dimension.id,
            task_type=TaskType.open_generation,
            title="Boundary case",
            prompt="Analyze a distinct boundary case and justify the conclusion.",
            rubric="Score correctness and justification.",
            scoring=TaskScoringSpec(instructions="Score correctness and justification."),
            metadata={"builder_blueprint_id": blueprints[0].id, "builder_task_index": 1},
        )
        return TaskSuite(
            objective=scoped_spec.objective,
            dimensions=scoped_spec.dimensions,
            blueprints=blueprints,
            tasks=[task],
        )

    monkeypatch.setattr("evalclaw.quality.improver.build_task_suite", fake_build)

    improved = _replace_or_expand_items(
        dataset,
        [
            ImprovementAction(
                action_type="expand_weak_dimension",
                dimension_id=dimension.id,
                reason="The target missed a boundary condition.",
                guidance="Add a distinct boundary case.",
            )
        ],
        BenchmarkConfig(task_builder="local"),
    )

    assert calls == 1
    assert len(improved.items) == 2
    assert improved.task_suite is not None
    assert len(improved.task_suite.tasks) == 2
    assert improved.items[-1].metadata["loop3_guidance"] == "Add a distinct boundary case."
