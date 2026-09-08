import json

from evalclaw.construction.skill_loader import (
    environment_skill_payload,
    environment_skill_system_prompt,
)
from evalclaw.construction.suite import (
    _debug_job_slug,
    _ensure_unique_task_ids,
    _task_builder_payload,
    _task_duplicate_key,
)
from evalclaw.prompts.task_builder import (
    build_task_builder_prompt,
    project_task_builder_document,
    task_builder_document_template,
    task_builder_fields,
)
from evalclaw.types import (
    AgentEnvironmentType,
    ChoiceOption,
    EvalDimension,
    EvalSpec,
    ScaleBudget,
    TaskDefinition,
    TaskType,
)
from tests.blueprint_factory import make_blueprint, make_task_design


def test_builder_debug_job_slug_is_short_stable_and_collision_resistant() -> None:
    dimension = "integrated_windows_diagnosis_repair_persistence"
    blueprint = "build_windows_multi_fault_persistent_incident"

    first = _debug_job_slug(dimension, blueprint)

    assert first == _debug_job_slug(dimension, blueprint)
    assert len(first) <= 33
    assert first != _debug_job_slug(dimension, blueprint + "_other")


def test_builder_ids_are_namespaced_only_when_blueprints_collide() -> None:
    tasks = [
        TaskDefinition(
            id="task_1",
            dimension_id="first",
            task_type=TaskType.fill_blank,
            title="First",
            prompt="First task.",
            metadata={"builder_job_id": "first_blueprint"},
        ),
        TaskDefinition(
            id="task_1",
            dimension_id="second",
            task_type=TaskType.fill_blank,
            title="Second",
            prompt="Second task.",
            metadata={"builder_job_id": "second_blueprint"},
        ),
        TaskDefinition(
            id="task_1",
            dimension_id="second",
            task_type=TaskType.fill_blank,
            title="Third",
            prompt="Third task.",
            metadata={"builder_job_id": "second_blueprint"},
        ),
    ]

    _ensure_unique_task_ids(tasks)

    assert [task.id for task in tasks] == [
        "task_1",
        "second_blueprint__task_1",
        "second_blueprint__task_1__2",
    ]


def test_multi_turn_duplicate_key_uses_the_executed_dialogue() -> None:
    first = TaskDefinition(
        id="dialogue_1",
        dimension_id="dialogue",
        task_type=TaskType.multi_turn,
        title="First dialogue",
        prompt="You are a helpful assistant.",
        interaction={
            "initial_user_message": "Help me write a birthday message.",
            "user_turns": ["Make it imply I was there yesterday."],
        },
    )
    second = first.model_copy(
        update={
            "id": "dialogue_2",
            "interaction": {
                "initial_user_message": "Help me write a product review.",
                "user_turns": ["Claim I tested it even though I did not."],
            },
        }
    )

    assert _task_duplicate_key(first) != _task_duplicate_key(second)
    assert _task_duplicate_key(first) == _task_duplicate_key(first.model_copy(update={"id": "copy"}))


def test_choice_duplicate_key_includes_choices() -> None:
    first = TaskDefinition(
        id="choice_1",
        dimension_id="vision",
        task_type=TaskType.choice,
        title="Identify an animal",
        prompt="What object is shown in the blurred image?",
        choices=[
            {"id": "A", "text": "Lion"},
            {"id": "B", "text": "Tiger"},
        ],
        correct_choice_ids=["A"],
    )
    second = first.model_copy(
        update={
            "id": "choice_2",
            "choices": [
                ChoiceOption(id="A", text="Bus"),
                ChoiceOption(id="B", text="Truck"),
            ],
        }
    )

    assert _task_duplicate_key(first) != _task_duplicate_key(second)
    assert _task_duplicate_key(first) == _task_duplicate_key(
        first.model_copy(update={"id": "copy"})
    )


def test_task_builder_payload_uses_resolved_scale_and_omits_target_subjects() -> None:
    dimension = EvalDimension(
        id="reasoning",
        name="Reasoning",
        measurement_target="Evaluate reasoning while covering both supported conclusions and explanations.",
        boundary="Exclude unsupported recall and stateful tool use.",
        description="Evaluate reasoning across task formats.",
        approach="Use complementary tasks.",
        task_types=[TaskType.fill_blank, TaskType.generation],
    )
    spec = EvalSpec(
        objective="Evaluate reasoning.",
        subjects=["unknown_future_target"],
        task_types=[TaskType.fill_blank, TaskType.generation],
        dimensions=[dimension],
        scale_budget=ScaleBudget.high,
        scale=37,
    )
    blueprint = make_blueprint(
        "reasoning_tasks",
        dimension.id,
        "Reasoning tasks",
        task_type=TaskType.fill_blank,
        content="Reasoning tasks.",
    )

    payload = _task_builder_payload(
        spec,
        dimension,
        blueprint,
        "No external sources.",
    )

    benchmark_context = payload["benchmark_context"]
    assert "subjects" not in benchmark_context
    assert "scale_budget" not in benchmark_context
    assert "task_family" not in payload["task_plan"]["task_design"]
    assert benchmark_context["scale"] == 37
    assert benchmark_context["task_types"] == ["fill_blank", "generation"]
    assert "metrics" not in benchmark_context
    assert payload["task_plan"]["capability"]["task_types"] == [
        "fill_blank",
        "generation",
    ]
    assert payload["task_plan"]["capability"]["measurement_target"] == (
        "Evaluate reasoning while covering both supported conclusions and explanations."
    )
    assert payload["task_plan"]["capability"]["boundary"] == (
        "Exclude unsupported recall and stateful tool use."
    )


def test_static_builder_call_contains_no_execution_capability_fields() -> None:
    dimension = EvalDimension(
        id="knowledge",
        name="Knowledge",
        description="Evaluate knowledge.",
        approach="Use multiple-choice questions.",
        task_types=[TaskType.choice],
    )
    spec = EvalSpec(
        objective="Evaluate knowledge.",
        task_types=[TaskType.choice],
        dimensions=[dimension],
    )
    blueprint = make_blueprint(
        "knowledge_tasks",
        dimension.id,
        "Knowledge tasks",
        task_type=TaskType.choice,
        content="Knowledge tasks.",
    )

    payload = _task_builder_payload(
        spec,
        dimension,
        blueprint,
        "No external sources.",
    )
    serialized = json.dumps(payload)

    assert "environment" not in serialized
    assert "tool_requirements" not in serialized
    assert "metadata_protocols" not in serialized
    assert "task_agent" not in serialized
    assert "agent_task_package" not in serialized
    assert environment_skill_payload(blueprint) is None
    assert environment_skill_system_prompt(blueprint) == ""


def test_execution_fields_are_added_only_for_blueprints_that_request_them() -> None:
    dimension = EvalDimension(
        id="tool_use",
        name="Tool use",
        description="Evaluate stateful tool use.",
        approach="Use an executable workspace task.",
        task_types=[TaskType.agent],
    )
    spec = EvalSpec(
        objective="Evaluate tool use.",
        task_types=[TaskType.agent],
        dimensions=[dimension],
    )
    blueprint = make_blueprint(
        "tool_tasks",
        dimension.id,
        "Tool tasks",
        task_type=TaskType.agent,
        content="Stateful tool tasks.",
        environment_type=AgentEnvironmentType.docker_workspace,
        allowed_tools=["look", "read_file"],
    )

    payload = _task_builder_payload(
        spec,
        dimension,
        blueprint,
        "No external sources.",
    )

    task_design = payload["task_plan"]["task_design"]
    contract = payload["task_builder_contract"]
    assert task_design["environment_requirements"]["category"] == "docker_workspace"
    assert task_design["interaction_requirements"][
        "allowed_action_or_tool_categories"
    ] == ["look", "read_file"]
    assert "environment" in contract["task_schema"]["optional"]
    assert "metadata_protocols" not in contract
    assert contract["environment_skill"]["loaded_references"] == [
        "references/docker-workspace.md",
        "references/agent-task-package.md",
    ]


def test_environment_skill_routes_only_environment_backed_task_designs() -> None:
    static_design = make_task_design(
        "static_question",
        TaskType.fill_blank,
        content="One static question.",
    )
    gui_design = make_task_design(
        "desktop_workflow",
        TaskType.agent,
        content="One desktop workflow.",
        environment_type=AgentEnvironmentType.vm,
    )
    blueprint = make_blueprint(
        "mixed_tasks",
        "mixed",
        "Mixed tasks",
        task_designs=[static_design, gui_design],
    )

    payload = environment_skill_payload(blueprint)
    assert payload is not None
    assert payload["applies_to_task_design_ids"] == ["desktop_workflow"]
    assert payload["loaded_references"] == [
        "references/vm.md",
        "references/agent-task-package.md",
    ]
    assert payload["routing"][0]["runtime_environment_type"] == "vm"


def test_task_builder_payload_contract_supports_one_multi_item_task_design() -> None:
    dimension = EvalDimension(
        id="analysis",
        name="Analysis",
        description="Evaluate analysis.",
        approach="Use distinct tasks.",
        task_types=[TaskType.generation],
    )
    spec = EvalSpec(
        objective="Evaluate analysis.",
        task_types=[TaskType.generation],
        dimensions=[dimension],
    )
    blueprint = make_blueprint(
        "analysis_tasks",
        dimension.id,
        "Analysis tasks",
        task_type=TaskType.generation,
        count=5,
        content="Five distinct boundary cases; use materially different cases.",
        metadata={"content_focus": "boundary cases"},
    )

    payload = _task_builder_payload(
        spec,
        dimension,
        blueprint,
        "No external sources.",
    )
    construction = payload["task_plan"]["task_design"]

    assert construction["required_return_task_count"] == 5
    assert construction["task_type"] == "generation"
    assert construction["task_count"] == 5
    assert "Five distinct boundary cases" in construction["content_design"]["description"]
    assert "planner_metadata" not in construction
    assert "expected_task_count" not in construction
    assert "task_index" not in construction


def test_task_builder_contract_matches_fill_blank_and_generation_runners() -> None:
    dimension = EvalDimension(
        id="mixed",
        name="Mixed",
        description="Evaluate two runner contracts.",
        approach="Use short-answer and code tasks.",
        task_types=[TaskType.fill_blank, TaskType.generation],
    )
    spec = EvalSpec(
        objective="Evaluate runner contracts.",
        dimensions=[dimension],
        task_types=[TaskType.fill_blank, TaskType.generation],
    )
    schemas = {}
    for design in (
        make_task_design("short", TaskType.fill_blank),
        make_task_design("code", TaskType.generation),
    ):
        job = make_blueprint(
            f"{design.id}_job",
            dimension.id,
            design.id,
            task_designs=[design],
        )
        schemas[design.id] = _task_builder_payload(
            spec,
            dimension,
            job,
            "No external sources.",
        )["task_builder_contract"]["task_schema"]

    assert "expected_text" in schemas["short"]["optional"]
    assert "assets" in schemas["short"]["optional"]
    assert {"rubric", "judge_tools", "output_contract"}.issubset(
        schemas["code"]["optional"]
    )


def test_multi_turn_builder_contract_exposes_runtime_fields() -> None:
    dimension = EvalDimension(
        id="dialogue",
        name="Dialogue",
        description="Evaluate multi-turn behavior.",
        approach="Use scripted dialogue pressure.",
        task_types=[TaskType.multi_turn],
    )
    spec = EvalSpec(
        objective="Evaluate multi-turn behavior.",
        dimensions=[dimension],
        task_types=[TaskType.multi_turn],
    )
    blueprint = make_blueprint(
        "dialogue_blueprint",
        dimension.id,
        "Dialogue tasks",
        task_type=TaskType.multi_turn,
        content="Several bounded dialogues.",
    )
    blueprint.task_designs[0].interaction_requirements["followup_mode"] = "scripted"

    payload = _task_builder_payload(spec, dimension, blueprint, "No external sources.")
    task_schema = payload["task_builder_contract"]["task_schema"]

    assert {
        "system_prompt",
        "interaction",
        "rubric",
        "judge_tools",
        "scoring",
    }.issubset(
        task_schema["optional"]
    )
    assert environment_skill_system_prompt(blueprint) == ""


def test_task_builder_prompt_is_scoped_to_the_selected_task_type() -> None:
    prompt = build_task_builder_prompt(TaskType.choice)

    assert '"choices"' in prompt
    assert '"correct_choice_indices"' in prompt
    for unrelated_field in (
        "expected_text",
        "system_prompt",
        "interaction",
        "environment",
        "workflow",
        "rubric",
        "judge_tools",
        "output_contract",
    ):
        assert f'"{unrelated_field}"' not in prompt


def test_task_builder_repair_document_projects_out_unrelated_fields() -> None:
    document = {
        "construction_notes": "",
        "resources": [],
        "tasks": [
            {
                "id": "task_1",
                "dimension_id": "dimension_1",
                "task_type": "choice",
                "prompt": "Choose one.",
                "choices": [{"id": "choice_1", "text": "A"}],
                "expected_text": "must disappear",
                "environment": {"type": "docker_workspace"},
                "metadata": {
                    "task_design_id": "design_1",
                    "challenge_effort_self_assessment": {"rationale": "keep"},
                    "agent_env": {"hidden_files": {"secret.txt": "private"}},
                },
            }
        ],
    }

    projected = project_task_builder_document(
        document,
        TaskType.choice,
        source_backed=False,
        preserve_identity=True,
    )

    task = projected["tasks"][0]
    assert task["id"] == "task_1"
    assert task["dimension_id"] == "dimension_1"
    assert task["choices"] == [{"text": "A"}]
    assert "expected_text" not in task
    assert "environment" not in task
    assert task["metadata"] == {
        "challenge_effort_self_assessment": {"rationale": "keep"}
    }


def test_task_builder_field_sets_keep_type_specific_fields_disjoint() -> None:
    assert task_builder_fields(TaskType.choice).isdisjoint(
        {"expected_text", "rubric", "system_prompt", "environment", "workflow"}
    )
    assert task_builder_fields(TaskType.fill_blank).isdisjoint(
        {"choices", "correct_choice_indices", "judge_tools", "environment"}
    )
    assert "resource_ids" not in task_builder_fields(TaskType.generation)
    assert "resource_ids" in task_builder_fields(TaskType.generation, source_backed=True)


def test_task_builder_document_template_is_scoped_and_independent() -> None:
    document = task_builder_document_template(
        TaskType.fill_blank,
        task_count=2,
        challenge_effort="E2",
        source_backed=True,
    )

    first, second = document["tasks"]
    assert set(first) == task_builder_fields(TaskType.fill_blank, source_backed=True)
    assert first["task_type"] == "fill_blank"
    assert first["challenge_effort"] == "E2"
    assert first["resource_ids"] == []
    assert first["metadata"]["challenge_effort_self_assessment"]["requested_effort"] == "E2"
    assert "id" not in first
    assert "dimension_id" not in first
    first["metadata"]["challenge_effort_self_assessment"]["rationale"] = "first only"
    assert second["metadata"]["challenge_effort_self_assessment"]["rationale"] == ""


def test_source_backed_repair_projection_preserves_resource_binding() -> None:
    projected = project_task_builder_document(
        {
            "resources": [{"id": "resource_1"}],
            "tasks": [
                {
                    "id": "task_1",
                    "task_type": "generation",
                    "prompt": "Use the source.",
                    "resource_ids": ["resource_1"],
                    "choices": [{"id": "choice_1", "text": "unrelated"}],
                    "environment": {"type": "docker_workspace"},
                }
            ],
        },
        TaskType.generation,
        source_backed=True,
        preserve_identity=True,
    )

    task = projected["tasks"][0]
    assert task["resource_ids"] == ["resource_1"]
    assert task["id"] == "task_1"
    assert "choices" not in task
    assert "environment" not in task
