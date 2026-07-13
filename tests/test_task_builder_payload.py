from evalclaw.agent.suite import _task_builder_payload
from evalclaw.types import (
    AgentTaskBlueprint,
    EvalDimension,
    EvalSpec,
    Metric,
    ScaleBudget,
    TaskType,
)


def test_task_builder_payload_uses_resolved_scale_and_omits_target_subjects() -> None:
    dimension = EvalDimension(
        id="reasoning",
        name="Reasoning",
        description="Evaluate reasoning across task formats.",
        approach="Use complementary executable tasks.",
        task_types=[TaskType.short_answer, TaskType.code_execution],
    )
    spec = EvalSpec(
        objective="Evaluate reasoning.",
        subjects=["unknown_future_target"],
        task_types=[TaskType.short_answer, TaskType.code_execution],
        dimensions=[dimension],
        scale_budget=ScaleBudget.high,
        scale=37,
        metrics=[Metric.exact_match, Metric.pass_at_1],
    )
    blueprint = AgentTaskBlueprint(
        id="reasoning_tasks",
        dimension_id=dimension.id,
        title="Reasoning tasks",
    )

    payload = _task_builder_payload(spec, dimension, blueprint, "No external sources.")

    benchmark_context = payload["benchmark_context"]
    assert "subjects" not in benchmark_context
    assert "scale_budget" not in benchmark_context
    assert "task_family" not in payload["task_plan"]["construction"]
    assert benchmark_context["scale"] == 37
    assert benchmark_context["task_types"] == ["short_answer", "code_execution"]
    assert benchmark_context["metrics"] == ["exact_match", "pass@1"]
    assert payload["task_plan"]["capability"]["task_types"] == [
        "short_answer",
        "code_execution",
    ]
