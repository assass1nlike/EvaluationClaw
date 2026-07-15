import json

from evalclaw.construction.suite import _task_builder_payload
from evalclaw.prompts.qc import QC_SYSTEM_PROMPT
from evalclaw.prompts.task_builder import EXECUTION_CAPABILITY_PROMPT, TASK_BUILDER_PROMPT
from evalclaw.types import (
    AgentEnvironmentType,
    EvalDimension,
    EvalSpec,
    Metric,
    ScaleBudget,
    TaskBlueprint,
    TaskType,
)


def test_task_builder_payload_uses_resolved_scale_and_omits_target_subjects() -> None:
    dimension = EvalDimension(
        id="reasoning",
        name="Reasoning",
        description="Evaluate reasoning across task formats.",
        approach="Use complementary tasks.",
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
    blueprint = TaskBlueprint(
        id="reasoning_tasks",
        dimension_id=dimension.id,
        title="Reasoning tasks",
        task_types=[TaskType.short_answer],
    )

    payload = _task_builder_payload(
        spec,
        dimension,
        blueprint,
        "No external sources.",
        task_type=TaskType.short_answer,
    )

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


def test_static_builder_call_contains_no_execution_capability_fields() -> None:
    dimension = EvalDimension(
        id="knowledge",
        name="Knowledge",
        description="Evaluate knowledge.",
        approach="Use multiple-choice questions.",
        task_types=[TaskType.multiple_choice],
    )
    spec = EvalSpec(
        objective="Evaluate knowledge.",
        task_types=[TaskType.multiple_choice],
        dimensions=[dimension],
    )
    blueprint = TaskBlueprint(
        id="knowledge_tasks",
        dimension_id=dimension.id,
        title="Knowledge tasks",
        task_types=[TaskType.multiple_choice],
    )

    payload = _task_builder_payload(
        spec,
        dimension,
        blueprint,
        "No external sources.",
        task_type=TaskType.multiple_choice,
    )
    serialized = json.dumps(payload)

    assert "environment" not in serialized
    assert "tool_requirements" not in serialized
    assert "metadata_protocols" not in serialized
    assert "task_agent" not in serialized
    assert "agent_task_package" not in serialized
    assert "environment" not in TASK_BUILDER_PROMPT.lower()


def test_execution_fields_are_added_only_for_blueprints_that_request_them() -> None:
    dimension = EvalDimension(
        id="tool_use",
        name="Tool use",
        description="Evaluate stateful tool use.",
        approach="Use an executable workspace task.",
        task_types=[TaskType.agent_interaction],
    )
    spec = EvalSpec(
        objective="Evaluate tool use.",
        task_types=[TaskType.agent_interaction],
        dimensions=[dimension],
    )
    blueprint = TaskBlueprint(
        id="tool_tasks",
        dimension_id=dimension.id,
        title="Tool tasks",
        task_types=[TaskType.agent_interaction],
        environment_type=AgentEnvironmentType.workspace,
        tool_requirements=["look", "read_file"],
    )

    payload = _task_builder_payload(
        spec,
        dimension,
        blueprint,
        "No external sources.",
        task_type=TaskType.agent_interaction,
    )

    construction = payload["task_plan"]["construction"]
    contract = payload["task_builder_contract"]
    assert construction["environment_type"] == "workspace"
    assert construction["tool_requirements"] == ["look", "read_file"]
    assert "environment" in contract["task_schema"]["optional"]
    assert "metadata_protocols" in contract
    assert "execution environment" in EXECUTION_CAPABILITY_PROMPT


def test_task_builder_payload_contract_is_one_task_per_call() -> None:
    dimension = EvalDimension(
        id="analysis",
        name="Analysis",
        description="Evaluate analysis.",
        approach="Use distinct tasks.",
        task_types=[TaskType.open_generation],
    )
    spec = EvalSpec(
        objective="Evaluate analysis.",
        task_types=[TaskType.open_generation],
        dimensions=[dimension],
    )
    blueprint = TaskBlueprint(
        id="analysis_tasks",
        dimension_id=dimension.id,
        title="Analysis tasks",
        task_types=[TaskType.open_generation],
        expected_task_count=5,
    )

    payload = _task_builder_payload(
        spec,
        dimension,
        blueprint,
        "No external sources.",
        task_index=3,
        total_task_count=5,
        task_type=TaskType.open_generation,
    )
    construction = payload["task_plan"]["construction"]

    assert construction["expected_task_count"] == 1
    assert construction["task_index"] == 3
    assert construction["blueprint_task_count"] == 5
    assert "Construct exactly one benchmark task" in TASK_BUILDER_PROMPT


def test_qc_prompt_requires_complete_but_evidence_based_review() -> None:
    assert "complete audit in one pass" in QC_SYSTEM_PROMPT
    assert "independently actionable" in QC_SYSTEM_PROMPT
    assert "invent hypothetical defects" in QC_SYSTEM_PROMPT
    assert "that is sound" in QC_SYSTEM_PROMPT
