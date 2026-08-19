from __future__ import annotations

from evalclaw.agent.task_builders.parsing import _task_from_raw
from evalclaw.construction.resources import _resource_from_raw
from evalclaw.core.identifiers import normalize_choice_data
from evalclaw.planning.loop import _apply_review
from evalclaw.planning.task_planner import _parse_plan_response
from evalclaw.protocols.multimodal import normalize_multimodal_metadata
from evalclaw.types import BenchmarkConfig, EvalDimension, EvalSpec, QcReport, TaskSuite, TaskType
from tests.config_helpers import dummy_config_kwargs


def test_task_builder_ignores_llm_entity_ids_and_assigns_options() -> None:
    task = _task_from_raw(
        {
            "id": "llm-invented-task",
            "dimension_id": "llm-invented-dimension",
            "task_type": "choice",
            "title": "A task",
            "prompt": "Choose one.",
            "choices": [
                {"id": "model-choice-x", "text": "First"},
                {"id": "model-choice-y", "text": "Second"},
            ],
            "correct_choice_ids": ["model-choice-y"],
        },
        "framework-task-1",
        default_dimension_id="framework-dimension-1",
        default_task_type=TaskType.choice,
    )

    assert task.id == "framework-task-1"
    assert task.dimension_id == "framework-dimension-1"
    assert [choice.id for choice in task.choices] == ["A", "B"]
    assert task.correct_choice_ids == ["B"]


def test_planner_assigns_dimension_and_task_design_ids() -> None:
    config = BenchmarkConfig(**dummy_config_kwargs())
    plan, issues = _parse_plan_response(
        {
            "plan": {
                "id": "model-plan",
                "objective": "Evaluate reasoning.",
                "dimensions": [
                    {
                        "id": "model-dimension",
                        "name": "Reasoning",
                        "measurement_target": "Reasoning",
                        "boundary": "No tools.",
                        "approach": "Short answers.",
                        "task_designs": [
                            {
                                "id": "model-design",
                                "task_type": "generation",
                                "task_count": 1,
                                "content_design": {"description": "Explain one case."},
                            }
                        ],
                    }
                ],
            }
        },
        config,
    )

    assert not issues
    assert plan.id == "evalclaw_plan"
    assert plan.dimensions[0].id == "dimension_1"
    assert plan.dimensions[0].task_designs[0].id == "dimension_1_task_design_1"


def test_choice_indices_are_zero_based_and_canonical() -> None:
    choices, correct = normalize_choice_data(
        [{"id": "ignored", "text": "one"}, {"id": "also-ignored", "text": "two"}],
        correct_choice_indices=[1],
    )

    assert [choice["id"] for choice in choices] == ["A", "B"]
    assert correct == ["B"]


def test_resources_and_multimodal_assets_ignore_model_ids() -> None:
    resource = _resource_from_raw({"id": "model-resource", "uri": "https://example.com"}, "framework-resource-1")
    metadata = normalize_multimodal_metadata(
        {
            "assets": [{"id": "model-asset", "kind": "image", "uri": "https://example.com/a.png"}],
            "content": [{"type": "asset", "asset_id": "model-asset"}],
        },
        owner_id="framework-task-1",
    )

    assert resource.id == "framework-resource-1"
    assert metadata is not None
    assert metadata["assets"][0]["id"] == "framework-task-1_asset_1"
    assert metadata["content"][0]["asset_id"] == "framework-task-1_asset_1"


def test_review_refs_can_target_new_framework_dimension_ids() -> None:
    source = EvalDimension(
        id="source",
        name="Source",
        description="Source dimension.",
        approach="Keep it.",
        target_item_count=1,
    )
    suite = TaskSuite(
        spec=EvalSpec(objective="Objective", dimensions=[source]),
        objective="Objective",
    )
    outcome = _apply_review(
        suite,
        {
            "add_dimensions": [
                {
                    "ref": "new_dimension",
                    "name": "New",
                    "description": "New dimension.",
                    "approach": "Test it.",
                    "target_item_count": 1,
                }
            ],
            "needs_more_items": [
                {"dimension_id": "new_dimension", "count": 2, "guidance": "Cover edges."}
            ],
        },
        QcReport(),
        None,
    )

    added = next(dimension for dimension in outcome.spec.dimensions if dimension.id != "source")
    assert added.id == "dimension_2"
    assert added.target_item_count == 2
