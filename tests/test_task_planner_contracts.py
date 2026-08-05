from __future__ import annotations

import json

import pytest

from evalclaw.planning.task_planner import (
    _audit_plan,
    _explicit_total_task_count,
    plan_benchmark,
)
from evalclaw.types import BenchmarkConfig, BenchmarkPlan, TaskType


def _plan(
    *,
    task_count: int = 1,
    task_type: TaskType = TaskType.generation,
    environment_category: str = "",
    followup_mode: str = "adaptive",
) -> BenchmarkPlan:
    environment = (
        {"category": environment_category, "purpose": "Run the interaction."}
        if environment_category
        else {}
    )
    return BenchmarkPlan.model_validate(
        {
            "id": "test_plan",
            "objective": "Test the requested capability.",
            "metrics": ["judge_score"],
            "dimensions": [
                {
                    "id": "capability",
                    "name": "Capability",
                    "measurement_target": "The requested capability.",
                    "boundary": "Exclude unrelated capabilities.",
                    "approach": "Measure it directly.",
                    "task_designs": [
                        {
                            "id": "tasks",
                            "task_type": task_type.value,
                            "task_count": task_count,
                            "content_design": {"description": "Concrete test cases."},
                            "interaction_requirements": (
                                {"followup_mode": followup_mode}
                                if task_type == TaskType.multi_turn and followup_mode
                                else {}
                            ),
                            "environment_requirements": environment,
                        }
                    ],
                    "blueprints": [
                        {
                            "id": "builder_job",
                            "title": "Build test cases",
                            "task_design_ids": ["tasks"],
                            "grouping_rationale": "The tasks share one construction method.",
                            "workload_reason": "The response fits one Builder call.",
                        }
                    ],
                }
            ],
        }
    )


def test_explicit_total_task_count_is_conservative() -> None:
    assert _explicit_total_task_count("Create exactly 50 scenario dialogue questions.") == 50
    assert _explicit_total_task_count("Create a total of exactly 20 crystallography questions.") == 20
    assert _explicit_total_task_count("总共出 20 道题，覆盖两种题型。") == 20
    assert _explicit_total_task_count("Create exactly 10 questions in each of 5 domains.") is None


def test_llm_planning_without_a_configured_model_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="fails closed"):
        plan_benchmark("Create one benchmark task.", BenchmarkConfig(task_builder="llm"))


def test_plan_audit_enforces_explicit_total() -> None:
    issues = _audit_plan(_plan(task_count=51), expected_task_count=50)

    assert any("requested exactly 50" in issue and "contains 51" in issue for issue in issues)


def test_plan_audit_keeps_multi_turn_out_of_environment_routes() -> None:
    wrong_route = _audit_plan(_plan(task_type=TaskType.multi_turn, environment_category="workspace"))
    correct_route = _audit_plan(_plan(task_type=TaskType.multi_turn))

    assert any("only valid for agent tasks" in issue for issue in wrong_route)
    assert correct_route == []


def test_plan_audit_requires_multi_turn_followup_mode() -> None:
    issues = _audit_plan(
        _plan(
            task_type=TaskType.multi_turn,
            followup_mode="",
        )
    )

    assert any("followup_mode" in issue for issue in issues)


def test_plan_audit_rejects_workspace_for_static_task() -> None:
    issues = _audit_plan(
        _plan(task_type=TaskType.fill_blank, environment_category="workspace")
    )

    assert any("only valid for agent tasks" in issue for issue in issues)


def test_planner_repairs_wrong_explicit_total(monkeypatch) -> None:
    responses = [_plan(task_count=51), _plan(task_count=50)]
    payloads: list[str] = []

    def fake_call_llm(messages, **kwargs):
        payloads.append(messages[0].content)
        return json.dumps({"plan": responses[len(payloads) - 1].model_dump(mode="json")})

    monkeypatch.setattr("evalclaw.planning.task_planner.call_llm", fake_call_llm)

    plan = plan_benchmark(
        "Create exactly 50 evaluation questions.",
        BenchmarkConfig(orchestrator_api_key="dummy", max_planner_iterations=2),
    )

    assert sum(design.task_count for dim in plan.dimensions for design in dim.task_designs) == 50
    assert len(payloads) == 2
    assert "explicitly requested exactly 50 tasks" in payloads[1]


def test_low_effort_planner_uses_bounded_output_budget(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(messages, **kwargs):
        captured.update(kwargs)
        return json.dumps({"plan": _plan().model_dump(mode="json")})

    monkeypatch.setenv("EVALCLAW_REASONING_EFFORT", "low")
    monkeypatch.setattr("evalclaw.planning.task_planner.call_llm", fake_call_llm)

    plan_benchmark(
        "Create exactly one benchmark task.",
        BenchmarkConfig(orchestrator_api_key="dummy"),
    )

    assert captured["max_tokens"] == 4096
