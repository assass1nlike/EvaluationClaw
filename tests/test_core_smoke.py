import json
import subprocess
import sys
import threading
import time
import types
from pathlib import Path, PureWindowsPath

import pytest

from evalclaw.construction import build_task_suite
from evalclaw.construction.packaging import pack_task_item
from evalclaw.construction.research import TaskBuilderCallError
from evalclaw.construction.validation import task_structure_issues
from evalclaw.core.scaling import scale_budget_target_items
from evalclaw.core.task_summary import TASK_CONTENT_SUMMARY_METADATA_KEY
from evalclaw.execution.agent_envs import build_agent_environment
from evalclaw.execution.desktop_agent_env import DesktopBridgeAgentEnvironment, DesktopBridgeStatus
from evalclaw.execution.docker import DockerStatus
from evalclaw.execution.docker_images import (
    DockerImageProbe,
    apply_docker_image_selection,
    select_docker_image,
)
from evalclaw.execution.environment_claw import run_environment_claw
from evalclaw.execution.lm_eval import _resolve_lm_eval_executable
from evalclaw.execution.runner import (
    _parse_agent_action,
    _score_choice,
    _score_fill_blank,
    _target_prompt,
    run_item,
)
from evalclaw.execution.sandbox import build_code_harness, run_python_sandbox
from evalclaw.execution.vm_provider import (
    VmProviderStatus,
    VmSession,
    _wait_for_virtualbox_bridge,
    create_local_vm_session,
    destroy_local_vm_session,
    probe_local_vm_backend,
    probe_vm_provider,
    trust_env_for_url,
)
from evalclaw.models.json_utils import extract_json
from evalclaw.models.llm import LLMOutputTruncatedError, TargetToolModelResponse
from evalclaw.pipeline import _persist_package
from evalclaw.planning.loop import (
    _planner_review,
    apply_human_review_feedback,
    format_human_review_overview,
)
from evalclaw.planning.planner import translate_goal_to_english
from evalclaw.planning.task_planner import _instruction_resource, plan_benchmark
from evalclaw.protocols.agent_task_package import compact_agent_task_package
from evalclaw.protocols.tool import ToolCall, ToolSpec, object_schema, validate_tool_call
from evalclaw.quality.qc import run_qc_gate
from evalclaw.reporting.artifacts import _portable_path, write_lm_eval_artifacts
from evalclaw.reporting.reporter import _is_source_backed as _report_is_source_backed
from evalclaw.reporting.reporter import build_report
from evalclaw.reporting.viewer import _viewer_payload, build_report_viewer_html
from evalclaw.sources.hf_discovery import _expanded_queries
from evalclaw.types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkItem,
    BenchmarkPackage,
    BenchmarkSource,
    ChallengeEffort,
    EvalDimension,
    EvalRun,
    EvalSpec,
    ItemResult,
    JudgeToolRef,
    QcCategory,
    QcIssue,
    QcReport,
    QcSeverity,
    ScaleBudget,
    SourceKind,
    TargetModelConfig,
    TaskDefinition,
    TaskResource,
    TaskScoringSpec,
    TaskSuite,
    TaskType,
)
from tests.blueprint_factory import make_blueprint
from tests.config_helpers import (
    dummy_config_kwargs,
    patch_task_builder_model,
    save_task_builder_response,
)


def test_sandbox_runs_in_isolated_container(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.execution.sandbox.docker_status",
        lambda **kwargs: DockerStatus(available=True, executable="docker"),
    )
    monkeypatch.setattr("evalclaw.execution.sandbox.resolve_docker_executable", lambda value: "docker")

    def fake_run(command, **kwargs):
        assert command[:3] == ["docker", "run", "--rm"]
        assert "--network" in command and command[command.index("--network") + 1] == "none"
        assert "--read-only" in command
        assert kwargs["input"] == 'assert 1 + 1 == 2\nprint("ok")'
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr("evalclaw.execution.sandbox.subprocess.run", fake_run)
    exit_code, stdout, stderr = run_python_sandbox('assert 1 + 1 == 2\nprint("ok")')

    assert exit_code == 0
    assert stdout.strip() == "ok"
    assert stderr == ""


def test_core_models_fill_defaults() -> None:
    target = TargetModelConfig(provider="deepseek", model="deepseek-v4-flash")
    config = BenchmarkConfig(targets=[target])
    dimension = EvalDimension(
        id="format_following",
        name="Format following",
        description="Checks whether responses follow a requested schema.",
        approach="Use constrained prompts and exact validation.",
    )

    assert target.id == "deepseek-v4-flash"
    assert config.targets[0].provider == "deepseek"
    assert dimension.weight == 1.0


def test_scale_budget_targets_are_raw_item_counts() -> None:
    assert scale_budget_target_items(ScaleBudget.low) == 100
    assert scale_budget_target_items(ScaleBudget.mid) == 500
    assert scale_budget_target_items(ScaleBudget.high) == 1000
    assert scale_budget_target_items(ScaleBudget.large) == 5000
    assert scale_budget_target_items(ScaleBudget.xlarge) == 20000


def test_docker_image_selector_prefers_common_runtime_images() -> None:
    node = select_docker_image(
        {
            "type": "docker_workspace",
            "visible_files": {"package.json": '{"name":"demo"}', "src/app.ts": "export const ok = true;"},
            "test_command": "npm test",
        }
    )
    rust = select_docker_image(
        {
            "type": "docker_workspace",
            "visible_files": {"Cargo.toml": "[package]\nname = 'demo'\n", "src/main.rs": "fn main() {}"},
            "test_command": "cargo test",
        }
    )
    applied_env, applied_selection = apply_docker_image_selection(
        {
            "type": "docker_workspace",
            "visible_files": {"Cargo.toml": "[package]\nname = 'demo'\n", "src/main.rs": "fn main() {}"},
            "test_command": "cargo test",
        }
    )
    shell = select_docker_image(
        {
            "type": "docker_workspace",
            "visible_files": {"deploy.sh": "apt-get update && apt-get install -y curl"},
            "test_command": "sh deploy.sh",
        }
    )
    explicit = select_docker_image(
        {
            "type": "docker_workspace",
            "image": "ubuntu:22.04",
            "visible_files": {"package.json": '{"name":"demo"}'},
        }
    )

    assert node.image == "node:22-bookworm-slim"
    assert rust.image == "rust:1.85-slim"
    assert applied_env["image"] == "rust:1.85-slim"
    assert applied_selection.image == "rust:1.85-slim"
    assert shell.image == "ubuntu:22.04"
    assert explicit.image == "ubuntu:22.04"
    assert explicit.explicit is True


def test_environment_claw_selects_missing_docker_image(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.docker_status",
        lambda **kwargs: DockerStatus(available=True, executable="docker", client_version="1", server_version="1"),
    )
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.inspect_docker_image",
        lambda image, **kwargs: DockerImageProbe(image=image, local=False, detail="not present locally"),
    )
    item = BenchmarkItem(
        id="docker_item",
        dimension_id="docker",
        task_type=TaskType.agent,
        prompt="Repair the Node project in the container.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "visible_files": {"package.json": '{"name":"demo"}'},
                "test_command": "npm test",
            }
        },
    )

    _, report = run_environment_claw([item], BenchmarkConfig())
    env = item.metadata["agent_env"]

    assert env["image"] == "node:22-bookworm-slim"
    assert env["image_selection"]["strategy"] == "evalclaw_builtin_rules.v1"
    assert any(action.action.startswith("select docker image node:22-bookworm-slim") for action in report.actions)
    assert any(action.action.startswith("pull docker image node:22-bookworm-slim") for action in report.actions)
    assert any(probe.name == "docker_image" for probe in report.probes)


def test_environment_claw_reports_custom_docker_image_build(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.docker_status",
        lambda **kwargs: DockerStatus(available=True, executable="docker", client_version="1", server_version="1"),
    )
    item = BenchmarkItem(
        id="docker_build_item",
        dimension_id="docker",
        task_type=TaskType.agent,
        prompt="Run a workspace that needs ffmpeg.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "image": "build://auto",
                "image_build": {
                    "base_image": "python:3.11-slim",
                    "system_packages": ["ffmpeg"],
                    "cran_packages": ["ggplot2"],
                    "go_packages": ["golang.org/x/tools/cmd/stringer@latest"],
                    "install_steps": [{"manager": "shell", "command": "echo custom"}],
                    "tag": "evalclaw-ffmpeg:test",
                },
                "visible_files": {"task.py": "print('ok')\n"},
                "test_command": "python task.py",
            }
        },
    )

    _, report = run_environment_claw([item], BenchmarkConfig())
    env = item.metadata["agent_env"]

    assert env["image"] == "build://auto"
    assert env["image_build"]["enabled"] is True
    build_actions = [action for action in report.actions if action.action.startswith("build docker image")]
    assert build_actions
    assert build_actions[0].data["package_fields"]["cran_packages"] == ["ggplot2"]
    assert build_actions[0].data["package_fields"]["go_packages"] == ["golang.org/x/tools/cmd/stringer@latest"]
    assert build_actions[0].data["install_step_count"] == 1
    assert not any(action.action.startswith("pull docker image build://auto") for action in report.actions)


def test_task_builder_requires_role_key_by_default() -> None:
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "agent_blueprint",
        dimension.id,
        "Agent task",
        task_type=TaskType.agent,
        content="One executable agent task.",
        environment_type=AgentEnvironmentType.docker_workspace,
    )

    with pytest.raises(RuntimeError, match="missing task-builder API key"):
        build_task_suite(
            spec,
            [blueprint],
            BenchmarkConfig(use_web_research=False),
        )


def test_task_builder_llm_failure_does_not_silently_fallback(monkeypatch) -> None:
    def fail_tools(*args, **kwargs):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", fail_tools)
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "agent_blueprint",
        dimension.id,
        "Agent task",
        task_type=TaskType.agent,
        content="One executable agent task.",
        environment_type=AgentEnvironmentType.docker_workspace,
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
        ),
    )

    assert suite.tasks == []


def test_task_builder_call_failure_does_not_use_structure_repairs(monkeypatch) -> None:
    calls = 0

    def fail_tools(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise TaskBuilderCallError("model call failed after 2 retry attempts")

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", fail_tools)
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "agent_blueprint",
        dimension.id,
        "Agent task",
        task_type=TaskType.agent,
        content="One executable agent task.",
        environment_type=AgentEnvironmentType.docker_workspace,
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
            task_builder_repair_attempts=5,
        ),
    )

    assert calls == 1
    assert suite.tasks == []


def test_task_builder_calls_llm_once_per_task_design(monkeypatch) -> None:
    payloads: list[dict] = []

    def one_task_call_llm(messages, *args, **kwargs):
        payload = json.loads(messages[0].content)
        payloads.append(payload)
        challenge_effort = payload["task_plan"]["capability"]["challenge_effort"]
        return json.dumps(
            {
                "tasks": [
                    {
                        "id": f"task_{task_index}",
                        "dimension_id": "agent_capability",
                        "challenge_effort": challenge_effort,
                        "title": f"Task {task_index}",
                        "prompt": f"Complete distinct task {task_index}.",
                        "environment": {
                            "type": "docker_workspace",
                            "test_command": "python3 -c \"assert True\"",
                        },
                        "scoring": {"pass_criteria": "Done."},
                        "metadata": {
                            "challenge_effort_self_assessment": {
                                "requested_effort": challenge_effort,
                                "meets_requested_effort": True,
                                "rationale": "The task matches the requested effort.",
                            }
                        },
                    }
                    for task_index in (1, 2)
                ]
            }
        )
    patch_task_builder_model(monkeypatch, one_task_call_llm)
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "agent_blueprint",
        dimension.id,
        "Two related workspace tasks",
        task_type=TaskType.agent,
        count=2,
        content="Move two distinct workspace items in separate tasks.",
        construction_requirements=["Implement both distinct workspace tasks."],
        environment_type=AgentEnvironmentType.docker_workspace,
        metadata={"content_focus": "two workspace items"},
    )

    progress: list[str] = []
    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
            task_builder_max_workers=1,
        ),
        log=progress.append,
    )

    assert [task.id for task in suite.tasks] == [
        "agent_blueprint_task_1",
        "agent_blueprint_task_2",
    ]
    assert len(payloads) == 1
    construction = payloads[0]["task_plan"]["task_design"]
    assert construction["required_return_task_count"] == 2
    assert construction["task_count"] == 2
    assert "Move two distinct workspace items" in construction["content_design"]["description"]
    assert any("starting 1/1" in message for message in progress)
    assert any("completed 1/1" in message for message in progress)


@pytest.mark.parametrize(
    "source_urls",
    [
        ["https://example.com/a"],
        ["https://example.com/a", "https://example.com/b"],
    ],
)
def test_task_builder_repairs_missing_external_source_binding(
    monkeypatch,
    source_urls: list[str],
) -> None:
    calls = 0
    selected_source_id = f"source_{len(source_urls)}"

    def sourced_task_call_llm(*args, **kwargs):
        nonlocal calls
        calls += 1
        task = {
            "id": "sourced_task",
            "dimension_id": "knowledge",
            "task_type": "fill_blank",
            "title": "Source-backed task",
            "prompt": "Answer using the selected external source.",
            "expected_texts": [selected_source_id],
            "scoring": {"pass_criteria": f"The answer is {selected_source_id}."},
            "metadata": {
                "challenge_effort_self_assessment": {
                    "requested_effort": "E3",
                    "meets_requested_effort": True,
                    "rationale": "The task requires grounded source use.",
                }
            },
        }
        if calls > 1:
            task["resource_ids"] = [selected_source_id]
        return json.dumps(
            {
                "resources": [
                    {"id": f"source_{index}", "kind": "web", "uri": url}
                    for index, url in enumerate(source_urls, 1)
                ],
                "tasks": [task],
            }
        )

    patch_task_builder_model(monkeypatch, sourced_task_call_llm)
    monkeypatch.setattr(
        "evalclaw.construction.suite._select_blueprint_sources",
        lambda *args, **kwargs: [],
    )
    dimension = EvalDimension(
        id="knowledge",
        name="Knowledge",
        description="Evaluate source-grounded knowledge.",
        approach="Use one short-answer task.",
        task_types=[TaskType.fill_blank],
    )
    spec = EvalSpec(
        objective="Evaluate grounded knowledge.",
        dimensions=[dimension],
        task_types=[TaskType.fill_blank],
    )
    blueprint = make_blueprint(
        "knowledge_blueprint",
        dimension.id,
        "Source-backed task",
        task_type=TaskType.fill_blank,
        content="Use the cited source.",
        source_plan={
            "strategy": "adapted",
            "suggested_urls": source_urls,
        },
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
            task_builder_max_workers=1,
            task_builder_repair_attempts=1,
        ),
    )

    assert calls == 2
    assert suite.tasks[0].source.uri == source_urls[-1]


def test_task_builder_repairs_external_resources_from_generated_strategy(monkeypatch) -> None:
    calls = 0

    def generated_task_call_llm(*args, **kwargs):
        nonlocal calls
        calls += 1
        task = {
            "task_type": "fill_blank",
            "title": "Generated task",
            "prompt": "Provide the exact answer specified by this generated task.",
            "expected_texts": ["answer"],
            "metadata": {
                "challenge_effort_self_assessment": {
                    "requested_effort": "E3",
                    "meets_requested_effort": True,
                    "rationale": "The task is generated directly from the design.",
                }
            },
        }
        resources = []
        if calls == 1:
            resources = [
                {"id": "unrequested", "kind": "web", "uri": "https://example.com/source"}
            ]
            task["resource_ids"] = ["unrequested"]
        return json.dumps({"resources": resources, "tasks": [task]})

    patch_task_builder_model(monkeypatch, generated_task_call_llm)
    dimension = EvalDimension(
        id="generated",
        name="Generated",
        description="Evaluate generated knowledge.",
        approach="Use one generated task.",
        task_types=[TaskType.fill_blank],
    )
    blueprint = make_blueprint(
        "generated_blueprint",
        dimension.id,
        "Generated task",
        task_type=TaskType.fill_blank,
        source_plan={"strategy": "generated"},
    )

    suite = build_task_suite(
        EvalSpec(
            objective="Evaluate generated knowledge.",
            dimensions=[dimension],
            task_types=[TaskType.fill_blank],
        ),
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            task_builder_max_workers=1,
            task_builder_repair_attempts=1,
        ),
    )

    assert calls == 2
    assert suite.resources == []
    assert suite.tasks[0].source.kind == SourceKind.self_generated


def test_task_builder_preserves_resource_bindings_when_shared_urls_are_deduplicated(
    monkeypatch,
) -> None:
    shared_uri = "https://example.com/shared"

    def sourced_task_call_llm(messages, *args, **kwargs):
        payload = json.loads(messages[0].content)
        blueprint_id = payload["task_plan"]["builder_job_id"]
        dimension_id = payload["task_plan"]["capability"]["id"]
        return json.dumps(
            {
                "resources": [
                    {
                        "id": "shared_source",
                        "kind": "web",
                        "uri": shared_uri,
                        "title": "Shared source",
                    }
                ],
                "tasks": [
                    {
                        "dimension_id": dimension_id,
                        "task_type": "fill_blank",
                        "title": f"Task for {blueprint_id}",
                        "prompt": f"Answer the distinct question for {blueprint_id}.",
                        "expected_texts": [blueprint_id],
                        "resource_ids": ["shared_source"],
                        "scoring": {"pass_criteria": f"The answer is {blueprint_id}."},
                        "metadata": {
                            "challenge_effort_self_assessment": {
                                "requested_effort": "E3",
                                "meets_requested_effort": True,
                                "rationale": "The task requires source-grounded reasoning.",
                            }
                        },
                    }
                ],
            }
        )

    patch_task_builder_model(monkeypatch, sourced_task_call_llm)
    monkeypatch.setattr(
        "evalclaw.construction.suite._select_blueprint_sources",
        lambda *args, **kwargs: [],
    )
    dimensions = [
        EvalDimension(
            id=f"dimension_{index}",
            name=f"Dimension {index}",
            description=f"Evaluate capability {index}.",
            approach="Use one source-grounded question.",
            task_types=[TaskType.fill_blank],
        )
        for index in (1, 2)
    ]
    spec = EvalSpec(
        objective="Evaluate two source-grounded capabilities.",
        dimensions=dimensions,
        task_types=[TaskType.fill_blank],
    )
    blueprints = [
        make_blueprint(
            f"blueprint_{index}",
            dimension.id,
            f"Source-backed task {index}",
            task_type=TaskType.fill_blank,
            content=f"Use the shared source for capability {index}.",
            source_plan={
                "strategy": "adapted",
                "suggested_urls": [shared_uri],
            },
        )
        for index, dimension in enumerate(dimensions, 1)
    ]

    suite = build_task_suite(
        spec,
        blueprints,
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
            task_builder_max_workers=1,
        ),
    )

    assert len(suite.resources) == 1
    canonical_id = suite.resources[0].id
    assert [task.source.uri for task in suite.tasks] == [shared_uri, shared_uri]
    assert [task.source_definition.resource_ids for task in suite.tasks] == [
        [canonical_id],
        [canonical_id],
    ]


def test_task_builder_rejects_overfilled_llm_output(monkeypatch) -> None:
    def overfilled_call_llm(*args, **kwargs):
        return json.dumps(
            {
                "tasks": [
                    {
                        "id": "task_1",
                        "dimension_id": "agent_capability",
                        "title": "One task",
                        "prompt": "Complete the first task.",
                        "scoring": {"pass_criteria": "Done."},
                    },
                    {
                        "id": "task_2",
                        "dimension_id": "agent_capability",
                        "title": "Second task",
                        "prompt": "Complete the second task.",
                        "scoring": {"pass_criteria": "Done."},
                    },
                ]
            }
        )

    patch_task_builder_model(monkeypatch, overfilled_call_llm)
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "agent_blueprint",
        dimension.id,
        "Agent task",
        task_type=TaskType.agent,
        content="One executable agent task.",
        environment_type=AgentEnvironmentType.docker_workspace,
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
        ),
    )

    assert suite.tasks == []


def test_task_builder_uses_challenge_effort(monkeypatch) -> None:
    def call_llm_with_challenge_effort(*args, **kwargs):
        return json.dumps(
            {
                "tasks": [
                    {
                        "id": "task_1",
                        "dimension_id": "agent_capability",
                        "title": "Hard task",
                        "prompt": "Complete a realistic multi-file repair task.",
                        "challenge_effort": "E3",
                        "environment": {
                            "type": "docker_workspace",
                            "test_command": "python3 -c \"assert True\"",
                        },
                        "scoring": {"pass_criteria": "Hidden tests pass."},
                        "metadata": {
                            "challenge_effort_self_assessment": {
                                "requested_effort": "E3",
                                "meets_requested_effort": True,
                                "rationale": "The task uses a realistic repair setup with hidden scoring.",
                                "effort_actions": ["Added nontrivial workspace state and hidden oracle."],
                            }
                        },
                    }
                ]
            }
        )

    patch_task_builder_model(monkeypatch, call_llm_with_challenge_effort)
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
        challenge_effort=ChallengeEffort.E3,
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "agent_blueprint",
        dimension.id,
        "Agent task",
        task_type=TaskType.agent,
        content="One executable agent task.",
        challenge_effort=ChallengeEffort.E3,
        environment_type=AgentEnvironmentType.docker_workspace,
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
        ),
    )

    assert suite.tasks[0].challenge_effort == ChallengeEffort.E3


def test_task_builder_recovers_truncation_in_preserved_conversation(monkeypatch) -> None:
    calls: list[list[dict]] = []

    def truncation_then_complete(messages, *args, **kwargs):
        calls.append(json.loads(json.dumps(messages)))
        if len(calls) <= 2:
            raise LLMOutputTruncatedError(
                "output truncated at 32768 completion tokens",
                partial_output=f"interrupted reasoning {len(calls)}",
            )
        content = json.dumps(
            {
                "tasks": [
                    {
                        "id": "recovered_task",
                        "dimension_id": "agent_capability",
                        "challenge_effort": "E3",
                        "title": "Recovered task",
                        "prompt": "Inspect the workspace and place the brief in the outgoing bin.",
                        "environment": {
                            "type": "docker_workspace",
                            "test_command": "python3 -c \"assert True\"",
                        },
                        "scoring": {"pass_criteria": "The brief is in the outgoing bin."},
                        "metadata": {
                                "challenge_effort_self_assessment": {
                                    "requested_effort": "E3",
                                    "meets_requested_effort": True,
                                    "rationale": "The complete task retains the requested construction effort.",
                                }
                        },
                    }
                ]
            }
        )
        content = save_task_builder_response(json.loads(calls[0][0]["content"]), content)
        return TargetToolModelResponse(
            adapter="openai",
            content=content,
            tool_calls=[],
            assistant_message={"role": "assistant", "content": content},
            raw_response={},
        )

    monkeypatch.setattr(
        "evalclaw.construction.research.call_orchestrator_with_tools",
        truncation_then_complete,
    )
    monkeypatch.setattr(
        "evalclaw.construction.research.summarize_task_builder_truncation",
        lambda error, **kwargs: f"summary: {error.partial_output}",
    )
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
        challenge_effort=ChallengeEffort.E3,
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "agent_blueprint",
        dimension.id,
        "Agent task",
        task_type=TaskType.agent,
        content="One executable agent task.",
        challenge_effort=ChallengeEffort.E3,
        environment_type=AgentEnvironmentType.docker_workspace,
    )
    config = BenchmarkConfig(
        **dummy_config_kwargs(),
        use_web_research=False,
        task_builder_repair_attempts=0,
    )

    suite = build_task_suite(spec, [blueprint], config)

    assert len(suite.tasks) == 1
    assert len(calls) == 3
    assert [message["role"] for message in calls[2]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert calls[2][1]["content"] == "summary: interrupted reasoning 1"
    assert calls[2][3]["content"] == "summary: interrupted reasoning 2"


def test_task_builder_reports_truncation_after_separate_retry_limit(monkeypatch) -> None:
    calls = 0

    def always_truncated(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise LLMOutputTruncatedError("still truncated")

    monkeypatch.setattr(
        "evalclaw.construction.research.call_orchestrator_with_tools",
        always_truncated,
    )
    monkeypatch.setattr(
        "evalclaw.construction.research.summarize_task_builder_truncation",
        lambda error, **kwargs: "interrupted work",
    )
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
        challenge_effort=ChallengeEffort.E3,
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "agent_blueprint",
        dimension.id,
        "Agent task",
        task_type=TaskType.agent,
        content="One executable agent task.",
        challenge_effort=ChallengeEffort.E3,
        environment_type=AgentEnvironmentType.docker_workspace,
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
            task_builder_repair_attempts=2,
        ),
    )

    assert suite.tasks == []
    assert "output truncated after 3 retry attempt" in suite.construction_notes
    assert "structural validation failed" not in suite.construction_notes
    assert calls == 4


def test_task_builder_recovers_missing_final_content_before_structure_repair(monkeypatch) -> None:
    calls: list[dict] = []

    def empty_then_complete(messages, *args, **kwargs):
        calls.append({"content": messages[0].content, "kwargs": kwargs})
        if len(calls) == 1:
            return ""
        return json.dumps(
            {
                "tasks": [
                    {
                        "task_type": "fill_blank",
                        "title": "Recovered task",
                        "prompt": "Provide the exact generated answer for this task.",
                        "expected_texts": ["answer"],
                        "metadata": {
                            "challenge_effort_self_assessment": {
                                "requested_effort": "E3",
                                "meets_requested_effort": True,
                                "rationale": "The task has a deterministic answer.",
                            }
                        },
                    }
                ]
            }
        )

    patch_task_builder_model(monkeypatch, empty_then_complete)
    dimension = EvalDimension(
        id="knowledge",
        name="Knowledge",
        description="Evaluate generated knowledge.",
        approach="Use one exact-answer task.",
        task_types=[TaskType.fill_blank],
    )
    blueprint = make_blueprint(
        "knowledge_blueprint",
        dimension.id,
        "Generated knowledge task",
        task_type=TaskType.fill_blank,
        source_plan={"strategy": "generated"},
    )

    suite = build_task_suite(
        EvalSpec(
            objective="Evaluate generated knowledge.",
            dimensions=[dimension],
            task_types=[TaskType.fill_blank],
        ),
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            task_builder_max_workers=1,
            task_builder_repair_attempts=0,
        ),
    )

    assert len(calls) == 2
    assert calls[1]["content"] == calls[0]["content"]
    assert calls[1]["kwargs"]["reduce_reasoning_effort"] is True
    assert calls[1]["kwargs"].get("expect_json", False) is False
    assert suite.tasks[0].expected_texts == ["answer"]


def test_task_builder_missing_final_content_does_not_use_structure_repairs(monkeypatch) -> None:
    calls = 0

    def always_empty(*args, **kwargs):
        nonlocal calls
        calls += 1
        return ""

    patch_task_builder_model(monkeypatch, always_empty)
    dimension = EvalDimension(
        id="knowledge",
        name="Knowledge",
        description="Evaluate generated knowledge.",
        approach="Use one exact-answer task.",
        task_types=[TaskType.fill_blank],
    )
    blueprint = make_blueprint(
        "knowledge_blueprint",
        dimension.id,
        "Generated knowledge task",
        task_type=TaskType.fill_blank,
        source_plan={"strategy": "generated"},
    )

    suite = build_task_suite(
        EvalSpec(
            objective="Evaluate generated knowledge.",
            dimensions=[dimension],
            task_types=[TaskType.fill_blank],
        ),
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            task_builder_max_workers=1,
            task_builder_repair_attempts=5,
        ),
    )

    assert calls == 2
    assert suite.tasks == []


def test_task_builder_parallelizes_llm_calls_and_preserves_order(monkeypatch) -> None:
    active_calls = 0
    max_active_calls = 0
    lock = threading.Lock()

    def concurrent_task_builder_tools(payload, **kwargs):
        nonlocal active_calls, max_active_calls
        blueprint_id = payload["task_plan"]["builder_job_id"]
        dimension_id = payload["task_plan"]["capability"]["id"]
        challenge_effort = payload["task_plan"]["capability"].get("challenge_effort", "E3")
        with lock:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
        try:
            time.sleep(0.15 if blueprint_id == "first_blueprint" else 0.05)
        finally:
            with lock:
                active_calls -= 1
        response, notes = (
            json.dumps(
                {
                    "tasks": [
                        {
                            "id": f"{blueprint_id}_task",
                            "dimension_id": dimension_id,
                            "challenge_effort": challenge_effort,
                            "title": f"{blueprint_id} task",
                            "prompt": f"Complete the task for {blueprint_id}.",
                            "environment": {
                                "type": "docker_workspace",
                                "test_command": "python3 -c \"assert True\"",
                            },
                            "scoring": {"pass_criteria": "Done."},
                            "metadata": {
                                "challenge_effort_self_assessment": {
                                    "requested_effort": challenge_effort,
                                    "meets_requested_effort": True,
                                    "rationale": "The task matches the requested construction effort for this test.",
                                }
                            },
                        }
                    ]
                }
            ),
            [],
        )
        return save_task_builder_response(payload, response), notes

    monkeypatch.setattr(
        "evalclaw.construction.suite.run_task_builder_tools", concurrent_task_builder_tools
    )
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprints = [
        make_blueprint(
            "first_blueprint",
            dimension.id,
            "First task",
            task_type=TaskType.agent,
            content="First task.",
            environment_type=AgentEnvironmentType.docker_workspace,
        ),
        make_blueprint(
            "second_blueprint",
            dimension.id,
            "Second task",
            task_type=TaskType.agent,
            content="Second task.",
            environment_type=AgentEnvironmentType.docker_workspace,
        ),
    ]

    suite = build_task_suite(
        spec,
        blueprints,
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
            task_builder_max_workers=2,
        ),
    )

    assert max_active_calls >= 2
    assert [task.id for task in suite.tasks] == [
        "first_blueprint_task_1",
        "second_blueprint_task_1",
    ]


def test_parallel_task_builder_failure_abandons_only_failed_job(monkeypatch) -> None:
    slow_started = threading.Event()
    slow_finished = threading.Event()

    def task_builder_tools(payload, **kwargs):
        blueprint_id = payload["task_plan"]["builder_job_id"]
        dimension_id = payload["task_plan"]["capability"]["id"]
        challenge_effort = payload["task_plan"]["capability"].get("challenge_effort", "E3")
        if blueprint_id == "slow_blueprint":
            slow_started.set()
            try:
                time.sleep(0.15)
            finally:
                slow_finished.set()
            response = json.dumps(
                {
                    "tasks": [
                        {
                            "id": "slow_task",
                            "dimension_id": dimension_id,
                            "challenge_effort": challenge_effort,
                            "title": "Slow task",
                            "prompt": "Complete the slow task.",
                            "environment": {
                                "type": "docker_workspace",
                                "test_command": "python3 -c \"assert True\"",
                            },
                            "scoring": {"pass_criteria": "Done."},
                            "metadata": {
                                "challenge_effort_self_assessment": {
                                    "requested_effort": challenge_effort,
                                    "meets_requested_effort": True,
                                    "rationale": "The task matches the requested construction effort.",
                                }
                            },
                        }
                    ]
                }
            )
            return save_task_builder_response(payload, response), []
        assert slow_started.wait(timeout=1)
        raise RuntimeError("builder failed")

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", task_builder_tools)
    dimension = EvalDimension(
        id="agent_capability",
        name="Agent capability",
        description="Evaluate realistic agent task execution.",
        approach="Use executable tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprints = [
        make_blueprint(
            "slow_blueprint",
            dimension.id,
            "Slow task",
            task_type=TaskType.agent,
            content="Slow task.",
            environment_type=AgentEnvironmentType.docker_workspace,
        ),
        make_blueprint(
            "failing_blueprint",
            dimension.id,
            "Failing task",
            task_type=TaskType.agent,
            content="Failing task.",
            environment_type=AgentEnvironmentType.docker_workspace,
        ),
    ]

    suite = build_task_suite(
        spec,
        blueprints,
        BenchmarkConfig(
            **dummy_config_kwargs(),
            task_builder_max_workers=2,
            task_builder_repair_attempts=0,
        ),
    )

    assert slow_finished.is_set()
    assert [task.id for task in suite.tasks] == ["slow_blueprint_task_1"]
    assert "builder failed" in suite.construction_notes


def test_task_builder_repairs_structural_validation_errors(monkeypatch, tmp_path) -> None:
    payloads: list[dict] = []

    def repairable_call_llm(messages, *args, **kwargs):
        payload = json.loads(messages[0].content)
        payloads.append(payload)
        challenge_effort = payload["task_plan"]["capability"].get("challenge_effort", "E3")
        if "repair" not in payload:
            return json.dumps(
                {
                    "tasks": [
                        {
                            "id": "gui_task",
                            "dimension_id": "desktop_agent",
                            "challenge_effort": challenge_effort,
                            "title": "GUI task",
                            "prompt": "Complete the desktop workflow and save the requested artifact.",
                            "environment": {"type": "vm"},
                            "scoring": {"pass_criteria": "The artifact is produced."},
                        }
                    ]
                }
            )
        candidate_path = Path(payload["revision"]["path"])
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["tasks"][0]["environment"] = {
            "type": "vm",
            "session": {
                "application": "spreadsheet",
                "entrypoint": "Desktop/input.xlsx",
            },
            "evaluation": {
                "method": "artifact_check",
                "expected_artifacts": ["Desktop/output.xlsx"],
                "pass_criteria": "Desktop/output.xlsx exists and matches the hidden checks.",
            },
        }
        candidate["tasks"][0]["scoring"] = {
            "method": "deterministic",
            "pass_criteria": "Desktop/output.xlsx exists and matches the hidden checks.",
            "partial_criteria": "The agent creates a related artifact but misses one check.",
            "fail_criteria": "No usable artifact is produced.",
        }
        candidate["tasks"][0]["metadata"] = {
            "challenge_effort_self_assessment": {
                "requested_effort": challenge_effort,
                "meets_requested_effort": True,
                "rationale": "The repaired task is complete enough for the requested effort level.",
            }
        }
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        return '{"status":"saved"}'

    patch_task_builder_model(monkeypatch, repairable_call_llm)
    dimension = EvalDimension(
        id="desktop_agent",
        name="Desktop agent",
        description="Evaluate GUI desktop task execution.",
        approach="Use executable GUI tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate desktop agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "desktop_blueprint",
        dimension.id,
        "Desktop workflow",
        task_type=TaskType.agent,
        content="One desktop workflow.",
        environment_type=AgentEnvironmentType.vm,
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
            task_builder_repair_attempts=1,
            task_builder_debug_dir=str(tmp_path / "builder-debug"),
        ),
    )

    assert len(payloads) == 2
    assert payloads[1]["repair"]["issues"]
    assert suite.tasks[0].metadata["agent_env"]["session"]["application"] == "spreadsheet"
    assert suite.tasks[0].metadata["agent_env"]["evaluation"]["method"] == "artifact_check"
    responses = sorted(tmp_path.glob("builder-debug/**/*.response.txt"))
    diagnostics = sorted(tmp_path.glob("builder-debug/**/*.diagnostics.json"))
    assert len(responses) == 2
    assert len(diagnostics) == 2
    statuses = [json.loads(path.read_text(encoding="utf-8"))["status"] for path in diagnostics]
    assert statuses == ["structural_validation_failed", "accepted"]


def test_task_builder_saves_all_raw_responses_when_repairs_fail(monkeypatch, tmp_path) -> None:
    def incomplete_gui_response(messages, *args, **kwargs):
        payload = json.loads(messages[0].content)
        effort = payload["task_plan"]["capability"].get("challenge_effort", "E3")
        return json.dumps(
            {
                "tasks": [
                    {
                        "id": "unscored_gui_task",
                        "dimension_id": "desktop_agent",
                        "task_type": "agent",
                        "challenge_effort": effort,
                        "title": "Unscored GUI task",
                        "prompt": "Inspect the desktop and repair the requested state.",
                        "environment": {
                            "type": "vm",
                            "session": {
                                "application": "desktop",
                                "start_state": "The desktop is visible.",
                            },
                        },
                        "scoring": {"pass_criteria": "The requested state is repaired."},
                        "metadata": {
                            "challenge_effort_self_assessment": {
                                "requested_effort": effort,
                                "meets_requested_effort": True,
                                "rationale": "The task requires a multi-step desktop repair.",
                            }
                        },
                    }
                ]
            }
        )

    patch_task_builder_model(monkeypatch, incomplete_gui_response)
    dimension = EvalDimension(
        id="desktop_agent",
        name="Desktop agent",
        description="Evaluate GUI desktop task execution.",
        approach="Use executable GUI tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate desktop agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "desktop_blueprint",
        dimension.id,
        "Desktop workflow",
        task_type=TaskType.agent,
        content="One desktop workflow.",
        environment_type=AgentEnvironmentType.vm,
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
            task_builder_repair_attempts=1,
            task_builder_debug_dir=str(tmp_path / "builder-debug"),
        ),
    )

    assert suite.tasks == []
    assert "environment.evaluation" in suite.construction_notes
    assert "structural validation failed after 1 repair attempt" in suite.construction_notes
    assert "output truncated" not in suite.construction_notes
    responses = sorted(tmp_path.glob("builder-debug/**/*.response.txt"))
    diagnostics = sorted(tmp_path.glob("builder-debug/**/*.diagnostics.json"))
    assert len(responses) == 2
    assert len(diagnostics) == 2
    assert all("unscored_gui_task" in path.read_text(encoding="utf-8") for path in responses)
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["status"]
        == "structural_validation_failed"
        for path in diagnostics
    )


def test_task_builder_repairs_non_object_top_level_response(monkeypatch) -> None:
    payloads: list[dict] = []

    def repairable_call_llm(messages, *args, **kwargs):
        payload = json.loads(messages[0].content)
        payloads.append(payload)
        if "repair" not in payload:
            return json.dumps([{"unexpected": "top-level list"}])
        return json.dumps(
            {
                "tasks": [
                    {
                        "id": "repaired_workspace_task",
                        "dimension_id": "tool_use",
                        "challenge_effort": "E2",
                        "title": "Repair response shape",
                        "prompt": "Inspect the workspace and produce the requested result.",
                        "environment": {
                            "type": "docker_workspace",
                            "test_command": "python3 -c \"assert True\"",
                        },
                        "scoring": {
                            "method": "deterministic",
                            "pass_criteria": "The requested result is complete.",
                        },
                        "metadata": {
                            "challenge_effort_self_assessment": {
                                "requested_effort": "E2",
                                "meets_requested_effort": True,
                                "rationale": "The repaired task has a complete state and deterministic oracle.",
                            }
                        },
                    }
                ]
            }
        )

    patch_task_builder_model(monkeypatch, repairable_call_llm)
    dimension = EvalDimension(
        id="tool_use",
        name="Tool use",
        description="Evaluate stateful tool use.",
        approach="Use an executable workspace task.",
        challenge_effort=ChallengeEffort.E2,
    )
    spec = EvalSpec(
        objective="Evaluate tool-using agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "tool_use_blueprint",
        dimension.id,
        "Tool-use workflow",
        task_type=TaskType.agent,
        content="One tool-use workflow.",
        challenge_effort=ChallengeEffort.E2,
        environment_type=AgentEnvironmentType.docker_workspace,
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
            task_builder_repair_attempts=1,
        ),
    )

    assert len(payloads) == 2
    assert payloads[1]["repair"]["issues"] == ["ValueError: expected a JSON object, got list"]
    assert Path(payloads[1]["revision"]["path"]).is_file()
    assert "previous_response" not in payloads[1]["repair"]
    assert suite.tasks[0].id == "tool_use_blueprint_task_1"


def test_task_builder_reports_per_task_normalization_errors_to_repair(monkeypatch) -> None:
    payloads: list[dict] = []

    def task_payload(index: int) -> dict[str, object]:
        return {
            "task_type": "generation",
            "title": f"Proof task {index}",
            "prompt": f"Prove statement {index}.",
            "rubric": "Award credit for a complete proof.",
            "metadata": {
                "challenge_effort_self_assessment": {
                    "requested_effort": "E3",
                    "meets_requested_effort": True,
                    "rationale": "The proof requires the requested reasoning effort.",
                }
            },
        }

    def repairable_call_llm(messages, *args, **kwargs):
        payload = json.loads(messages[0].content)
        payloads.append(payload)
        tasks = [task_payload(1), task_payload(2)]
        if "repair" not in payload:
            tasks[1]["judge_tools"] = [{"name": "python_tests", "config": {}}]
        return json.dumps({"tasks": tasks})

    patch_task_builder_model(monkeypatch, repairable_call_llm)
    dimension = EvalDimension(
        id="proof",
        name="Proof",
        description="Evaluate mathematical proof construction.",
        approach="Use two proof tasks.",
        task_types=[TaskType.generation],
    )
    blueprint = make_blueprint(
        "proof_blueprint",
        dimension.id,
        "Proof tasks",
        task_type=TaskType.generation,
        count=2,
    )

    suite = build_task_suite(
        EvalSpec(
            objective="Evaluate mathematical proofs.",
            dimensions=[dimension],
            task_types=[TaskType.generation],
        ),
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            task_builder_max_workers=1,
            task_builder_repair_attempts=1,
        ),
    )

    assert len(suite.tasks) == 2
    issues = payloads[1]["repair"]["issues"]
    assert any("task #2 could not be normalized" in issue for issue in issues)
    assert any("judge_tools.0.tool" in issue for issue in issues)
    assert any("produced 1 usable task(s)" in issue for issue in issues)


def test_agent_task_content_summary_is_persisted_for_reports() -> None:
    config = BenchmarkConfig(use_web_research=False)
    dimension = EvalDimension(
        id="code_repair",
        name="Code repair",
        description="Evaluate iterative code repair.",
        approach="Use hidden tests.",
    )
    spec = EvalSpec(
        objective="Evaluate code repair agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    task = TaskDefinition(
        id="code_repair_task_1",
        dimension_id=dimension.id,
        task_type=TaskType.agent,
        title="Repair parsing bug",
        content_summary="CSV parser edge case",
        description="Fix a parser bug and pass hidden tests.",
        prompt="Fix parser.py and run tests until they pass.",
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.docker_workspace,
            visible_files={"parser.py": "def parse(x):\n    return x\n"},
            hidden_files={"tests.py": "assert True\n"},
            test_command="python3 tests.py",
        ),
        scoring=TaskScoringSpec(
            method="deterministic",
            pass_criteria="Hidden tests pass.",
            partial_criteria="Meaningful repair attempt.",
            fail_criteria="No useful change.",
        ),
    )
    item = pack_task_item(task, dimension, resource_by_id={})

    assert item.metadata[TASK_CONTENT_SUMMARY_METADATA_KEY] == "CSV Parser Edge Case"
    assert item.metadata["agent_task_package"]["capability_target"]["content_summary"] == "CSV Parser Edge Case"
    assert item.source.kind == SourceKind.self_generated
    assert item.source.uri == ""


def test_agent_task_structure_validation_flags_truncated_prompt() -> None:
    task = TaskDefinition(
        id="gui_task_1",
        dimension_id="industrial_gui",
        task_type=TaskType.agent,
        title="Industrial GUI task",
        description="Use desktop applications to produce artifacts.",
        prompt=(
            "Use the VM desktop software stack to inspect the provided project files, operate the required "
            "applications, produce the requested intermediate artifacts, save the final deliverables, and then "
            "run the bridge evaluation. The design-change propagation requirement must be carried"
        ),
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.vm,
            requires_vm=True,
            vm={"image": "evalclaw-gui"},
            session={"application": "desktop", "expected_artifacts": ["Desktop/out.txt"]},
            evaluation={"method": "hidden_script", "pass_criteria": "Artifact exists."},
        ),
        scoring=TaskScoringSpec(
            method="deterministic",
            pass_criteria="Artifact exists.",
            partial_criteria="Partial artifact exists.",
            fail_criteria="No artifact.",
        ),
    )

    issues = task_structure_issues(task)

    assert any("prompt appears truncated" in issue.lower() for issue in issues)


def test_task_structure_validation_allows_short_final_domain_symbol() -> None:
    task = TaskDefinition(
        id="space_group_mcq",
        dimension_id="crystallography",
        task_type=TaskType.choice,
        title="Identify a space group",
        description="Choose the space group consistent with the absences.",
        prompt=(
            "A crystal has C-centering and systematic absences 00l with l=2n. Which space group "
            "is consistent with these observations?\n\nA) C2\nB) C21\nC) P21\nD) Cc"
        ),
        choices=[
            {"id": "A", "text": "C2"},
            {"id": "B", "text": "C21"},
            {"id": "C", "text": "P21"},
            {"id": "D", "text": "Cc"},
        ],
        correct_choice_ids=["B"],
        scoring=TaskScoringSpec(method="exact_match", pass_criteria="Answer B."),
    )

    issues = task_structure_issues(task)

    assert not any("prompt appears truncated" in issue.lower() for issue in issues)


def test_agent_environment_rejects_removed_tools_field() -> None:
    with pytest.raises(ValueError, match="tools"):
        AgentEnvironmentSpec.model_validate(
            {
                "type": "docker_workspace",
                "tools": [{"name": "read_file"}],
            }
        )


def test_compact_agent_task_package_marks_clipped_visible_instructions() -> None:
    package = {
        "schema_version": "evalclaw.agent_task_package.v1",
        "visible_inputs": {
            "instructions": "Use the VM workflow. " + ("Record application handoffs and artifacts. " * 80),
            "files": {"brief.md": "content"},
        },
    }

    compact = compact_agent_task_package(package)
    instructions = compact["visible_inputs"]["instructions"]

    assert "QC summary clipped here" in instructions
    assert "canonical metadata.agent_task_package contains the full field" in instructions


def test_report_source_backed_ignores_generated_agent_fixture_provenance() -> None:
    item = BenchmarkItem(
        id="generated_agent_task",
        dimension_id="code_repair",
        task_type=TaskType.agent,
        prompt="Fix the generated fixture.",
        source=BenchmarkSource(kind=SourceKind.imported, uri="generated_agent_task", title="Generated task"),
        metadata={
            "agent_task_package": {
                "resource_provenance": {
                    "source_kind": "generated_fixture",
                    "source_uris": [],
                }
            }
        },
    )

    assert _report_is_source_backed(item) is False


def test_qc_rejects_complex_gui_item_without_task_package() -> None:
    item = BenchmarkItem(
        id="gui_missing_package",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Use the desktop app to create an artifact.",
        rubric="Score by bridge artifact checks.",
        metadata={
            "task_agent": {
                "schema_version": "evalclaw.task_agent.v1",
                "system_prompt": "You are the target agent.",
                "scoring": {"method": "deterministic", "instructions": "Use bridge checks."},
            },
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "evalclaw-gui"},
                "session": {"application": "file_manager", "expected_artifacts": ["Desktop/out.txt"]},
                "evaluation": {"method": "artifact_check", "pass_criteria": "Desktop/out.txt exists"},
            },
        },
    )
    spec = EvalSpec(
        objective="Evaluate GUI desktop agents.",
        dimensions=[
            EvalDimension(
                id="vm",
                name="GUI",
                description="GUI task",
                approach="Use a GUI desktop bridge with artifact scoring.",
            )
        ],
        task_types=[TaskType.agent],
    )
    suite = TaskSuite(
        spec=spec,
        objective=spec.objective,
        tasks=[item],
        resources=[],
    )

    qc = run_qc_gate(suite, BenchmarkConfig())

    assert item.id in qc.rejected_item_ids
    assert any("metadata.agent_task_package" in issue.message for issue in qc.issues)


def test_agent_dataset_repairs_invalid_builder_task_package() -> None:
    dimension = EvalDimension(
        id="vm",
        name="GUI",
        description="Evaluate GUI desktop task execution.",
        approach="Use a VM-backed GUI task.",
    )
    spec = EvalSpec(
        objective="Evaluate GUI desktop agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "gui_blueprint",
        dimension.id,
        "GUI task",
        task_type=TaskType.agent,
        content="One GUI task.",
        environment_type=AgentEnvironmentType.vm,
    )
    task = TaskDefinition(
        id="gui_blueprint_task_1",
        dimension_id=dimension.id,
        task_type=TaskType.agent,
        title="GUI task",
        description="Complete the requested file operation in the desktop environment.",
        prompt="Use the file manager to create Desktop/out.txt.",
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.vm,
            requires_vm=True,
            vm={"image": "evalclaw-gui"},
            session={"application": "file_manager", "expected_artifacts": ["Desktop/out.txt"]},
            evaluation={"method": "artifact_check", "pass_criteria": "Desktop/out.txt exists"},
        ),
        scoring=TaskScoringSpec(
            method="artifact_check",
            pass_criteria="Desktop/out.txt exists",
        ),
        metadata={
            "builder_job_id": blueprint.id,
            "task_design_id": blueprint.task_designs[0].id,
            "agent_task_package": {"schema_version": "broken"},
        },
    )
    item = pack_task_item(task, dimension, resource_by_id={})

    package = item.metadata["agent_task_package"]

    assert package["schema_version"] == "evalclaw.agent_task_package.v1"
    assert package["visible_inputs"]["instructions"]
    assert package["output_contract"]["required_outputs"]


def test_build_agent_environment_injects_gui_bridge_runtime_config(monkeypatch) -> None:
    captured: dict = {}
    fake_env = object()

    def fake_from_config(config: dict) -> object:
        captured.update(config)
        return fake_env

    monkeypatch.setattr(
        "evalclaw.execution.agent_envs.DesktopBridgeAgentEnvironment.from_config",
        fake_from_config,
    )
    item = BenchmarkItem(
        id="gui_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Operate the GUI.",
        metadata={
            "agent_env": {
                "type": "vm",
                "session": {"application": "browser"},
                "evaluation": {"method": "bridge_state_check"},
            }
        },
    )

    env = build_agent_environment(
        item,
        BenchmarkConfig(
            gui_bridge_url="http://127.0.0.1:7766",
            gui_bridge_api_key="token",
            gui_bridge_timeout_s=12,
        ),
    )

    assert env is fake_env
    assert captured["bridge_url"] == "http://127.0.0.1:7766"
    assert captured["bridge_api_key"] == "token"
    assert captured["timeout"] == 12
    assert captured["session"] == {"application": "browser"}
    assert captured["evaluation"] == {"method": "bridge_state_check"}


def test_build_agent_environment_injects_vm_provider_runtime_config(monkeypatch) -> None:
    captured: dict = {}
    fake_env = object()

    def fake_from_config(config: dict) -> object:
        captured.update(config)
        return fake_env

    monkeypatch.setattr(
        "evalclaw.execution.agent_envs.DesktopBridgeAgentEnvironment.from_config",
        fake_from_config,
    )
    item = BenchmarkItem(
        id="gui_vm_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Operate the VM GUI.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "evalclaw-gui"},
                "session": {
                    "application": "browser",
                    "baseline_checks": [
                        {"method": "command", "command": "exit 0", "expected_exit_code": 0}
                    ],
                },
                "evaluation": {"method": "bridge_state_check"},
            }
        },
    )

    env = build_agent_environment(
        item,
        BenchmarkConfig(
            gui_bridge_url="http://shared-bridge:7766",
            vm_provider_url="http://127.0.0.1:7788",
            vm_provider_api_key="vm-token",
            vm_provider_timeout_s=44,
            vm_provider_destroy_on_cleanup=False,
        ),
    )

    assert env is fake_env
    assert captured["bridge_url"] == ""
    assert captured["vm_provider_url"] == "http://127.0.0.1:7788"
    assert captured["vm_provider_api_key"] == "vm-token"
    assert captured["vm_provider_timeout"] == 44
    assert captured["destroy_vm_on_cleanup"] is False
    assert captured["vm"] == {"image": "evalclaw-gui"}


def test_build_agent_environment_defaults_vm_provider_to_local_auto(monkeypatch) -> None:
    captured: dict = {}
    fake_env = object()

    def fake_from_config(config: dict) -> object:
        captured.update(config)
        return fake_env

    monkeypatch.setattr(
        "evalclaw.execution.agent_envs.DesktopBridgeAgentEnvironment.from_config",
        fake_from_config,
    )
    item = BenchmarkItem(
        id="gui_vm_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Operate the VM GUI.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "evalclaw-gui"},
                "session": {"application": "file_manager"},
                "evaluation": {"method": "artifact_check"},
            }
        },
    )

    env = build_agent_environment(item, BenchmarkConfig())

    assert env is fake_env
    assert captured["bridge_url"] == ""
    assert captured["vm_provider_url"] == "local://auto"


def test_environment_claw_blocks_missing_gui_bridge(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.probe_desktop_bridge",
        lambda *args, **kwargs: DesktopBridgeStatus(False, detail="bridge missing"),
    )
    item = BenchmarkItem(
        id="gui_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Operate the GUI.",
        metadata={
            "agent_env": {
                "type": "vm",
                "session": {"application": "browser"},
                "evaluation": {"method": "bridge_state_check"},
            }
        },
    )

    _, report = run_environment_claw([item], BenchmarkConfig())

    assert any(probe.name == "gui_bridge" and not probe.ok for probe in report.probes)
    assert report.blocking_errors


def test_environment_claw_blocks_missing_vm_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.probe_vm_provider",
        lambda *args, **kwargs: VmProviderStatus(False, detail="vm provider missing"),
    )
    item = BenchmarkItem(
        id="gui_vm_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Operate the VM GUI.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "evalclaw-gui"},
                "session": {"application": "browser"},
                "evaluation": {"method": "bridge_state_check"},
            }
        },
    )

    _, report = run_environment_claw([item], BenchmarkConfig())

    assert any(probe.name == "vm_provider" and not probe.ok for probe in report.probes)
    assert not any(probe.name == "gui_bridge" for probe in report.probes)
    assert report.blocking_errors
    assert report.blocked_item_ids == ["gui_vm_item"]


def test_environment_claw_blocks_only_the_items_whose_environment_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.probe_vm_provider",
        lambda *args, **kwargs: VmProviderStatus(False, detail="vm provider missing"),
    )
    vm_item = BenchmarkItem(
        id="gui_vm_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Operate the VM GUI.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "evalclaw-gui"},
                "session": {"application": "browser"},
                "evaluation": {"method": "bridge_state_check"},
            }
        },
    )
    plain_item = BenchmarkItem(
        id="plain_item",
        dimension_id="core",
        task_type=TaskType.choice,
        prompt="Choose A.",
        choices=[{"id": "A", "text": "A"}, {"id": "B", "text": "B"}],
        correct_choice_ids=["A"],
    )

    _, report = run_environment_claw([vm_item, plain_item], BenchmarkConfig())

    assert report.blocking_errors
    assert report.blocked_item_ids == ["gui_vm_item"]


def test_environment_claw_defaults_vm_provider_probe_to_local_auto(monkeypatch) -> None:
    captured: dict = {}

    def fake_probe(provider_url, **kwargs):
        captured["provider_url"] = provider_url
        return VmProviderStatus(False, provider_url=str(provider_url), detail="missing local backend")

    monkeypatch.setattr("evalclaw.execution.environment_claw.probe_vm_provider", fake_probe)
    item = BenchmarkItem(
        id="gui_vm_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Operate the VM GUI.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "evalclaw-gui"},
                "session": {"application": "browser"},
                "evaluation": {"method": "bridge_state_check"},
            }
        },
    )

    _, report = run_environment_claw([item], BenchmarkConfig())

    assert captured["provider_url"] == "local://auto"
    assert any(probe.name == "vm_provider" and probe.data["provider_url"] == "local://auto" for probe in report.probes)


def test_environment_claw_accepts_available_vm_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.probe_vm_provider",
        lambda *args, **kwargs: VmProviderStatus(
            True,
            provider_url="http://127.0.0.1:7788",
            detail="ok",
            data={"provider": "fake"},
        ),
    )
    item = BenchmarkItem(
        id="gui_vm_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Operate the VM GUI.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "evalclaw-gui"},
                "session": {
                    "application": "browser",
                    "baseline_checks": [
                        {"method": "command", "command": "exit 0", "expected_exit_code": 0}
                    ],
                },
                "evaluation": {"method": "bridge_state_check"},
            }
        },
    )

    _, report = run_environment_claw([item], BenchmarkConfig(vm_provider_url="http://127.0.0.1:7788"))

    assert any(probe.name == "vm_provider" and probe.ok for probe in report.probes)
    assert report.blocking_errors == []


def test_environment_claw_accepts_available_gui_bridge(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.probe_desktop_bridge",
        lambda *args, **kwargs: DesktopBridgeStatus(
            True,
            bridge_url="http://127.0.0.1:7766",
            detail="ok",
            data={"bridge": "fake"},
        ),
    )
    item = BenchmarkItem(
        id="gui_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Operate the GUI.",
        metadata={
            "agent_env": {
                "type": "vm",
                "session": {"application": "browser"},
                "evaluation": {"method": "bridge_state_check"},
            }
        },
    )

    _, report = run_environment_claw([item], BenchmarkConfig(gui_bridge_url="http://127.0.0.1:7766"))

    assert any(probe.name == "gui_bridge" and probe.ok for probe in report.probes)
    assert report.blocking_errors == []


def test_desktop_bridge_creates_and_cleans_vm_session(monkeypatch) -> None:
    created: dict = {}
    destroyed: list[tuple[str, str]] = []
    requests: list[tuple[str, str, dict | None]] = []

    def fake_create_vm_session(provider_url, **kwargs):
        created["provider_url"] = provider_url
        created.update(kwargs)
        return VmSession(vm_id="vm-1", bridge_url="http://vm-bridge:7766", bridge_api_key="bridge-token")

    def fake_destroy_vm_session(provider_url, vm_id, **kwargs):
        destroyed.append((provider_url, vm_id))

    class FakeResponse:
        content = b"{}"

        def __init__(self, payload: dict):
            self.payload = payload
            self.content = json.dumps(payload).encode()

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, *, base_url, timeout, headers, trust_env=True):
            self.base_url = base_url
            self.timeout = timeout
            self.headers = headers
            self.trust_env = trust_env

        def request(self, method, path, json=None):
            requests.append((method, path, json))
            if method == "GET" and path == "/health":
                return FakeResponse({"observation": "ready"})
            if method == "POST" and path == "/sessions":
                return FakeResponse({"session_id": "session-1", "observation": "started"})
            if method == "POST" and path.endswith("/evaluate"):
                return FakeResponse({"score": 1.0, "done": True})
            return FakeResponse({"observation": "ok"})

        def delete(self, path):
            requests.append(("DELETE", path, None))
            return FakeResponse({})

        def close(self):
            return None

    monkeypatch.setattr("evalclaw.execution.desktop_agent_env.create_vm_session", fake_create_vm_session)
    monkeypatch.setattr("evalclaw.execution.desktop_agent_env.destroy_vm_session", fake_destroy_vm_session)
    monkeypatch.setattr("evalclaw.execution.desktop_agent_env.httpx.Client", FakeClient)

    env = DesktopBridgeAgentEnvironment.from_config(
        {
            "type": "vm",
            "requires_vm": True,
            "vm_provider_url": "http://vm-provider:7788",
            "vm_provider_api_key": "vm-token",
            "vm_provider_timeout": 55,
            "vm": {"image": "evalclaw-gui"},
            "session": {"application": "browser"},
            "evaluation": {"method": "bridge_state_check"},
            "max_steps": 3,
            "timeout": 7,
        }
    )
    outcome = env.step({"action": "evaluate", "args": {}})
    env.cleanup()

    assert created["provider_url"] == "http://vm-provider:7788"
    assert created["api_key"] == "vm-token"
    assert created["vm_spec"] == {"image": "evalclaw-gui"}
    assert created["session_spec"] == {"application": "browser"}
    assert created["timeout"] == 55
    assert env.vm_id == "vm-1"
    assert env.bridge_url == "http://vm-bridge:7766"
    assert outcome.done is True
    assert destroyed == [("http://vm-provider:7788", "vm-1")]
    assert ("POST", "/sessions", {"session": {"application": "browser", "vm": {"image": "evalclaw-gui"}, "vm_id": "vm-1", "requires_vm": True}}) in requests


def test_desktop_bridge_fails_closed_when_baseline_is_not_confirmed(monkeypatch) -> None:
    deleted: list[str] = []

    class FakeResponse:
        content = b"{}"

        def __init__(self, payload: dict):
            self.payload = payload
            self.content = json.dumps(payload).encode()

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def request(self, method, path, json=None):
            if method == "POST" and path == "/sessions":
                return FakeResponse(
                    {
                        "session_id": "session-unverified",
                        "baseline_results": [
                            {
                                "id": "fixture_ready",
                                "passed": False,
                                "result": {"exit_code": 1, "stderr": "fixture is missing"},
                            }
                        ],
                    }
                )
            return FakeResponse({"status": "ok"})

        def delete(self, path):
            deleted.append(path)
            return FakeResponse({})

        def close(self):
            return None

    monkeypatch.setattr("evalclaw.execution.desktop_agent_env.httpx.Client", FakeClient)

    with pytest.raises(RuntimeError, match="fixture_ready: fixture is missing"):
        DesktopBridgeAgentEnvironment(
            bridge_url="http://127.0.0.1:7766",
            bridge_api_key=None,
            session_config={
                "application": "desktop",
                "baseline_checks": [{"method": "file_exists", "path": "/opt/evalclaw/vm-materialized"}],
            },
            evaluation_config={},
        )

    assert deleted == ["/sessions/session-unverified"]


def test_probe_vm_provider_uses_local_auto_when_no_url(monkeypatch) -> None:
    monkeypatch.setattr("evalclaw.execution.vm_provider._virtualbox_executable", lambda: "VBoxManage")
    monkeypatch.setattr("evalclaw.execution.vm_provider._run_command", lambda *args, **kwargs: (True, "7.0.0"))

    status = probe_vm_provider(None)

    assert status.available is True
    assert status.provider_url == "local://virtualbox"
    assert status.data["local_backend"] == "virtualbox"


def test_probe_local_vm_backend_accepts_qemu_when_tools_exist(monkeypatch) -> None:
    monkeypatch.setattr("evalclaw.execution.vm_provider._qemu_executable", lambda: "qemu-system-x86_64")
    monkeypatch.setattr("evalclaw.execution.vm_provider._qemu_img_executable", lambda: "qemu-img")

    status = probe_local_vm_backend("local://qemu")

    assert status.available is True
    assert status.backend == "qemu"
    assert status.executable == "qemu-system-x86_64"
    assert status.data["provider_url"] == "local://qemu"
    assert status.data["qemu_img"] == "qemu-img"


def test_vm_provider_disables_proxy_env_for_local_urls() -> None:
    assert trust_env_for_url("http://127.0.0.1:7766") is False
    assert trust_env_for_url("http://localhost:7766") is False
    assert trust_env_for_url("http://[::1]:7766") is False
    assert trust_env_for_url("http://vm-provider.internal:7788") is True


def test_create_local_vm_session_virtualbox(monkeypatch, tmp_path) -> None:
    commands: list[list[str]] = []
    seed_iso = tmp_path / "windows-config-drive.iso"
    seed_iso.write_bytes(b"seed")

    def fake_run_command(command, *, timeout=30):
        commands.append(command)
        return True, "ok"

    monkeypatch.setattr("evalclaw.execution.vm_provider._virtualbox_executable", lambda: "VBoxManage")
    monkeypatch.setattr("evalclaw.execution.vm_provider._run_command", fake_run_command)
    monkeypatch.setattr("evalclaw.execution.vm_provider._free_local_port", lambda: 18766)
    monkeypatch.setattr("evalclaw.execution.vm_provider._wait_for_bridge", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr("evalclaw.execution.vm_provider.uuid.uuid4", lambda: types.SimpleNamespace(hex="abcdef123456"))

    session = create_local_vm_session(
        "local://virtualbox",
        vm_spec={
            "image": "evalclaw-gui-ubuntu-22.04",
            "snapshot": "clean",
            "seed_iso": str(seed_iso),
            "bridge": {"guest_port": 7766},
        },
        session_spec={"application": "file_manager"},
        timeout=12,
    )

    assert session.vm_id == "evalclaw-evalclaw-gui-ubuntu-22.04-abcdef12"
    assert session.bridge_url == "http://127.0.0.1:18766"
    assert session.data["provider_url"] == "local://virtualbox"
    assert commands[0] == ["VBoxManage", "--version"]
    assert commands[1] == [
        "VBoxManage",
        "clonevm",
        "evalclaw-gui-ubuntu-22.04",
        "--snapshot",
        "clean",
        "--name",
        "evalclaw-evalclaw-gui-ubuntu-22.04-abcdef12",
        "--register",
        "--mode",
        "machine",
    ]
    assert [
        "VBoxManage",
        "storagectl",
        "evalclaw-evalclaw-gui-ubuntu-22.04-abcdef12",
        "--name",
        "EvalClawConfigDrive",
        "--add",
        "sata",
        "--controller",
        "IntelAhci",
    ] in commands
    assert [
        "VBoxManage",
        "storageattach",
        "evalclaw-evalclaw-gui-ubuntu-22.04-abcdef12",
        "--storagectl",
        "EvalClawConfigDrive",
        "--port",
        "0",
        "--device",
        "0",
        "--type",
        "dvddrive",
        "--medium",
        str(seed_iso.resolve()),
    ] in commands
    assert [
        "VBoxManage",
        "modifyvm",
        "evalclaw-evalclaw-gui-ubuntu-22.04-abcdef12",
        "--natpf1",
        "evalclaw-bridge,tcp,127.0.0.1,18766,,7766",
    ] in commands
    assert ["VBoxManage", "startvm", "evalclaw-evalclaw-gui-ubuntu-22.04-abcdef12", "--type", "headless"] in commands


def test_create_local_vm_session_reuses_existing_virtualbox_sata_controller(monkeypatch, tmp_path) -> None:
    commands: list[list[str]] = []
    seed_iso = tmp_path / "windows-config-drive.iso"
    seed_iso.write_bytes(b"seed")

    def fake_run_command(command, *, timeout=30):
        commands.append(command)
        if command[1:3] == ["showvminfo", "evalclaw-windows-template-abcdef12"]:
            return True, "\n".join(
                [
                    'storagecontrollername0="SATA Controller"',
                    'storagecontrollertype0="IntelAhci"',
                    'storagecontrollerportcount0="30"',
                    '"SATA Controller-0-0"="base.vdi"',
                    '"SATA Controller-1-0"="installer.iso"',
                    '"SATA Controller-2-0"="none"',
                ]
            )
        return True, "ok"

    monkeypatch.setattr("evalclaw.execution.vm_provider._virtualbox_executable", lambda: "VBoxManage")
    monkeypatch.setattr("evalclaw.execution.vm_provider._run_command", fake_run_command)
    monkeypatch.setattr("evalclaw.execution.vm_provider._free_local_port", lambda: 18766)
    monkeypatch.setattr("evalclaw.execution.vm_provider._wait_for_bridge", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr("evalclaw.execution.vm_provider.uuid.uuid4", lambda: types.SimpleNamespace(hex="abcdef123456"))

    create_local_vm_session(
        "local://virtualbox",
        vm_spec={"image": "windows-template", "seed_iso": str(seed_iso)},
        timeout=12,
    )

    assert not any(command[1:2] == ["storagectl"] for command in commands)
    assert [
        "VBoxManage",
        "storageattach",
        "evalclaw-windows-template-abcdef12",
        "--storagectl",
        "SATA Controller",
        "--port",
        "2",
        "--device",
        "0",
        "--type",
        "dvddrive",
        "--medium",
        str(seed_iso.resolve()),
    ] in commands


def test_virtualbox_bridge_wait_resets_only_after_explicit_restart_signal(monkeypatch) -> None:
    bridge_results = iter([(False, "pending"), (False, "pending"), (True, "ready")])
    commands: list[list[str]] = []

    monkeypatch.setattr(
        "evalclaw.execution.vm_provider._wait_for_bridge",
        lambda *args, **kwargs: next(bridge_results),
    )
    monkeypatch.setattr(
        "evalclaw.execution.vm_provider._virtualbox_restart_requested",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "evalclaw.execution.vm_provider._run_command",
        lambda command, **kwargs: (commands.append(command) is None, "ok"),
    )

    ok, detail = _wait_for_virtualbox_bridge(
        "VBoxManage",
        "vm-1",
        "http://127.0.0.1:7766",
        timeout=30,
        restart_grace=0,
    )

    assert ok is True
    assert detail == "ready"
    assert commands == [["VBoxManage", "controlvm", "vm-1", "reset"]]


def test_create_local_vm_session_qemu_uses_overlay_and_port_forward(monkeypatch, tmp_path) -> None:
    commands: list[list[str]] = []
    processes: list[object] = []
    disk_image = tmp_path / "base.qcow2"
    disk_image.write_bytes(b"base")
    seed_iso = tmp_path / "seed.iso"
    seed_iso.write_bytes(b"seed")

    class FakeProcess:
        def __init__(self, command, stdout=None, stderr=None):
            self.command = command
            self.stdout = stdout
            self.stderr = stderr
            self.terminated = False
            self.killed = False
            self.waited = False
            self._poll = None
            processes.append(self)

        def poll(self):
            return self._poll

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            self._poll = 0
            return 0

        def kill(self):
            self.killed = True
            self._poll = -9

    def fake_run_command(command, *, timeout=30):
        commands.append(command)
        if command[:4] == ["qemu-img", "create", "-f", "qcow2"]:
            tmp_path.joinpath("runtime").mkdir(exist_ok=True)
            Path(command[-1]).write_bytes(b"overlay")
        return True, "ok"

    monkeypatch.setattr("evalclaw.execution.vm_provider._qemu_executable", lambda: "qemu-system-x86_64")
    monkeypatch.setattr("evalclaw.execution.vm_provider._qemu_img_executable", lambda: "qemu-img")
    monkeypatch.setattr("evalclaw.execution.vm_provider._run_command", fake_run_command)
    monkeypatch.setattr("evalclaw.execution.vm_provider.subprocess.Popen", FakeProcess)
    monkeypatch.setattr("evalclaw.execution.vm_provider._free_local_port", lambda: 18767)
    monkeypatch.setattr("evalclaw.execution.vm_provider._wait_for_bridge", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr("evalclaw.execution.vm_provider.uuid.uuid4", lambda: types.SimpleNamespace(hex="feedface1234"))
    monkeypatch.setenv("EVALCLAW_VM_WORK_DIR", str(tmp_path / "runtime"))

    session = create_local_vm_session(
        "local://qemu",
        vm_spec={
            "disk_image": str(disk_image),
            "seed_iso": str(seed_iso),
            "bridge": {"guest_port": 7766},
            "memory_mb": 1024,
            "cpus": 1,
        },
        session_spec={"application": "file_manager"},
        timeout=12,
    )

    assert session.vm_id == "evalclaw-qemu-base-feedface"
    assert session.bridge_url == "http://127.0.0.1:18767"
    assert session.data["provider_url"] == "local://qemu"
    assert commands[0][:6] == ["qemu-img", "create", "-f", "qcow2", "-F", "qcow2"]
    process = processes[0]
    assert "-nic" in process.command
    assert "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:18767-:7766" in process.command
    assert f"file={tmp_path / 'runtime' / 'evalclaw-qemu-base-feedface.qcow2'},if=virtio,format=qcow2,cache=writethrough" in process.command
    assert f"file={seed_iso.resolve()},if=ide,media=cdrom,readonly=on" in process.command

    overlay_path = tmp_path / "runtime" / "evalclaw-qemu-base-feedface.qcow2"
    assert overlay_path.exists()
    destroy_local_vm_session("local://qemu", session.vm_id)

    assert process.terminated is True
    assert process.waited is True
    assert process.killed is False
    assert not overlay_path.exists()


def test_agent_action_parser_accepts_gui_actions() -> None:
    action, error = _parse_agent_action('{"action":"click","args":{"x":10,"y":20}}')
    assert error is None
    assert action == {"action": "click", "args": {"x": 10, "y": 20}}

    action, error = _parse_agent_action("key ctrl+s")
    assert error is None
    assert action == {"action": "key", "args": {"keys": ["ctrl", "s"]}}

    action, error = _parse_agent_action("click 100,200")
    assert error is None
    assert action == {"action": "click", "args": {"x": 100.0, "y": 200.0}}


def test_environment_claw_can_be_disabled(monkeypatch) -> None:
    def fail_probe(*args, **kwargs):
        raise AssertionError("environment claw should not probe when disabled")

    monkeypatch.setattr("evalclaw.execution.environment_claw.docker_status", fail_probe)
    item = BenchmarkItem(
        id="docker_agent",
        dimension_id="code",
        task_type=TaskType.agent,
        prompt="Fix the repository.",
        metadata={"agent_env": {"type": "docker_workspace"}},
    )

    updated, report = run_environment_claw([item], BenchmarkConfig(environment_claw=False))

    assert updated.environment_claw is False
    assert report.enabled is False


def test_large_scale_llm_qc_uses_stratified_sample(monkeypatch) -> None:
    captured_payload = {}

    def fake_call_llm(messages, **kwargs):
        captured_payload.update(json.loads(messages[0].content))
        return json.dumps({"issues": []})

    monkeypatch.setattr("evalclaw.quality.llm_checks.call_llm", fake_call_llm)
    dim_a = EvalDimension(id="a", name="A", description="A", approach="A")
    dim_b = EvalDimension(id="b", name="B", description="B", approach="B")
    spec = EvalSpec(objective="Large eval", dimensions=[dim_a, dim_b], scale_budget=ScaleBudget.large)
    items = [
        BenchmarkItem(
            id=f"a_{index}",
            dimension_id="a",
            task_type=TaskType.choice,
            prompt=f"Choose the correct robust answer for A case {index}.",
            choices=[{"id": "A", "text": "correct"}, {"id": "B", "text": "wrong"}],
            correct_choice_ids=["A"],
        )
        for index in range(30)
    ] + [
        BenchmarkItem(
            id=f"b_{index}",
            dimension_id="b",
            task_type=TaskType.generation,
            prompt=f"Explain the robust answer for B case {index}.",
            rubric="Score correctness.",
        )
        for index in range(30)
    ]

    suite = TaskSuite(
        spec=spec,
        objective=spec.objective,
        tasks=items,
    )
    run_qc_gate(
        suite,
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_llm_qc=True,
            scale_budget=ScaleBudget.large,
            large_scale_llm_qc_sample_size=10,
        ),
    )

    assert captured_payload["llm_qc_sampling"]["sample_size"] == 10
    assert captured_payload["llm_qc_sampling"]["groups"] == 2
    sampled_dimensions = {item["dimension_id"] for item in captured_payload["items"]}
    assert sampled_dimensions == {"a", "b"}


def test_planner_instruction_resource_contains_design_constraints() -> None:
    instruction = _instruction_resource(
        "Evaluate visual scientific reasoning from images.",
        BenchmarkConfig(scale_budget=ScaleBudget.high),
    )

    assert "Evaluate visual scientific reasoning from images." in instruction
    assert '"scale_budget": "high"' in instruction
    assert '"available_task_types"' in instruction
    assert '"available_environment_types"' in instruction
    assert '"target_models"' not in instruction
    assert '"reference_model"' not in instruction
    assert '"available_metrics"' not in instruction
    assert '"science_policy"' not in instruction


def test_planner_instruction_resource_omits_irrelevant_domain_policies() -> None:
    instruction = _instruction_resource(
        "Evaluate text-only instruction following.",
        BenchmarkConfig(scale_budget=ScaleBudget.low),
    )

    assert '"target_models"' not in instruction
    assert '"science_policy"' not in instruction
    assert '"reference_model"' not in instruction


def test_goal_translation_before_planning(monkeypatch) -> None:
    def fake_call_llm(*args, **kwargs):
        return '{"english_goal":"Evaluate complex mathematical reasoning."}'

    monkeypatch.setattr("evalclaw.planning.planner.call_llm", fake_call_llm)

    translated = translate_goal_to_english(
        "评估复杂数学推理能力",
        BenchmarkConfig(**dummy_config_kwargs()),
    )

    assert translated == "Evaluate complex mathematical reasoning."


def test_goal_translation_requires_planner_model() -> None:
    with pytest.raises(RuntimeError, match="Planner model is not configured"):
        translate_goal_to_english("Evaluate mathematical reasoning", BenchmarkConfig())


def test_english_goal_still_uses_language_normalizer(monkeypatch) -> None:
    calls = 0

    def fake_call_llm(*args, **kwargs):
        nonlocal calls
        calls += 1
        return '{"english_goal":"Evaluate mathematical reasoning."}'

    monkeypatch.setattr("evalclaw.planning.planner.call_llm", fake_call_llm)

    translated = translate_goal_to_english(
        "Evaluate mathematical reasoning.",
        BenchmarkConfig(**dummy_config_kwargs()),
    )

    assert translated == "Evaluate mathematical reasoning."
    assert calls == 1


def test_extract_json_parses_json_repair_string_return(monkeypatch) -> None:
    fake_json_repair = types.SimpleNamespace(repair_json=lambda *args, **kwargs: '{"ok": true}')
    monkeypatch.setitem(sys.modules, "json_repair", fake_json_repair)

    assert extract_json("not valid json") == {"ok": True}


def test_code_harness_injects_model_output_as_json_string() -> None:
    harness = build_code_harness("assert {model_output} == 'answer'", "answer")

    assert harness == "assert \"answer\" == 'answer'"


def test_choice_scoring_requires_exact_selected_id_set() -> None:
    item = BenchmarkItem(
        id="choice",
        dimension_id="math",
        task_type=TaskType.choice,
        prompt="Select all correct choices.",
        choices=[
            {"id": "A", "text": "7"},
            {"id": "B", "text": "11"},
            {"id": "C", "text": "15"},
        ],
        correct_choice_ids=["A", "C"],
    )

    assert _score_choice('["A", "C"]', item) == 1.0
    assert _score_choice("A, C", item) == 1.0
    assert _score_choice("A", item) == 0.0


def test_fill_blank_scoring_only_trims_outer_whitespace() -> None:
    assert _score_fill_blank("  Exact answer\n", ["Exact answer"]) == 1.0
    assert _score_fill_blank("exact answer", ["Exact answer"]) == 0.0
    assert _score_fill_blank("Exact answer.", ["Exact answer"]) == 0.0


def test_fill_blank_scoring_accepts_any_listed_answer() -> None:
    assert _score_fill_blank("42", ["42", "forty-two"]) == 1.0
    assert _score_fill_blank("  forty-two ", ["42", "forty-two"]) == 1.0
    assert _score_fill_blank("43", ["42", "forty-two"]) == 0.0
    assert _score_fill_blank("42", []) == 0.0


def test_choice_scoring_does_not_accept_incidental_letters() -> None:
    response = "The second intersection is point B, and the distance is \\[\\boxed{\\frac{22\\sqrt{5}}{5}}\\]."
    item = BenchmarkItem(
        id="choice",
        dimension_id="math",
        task_type=TaskType.choice,
        prompt="Choose one.",
        choices=[{"id": "A", "text": "first"}, {"id": "B", "text": "second"}],
        correct_choice_ids=["B"],
    )

    assert _score_choice(response, item) == 0.0


def test_choice_prompt_includes_choices() -> None:
    item = BenchmarkItem(
        id="mc",
        dimension_id="math",
        task_type=TaskType.choice,
        prompt="What is 2 + 2?",
        choices=[{"id": "A", "text": "3"}, {"id": "B", "text": "4"}],
        correct_choice_ids=["B"],
    )

    rendered = _target_prompt(item)

    assert "Choices:" in rendered
    assert "A: 3" in rendered
    assert "B: 4" in rendered


def test_qc_warns_on_invalid_science_metadata() -> None:
    item = BenchmarkItem(
        id="bad_science",
        dimension_id="science",
        task_type=TaskType.fill_blank,
        prompt="What force is required for a 1 kg object accelerating at 2 m/s^2?",
        expected_texts=["2 N"],
        metadata={"science": {"schema_version": "old"}},
    )
    spec = EvalSpec(
        objective="Evaluate science reasoning.",
        dimensions=[EvalDimension(id="science", name="Science", description="Science", approach="Science")],
    )

    report = run_qc_gate(TaskSuite(spec=spec, objective=spec.objective, tasks=[item]), BenchmarkConfig())

    assert any("metadata.science.schema_version" in issue.message for issue in report.issues)


def test_report_shows_source_coverage() -> None:
    dimension = EvalDimension(
        id="number_theory",
        name="Number theory",
        description="Proof tasks",
        approach="Use rigorous proof",
    )
    spec = EvalSpec(objective="Evaluate math reasoning", dimensions=[dimension])
    item = BenchmarkItem(
        id="proof_item",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Prove that there are infinitely many primes.",
        rubric="Score the proof for correctness and rigor.",
        source=BenchmarkSource(
            kind=SourceKind.hf_dataset,
            uri="hf://datasets/example/math#split=train&row=1",
            title="example/math",
        ),
    )
    suite = TaskSuite(spec=spec, objective=spec.objective, tasks=[item])
    qc = QcReport(passed_item_ids=[item.id])
    report = build_report(EvalRun(suite=suite, qc_report=qc))

    assert "Source-backed used items: 1/1" in report.markdown
    assert "item_source:hf_dataset" in report.markdown


def test_report_deduplicates_source_candidates() -> None:
    dimension = EvalDimension(
        id="number_theory",
        name="Number theory",
        description="Proof tasks",
        approach="Use rigorous proof",
    )
    spec = EvalSpec(objective="Evaluate math reasoning", dimensions=[dimension])
    source = BenchmarkSource(kind=SourceKind.hf_dataset, uri="hf://datasets/example/math", title="example/math")
    item = BenchmarkItem(
        id="proof_item",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Prove that there are infinitely many primes.",
        rubric="Score proof correctness.",
        source=source,
    )

    report = build_report(
        EvalRun(
            suite=TaskSuite(
                spec=spec,
                objective=spec.objective,
                tasks=[item],
                resources=[
                    TaskResource(id="math/hf", kind="hf_dataset", uri=source.uri, title=source.title),
                    TaskResource(id="math/hf", kind="hf_dataset", uri=source.uri, title=source.title),
                ],
            ),
            qc_report=QcReport(passed_item_ids=[item.id]),
        )
    )

    assert "External source candidates: 1" in report.markdown


def test_report_buckets_count_only_qc_accepted_items() -> None:
    dimension = EvalDimension(
        id="math",
        name="Math",
        description="Math reasoning",
        approach="Use mixed tasks.",
    )
    spec = EvalSpec(
        objective="Evaluate math reasoning",
        dimensions=[dimension],
        task_types=[TaskType.choice, TaskType.generation],
    )
    accepted = BenchmarkItem(
        id="accepted_mc",
        dimension_id=dimension.id,
        task_type=TaskType.choice,
        prompt="What is 2+2?",
        choices=[{"id": "A", "text": "3"}, {"id": "B", "text": "4"}],
        correct_choice_ids=["B"],
    )
    rejected = BenchmarkItem(
        id="rejected_open",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Prove a false statement.",
        rubric="Bad rubric.",
    )

    report = build_report(
        EvalRun(
            suite=TaskSuite(spec=spec, objective=spec.objective, tasks=[accepted, rejected]),
            qc_report=QcReport(passed_item_ids=[accepted.id], rejected_item_ids=[rejected.id]),
        )
    )

    assert "Items generated: 2" in report.markdown
    assert "Items accepted for run: 1" in report.markdown
    assert "Items rejected by QC: 1" in report.markdown
    assert "task:choice | 1" in report.markdown
    assert "task:generation" not in report.markdown


def test_report_includes_item_level_audit_details() -> None:
    dimension = EvalDimension(
        id="dialogue",
        name="Dialogue",
        description="Multi-turn behavior",
        approach="Inspect transcript",
    )
    spec = EvalSpec(objective="Evaluate dialogue behavior", dimensions=[dimension], task_types=[TaskType.multi_turn])
    item = BenchmarkItem(
        id="dialogue_item",
        dimension_id="dialogue",
        task_type=TaskType.multi_turn,
        prompt="Answer politely, then handle a correction.",
        rubric="Score correctness and tone.",
        metadata={"turns": ["Actually, revise that."]},
    )
    result = ItemResult(
        item_id=item.id,
        target_id="mock",
        raw_response=json.dumps(
            [
                {"role": "user", "content": item.prompt},
                {"role": "assistant", "content": "Initial answer."},
                {"role": "user", "content": "Actually, revise that."},
                {"role": "assistant", "content": "Revised answer."},
            ]
        ),
        score=0.6,
        judge_reasoning="The answer partially follows the requested correction.",
        latency_ms=12,
    )
    suite = TaskSuite(spec=spec, objective=spec.objective, tasks=[item])
    report = build_report(EvalRun(suite=suite, qc_report=QcReport(passed_item_ids=[item.id]), results=[result]))

    assert "## Item Results" in report.markdown
    assert "## Detailed Item Records" in report.markdown
    assert "### Response / Trace" in report.markdown
    assert "[1] USER: Answer politely" in report.markdown
    assert "## Failure Mode Summary" in report.markdown


def test_multi_turn_runner_uses_task_agent_for_followups_and_scoring(monkeypatch) -> None:
    target_prompts: list[str] = []
    task_agent_models: list[str | None] = []
    task_agent_systems: list[str | None] = []
    task_agent_responses = iter(
        [
            json.dumps({"done": False, "turn": "Please revise it to be shorter."}),
            json.dumps({"done": True}),
            json.dumps({"score_raw": 4, "score_normalized": 0.8, "reasoning": "Good revision."}),
        ]
    )

    def fake_call_target_model(prompt, *args, **kwargs):
        target_prompts.append(prompt)
        return f"target response to: {prompt}"

    def fake_call_llm(messages, **kwargs):
        task_agent_models.append(kwargs.get("model"))
        task_agent_systems.append(kwargs.get("system"))
        return next(task_agent_responses)

    monkeypatch.setattr("evalclaw.execution.runner.call_target_model", fake_call_target_model)
    monkeypatch.setattr("evalclaw.execution.runner.call_llm", fake_call_llm)
    item = BenchmarkItem(
        id="dialogue_task_agent",
        dimension_id="dialogue",
        task_type=TaskType.multi_turn,
        prompt="Summarize this plan in two bullets.",
        rubric="Score the full dialogue.",
        metadata={
            "task_agent": {
                "schema_version": "evalclaw.task_agent.v1",
                "agent_role": "dialogue_simulator",
                "system_prompt": "You are the per-task user simulator. Return JSON only.",
                "initial_content": {"scenario": "The user wants a concise project plan."},
                "interaction": {"max_turns": 3, "followup_instruction": "Ask for a shorter revision."},
                "scoring": {
                    "method": "agent_judge",
                    "instructions": "Score whether the target handled the revision request.",
                    "levels": {"5": "complete", "3": "partial", "1": "failed"},
                },
            }
        },
    )
    config = BenchmarkConfig(
        task_models=[
            TargetModelConfig(provider="mock", model="mock-task-agent", api_key="dummy")
        ],
        targets=[TargetModelConfig(provider="mock", model="mock-target")],
    )

    result = run_item(item, config)
    transcript = json.loads(result.raw_response)

    assert target_prompts == ["Summarize this plan in two bullets.", "Please revise it to be shorter."]
    assert [message["content"] for message in transcript if message["role"] == "user"] == target_prompts
    assert result.score == 0.8
    assert "task_agent_judge" in (result.judge_reasoning or "")
    assert task_agent_models == ["mock-task-agent", "mock-task-agent", "mock-task-agent"]
    assert all(system == "You are the per-task user simulator. Return JSON only." for system in task_agent_systems)


def test_static_qc_treats_challenge_effort_as_builder_guidance() -> None:
    dimension = EvalDimension(
        id="expert_reasoning",
        name="Expert reasoning",
        description="Expert tasks requiring substantial construction effort",
        approach="Use E3 prompts",
        challenge_effort=ChallengeEffort.E3,
    )
    spec = EvalSpec(
        objective="Evaluate expert reasoning",
        dimensions=[dimension],
        scale_budget=ScaleBudget.high,
        task_types=[TaskType.generation],
    )
    item = BenchmarkItem(
        id="lower_effort_item",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Explain a simple concept clearly.",
        rubric="Score correctness and clarity.",
        challenge_effort=ChallengeEffort.E2,
    )

    qc = run_qc_gate(TaskSuite(spec=spec, objective=spec.objective, tasks=[item]), BenchmarkConfig())

    assert not any(issue.category == QcCategory.challenge_effort for issue in qc.issues)
    assert any("High-budget dimension" in issue.message for issue in qc.issues)


def test_static_qc_rejects_exact_duplicate_prompts() -> None:
    dimension = EvalDimension(
        id="algebra",
        name="Algebra",
        description="Algebra reasoning",
        approach="Use equations.",
    )
    spec = EvalSpec(objective="Evaluate algebra", dimensions=[dimension])
    item_a = BenchmarkItem(
        id="item_a",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Solve the quadratic equation x^2 - 5x + 6 = 0 and show the roots.",
        rubric="Score exact roots and reasoning.",
    )
    item_b = item_a.model_copy(update={"id": "item_b"})

    qc = run_qc_gate(TaskSuite(spec=spec, objective=spec.objective, tasks=[item_a, item_b]), BenchmarkConfig())

    assert "item_b" in qc.rejected_item_ids
    assert any(issue.category.value == "duplicate" and issue.severity.value == "error" for issue in qc.issues)


def test_static_qc_rejects_contradictory_reference_rubric() -> None:
    dimension = EvalDimension(
        id="algebra",
        name="Algebra",
        description="Algebra reasoning",
        approach="Use equations.",
    )
    spec = EvalSpec(objective="Evaluate algebra", dimensions=[dimension])
    item = BenchmarkItem(
        id="bad_rubric",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Find all real x such that f(f(x)) = x for f(x) = (2x+1)/(x-3).",
        rubric="Correct answer {-1, 3}. Actually 3 is extraneous and not in domain, so answer is only {-1}.",
    )

    qc = run_qc_gate(TaskSuite(spec=spec, objective=spec.objective, tasks=[item]), BenchmarkConfig())

    assert "bad_rubric" in qc.rejected_item_ids
    assert any("contradictory reference answer" in issue.message for issue in qc.issues)


def test_static_qc_ignores_choice_rubric() -> None:
    dimension = EvalDimension(
        id="arithmetic",
        name="Arithmetic",
        description="Arithmetic accuracy",
        approach="Use exact calculations.",
        task_types=[TaskType.choice],
    )
    spec = EvalSpec(
        objective="Evaluate arithmetic",
        dimensions=[dimension],
        task_types=[TaskType.choice],
    )
    item = BenchmarkItem(
        id="choice_with_rubric",
        dimension_id=dimension.id,
        task_type=TaskType.choice,
        prompt="Compute sqrt(144) + cbrt(64) - sqrt(25).",
        choices=[
            {"id": "A", "text": "6"},
            {"id": "B", "text": "9"},
            {"id": "C", "text": "11"},
            {"id": "D", "text": "13"},
        ],
        correct_choice_ids=["B"],
        rubric=(
            "The correct answer is B. Actually, an alternative derivation suggests C, "
            "so therefore the answer is C."
        ),
    )

    qc = run_qc_gate(TaskSuite(spec=spec, objective=spec.objective, tasks=[item]), BenchmarkConfig())

    assert qc.rejected_item_ids == []
    assert qc.issues == []


def test_hf_discovery_expands_math_queries() -> None:
    dimension = EvalDimension(
        id="number_theory",
        name="数论",
        description="高挑战数学证明题",
        approach="Use rigorous proof",
        research_queries=["challenging number theory proof problems with counterexample"],
    )

    queries = _expanded_queries(dimension)

    assert "challenging number theory proof problems with counterexample" in queries
    assert "math reasoning" in queries
    assert "olympiad math" in queries


def test_hf_discovery_expands_known_benchmark_queries() -> None:
    dimension = EvalDimension(
        id="graduate_science_reasoning",
        name="Graduate science reasoning",
        description="Expert biology chemistry and physics reasoning",
        approach="Use published benchmarks",
    )

    queries = _expanded_queries(dimension)

    assert "gpqa" in queries
    assert "mmlu pro" in queries


class _AgentProtocolTestEnvironment:
    def __init__(self, max_steps: int = 3) -> None:
        self.max_steps = max_steps
        self.steps = 0
        self.invalid_actions = 0
        self.done = False
        self.changed = False

    def tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name="inspect", description="Inspect state.", parameters=object_schema()),
            ToolSpec(
                name="apply_change",
                description="Apply the requested change.",
                parameters=object_schema(
                    {"content": {"type": "string"}},
                    required=["content"],
                ),
            ),
            ToolSpec(name="final", description="Finish.", parameters=object_schema()),
        ]

    def action_schema(self) -> str:
        return "Use inspect, apply_change, or final."

    def observation(self) -> str:
        return f"changed={self.changed}"

    def step(self, action: dict) -> object:
        self.steps += 1
        name = action.get("action")
        if name == "apply_change":
            self.changed = True
        elif name == "final":
            self.done = True
        return types.SimpleNamespace(
            observation=self.observation(),
            done=self.done,
            error=None,
        )

    def score(self) -> float:
        return 1.0 if self.changed and self.done else 0.0

    def summary(self) -> str:
        return f"changed={self.changed}; done={self.done}"

    def state(self) -> dict:
        return {"environment": "test", "changed": self.changed, "done": self.done}

    def cleanup(self) -> None:
        return None


def _use_agent_protocol_test_environment(monkeypatch, *, max_steps: int = 3) -> None:
    monkeypatch.setattr(
        "evalclaw.runners.agent.build_agent_environment",
        lambda item, config: _AgentProtocolTestEnvironment(max_steps),
    )


def test_tool_protocol_validates_required_and_enum_arguments() -> None:
    spec = ToolSpec(
        name="move",
        description="Move rooms.",
        parameters=object_schema({"room": {"type": "string", "enum": ["office", "lab"]}}, required=["room"]),
    )

    assert validate_tool_call(ToolCall(id="call_1", name="move", arguments={"room": "office"}), [spec]) == []
    assert validate_tool_call(ToolCall(id="call_2", name="move", arguments={}), [spec]) == [
        "Missing required argument: room."
    ]
    assert validate_tool_call(ToolCall(id="call_3", name="move", arguments={"room": "kitchen"}), [spec]) == [
        "Argument room must be one of: office, lab."
    ]
    assert validate_tool_call(ToolCall(id="call_4", name="fly", arguments={}), [spec]) == [
        "Unknown tool/action: fly."
    ]


def test_agent_runner_uses_action_observation_loop(monkeypatch) -> None:
    _use_agent_protocol_test_environment(monkeypatch)
    responses = iter(
        [
            '{"action":"inspect","args":{}}',
            '{"action":"apply_change","args":{"content":"fixed"}}',
            '{"action":"final","args":{}}',
        ]
    )

    def fake_call_target_model(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr("evalclaw.runners.agent.call_target_model", fake_call_target_model)
    item = BenchmarkItem(
        id="agent_item",
        dimension_id="agent",
        task_type=TaskType.agent,
        prompt="Put the blue notebook in the outgoing bin.",
        rubric="Use deterministic environment scoring.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "test_command": "python3 -c \"assert True\"",
                "max_steps": 5,
            }
        },
    )
    config = BenchmarkConfig(targets=[TargetModelConfig(provider="mock", model="mock-agent")])

    result = run_item(item, config)
    trace = json.loads(result.raw_response)

    assert result.score == 1.0
    assert len(trace["trace"]) == 3
    assert trace["final_state"]["changed"] is True
    assert trace["tool_protocol_version"] == "evalclaw.tool_protocol.v1"
    assert trace["tool_specs"][0]["name"] == "inspect"
    assert trace["trace"][0]["tool_call"]["name"] == "inspect"
    assert trace["trace"][0]["tool_result"]["name"] == "inspect"


def test_agent_rejects_invalid_tool_arguments(monkeypatch) -> None:
    _use_agent_protocol_test_environment(monkeypatch, max_steps=1)
    responses = iter(['{"action":"apply_change","args":{}}'])

    def fake_call_target_model(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr("evalclaw.runners.agent.call_target_model", fake_call_target_model)
    item = BenchmarkItem(
        id="agent_item",
        dimension_id="agent",
        task_type=TaskType.agent,
        prompt="Move somewhere.",
        rubric="Use deterministic environment scoring.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "test_command": "python3 -c \"assert True\"",
                "max_steps": 1,
            }
        },
    )
    config = BenchmarkConfig(targets=[TargetModelConfig(provider="mock", model="mock-agent")])

    result = run_item(item, config)
    trace = json.loads(result.raw_response)

    assert result.score == 0.0
    assert "Missing required argument: content" in trace["trace"][0]["error"]
    assert trace["trace"][0]["tool_result"]["error"] == "Missing required argument: content."


def test_agent_uses_task_agent_system_prompt(monkeypatch) -> None:
    _use_agent_protocol_test_environment(monkeypatch)
    captured_systems: list[str | None] = []
    responses = iter(
        [
            '{"action":"inspect","args":{}}',
            '{"action":"apply_change","args":{"content":"fixed"}}',
            '{"action":"final","args":{}}',
        ]
    )

    def fake_call_target_model(*args, **kwargs):
        captured_systems.append(kwargs.get("system_prompt"))
        return next(responses)

    monkeypatch.setattr("evalclaw.runners.agent.call_target_model", fake_call_target_model)
    item = BenchmarkItem(
        id="agent_item",
        dimension_id="agent",
        task_type=TaskType.agent,
        prompt="Put the blue notebook in the outgoing bin.",
        rubric="Use deterministic environment scoring.",
        metadata={
            "task_agent": {
                "schema_version": "evalclaw.task_agent.v1",
                "agent_role": "target_agent_executor",
                "system_prompt": "Custom per-item agent system prompt. Return JSON only.",
                "scoring": {"method": "deterministic", "pass_fail": {"pass": "done", "fail": "not done"}},
            },
            "agent_env": {
                "type": "docker_workspace",
                "test_command": "python3 -c \"assert True\"",
                "max_steps": 5,
            },
        },
    )
    config = BenchmarkConfig(targets=[TargetModelConfig(provider="mock", model="mock-agent")])

    result = run_item(item, config)

    assert result.score == 1.0
    assert captured_systems
    assert set(captured_systems) == {"Custom per-item agent system prompt. Return JSON only."}


def test_agent_uses_openai_native_tool_result_messages(monkeypatch) -> None:
    _use_agent_protocol_test_environment(monkeypatch)
    captured_calls: list[dict] = []
    calls = iter(
        [
            ToolCall(id="call_1", name="inspect", arguments={}),
            ToolCall(id="call_2", name="apply_change", arguments={"content": "fixed"}),
            ToolCall(id="call_3", name="final", arguments={}),
        ]
    )

    def fake_call_target_model_with_tools(messages, target, tools, **kwargs):
        captured_calls.append(
            {
                "messages": json.loads(json.dumps(messages)),
                "target": target.model,
                "tool_names": [tool.name for tool in tools],
                "system_prompt": kwargs.get("system_prompt"),
            }
        )
        call = next(calls)
        assistant_message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
            ],
        }
        return TargetToolModelResponse(
            adapter="openai",
            content="",
            tool_calls=[call],
            assistant_message=assistant_message,
            raw_response={"choices": [{"message": assistant_message}]},
        )

    monkeypatch.setattr("evalclaw.runners.agent.call_target_model_with_tools", fake_call_target_model_with_tools)
    item = BenchmarkItem(
        id="agent_item",
        dimension_id="agent",
        task_type=TaskType.agent,
        prompt="Put the blue notebook in the outgoing bin.",
        rubric="Use deterministic environment scoring.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "test_command": "python3 -c \"assert True\"",
                "max_steps": 5,
            }
        },
    )
    config = BenchmarkConfig(
        targets=[TargetModelConfig(provider="openai", model="gpt-5", api_key="test-key")],
    )

    result = run_item(item, config)
    trace = json.loads(result.raw_response)

    assert result.score == 1.0
    assert trace["tool_message_protocol"] == "provider_native"
    assert trace["tool_adapter"] == "openai"
    assert captured_calls[0]["tool_names"][:2] == ["inspect", "apply_change"]
    assert "Native tool protocol override" in captured_calls[0]["system_prompt"]
    assert all("Continue with one JSON action" not in str(call["messages"]) for call in captured_calls)
    assert any(message["role"] == "tool" for message in captured_calls[1]["messages"])


def test_agent_uses_anthropic_tool_result_blocks(monkeypatch) -> None:
    _use_agent_protocol_test_environment(monkeypatch)
    captured_messages: list[list[dict]] = []
    calls = iter(
        [
            ToolCall(id="toolu_1", name="inspect", arguments={}),
            ToolCall(id="toolu_2", name="apply_change", arguments={"content": "fixed"}),
            ToolCall(id="toolu_3", name="final", arguments={}),
        ]
    )

    def fake_call_target_model_with_tools(messages, target, tools, **kwargs):
        captured_messages.append(json.loads(json.dumps(messages)))
        call = next(calls)
        assistant_message = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I will act."},
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments},
            ],
        }
        return TargetToolModelResponse(
            adapter="anthropic",
            content="I will act.",
            tool_calls=[call],
            assistant_message=assistant_message,
            raw_response={"content": assistant_message["content"]},
        )

    monkeypatch.setattr("evalclaw.runners.agent.call_target_model_with_tools", fake_call_target_model_with_tools)
    item = BenchmarkItem(
        id="agent_item",
        dimension_id="agent",
        task_type=TaskType.agent,
        prompt="Put the blue notebook in the outgoing bin.",
        rubric="Use deterministic environment scoring.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "test_command": "python3 -c \"assert True\"",
                "max_steps": 5,
            }
        },
    )
    config = BenchmarkConfig(
        targets=[TargetModelConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="test-key")],
    )

    result = run_item(item, config)
    trace = json.loads(result.raw_response)

    assert result.score == 1.0
    assert trace["tool_adapter"] == "anthropic"
    followup_messages = captured_messages[1]
    assert any(
        message["role"] == "user"
        and isinstance(message["content"], list)
        and message["content"][0]["type"] == "tool_result"
        for message in followup_messages
    )


def test_judge_invalid_json_is_reported_as_evaluator_error(monkeypatch) -> None:
    monkeypatch.setattr("evalclaw.execution.runner.call_target_model", lambda *args, **kwargs: "A plausible answer.")
    monkeypatch.setattr("evalclaw.execution.runner.call_llm", lambda *args, **kwargs: "not json")
    item = BenchmarkItem(
        id="open_item",
        dimension_id="reasoning",
        task_type=TaskType.generation,
        prompt="Explain a theorem.",
        rubric="Score correctness.",
    )
    config = BenchmarkConfig(
        **dummy_config_kwargs(),
        targets=[TargetModelConfig(provider="mock", model="mock-agent")],
    )

    result = run_item(item, config)

    assert result.error == "Judge returned invalid JSON after retry."
    assert result.judge_reasoning == "Judge returned invalid JSON after retry."


def test_python_tests_tool_supplies_evidence_to_generation_judge(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(
        "evalclaw.execution.runner._target_has_credentials",
        lambda *args, **kwargs: (True, "OPENAI_API_KEY"),
    )
    monkeypatch.setattr(
        "evalclaw.execution.runner.call_target_model",
        lambda *args, **kwargs: "def add(a, b): return a + b",
    )
    monkeypatch.setattr(
        "evalclaw.execution.runner.run_python_sandbox",
        lambda *args, **kwargs: (0, "tests passed", ""),
    )

    def fake_call_llm(messages, **kwargs):
        captured.update(json.loads(messages[0].content))
        return json.dumps({"score_normalized": 1.0, "reasoning": "Verified by tests."})

    monkeypatch.setattr("evalclaw.execution.runner.call_llm", fake_call_llm)
    item = BenchmarkItem(
        id="code_generation",
        dimension_id="code",
        task_type=TaskType.generation,
        prompt="Implement add(a, b).",
        rubric="Score functional correctness using the test evidence.",
        judge_tools=[
            JudgeToolRef(
                tool="python_tests",
                config={"test_code": "assert callable({model_output})"},
            )
        ],
    )
    config = BenchmarkConfig(
        **dummy_config_kwargs(),
        targets=[TargetModelConfig(provider="mock", model="mock-target")],
    )

    result = run_item(item, config)

    assert result.score == 1.0
    assert captured["external_evidence"][0]["tool"] == "python_tests"
    assert captured["external_evidence"][0]["passed"] is True


def test_qc_rejects_removed_reference_model_response_tool() -> None:
    dimension = EvalDimension(
        id="helpfulness",
        name="Helpfulness",
        description="Compare helpfulness.",
        approach="Use pairwise prompts.",
    )
    item = BenchmarkItem(
        id="pairwise_item",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Explain how to debug a failing unit test.",
        rubric="Prefer the more actionable answer.",
        judge_tools=[JudgeToolRef(tool="reference_model_response")],
    )

    qc = run_qc_gate(
        TaskSuite(spec=EvalSpec(objective="Compare models", dimensions=[dimension]), objective="Compare models", tasks=[item]),
        BenchmarkConfig(run_targets=True),
    )

    assert "pairwise_item" in qc.rejected_item_ids
    assert any("Unsupported judge tool" in issue.message for issue in qc.issues)


def test_docker_workspace_agent_can_revise_after_test_failure(monkeypatch) -> None:
    responses = iter(
        [
            json.dumps(
                {
                    "action": "write_file",
                    "args": {
                        "path": "solution.py",
                        "content": "def max_pair_sum(nums):\n    return max(nums)\n",
                    },
                }
            ),
            '{"action":"run_tests","args":{}}',
            json.dumps(
                {
                    "action": "write_file",
                    "args": {
                        "path": "solution.py",
                        "content": "def max_pair_sum(nums):\n    nums = sorted(nums)\n    return nums[-1] + nums[-2]\n",
                    },
                }
            ),
            '{"action":"run_tests","args":{}}',
        ]
    )

    def fake_call_target_model(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr("evalclaw.runners.agent.call_target_model", fake_call_target_model)
    item = BenchmarkItem(
        id="code_agent_item",
        dimension_id="code_agent",
        task_type=TaskType.agent,
        prompt="Implement max_pair_sum(nums) and run tests until they pass.",
        rubric="Use deterministic hidden-test scoring.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "visible_files": {"solution.py": "def max_pair_sum(nums):\n    pass\n"},
                "hidden_files": {
                    "tests.py": (
                        "from solution import max_pair_sum\n\n"
                        "assert max_pair_sum([1, 2, 3, 4]) == 7\n"
                        "assert max_pair_sum([-5, -2, -3]) == -5\n"
                    )
                },
                "test_command": "python3 tests.py",
                "max_steps": 6,
            }
        },
    )
    config = BenchmarkConfig(targets=[TargetModelConfig(provider="mock", model="mock-agent")])

    result = run_item(item, config)
    trace = json.loads(result.raw_response)

    assert result.score == 1.0
    assert len(trace["trace"]) == 4
    assert trace["trace"][1]["score_after_step"] == 0.0
    assert trace["trace"][3]["score_after_step"] == 1.0
    assert trace["final_state"]["last_test"]["passed"] is True


def test_complex_code_smoke_requires_second_repair(monkeypatch) -> None:
    from scripts.run_complex_agent_smokes import make_code_repair_item, run_scripted_item

    item, actions, config = make_code_repair_item()

    result = run_scripted_item(item, actions, config)
    trace = result["raw"]["trace"]

    assert result["score"] == 1.0
    assert len(trace) == 5
    assert trace[2]["parsed_action"]["action"] == "run_tests"
    assert trace[2]["score_after_step"] == 0.0
    assert "Evaluator not passed" in trace[2]["observation"]
    assert trace[4]["parsed_action"]["action"] == "run_tests"
    assert trace[4]["score_after_step"] == 1.0


def test_llm_qc_receives_agent_env_metadata(monkeypatch) -> None:
    captured_payload = {}

    def fake_call_llm(messages, **kwargs):
        captured_payload.update(json.loads(messages[0].content))
        return json.dumps(
            {
                "issues": [
                    {
                        "item_id": "code_agent_item",
                        "severity": "error",
                        "category": "scoring",
                        "message": "Hidden tests are not visible to the target, so the item is unverifiable.",
                        "suggested_action": "Expose test details.",
                    }
                ],
                "summary": "ok",
            }
        )

    monkeypatch.setattr("evalclaw.quality.llm_checks.call_llm", fake_call_llm)
    dimension = EvalDimension(
        id="code_agent",
        name="Code agent",
        description="Evaluate iterative coding agents.",
        approach="Use hidden tests in a code sandbox.",
    )
    spec = EvalSpec(
        objective="Evaluate whether an agent fixes code robustly instead of hardcoding tests.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    item = BenchmarkItem(
        id="code_agent_item",
        dimension_id="code_agent",
        task_type=TaskType.agent,
        prompt="Implement max_pair_sum(nums) and run tests until they pass.",
        rubric="Use deterministic hidden-test scoring.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "visible_files": {"solution.py": "def max_pair_sum(nums):\n    pass\n"},
                "hidden_files": {"tests.py": "from solution import max_pair_sum\n"},
                "test_command": "python3 tests.py",
                "max_steps": 6,
            },
            "agent_task_package": {
                "schema_version": "evalclaw.agent_task_package.v1",
                "capability_target": {"name": "Iterative code repair"},
                "visible_inputs": {
                    "instructions": "Implement max_pair_sum(nums) and run tests until they pass.",
                    "file_names": ["solution.py"],
                },
                "hidden_references": {"file_names": ["tests.py"]},
                "output_contract": {"expected_artifacts": ["solution.py"]},
                "evaluation": {
                    "method": "deterministic",
                    "pass_criteria": "python3 tests.py passes.",
                },
                "artifact_collection": {"collect_trajectory": True},
                "trajectory_requirements": {"required_tools": ["read_file", "write_file"]},
            },
        },
    )
    config = BenchmarkConfig(**dummy_config_kwargs(), use_llm_qc=True)

    qc = run_qc_gate(TaskSuite(spec=spec, objective=spec.objective, tasks=[item]), config)

    agent_env = captured_payload["items"][0]["metadata"]["agent_env"]
    assert qc.rejected_item_ids == []
    assert any("demoted from an LLM QC blocking error" in issue.message for issue in qc.issues)
    assert agent_env["type"] == "docker_workspace"
    assert agent_env["visible_files_names"] == ["solution.py"]
    assert agent_env["hidden_files_names"] == ["tests.py"]
    assert "Full file contents are omitted" in agent_env["hidden_files_content_note"]
    assert agent_env["test_command"] == "python3 tests.py"


def test_agent_action_parser_recovers_write_file_args() -> None:
    action, error = _parse_agent_action(
        'The file update is below. {"path":"solution.py","content":"def solve():\\n    return 1\\n"}'
    )

    assert error is None
    assert action == {
        "action": "write_file",
        "args": {"path": "solution.py", "content": "def solve():\n    return 1\n"},
    }


def test_report_viewer_html_includes_general_diagnostics() -> None:
    dimension = EvalDimension(
        id="proof_reasoning",
        name="Proof reasoning",
        description="Evaluate mathematical proof reasoning.",
        approach="Use source-backed proof problems.",
    )
    spec = EvalSpec(
        id="math_reasoning_eval",
        objective="Evaluate complex mathematical reasoning.",
        dimensions=[dimension],
        task_types=[TaskType.generation],
    )
    item = BenchmarkItem(
        id="proof_item_1",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Prove that sqrt(2) is irrational.",
        rubric="Score rigor and correctness.",
        source=BenchmarkSource(
            kind=SourceKind.hf_dataset,
            uri="hf://datasets/example/math#row=1",
            title="example/math",
        ),
    )
    result = ItemResult(
        item_id=item.id,
        target_id="mock",
        raw_response="Assume sqrt(2)=a/b in lowest terms...",
        score=0.7,
        judge_reasoning="The proof has the right contradiction structure but misses a coprimality detail.",
    )
    run = EvalRun(
        suite=TaskSuite(spec=spec, objective=spec.objective, tasks=[item]),
        qc_report=QcReport(passed_item_ids=[item.id]),
        results=[result],
    )
    report = build_report(run)
    package = BenchmarkPackage(
        goal=spec.objective,
        spec=spec,
        suite=run.suite,
        qc_report=run.qc_report,
        run=run,
        report=report,
    )
    html = build_report_viewer_html(package)
    payload = _viewer_payload(package)

    assert "EvaluationClaw Diagnostic Report" in html
    assert "Capability Profile" in html
    assert "Capability By Dimension" in html
    assert "Capability By Task Type" in html
    assert "Dataset Composition" not in html
    assert "Task Composition and QC" in html
    assert "Generated / QC passed" in html
    assert "Sourced / QC passed" in html
    assert "Average QC issues" in html
    assert "- Average QC issues:" in report.markdown
    assert "Challenge Effort Distribution" in html
    assert "QC and Judge Audit" not in html
    assert "Item Explorer" in html
    assert "proof_item_1" in html
    assert "pkg.suite.items" not in html
    assert "pkg.suite.tasks" in html
    assert "source-backed" in html
    assert "reasoning" in html
    assert payload["diagnostics"]["judge"]["double_pass_enabled"] is False

    run.runner_artifacts["judge"] = {"double_pass_enabled": True}
    payload = _viewer_payload(package)
    assert payload["diagnostics"]["judge"]["double_pass_enabled"] is True


def test_report_viewer_html_includes_agent_trace() -> None:
    dimension = EvalDimension(
        id="code_agent",
        name="Code agent",
        description="Evaluate iterative coding agents.",
        approach="Use code sandbox traces.",
    )
    spec = EvalSpec(
        id="code_agent_eval",
        objective="Evaluate code agents that write code, run tests, inspect errors, and revise.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    item = BenchmarkItem(
        id="code_agent_item",
        dimension_id=dimension.id,
        task_type=TaskType.agent,
        prompt="Implement max_pair_sum(nums) and run tests until they pass.",
        rubric="Use hidden-test scoring.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "test_command": "python3 tests.py",
                "max_steps": 4,
            }
        },
    )
    result = ItemResult(
        item_id=item.id,
        target_id="mock",
        raw_response=json.dumps(
            {
                "environment": "docker_workspace",
                "trace": [
                    {
                        "step": 1,
                        "parsed_action": {"action": "write_file", "args": {"path": "solution.py"}},
                        "score_after_step": 0.25,
                        "done": False,
                        "observation": "file written",
                    },
                    {
                        "step": 2,
                        "parsed_action": {"action": "run_tests", "args": {}},
                        "score_after_step": 1.0,
                        "done": True,
                        "observation": "tests passed",
                    },
                ],
                "final_state": {"last_test": {"passed": True}},
            }
        ),
        score=1.0,
    )
    run = EvalRun(
        suite=TaskSuite(spec=spec, objective=spec.objective, tasks=[item]),
        qc_report=QcReport(passed_item_ids=[item.id]),
        results=[result],
    )
    html = build_report_viewer_html(
        BenchmarkPackage(
            goal=spec.objective,
            spec=spec,
            suite=run.suite,
            qc_report=run.qc_report,
            run=run,
            report=build_report(run),
        )
    )

    assert "Agent Interaction Diagnostics" not in html
    assert "Code Execution Diagnostics" not in html
    assert "Task Designs" in html
    assert "Model Performance Analysis" in html
    assert "Task Content" not in html
    assert "<h2>Artifacts</h2>" not in html
    assert 'href="#artifacts"' not in html
    assert "1. Source and construction metadata" in html
    assert "2. Target-visible prompt" in html
    assert "Agent Trace Summary" in html
    assert "Raw response" in html
    assert "write_file" in html


def test_report_viewer_item_explorer_uses_six_unified_task_fields() -> None:
    dimension = EvalDimension(
        id="repo_repair",
        name="Repository repair",
        description="Evaluate executable repository repair tasks.",
        approach="Use hidden tests and reference solutions.",
    )
    spec = EvalSpec(
        id="task_design_schema_eval",
        objective="Evaluate task design report coverage.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    item = BenchmarkItem(
        id="repo_repair_item",
        dimension_id=dimension.id,
        task_type=TaskType.agent,
        prompt="Fix the failing parser and leave a patch in the workspace.",
        rubric="Pass if the hidden tests pass and the parser handles escaped delimiters.",
        source=BenchmarkSource(kind=SourceKind.web, uri="https://example.test/issue", title="Parser issue"),
        metadata={
            "task_content_summary": "Escaped delimiter parser fix",
            "agent_env": {
                "type": "docker_workspace",
                "image": "python:3.11-slim",
                "visible_files": {"parser.py": "def parse(x):\n    return x.split(',')\n"},
                "hidden_files": {"tests/test_parser.py": "def test_hidden():\n    assert True\n"},
                "test_command": "python -m pytest",
            },
            "agent_task_package": {
                "schema_version": "evalclaw.agent_task_package.v1",
                "style": "ale_executable_task",
                "capability_target": {"name": "Code repair", "content_summary": "Parser escape handling"},
                "visible_inputs": {
                    "instructions": "Inspect parser.py and update the implementation.",
                    "files": {"README.md": "Parser accepts comma-delimited rows."},
                },
                "hidden_references": {
                    "files": {"reference_solution.py": "def parse(x):\n    return ['fixed']\n"},
                    "reference_artifacts": ["reference behavior for escaped delimiters"],
                },
                "output_contract": {"required_outputs": ["modified parser.py"], "expected_artifacts": ["patch"]},
                "evaluation": {"method": "deterministic", "pass_criteria": "All hidden tests pass."},
                "resource_provenance": {"source_kind": "generated_fixture", "construction_notes": "Small fixture."},
            },
        },
    )
    run = EvalRun(
        suite=TaskSuite(spec=spec, objective=spec.objective, tasks=[item]),
        qc_report=QcReport(passed_item_ids=[item.id]),
        results=[],
    )
    html = build_report_viewer_html(
        BenchmarkPackage(
            goal=spec.objective,
            spec=spec,
            suite=run.suite,
            qc_report=run.qc_report,
            run=run,
            report=build_report(run),
        )
    )

    assert "1. Source and construction metadata" in html
    assert "2. Target-visible prompt" in html
    assert "3. Outputs, scoring, and evaluator materials" in html
    assert "4. Model-visible context and resources" in html
    assert "5. Tools, environment, and initial state" in html
    assert "6. Reference answer or solution" in html
    assert "Quality flags" in html
    assert "Evaluation requirements" in html
    assert "Model-visible resources" in html
    assert "Observation and action space" in html
    assert "reference_solution.py" in html
    assert "python:3.11-slim" in html
    assert "Source URI" not in html


def test_report_viewer_qc_audit_renders_markdown_and_groups_repeated_item_issues() -> None:
    dimension = EvalDimension(
        id="qc_dimension",
        name="QC dimension",
        description="Evaluate QC reporting.",
        approach="Use repeated QC issues.",
    )
    spec = EvalSpec(id="qc_audit_eval", objective="Evaluate QC audit rendering.", dimensions=[dimension])
    item = BenchmarkItem(
        id="qc_item",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Explain the fix.",
        rubric="Score for correctness.",
    )
    qc = QcReport(
        passed_item_ids=[],
        rejected_item_ids=[item.id],
        issues=[
            QcIssue(
                item_id=item.id,
                severity=QcSeverity.warning,
                category=QcCategory.clarity,
                message="**First pass** found missing detail.",
                suggested_action="- Add a concrete acceptance criterion.",
            ),
            QcIssue(
                item_id=item.id,
                severity=QcSeverity.error,
                category=QcCategory.scoring,
                message="```text\nsecond pass\n```",
                suggested_action="Use `deterministic` scoring.",
            ),
        ],
        quality_score=0.5,
    )
    run = EvalRun(suite=TaskSuite(spec=spec, objective=spec.objective, tasks=[item]), qc_report=qc, results=[])
    html = build_report_viewer_html(
        BenchmarkPackage(
            goal=spec.objective,
            spec=spec,
            suite=run.suite,
            qc_report=qc,
            run=run,
            report=build_report(run),
        )
    )

    assert "function markdownNode" in html
    assert "function groupedQcIssues" in html
    assert "Show more (" in html
    assert "<strong>$1</strong>" in html
    assert "**First pass** found missing detail." in html
    assert "Use `deterministic` scoring." in html


def test_persist_package_writes_browser_report_and_manifest(tmp_path) -> None:
    dimension = EvalDimension(
        id="format_following",
        name="Format following",
        description="Evaluate instruction and format constraints.",
        approach="Use constrained prompts.",
    )
    spec = EvalSpec(
        id="browser_report_eval",
        objective="Evaluate format following.",
        dimensions=[dimension],
    )
    item = BenchmarkItem(
        id="format_item",
        dimension_id=dimension.id,
        task_type=TaskType.fill_blank,
        prompt="Return only JSON.",
        rubric="Valid JSON receives full credit.",
    )
    run = EvalRun(
        suite=TaskSuite(spec=spec, objective=spec.objective, tasks=[item]),
        qc_report=QcReport(passed_item_ids=[item.id]),
        results=[
            ItemResult(
                item_id=item.id,
                target_id="mock",
                raw_response='{"ok": true, "debug_key": "sk-testsecret123"}',
                score=1.0,
            )
        ],
    )
    pkg = BenchmarkPackage(
        goal=spec.objective,
        spec=spec,
        suite=run.suite,
        qc_report=run.qc_report,
        run=run,
        report=build_report(run),
    )

    _persist_package(pkg, BenchmarkConfig(), str(tmp_path), log=lambda _: None)

    html_files = list(tmp_path.glob("evalclaw_*.html"))
    md_files = list(tmp_path.glob("evalclaw_*.md"))
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert len(html_files) == 1
    assert "EvaluationClaw Diagnostic Report" in html_files[0].read_text(encoding="utf-8")
    assert "frontend_report_html" in md_files[0].read_text(encoding="utf-8")
    assert manifest["frontend_report"] == str(html_files[0])
    persisted_text = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.glob("evalclaw_*.*"))
    assert "sk-testsecret123" not in persisted_text
    assert "[REDACTED]" in persisted_text


def test_lm_eval_artifacts_use_portable_data_file_paths(tmp_path) -> None:
    dimension = EvalDimension(
        id="format_following",
        name="Format following",
        description="Evaluate instruction and format constraints.",
        approach="Use constrained prompts.",
    )
    spec = EvalSpec(id="portable_path_eval", objective="Evaluate format following.", dimensions=[dimension])
    item = BenchmarkItem(
        id="format_item",
        dimension_id=dimension.id,
        task_type=TaskType.fill_blank,
        prompt="Return OK.",
        expected_texts=["OK"],
    )

    artifacts = write_lm_eval_artifacts(TaskSuite(spec=spec, objective=spec.objective, tasks=[item]), tmp_path)
    yaml_text = artifacts["yaml_exact_match"].read_text(encoding="utf-8")

    assert _portable_path(PureWindowsPath("C:/tmp/evalclaw/task.jsonl")) == "C:/tmp/evalclaw/task.jsonl"
    assert artifacts["jsonl_exact_match"].as_posix() in yaml_text


def test_lm_eval_executable_resolves_from_environment_scripts_dir(tmp_path, monkeypatch) -> None:
    scripts_dir = tmp_path / "Scripts"
    scripts_dir.mkdir()
    executable = scripts_dir / "lm_eval.exe"
    executable.write_text("", encoding="utf-8")

    monkeypatch.setattr("evalclaw.execution.lm_eval.sysconfig.get_path", lambda name: str(scripts_dir))
    monkeypatch.setattr("evalclaw.execution.lm_eval.shutil.which", lambda name: None)

    assert _resolve_lm_eval_executable() == str(executable)


def test_human_review_overview_mentions_dimension_item_mix_without_qc_details() -> None:
    dimension = EvalDimension(
        id="format_following",
        name="Format following",
        description="Evaluate strict format constraints.",
        approach="Use answer-keyed checks.",
        target_item_count=2,
        task_types=[TaskType.choice],
    )
    item = BenchmarkItem(
        id="item_1",
        dimension_id=dimension.id,
        task_type=TaskType.choice,
        prompt="Which response is valid JSON?",
        choices=[{"id": "A", "text": "{}"}, {"id": "B", "text": "prose"}],
        correct_choice_ids=["A"],
    )
    item = item.model_copy(
        update={
            "source_definition": TaskDefinition(
                id=item.id,
                dimension_id=dimension.id,
                task_type=TaskType.choice,
                title="JSON response selection",
                content_summary="Choose the syntactically valid JSON response.",
                description="A strict output-format check.",
                prompt=item.prompt,
                choices=item.choices,
                correct_choice_ids=item.correct_choice_ids,
                system_prompt="Return only the selected option.",
                resource_ids=["json_spec"],
                environment=AgentEnvironmentSpec(
                    bridge_api_key="hidden-bridge-key",
                    vm_provider_api_key="hidden-vm-key",
                ),
            )
        }
    )
    qc = QcReport(passed_item_ids=[item.id], rejected_item_ids=[], issues=[], quality_score=0.9)
    overview = format_human_review_overview(
        TaskSuite(spec=EvalSpec(objective="Evaluate format following", dimensions=[dimension]), objective="Evaluate format following", tasks=[item]),
        qc,
        BenchmarkConfig(),
    )

    assert "EvaluationClaw benchmark is ready for human review." in overview
    assert "format_following" in overview
    assert "| Dimension | Target | Ready | Item types |" in overview
    assert "choice: 1" in overview
    assert "QC quality" not in overview
    assert "QC issues" not in overview
    assert "## All Items" in overview
    assert "### `item_1`" in overview
    assert "Which response is valid JSON?" in overview
    assert "`A` (correct): {}" in overview
    assert "JSON response selection" in overview
    assert "Choose the syntactically valid JSON response." in overview
    assert "Return only the selected option." in overview
    assert "hidden-bridge-key" not in overview
    assert "hidden-vm-key" not in overview
    assert "cite the exact item id shown above" in overview


def test_planner_review_uses_dimension_summaries_as_the_only_count_fields(monkeypatch) -> None:
    dimension = EvalDimension(
        id="format_following",
        name="Format following",
        description="Evaluate strict format constraints.",
        approach="Use answer-keyed checks.",
        target_item_count=2,
        task_types=[TaskType.choice],
    )
    item = BenchmarkItem(
        id="item_1",
        dimension_id=dimension.id,
        task_type=TaskType.choice,
        prompt="Which response is valid JSON?",
        choices=[{"id": "A", "text": "{}"}, {"id": "B", "text": "prose"}],
        correct_choice_ids=["A"],
    )
    suite = TaskSuite(
        spec=EvalSpec(objective="Evaluate format following", dimensions=[dimension]),
        objective="Evaluate format following",
        tasks=[item],
    )
    captured: dict = {}

    def fake_call_llm(messages, **kwargs):
        captured.update(json.loads(messages[0].content))
        return '{"done": true}'

    monkeypatch.setattr("evalclaw.planning.loop.call_llm", fake_call_llm)
    review = _planner_review(
        suite,
        QcReport(passed_item_ids=[item.id]),
        BenchmarkConfig(planner_model="planner", planner_api_key="key"),
        human_feedback="Keep the benchmark concise.",
    )

    assert review["done"] is True
    assert "target_counts" not in captured
    assert "current_counts" not in captured
    assert captured["dimension_dataset_summaries"] == [
        {
            "dimension_id": dimension.id,
            "planned_materialized_target": 2,
            "current_items": 1,
            "task_counts": {"choice": 1},
            "source_counts": {"self_generated": 1},
            "target_item_count": 2,
            "target_source_backed_count": 0,
            "target_generated_count": None,
        }
    ]


def test_planner_review_includes_named_item_beyond_default_excerpt_limit(monkeypatch) -> None:
    dimension = EvalDimension(
        id="review_dimension",
        name="Review dimension",
        description="Exercise item-specific human review.",
        approach="Use generated prompts.",
        target_item_count=82,
        task_types=[TaskType.generation],
    )
    tasks = [
        BenchmarkItem(
            id=f"item_{index}",
            dimension_id=dimension.id,
            task_type=TaskType.generation,
            prompt=(f"Prompt {index}: " + "x" * 800),
            rubric=(f"Rubric {index}: " + "y" * 600),
        )
        for index in range(82)
    ]
    tasks[-1] = tasks[-1].model_copy(
        update={
            "source_definition": TaskDefinition(
                id=tasks[-1].id,
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                title="Named item definition",
                content_summary="The complete definition for a specifically requested item.",
                description="Used to verify targeted human review context.",
                prompt=tasks[-1].prompt,
                rubric=tasks[-1].rubric,
                system_prompt="Follow the requested output contract.",
                interaction={"mode": "single_turn"},
                environment=AgentEnvironmentSpec(bridge_api_key="hidden-key"),
                scoring=TaskScoringSpec(pass_criteria="Satisfy every rubric criterion."),
            )
        }
    )
    suite = TaskSuite(
        spec=EvalSpec(objective="Evaluate review targeting", dimensions=[dimension]),
        objective="Evaluate review targeting",
        tasks=tasks,
    )
    captured: dict = {}

    def fake_call_llm(messages, **kwargs):
        captured.update(json.loads(messages[0].content))
        return '{"done": true}'

    monkeypatch.setattr("evalclaw.planning.loop.call_llm", fake_call_llm)
    _planner_review(
        suite,
        QcReport(passed_item_ids=[item.id for item in tasks]),
        BenchmarkConfig(planner_model="planner", planner_api_key="key"),
        human_feedback="Update item_81: make its edge case explicit.",
    )

    excerpts = captured["items"]
    assert len(excerpts) == 81
    assert [entry["id"] for entry in excerpts[-2:]] == ["item_79", "item_81"]
    assert "item_80" not in {entry["id"] for entry in excerpts}
    assert excerpts[-1]["prompt"] == tasks[-1].prompt
    assert excerpts[-1]["rubric"] == tasks[-1].rubric
    assert excerpts[-1]["task_definition"]["title"] == "Named item definition"
    assert excerpts[-1]["task_definition"]["system_prompt"] == (
        "Follow the requested output contract."
    )
    assert "hidden-key" not in json.dumps(excerpts[-1])


def test_human_review_feedback_can_add_dimension_and_refill(monkeypatch) -> None:
    base_dimension = EvalDimension(
        id="core_capability",
        name="Core capability",
        description="Evaluate the main capability.",
        approach="Use concise prompts.",
        target_item_count=1,
    )
    suite = TaskSuite(
        spec=EvalSpec(objective="Evaluate capability", dimensions=[base_dimension]),
        objective="Evaluate capability",
        tasks=[
            BenchmarkItem(
                id="base_item",
                dimension_id=base_dimension.id,
                task_type=TaskType.generation,
                prompt="Explain the core capability.",
                rubric="Score correctness.",
            )
        ],
    )
    qc = QcReport(passed_item_ids=["base_item"], rejected_item_ids=[], issues=[], quality_score=1.0)
    new_dimension = EvalDimension(
        id="agentic_escalation",
        name="Agentic escalation",
        description="Test multi-step escalation handling.",
        approach="Use short agent-style probes.",
        target_item_count=1,
        task_types=[TaskType.generation],
    )
    generated_item = BenchmarkItem(
        id="generated_item",
        dimension_id="dimension_2",
        task_type=TaskType.generation,
        prompt="Describe escalation handling.",
        rubric="Score clarity.",
    )

    def fake_planner_review(*args, **kwargs):
        return {
            "done": True,
            "add_dimensions": [new_dimension.model_dump(mode="json")],
            "needs_more_items": [{"dimension_id": new_dimension.id, "count": 1, "guidance": "Add one item."}],
        }

    new_blueprint = make_blueprint(
        "new_job",
        "dimension_2",
        "Agentic escalation",
        task_type=TaskType.generation,
        count=1,
        content="Describe escalation handling.",
    )

    def fake_plan_from_spec(spec_arg, config, **kwargs):
        assert {dimension.id for dimension in spec_arg.dimensions} == {"dimension_2"}
        return types.SimpleNamespace(builder_jobs=[new_blueprint])

    def fake_build_task_suite(spec_arg, blueprints, config, **kwargs):
        return TaskSuite(
            spec=spec_arg,
            objective=spec_arg.objective,
            tasks=[generated_item],
            blueprints=blueprints,
        )

    monkeypatch.setattr("evalclaw.planning.loop._planner_review", fake_planner_review)
    monkeypatch.setattr("evalclaw.planning.loop.plan_from_spec", fake_plan_from_spec)
    monkeypatch.setattr("evalclaw.planning.loop.build_task_suite", fake_build_task_suite)
    monkeypatch.setattr("evalclaw.planning.loop.run_qc_gate", lambda suite, config, **kwargs: qc)

    _, revised_suite, revised_qc = apply_human_review_feedback(
        suite,
        qc,
        BenchmarkConfig(max_qc_iterations=1),
        "Please add agentic escalation coverage.",
    )

    assert {dimension.id for dimension in revised_suite.spec.dimensions} == {
        "core_capability",
        "dimension_2",
    }
    # The untouched core item is retained verbatim.
    assert any(item.id == "base_item" for item in revised_suite.tasks)
    assert any(item.dimension_id == "dimension_2" for item in revised_suite.tasks)
    assert revised_qc.rejected_item_ids == []


def test_human_review_ignores_destructive_delete_of_qc_passed_items(monkeypatch) -> None:
    dimension = EvalDimension(
        id="core_capability",
        name="Core capability",
        description="Evaluate the main capability.",
        approach="Use concise prompts.",
        target_item_count=1,
        task_types=[TaskType.generation],
    )
    item = BenchmarkItem(
        id="base_item",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Explain the core capability.",
        rubric="Score correctness.",
    )
    suite = TaskSuite(
        spec=EvalSpec(objective="Evaluate capability", dimensions=[dimension]),
        objective="Evaluate capability",
        tasks=[item],
    )
    qc = QcReport(passed_item_ids=["base_item"], rejected_item_ids=[], issues=[], quality_score=1.0)

    def fake_planner_review(*args, **kwargs):
        return {"done": False, "delete_item_ids": ["base_item"], "notes": "Prefer another item."}

    monkeypatch.setattr("evalclaw.planning.loop._planner_review", fake_planner_review)
    monkeypatch.setattr("evalclaw.planning.loop.run_qc_gate", lambda suite, config, **kwargs: qc)

    _, revised_suite, revised_qc = apply_human_review_feedback(
        suite,
        qc,
        BenchmarkConfig(max_qc_iterations=1),
        "Review the item.",
    )

    assert [revised_item.id for revised_item in revised_suite.tasks] == ["base_item"]
    assert revised_qc.rejected_item_ids == []


def test_human_review_rewrites_single_item_from_update_items(monkeypatch) -> None:
    """update_items rewrites exactly the named item in place, preserving its id."""
    dimension = EvalDimension(
        id="core_capability",
        name="Core capability",
        description="Evaluate the main capability.",
        approach="Use concise prompts.",
        target_item_count=1,
        task_types=[TaskType.generation],
    )
    blueprint = make_blueprint(
        "b1",
        dimension.id,
        "Core blueprint",
        task_type=TaskType.generation,
        count=1,
        content="Explain the core capability.",
    )
    source = TaskDefinition(
        id="base_item",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        title="Base item",
        prompt="Explain the core capability.",
        scoring=TaskScoringSpec(pass_criteria="Correct."),
        metadata={"builder_job_id": blueprint.id, "task_design_id": blueprint.task_design_ids[0]},
    )
    item = BenchmarkItem.model_validate(
        {
            "id": "base_item",
            "dimension_id": dimension.id,
            "task_type": "generation",
            "prompt": "Explain the core capability.",
        }
    ).model_copy(update={"source_definition": source})
    blueprint_item = item.model_copy(update={"prompt": "Explain the core capability with a concrete example."})
    suite = TaskSuite(
        spec=EvalSpec(objective="Evaluate capability", dimensions=[dimension]),
        objective="Evaluate capability",
        tasks=[item],
        blueprints=[blueprint],
    )
    qc = QcReport(passed_item_ids=["base_item"], rejected_item_ids=[], issues=[], quality_score=1.0)

    def fake_planner_review(*args, **kwargs):
        return {
            "done": False,
            "update_items": [
                {
                    "item_id": "base_item",
                    "dimension_id": dimension.id,
                    "guidance": "Add a concrete example to the prompt.",
                }
            ],
            "notes": "Clarify the item.",
        }

    def fake_rewrite_build(spec_arg, blueprints, config, **kwargs):
        revision = (kwargs.get("revision_context_by_dimension") or {}).get(dimension.id) or {}
        assert revision.get("reason") == "human_review_item_update"
        previous = revision.get("previous_tasks") or []
        assert [task["id"] for task in previous] == ["base_item"]
        return TaskSuite(
            spec=spec_arg,
            objective=spec_arg.objective,
            tasks=[blueprint_item],
            blueprints=[blueprint],
        )

    monkeypatch.setattr("evalclaw.planning.loop._planner_review", fake_planner_review)
    monkeypatch.setattr("evalclaw.planning.loop.build_task_suite", fake_rewrite_build)
    monkeypatch.setattr("evalclaw.planning.loop.run_qc_gate", lambda suite, config, **kwargs: qc)

    _, revised_suite, revised_qc = apply_human_review_feedback(
        suite,
        qc,
        BenchmarkConfig(max_qc_iterations=1),
        "Rewrite the item.",
    )

    assert len(revised_suite.tasks) == 1
    rewritten = revised_suite.tasks[0]
    assert rewritten.id == "base_item"
    assert "concrete example" in rewritten.prompt
    assert revised_qc.rejected_item_ids == []
