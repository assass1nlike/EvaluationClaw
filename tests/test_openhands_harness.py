"""Tests for the OpenHands harness runner and its wiring."""
from __future__ import annotations

from pathlib import Path

import pytest

from evalclaw.runners import agent as agent_module
from evalclaw.runners import harness as harness_module
from evalclaw.runners import openhands as openhands_module
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    TargetModelConfig,
    TaskType,
)


def _item(agent_env: dict) -> BenchmarkItem:
    return BenchmarkItem(
        id="task_1",
        dimension_id="d1",
        task_type=TaskType.agent,
        prompt="Write a function that adds two numbers.",
        metadata={"agent_env": agent_env},
    )


def _target(harness: str = "") -> TargetModelConfig:
    return TargetModelConfig(provider="openai", model="gpt-5", api_key="k", harness=harness)


def test_target_model_config_has_harness_field() -> None:
    assert _target("openhands").harness == "openhands"
    assert _target().harness == ""


def test_run_agent_interaction_dispatches_to_harness(monkeypatch) -> None:
    captured: dict = {}

    class FakeRunner:
        name = "openhands"

        def run(self, item, target, config, *, artifact_dir=None):
            captured["called"] = True
            return "raw", 1.0, "ok"

    monkeypatch.setattr(harness_module, "get_harness", lambda name: FakeRunner())

    raw, score, reasoning = agent_module.run_agent_interaction(
        _item({"type": "docker_workspace"}),
        _target("openhands"),
        BenchmarkConfig(),
    )

    assert captured["called"] is True
    assert (raw, score, reasoning) == ("raw", 1.0, "ok")


def test_run_agent_interaction_without_harness_skips_harness(monkeypatch) -> None:
    def fake_get_harness(name):
        raise AssertionError("harness must not be looked up")

    monkeypatch.setattr(harness_module, "get_harness", fake_get_harness)
    monkeypatch.setattr(
        agent_module,
        "_run_agent_interaction_native_tools",
        lambda *args, **kwargs: ("raw", 0.0, "ok"),
    )
    monkeypatch.setattr(
        agent_module,
        "_run_agent_interaction_json_actions",
        lambda *args, **kwargs: ("raw", 0.0, "ok"),
    )

    raw, score, reasoning = agent_module.run_agent_interaction(
        _item({"type": "docker_workspace"}),
        _target(),
        BenchmarkConfig(),
    )

    assert (raw, score, reasoning) == ("raw", 0.0, "ok")


def test_openhands_runner_builds_image_and_scores(monkeypatch) -> None:
    calls: dict = {}

    def fake_prepare(item, config):
        calls["prepare"] = True
        return "evalclaw-task:abc", Path("/tmp/work")

    def fake_run_cli(item, target, image, workdir):
        calls["run_image"] = image
        return '{"result": "done"}'

    def fake_score(item, config, image, workdir):
        calls["score_image"] = image
        return 0.75, "partial"

    monkeypatch.setattr(harness_module, "prepare_docker_task", fake_prepare)
    monkeypatch.setattr(openhands_module, "_run_openhands_cli", fake_run_cli)
    monkeypatch.setattr(harness_module, "score_docker_task", fake_score)

    raw, score, reasoning = openhands_module.OpenHandsRunner().run(
        _item({"type": "docker_workspace", "visible_files": {"a.py": "print(1)"}}),
        _target("openhands"),
        BenchmarkConfig(),
    )

    assert calls["prepare"] is True
    assert calls["run_image"] == "evalclaw-task:abc"
    assert calls["score_image"] == "evalclaw-task:abc"
    assert (score, reasoning) == (0.75, "partial")


def test_openhands_env_sets_model_and_image() -> None:
    env = openhands_module._openhands_env(
        _target("openhands"),
        "evalclaw-task:abc",
        Path("/tmp/work"),
    )
    assert env["LLM_MODEL"] == "gpt-5"
    assert env["LLM_API_KEY"] == "k"
    assert env["SANDBOX_BASE_CONTAINER_IMAGE"] == "evalclaw-task:abc"
    assert env["SANDBOX_VOLUMES"] == "/tmp/work:/workspace:rw"


def test_unsupported_harness_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported harness"):
        TargetModelConfig(provider="openai", model="gpt-5", harness="unknown-harness")


def test_tool_constraints_rejected_under_harness(monkeypatch) -> None:
    monkeypatch.setattr(
        harness_module,
        "prepare_docker_task",
        lambda item, config: ("img", Path("/tmp/work")),
    )
    with pytest.raises(RuntimeError, match="tool constraints"):
        openhands_module.OpenHandsRunner().run(
            _item({"type": "docker_workspace", "workspace_tools": ["read_file"]}),
            _target("openhands"),
            BenchmarkConfig(),
        )
