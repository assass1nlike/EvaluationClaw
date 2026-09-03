from __future__ import annotations

import json

import pytest

from evalclaw.construction.suite import build_task_suite
from evalclaw.planning.task_planner import plan_benchmark
from evalclaw.types import (
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    TaskSuite,
    TaskType,
    TaskTypeAllocation,
)
from tests.blueprint_factory import make_blueprint, make_task_design
from tests.config_helpers import dummy_config_kwargs, patch_task_builder_model


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
                                        "source_plan": {"strategy": "generated"},
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
                                        "source_plan": {"strategy": "generated"},
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
            environment_type=AgentEnvironmentType.docker_workspace,
            allowed_tools=["look", "read_file", "write_file"],
        ),
    ]

    def fake_call_llm(messages, **kwargs):
        payload = json.loads(messages[0].content)
        blueprint_id = payload["task_plan"]["builder_job_id"]
        assessment = {
            "requested_effort": "E3",
            "meets_requested_effort": True,
            "rationale": "The task implements the complete planned contract.",
        }
        task = (
            {
                "task_type": "choice",
                "title": "Mixed MCQ",
                "prompt": "Which option is the correct factual answer?",
                "choices": [
                    {"id": "A", "text": "The correct answer."},
                    {"id": "B", "text": "An incorrect answer."},
                ],
                "correct_choice_ids": ["A"],
                "metadata": {"challenge_effort_self_assessment": assessment},
            }
            if blueprint_id == "mixed_mcq"
            else {
                "task_type": "agent",
                "title": "Mixed interaction",
                "prompt": "Move the blue notebook from the office to the mailroom.",
                "environment": {
                    "type": "docker_workspace",
                    "test_command": "python3 -c \"assert True\"",
                },
                "scoring": {"pass_criteria": "The blue notebook is in the outgoing bin."},
                "metadata": {"challenge_effort_self_assessment": assessment},
            }
        )
        return json.dumps(
            {
                "construction_notes": "Model-built test fixture.",
                "resources": [],
                "tasks": [task],
            }
        )

    patch_task_builder_model(monkeypatch, fake_call_llm)

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
    assert suite.tasks[1].metadata["agent_env"]["type"] == "docker_workspace"
    assert len(suite.tasks) == 2
