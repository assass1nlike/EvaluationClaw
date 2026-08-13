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
from evalclaw.prompts.qc import QC_SYSTEM_PROMPT
from evalclaw.prompts.task_builder import TASK_BUILDER_PROMPT
from evalclaw.types import (
    AgentEnvironmentType,
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
    assert "environment" not in TASK_BUILDER_PROMPT.lower()
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
        environment_type=AgentEnvironmentType.workspace,
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
    assert task_design["environment_requirements"]["category"] == "workspace"
    assert task_design["interaction_requirements"][
        "allowed_action_or_tool_categories"
    ] == ["look", "read_file"]
    assert "environment" in contract["task_schema"]["optional"]
    assert "metadata_protocols" not in contract
    assert contract["environment_skill"]["loaded_references"] == [
        "references/workspace.md"
    ]
    skill_prompt = environment_skill_system_prompt(blueprint)
    assert "# Build Environment-Backed Tasks" in skill_prompt
    assert "initial state -> exposed observations/actions" in skill_prompt
    assert 'path="references/workspace.md"' in skill_prompt
    assert "built-in room, object, inventory" in skill_prompt
    assert 'path="references/docker-workspace.md"' not in skill_prompt
    assert 'path="references/agent-task-package.md"' not in skill_prompt


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
        environment_type=AgentEnvironmentType.gui_desktop,
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
        "references/gui-desktop.md",
        "references/agent-task-package.md",
    ]
    assert payload["routing"][0]["runtime_environment_type"] == "gui_desktop"
    skill_prompt = environment_skill_system_prompt(blueprint)
    assert 'path="references/gui-desktop.md"' in skill_prompt
    assert "Cloudbase-Init's NoCloud service" in skill_prompt
    assert "baseline_verified=true" in skill_prompt
    assert "not a snapshot reference" in skill_prompt
    assert '"vm_provisioning"' in skill_prompt
    assert '"baseline_checks"' in skill_prompt
    assert '"evaluation"' in skill_prompt
    assert "`session.evaluation_checks`" in skill_prompt
    assert "Do not move `evaluation` into `session`" in skill_prompt
    assert "Opaque names" in skill_prompt
    assert "not registered or resolved by the generic bridge" in skill_prompt
    assert 'path="references/agent-task-package.md"' in skill_prompt
    assert 'path="references/workspace.md"' not in skill_prompt


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
    assert "Implement one Planner-authored TaskDesign" in TASK_BUILDER_PROMPT
    assert "only the listed replacement tasks" in TASK_BUILDER_PROMPT
    assert '"resource_ids": []' in TASK_BUILDER_PROMPT
    assert "resource_ids" in TASK_BUILDER_PROMPT
    assert "treat a URL, title, dataset landing page, or brief" in TASK_BUILDER_PROMPT
    assert "missing evidence with invented facts" in TASK_BUILDER_PROMPT
    assert "Materialize every dependency implied by each concrete task" in TASK_BUILDER_PROMPT
    assert "actual inputs, assets, files, services" in TASK_BUILDER_PROMPT


def test_qc_prompt_requires_complete_but_evidence_based_review() -> None:
    assert "complete audit in one pass" in QC_SYSTEM_PROMPT
    assert "independently actionable" in QC_SYSTEM_PROMPT
    assert "invent hypothetical defects" in QC_SYSTEM_PROMPT
    assert "that is sound" in QC_SYSTEM_PROMPT
    assert "matching object in\ntask_designs" in QC_SYSTEM_PROMPT
    assert "not implementation evidence" in QC_SYSTEM_PROMPT
    assert "shape and runner-contract validation only" in QC_SYSTEM_PROMPT
    assert "prompt_is_complete=false" in QC_SYSTEM_PROMPT
    assert "not present in the canonical task" in QC_SYSTEM_PROMPT
    assert "metadata.agent_env and metadata.agent_task_package" in QC_SYSTEM_PROMPT
    assert "cannot add, remove, or override runtime tools" in QC_SYSTEM_PROMPT


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
    requirements = {}
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
        requirements.update(
            _task_builder_payload(
                spec,
                dimension,
                job,
                "No external sources.",
            )["task_builder_contract"]["task_schema"]["type_requirements"]
        )

    assert "expected_text" in requirements["fill_blank"][0]
    assert "python_tests" in requirements["generation"][0]


def test_multi_turn_builder_contract_names_the_runtime_fields_exactly() -> None:
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
    requirements = payload["task_builder_contract"]["task_schema"]["type_requirements"]["multi_turn"]

    assert "interaction.user_turns" in requirements[0]
    assert "non-empty strings" in requirements[0]
    assert environment_skill_system_prompt(blueprint) == ""


def test_adaptive_multi_turn_contract_forbids_scripted_turns() -> None:
    dimension = EvalDimension(
        id="adaptive_dialogue",
        name="Adaptive dialogue",
        description="Evaluate response-conditioned pressure.",
        approach="Adapt every follow-up to the target's latest reply.",
        task_types=[TaskType.multi_turn],
    )
    spec = EvalSpec(
        objective="Evaluate adaptive multi-turn behavior.",
        dimensions=[dimension],
        task_types=[TaskType.multi_turn],
    )
    design = make_task_design(
        "adaptive_design",
        TaskType.multi_turn,
    )
    design.interaction_requirements["followup_mode"] = "adaptive"
    blueprint = make_blueprint(
        "adaptive_blueprint",
        dimension.id,
        "Adaptive tasks",
        task_designs=[design],
    )

    requirements = _task_builder_payload(
        spec, dimension, blueprint, "No external sources."
    )["task_builder_contract"]["task_schema"]["type_requirements"]["multi_turn"]

    assert "followup_instruction" in requirements[0]
    assert "omit interaction.user_turns" in requirements[0]
    assert any("system_prompt is exclusively" in requirement for requirement in requirements)
