from __future__ import annotations

import json

from evalclaw.construction.validation import task_structure_issues
from evalclaw.quality.dataset_checks import _coverage_issues, _duplicate_issues
from evalclaw.quality.llm_checks import _compact_metadata_for_qc, _llm_qc
from evalclaw.quality.qc import run_qc_gate
from evalclaw.quality.static_checks import _static_item_issues
from evalclaw.types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    QcSeverity,
    TaskDefinition,
    TaskType,
)
from tests.blueprint_factory import make_blueprint


def _task(
    task_type: TaskType,
    *,
    environment: AgentEnvironmentSpec | None = None,
    answer: str | None = None,
    rubric: str | None = None,
    test_code: str | None = None,
    interaction: dict | None = None,
) -> TaskDefinition:
    return TaskDefinition(
        id="task_1",
        dimension_id="dimension_1",
        task_type=task_type,
        title="Contract test",
        prompt="Complete the requested benchmark task and return the required result.",
        answer=answer,
        rubric=rubric,
        test_code=test_code,
        environment=environment,
        interaction=interaction or {},
    )


def test_short_answer_may_use_rubric_instead_of_exact_answer() -> None:
    task = _task(TaskType.short_answer, rubric="Accept any equivalent explanation of the result.")

    assert task_structure_issues(task) == []


def test_code_execution_requires_a_test_that_consumes_model_output() -> None:
    missing = _task(TaskType.code_execution, rubric="Score correctness.")
    unrelated = _task(TaskType.code_execution, test_code="assert 2 + 2 == 4")
    valid = _task(TaskType.code_execution, test_code="assert {model_output} == '4'")

    assert any("must provide test_code" in issue for issue in task_structure_issues(missing))
    assert any("must consume the response" in issue for issue in task_structure_issues(unrelated))
    assert task_structure_issues(valid) == []


def test_empty_code_sandbox_is_valid_when_the_agent_creates_files() -> None:
    task = _task(
        TaskType.agent_interaction,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.code_sandbox,
            test_command="python3 verify.py",
        ),
    )

    assert task_structure_issues(task) == []


def test_docker_browser_validation_does_not_guess_capabilities_from_image_name() -> None:
    task = _task(
        TaskType.agent_interaction,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.docker_workspace,
            image="organization/custom-runtime:1",
            test_command="python3 verify.py",
            browser={
                "enabled": True,
                "runtime": "playwright_python",
                "start_url": "http://127.0.0.1:8000",
                "allowed_origins": ["http://127.0.0.1:8000"],
            },
        ),
    )

    assert task_structure_issues(task) == []


def test_workspace_contract_matches_the_builtin_room_inventory_runtime() -> None:
    valid = _task(
        TaskType.agent_interaction,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.workspace,
            workspace={
                "start_room": "office",
                "rooms": {"office": ["brief"], "mailroom": []},
                "goal": {"outgoing_bin": ["brief"]},
            },
        ),
    )
    invalid = valid.model_copy(
        update={
            "environment": valid.environment.model_copy(
                update={
                    "workspace": {
                        "rooms": {"office": []},
                        "goal": {"outgoing_bin": ["missing_brief"]},
                    }
                }
            )
        }
    )

    assert task_structure_issues(valid) == []
    invalid_issues = task_structure_issues(invalid)
    assert any("mailroom" in issue for issue in invalid_issues)
    assert any("must exist" in issue for issue in invalid_issues)


def test_gui_contract_requires_a_startable_session_evaluator_and_vm_source() -> None:
    task = _task(
        TaskType.agent_interaction,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.gui_desktop,
            requires_vm=True,
            vm={"display": "1920x1080"},
            session={"workflow": "Edit the document."},
            evaluation={"description": "Check the document."},
        ),
    )

    issues = task_structure_issues(task)

    assert any("application or desktop surface" in issue for issue in issues)
    assert any("launch or start state" in issue for issue in issues)
    assert any("executable evaluation" in issue for issue in issues)
    assert any("runner-resolvable" in issue for issue in issues)


def test_gui_vm_provisioning_matches_declared_guest_os() -> None:
    base_environment = AgentEnvironmentSpec(
        type=AgentEnvironmentType.gui_desktop,
        requires_vm=True,
        vm={"image": "windows-11-cloudbase", "guest_os": "windows"},
        session={
            "application": "desktop",
            "start_state": "Signed in at the desktop.",
            "baseline_checks": [
                {"method": "path_exists", "path": r"C:\EvalClaw"},
            ],
        },
        evaluation={"method": "bridge_state_check"},
        vm_provisioning={"powershell_commands": ["New-Item C:\\EvalClaw -ItemType Directory -Force"]},
    )
    valid = _task(TaskType.agent_interaction, environment=base_environment)
    invalid = valid.model_copy(
        update={
            "environment": base_environment.model_copy(
                update={"vm_provisioning": {"apt_packages": ["curl"]}}
            )
        }
    )
    unchecked = valid.model_copy(
        update={
            "environment": base_environment.model_copy(
                update={"session": {"application": "desktop", "start_state": "Signed in."}}
            )
        }
    )

    assert task_structure_issues(valid) == []
    assert any("Linux-only package fields" in issue for issue in task_structure_issues(invalid))
    assert any("baseline_checks" in issue for issue in task_structure_issues(unchecked))


def test_dialogue_contract_requires_bounded_scripted_or_dynamic_followups() -> None:
    invalid = _task(
        TaskType.multi_turn,
        environment=AgentEnvironmentSpec(type=AgentEnvironmentType.dialogue),
        rubric="Score the complete dialogue.",
        interaction={"max_turns": 3},
    )
    valid = invalid.model_copy(
        update={"interaction": {"max_turns": 3, "user_turns": ["Please revise the answer."]}}
    )

    assert any("user_turns or a followup_instruction" in issue for issue in task_structure_issues(invalid))
    assert task_structure_issues(valid) == []


def test_pairwise_reference_model_is_required_only_when_execution_is_requested() -> None:
    dimension = EvalDimension(
        id="comparison",
        name="Comparison",
        description="Compare response quality.",
        approach="Use pairwise judging.",
        task_types=[TaskType.pairwise_preference],
    )
    spec = EvalSpec(
        objective="Compare model responses.",
        dimensions=[dimension],
        task_types=[TaskType.pairwise_preference],
    )
    item = BenchmarkItem(
        id="pairwise_1",
        dimension_id=dimension.id,
        task_type=TaskType.pairwise_preference,
        prompt="Write a concise explanation of why the proposed change is safe and effective.",
        rubric="Prefer correctness, completeness, and clarity; return a tie when quality is equivalent.",
    )
    dataset = BenchmarkDataset(spec=spec, items=[item])

    draft_qc = run_qc_gate(dataset, BenchmarkConfig(run_targets=False))
    execution_qc = run_qc_gate(dataset, BenchmarkConfig(run_targets=True))

    assert not any("reference_model" in issue.message for issue in draft_qc.issues)
    assert any("reference_model" in issue.message for issue in execution_qc.issues)


def test_dataset_checks_duplicate_ids_unknown_dimensions_and_near_duplicates() -> None:
    item_a = BenchmarkItem(
        id="same_id",
        dimension_id="known",
        task_type=TaskType.open_generation,
        prompt="Analyze the supplied dataset and explain the first trend in detail.",
        rubric="Score factual accuracy.",
    )
    item_b = item_a.model_copy(
        update={"prompt": "Analyze the supplied dataset and explain the second trend in detail."}
    )
    duplicate_issues = _duplicate_issues([item_a, item_b])

    assert any("duplicated" in issue.message for issue in duplicate_issues)
    near = [issue for issue in duplicate_issues if "very similar" in issue.message]
    assert near and all(issue.severity == QcSeverity.warning for issue in near)

    spec = EvalSpec(
        objective="Test coverage.",
        dimensions=[
            EvalDimension(
                id="known",
                name="Known",
                description="Known capability.",
                approach="Use direct tasks.",
            )
        ],
    )
    unknown = item_a.model_copy(update={"id": "unknown", "dimension_id": "missing"})
    assert any(
        "unknown dimension" in issue.message
        for issue in _coverage_issues(BenchmarkDataset(spec=spec, items=[unknown]))
    )


def test_multimodal_qc_requires_resolvable_assets_and_valid_references() -> None:
    item = BenchmarkItem(
        id="image_1",
        dimension_id="vision",
        task_type=TaskType.open_generation,
        prompt="Inspect the supplied image and describe the main visible anomaly.",
        rubric="Score against visible evidence.",
        metadata={
            "multimodal": {
                "schema_version": "evalclaw.multimodal.v1",
                "modalities": ["image"],
                "assets": [{"id": "actual", "kind": "image"}],
                "content": [{"type": "asset", "asset_id": "missing"}],
            }
        },
    )

    messages = [issue.message for issue in _static_item_issues(item)]

    assert any("no resolvable source" in message for message in messages)
    assert any("unknown asset" in message for message in messages)


def test_llm_qc_receives_task_design_and_execution_relevant_environment_details(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(messages, *args, **kwargs):
        captured.update(json.loads(messages[0].content))
        return json.dumps({"issues": [], "summary": "ok"})

    monkeypatch.setattr("evalclaw.quality.llm_checks.call_llm", fake_call_llm)
    dimension = EvalDimension(
        id="analysis",
        name="Analysis",
        description="Evaluate analysis.",
        approach="Use an open response.",
        task_types=[TaskType.open_generation],
    )
    spec = EvalSpec(
        objective="Evaluate analysis.",
        dimensions=[dimension],
        task_types=[TaskType.open_generation],
    )
    blueprint = make_blueprint(
        "analysis_blueprint",
        dimension.id,
        "Analysis task",
        task_type=TaskType.open_generation,
    )
    design_id = blueprint.task_designs[0].id
    item = BenchmarkItem(
        id="analysis_1",
        dimension_id=dimension.id,
        task_type=TaskType.open_generation,
        prompt="Analyze the evidence and explain the most defensible conclusion.",
        rubric="Score evidence use and correctness.",
        metadata={"task_design_id": design_id},
    )
    dataset = BenchmarkDataset(spec=spec, items=[item], blueprints=[blueprint])

    _llm_qc(dataset, BenchmarkConfig(orchestrator_api_key="dummy"))

    assert captured["task_designs"][0]["id"] == design_id

    compact = _compact_metadata_for_qc(
        {
            "agent_env": {
                "type": "gui_desktop",
                "session": {"application": "desktop", "launch_state": "Start menu is open."},
                "evaluation": {"checks": [{"command": "verify-state"}]},
                "vm": {"template": "windows-template", "snapshot": "broken-state"},
                "vm_provisioning": {"install_steps": ["prepare-state"]},
            }
        }
    )["agent_env"]
    assert compact["session"]["launch_state"] == "Start menu is open."
    assert compact["evaluation"]["checks"][0]["command"] == "verify-state"
    assert compact["vm"]["snapshot"] == "broken-state"
    assert compact["vm_provisioning"]["install_steps"] == ["prepare-state"]
