from __future__ import annotations

import json

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
    TaskDefinition,
    TaskScoringSpec,
    TaskSuite,
    TaskType,
    TaskTypeAllocation,
)
from tests.blueprint_factory import make_blueprint, make_task_design


def _mixed_spec() -> EvalSpec:
    dimension = EvalDimension(
        id="mixed",
        name="Mixed capability",
        description="Evaluate factual analysis and stateful tool use.",
        approach="Use both direct questions and executable tasks.",
        task_types=[TaskType.choice, TaskType.agent],
        target_item_count=2,
    )
    return EvalSpec(
        objective="Evaluate factual analysis and tool use.",
        task_types=[TaskType.choice, TaskType.agent],
        dimensions=[dimension],
        scale=2,
    )


def test_planner_creates_adaptive_blueprint_work_packages(monkeypatch) -> None:
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

    monkeypatch.setattr("evalclaw.planning.task_planner._fallback_outline", fake_plan)

    planned = plan_benchmark(spec.objective, BenchmarkConfig(task_builder="local"))

    assert calls == 1
    derived = planned.to_eval_spec()
    assert derived.objective == spec.objective
    assert derived.scale == 5
    assert derived.task_types == spec.task_types
    assert len(planned.blueprints) == 2
    assert [blueprint.planned_task_count for blueprint in planned.blueprints] == [3, 2]
    assert [
        blueprint.task_type_allocation[0].task_type
        for blueprint in planned.blueprints
    ] == [TaskType.choice, TaskType.agent]
    assert planned.blueprints[0].environment_type is None
    assert planned.blueprints[0].tool_requirements == []
    assert planned.blueprints[1].environment_type == AgentEnvironmentType.workspace
    assert all(blueprint.metadata for blueprint in planned.blueprints)
    assert planned.audit.passed is True


def test_planner_skill_drives_one_mixed_type_family_blueprint(monkeypatch) -> None:
    spec = _mixed_spec().model_copy(
        update={
            "scale": 5,
            "dimensions": [
                _mixed_spec().dimensions[0].model_copy(
                    update={
                        "target_item_count": 5,
                        "measurement_target": "Complementary factual and explanatory analysis.",
                        "boundary": "Exclude stateful tool use and unrelated recall.",
                        "task_types": [
                            TaskType.choice,
                            TaskType.generation,
                        ],
                        "task_type_allocation": [
                            TaskTypeAllocation(
                                task_type=TaskType.choice,
                                count=3,
                            ),
                            TaskTypeAllocation(
                                task_type=TaskType.generation,
                                count=2,
                            ),
                        ],
                        "item_requirements": [
                            "Use one shared case to test factual and explanatory analysis."
                        ],
                    }
                )
            ],
            "task_types": [TaskType.choice, TaskType.generation],
        }
    )
    captured: dict[str, object] = {"calls": 0}

    def fake_call_llm(messages, *, system, **kwargs):
        captured["calls"] = int(captured["calls"]) + 1
        captured["system"] = system
        captured["payload"] = messages[0].content
        return json.dumps(
            {
                "plan": {
                    "id": "shared_case_plan",
                    "objective": spec.objective,
                    "metrics": ["judge_score"],
                    "constraints": [],
                    "planner_notes": "",
                    "dimensions": [
                        {
                            "id": "mixed",
                            "name": "Mixed capability",
                            "measurement_target": "Complementary factual and explanatory analysis.",
                            "boundary": "Exclude stateful tool use and unrelated recall.",
                            "approach": "Use one shared case.",
                            "content_requirements": [
                                "Use one shared case to test factual and explanatory analysis."
                            ],
                            "exclusions": ["Stateful tool use"],
                            "task_designs": [
                                {
                                    "id": "shared_case_mcq",
                                    "task_type": "choice",
                                    "task_count": 3,
                                    "challenge_effort": "E3",
                                    "content_design": {
                                        "purpose": "Test supported facts.",
                                        "description": "Three distinct factual questions over one case.",
                                    },
                                },
                                {
                                    "id": "shared_case_explanation",
                                    "task_type": "generation",
                                    "task_count": 2,
                                    "challenge_effort": "E3",
                                    "content_design": {
                                        "purpose": "Test explanation.",
                                        "description": "Two distinct explanations over the same case.",
                                    },
                                },
                            ],
                            "blueprints": [
                                {
                                    "id": "shared_case_blueprint",
                                    "title": "Questions over one shared case",
                                    "task_design_ids": [
                                        "shared_case_mcq",
                                        "shared_case_explanation",
                                    ],
                                    "grouping_rationale": "All tasks share one compact case.",
                                    "workload_reason": "Five short tasks fit in one Builder call.",
                                    "metadata": {"content_focus": "shared case"},
                                }
                            ],
                        }
                    ],
                }
            }
        )

    monkeypatch.setattr("evalclaw.planning.task_planner.call_llm", fake_call_llm)

    plan = plan_benchmark(
        spec.objective,
        BenchmarkConfig(orchestrator_api_key="dummy"),
    )

    assert captured["calls"] == 1
    assert "# Design Benchmark Content and Blueprints" in str(captured["system"])
    assert 'path="reference/universal_format.json"' in str(captured["system"])
    assert 'path="resources/instruction.md"' in str(captured["payload"])
    assert spec.objective in str(captured["payload"])
    assert len(plan.blueprints) == 1
    assert plan.blueprints[0].planned_task_count == 5
    assert len(plan.blueprints[0].task_type_allocation) == 2
    derived = plan.to_eval_spec()
    assert derived.task_types == [TaskType.choice, TaskType.generation]
    assert derived.scale == 5
    assert [item.count for item in derived.dimensions[0].task_type_allocation] == [3, 2]
    assert plan.audit.passed is True


def test_one_builder_call_materializes_a_mixed_type_blueprint(monkeypatch) -> None:
    dimension = EvalDimension(
        id="shared_case",
        name="Shared case",
        description="Evaluate factual and explanatory analysis over one case.",
        approach="Use one shared prompt context.",
        task_types=[TaskType.choice, TaskType.generation],
        target_item_count=2,
    )
    spec = EvalSpec(
        objective="Evaluate mixed responses.",
        task_types=[TaskType.choice, TaskType.generation],
        dimensions=[dimension],
        scale=2,
    )
    blueprint = make_blueprint(
        "mixed_blueprint",
        dimension.id,
        "Shared case questions",
        task_designs=[
            make_task_design(
                "shared_case_mcq",
                TaskType.choice,
                content="One factual question over the shared case.",
            ),
            make_task_design(
                "shared_case_explanation",
                TaskType.generation,
                content="One explanatory question over the shared case.",
            ),
        ],
    )
    calls = 0

    def fake_call_llm(*args, **kwargs):
        nonlocal calls
        calls += 1
        common_metadata = {
            "challenge_effort_self_assessment": {
                "requested_effort": "E3",
                "meets_requested_effort": True,
                "rationale": "Both tasks are complete and distinct.",
            }
        }
        return json.dumps(
            {
                "tasks": [
                    {
                        "id": "case_mcq",
                        "dimension_id": dimension.id,
                        "task_type": "choice",
                        "title": "Identify the supported fact",
                        "prompt": "Which statement is supported by the shared case?",
                        "choices": [{"id": "A", "text": "Supported"}, {"id": "B", "text": "Unsupported"}],
                        "correct_choice_ids": ["A"],
                        "scoring": {"pass_criteria": "Answer A."},
                        "metadata": common_metadata,
                    },
                    {
                        "id": "case_explanation",
                        "dimension_id": dimension.id,
                        "task_type": "generation",
                        "title": "Explain the implication",
                        "prompt": "Explain the main implication of the shared case.",
                        "rubric": "Reward a correct, evidence-grounded explanation.",
                        "scoring": {"pass_criteria": "The explanation uses the case evidence."},
                        "metadata": common_metadata,
                    },
                ]
            }
        )

    monkeypatch.setattr("evalclaw.construction.suite.call_llm", fake_call_llm)
    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(orchestrator_api_key="dummy", task_builder_max_workers=1),
    )

    assert calls == 1
    assert [task.task_type for task in suite.tasks] == [
        TaskType.choice,
        TaskType.generation,
    ]


def test_one_task_builder_constructs_static_and_interactive_tasks_together() -> None:
    spec = _mixed_spec()
    blueprints = [
        make_blueprint(
            "mixed_mcq",
            "mixed",
            "Mixed MCQ",
            task_type=TaskType.choice,
            content="One factual question.",
        ),
        make_blueprint(
            "mixed_interaction",
            "mixed",
            "Mixed interaction",
            task_type=TaskType.agent,
            content="One workspace interaction.",
            environment_type=AgentEnvironmentType.workspace,
            allowed_tools=["look", "read_file", "write_file"],
        ),
    ]

    suite = build_task_suite(
        spec,
        blueprints,
        BenchmarkConfig(task_builder="local", task_builder_max_workers=1),
    )
    dataset = task_suite_to_dataset(suite, spec, BenchmarkConfig())

    assert [task.task_type for task in suite.tasks] == [
        TaskType.choice,
        TaskType.agent,
    ]
    assert suite.tasks[0].environment is None
    assert suite.tasks[1].environment is not None
    assert [item.task_type for item in dataset.items] == [
        TaskType.choice,
        TaskType.agent,
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
        task_types=[TaskType.generation],
        target_item_count=1,
    )
    spec = EvalSpec(
        objective="Evaluate analysis.",
        task_types=[TaskType.generation],
        dimensions=[dimension],
        scale=1,
    )
    blueprint = make_blueprint(
        "analysis_blueprint",
        dimension.id,
        "Analysis",
        task_type=TaskType.generation,
        content="One analysis task.",
    )
    original = TaskDefinition(
        id="analysis_original",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        title="Original",
        prompt="Analyze the original case and justify the conclusion.",
        rubric="Score correctness and justification.",
        scoring=TaskScoringSpec(instructions="Score correctness and justification."),
        metadata={
            "builder_blueprint_id": blueprint.id,
            "task_design_id": blueprint.task_design_ids[0],
        },
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
            task_type=TaskType.generation,
            title="Boundary case",
            prompt="Analyze a distinct boundary case and justify the conclusion.",
            rubric="Score correctness and justification.",
            scoring=TaskScoringSpec(instructions="Score correctness and justification."),
            metadata={"builder_blueprint_id": blueprints[0].id},
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
