from __future__ import annotations

import json

import pytest

from evalclaw.construction.suite import build_task_suite
from evalclaw.planning.task_planner import plan_benchmark
from evalclaw.quality.improver import _replace_or_expand_items
from evalclaw.types import (
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    ImprovementAction,
    TaskSuite,
    TaskType,
    TaskTypeAllocation,
)
from tests.blueprint_factory import make_blueprint, make_task_design
from tests.config_helpers import dummy_config_kwargs


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


def test_planner_derives_one_builder_job_per_requested_task_design(monkeypatch) -> None:
    spec = _mixed_spec().model_copy(
        update={
            "scale": 15,
            "dimensions": [
                _mixed_spec().dimensions[0].model_copy(
                    update={
                        "target_item_count": 15,
                        "measurement_target": "Complementary factual and explanatory analysis.",
                        "boundary": "Exclude stateful tool use and unrelated recall.",
                        "task_types": [
                            TaskType.choice,
                            TaskType.generation,
                        ],
                        "task_type_allocation": [
                            TaskTypeAllocation(
                                task_type=TaskType.choice,
                                count=5,
                            ),
                            TaskTypeAllocation(
                                task_type=TaskType.generation,
                                count=10,
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
                    "constraints": [],
                    "planner_notes": "",
                    "dimensions": [
                        {
                            "id": "mixed",
                            "name": "Mixed capability",
                            "measurement_target": (
                                "Complementary factual and explanatory analysis over one shared case; "
                                "cover both supported facts and evidence-grounded explanations."
                            ),
                            "boundary": (
                                "Exclude stateful tool use, unrelated recall, and claims unsupported "
                                "by the shared case."
                            ),
                            "approach": "Use one shared case.",
                            "task_designs": [
                                {
                                    "id": "shared_case_mcq",
                                    "task_type": "choice",
                                    "task_count": 5,
                                    "challenge_effort": "E3",
                                    "content_design": {
                                        "purpose": "Test supported facts.",
                                        "description": "Five distinct factual questions over one case.",
                                    },
                                },
                                {
                                    "id": "shared_case_explanation",
                                    "task_type": "generation",
                                    "task_count": 10,
                                    "challenge_effort": "E3",
                                    "content_design": {
                                        "purpose": "Test explanation.",
                                        "description": "Ten distinct explanations over the same case.",
                                    },
                                },
                            ],
                        }
                    ],
                }
            }
        )

    monkeypatch.setattr("evalclaw.planning.task_planner.call_llm", fake_call_llm)

    plan = plan_benchmark(
        spec.objective,
        BenchmarkConfig(**dummy_config_kwargs()),
    )

    assert captured["calls"] == 1
    assert "# Design Benchmark Content and TaskDesigns" in str(captured["system"])
    assert 'path="reference/universal_format.json"' in str(captured["system"])
    assert 'path="resources/instruction.md"' in str(captured["payload"])
    assert spec.objective in str(captured["payload"])
    assert len(plan.builder_jobs) == 2
    assert [job.planned_task_count for job in plan.builder_jobs] == [5, 10]
    assert all(len(job.task_designs) == 1 for job in plan.builder_jobs)
    derived = plan.to_eval_spec()
    assert derived.task_types == [TaskType.choice, TaskType.generation]
    assert derived.scale == 15
    assert [item.count for item in derived.dimensions[0].task_type_allocation] == [5, 10]
    assert plan.audit.passed is True


def test_build_task_suite_rejects_multi_design_blueprint() -> None:
    dimension = EvalDimension(
        id="shared_case",
        name="Shared case",
        description="Evaluate factual and explanatory analysis over one case.",
        approach="Use one shared prompt context.",
        task_types=[TaskType.choice, TaskType.generation],
        target_item_count=15,
    )
    spec = EvalSpec(
        objective="Evaluate mixed responses.",
        task_types=[TaskType.choice, TaskType.generation],
        dimensions=[dimension],
        scale=15,
    )
    blueprint = make_blueprint(
        "mixed_blueprint",
        dimension.id,
        "Shared case questions",
        task_designs=[
            make_task_design(
                "shared_case_mcq",
                TaskType.choice,
                count=5,
                content="One factual question over the shared case.",
            ),
            make_task_design(
                "shared_case_explanation",
                TaskType.generation,
                count=10,
                content="One explanatory question over the shared case.",
            ),
        ],
    )

    with pytest.raises(ValueError, match="exactly one TaskDesign"):
        build_task_suite(
            spec,
            [blueprint],
            BenchmarkConfig(**dummy_config_kwargs(), task_builder_max_workers=1),
        )


def test_one_task_builder_constructs_static_and_interactive_tasks_together(monkeypatch) -> None:
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

    blueprint_by_id = {blueprint.id: blueprint for blueprint in blueprints}

    def fake_call_llm(messages, **kwargs):
        from evalclaw.construction.builders import _fallback_task_for_blueprint

        payload = json.loads(messages[0].content)
        blueprint_id = payload["task_plan"]["builder_job_id"]
        blueprint = blueprint_by_id[blueprint_id]
        task = _fallback_task_for_blueprint(
            spec,
            spec.dimensions[0],
            blueprint,
            index=1,
            task_type=blueprint.task_designs[0].task_type,
        )
        task.metadata.update(
            {
                "task_design_id": blueprint.task_designs[0].id,
                "challenge_effort_self_assessment": {
                    "requested_effort": blueprint.task_designs[0].challenge_effort.value,
                    "meets_requested_effort": True,
                    "rationale": "The task implements the complete planned contract.",
                },
            }
        )
        return json.dumps(
            {
                "construction_notes": "Model-built test fixture.",
                "resources": [],
                "tasks": [task.model_dump(mode="json")],
            }
        )

    monkeypatch.setattr("evalclaw.construction.suite.call_llm", fake_call_llm)

    suite = build_task_suite(
        spec,
        blueprints,
        BenchmarkConfig(**dummy_config_kwargs(), task_builder_max_workers=1),
    )

    assert [task.task_type for task in suite.tasks] == [
        TaskType.choice,
        TaskType.agent,
    ]
    assert "agent_env" not in suite.tasks[0].metadata
    assert suite.tasks[1].metadata["agent_env"]["type"] == "workspace"
    assert len(suite.tasks) == 2


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
    original = BenchmarkItem(
        id="analysis_original",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Analyze the original case and justify the conclusion.",
        rubric="Score correctness and justification.",
        metadata={
            "builder_job_id": blueprint.id,
            "task_design_id": blueprint.task_design_ids[0],
        },
    )
    suite = TaskSuite(
        spec=spec,
        objective=spec.objective,
        dimensions=[dimension],
        blueprints=[blueprint],
        tasks=[original],
    )
    calls = 0

    def fake_build(scoped_spec, blueprints, config, **kwargs):
        nonlocal calls
        calls += 1
        assert "Loop 3 guidance" in " ".join(blueprints[0].construction_requirements)
        task = BenchmarkItem(
            id="temporary",
            dimension_id=dimension.id,
            task_type=TaskType.generation,
            prompt="Analyze a distinct boundary case and justify the conclusion.",
            rubric="Score correctness and justification.",
            metadata={"builder_job_id": blueprints[0].id},
        )
        return TaskSuite(
            spec=scoped_spec,
            objective=scoped_spec.objective,
            dimensions=scoped_spec.dimensions,
            blueprints=blueprints,
            tasks=[task],
        )

    monkeypatch.setattr("evalclaw.quality.improver.build_task_suite", fake_build)
    monkeypatch.setattr(
        "evalclaw.quality.improver.plan_blueprints_for_spec",
        lambda spec, config, **kwargs: [blueprint],
    )

    improved = _replace_or_expand_items(
        suite,
        [
            ImprovementAction(
                action_type="expand_weak_dimension",
                dimension_id=dimension.id,
                reason="The target missed a boundary condition.",
                guidance="Add a distinct boundary case.",
            )
        ],
        BenchmarkConfig(),
    )

    assert calls == 1
    assert len(improved.tasks) == 2
    assert improved.tasks[-1].metadata["loop3_guidance"] == "Add a distinct boundary case."
