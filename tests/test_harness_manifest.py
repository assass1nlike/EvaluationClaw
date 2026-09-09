"""Tests for the manifest-driven harness runner."""
from __future__ import annotations

from pathlib import Path

import pytest

from evalclaw.runners import harness as harness_module
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    TargetModelConfig,
    TaskType,
)


def _item() -> BenchmarkItem:
    return BenchmarkItem(
        id="task_1",
        dimension_id="d1",
        task_type=TaskType.agent,
        prompt="Write a function.",
        metadata={"agent_env": {"type": "docker_workspace"}},
    )


def _target() -> TargetModelConfig:
    return TargetModelConfig(provider="openai", model="gpt-5", api_key="k")


def _write_manifest(tmp_path, name: str = "my-harness") -> Path:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"name: {name}\n"
        "run: 'my-agent --task {task} --image {image} --workdir {workdir}'\n"
        "model_env:\n"
        "  model: MY_AGENT_MODEL\n"
        "  api_key: MY_AGENT_KEY\n"
        "timeout: 60\n",
        encoding="utf-8",
    )
    return manifest


def test_load_manifest_harness_registers(tmp_path) -> None:
    name = harness_module.load_manifest_harness(_write_manifest(tmp_path))
    assert name == "my-harness"
    assert "my-harness" in harness_module.SUPPORTED_HARNESSES
    assert harness_module._HARNESS_RUNNERS["my-harness"].name == "my-harness"


def test_load_manifest_harness_requires_name_and_run(tmp_path) -> None:
    manifest = tmp_path / "bad.yaml"
    manifest.write_text("name: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="name and run"):
        harness_module.load_manifest_harness(manifest)


def test_manifest_runner_launches_and_scores(monkeypatch) -> None:
    calls: dict = {}

    def fake_prepare(item, config):
        return "img", Path("/tmp/work")

    def fake_score(item, config, image, workdir):
        return 0.5, "partial"

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["env"] = kwargs.get("env", {})
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module, "prepare_docker_task", fake_prepare)
    monkeypatch.setattr(harness_module, "score_docker_task", fake_score)
    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)

    manifest = harness_module.ManifestHarness(
        name="my-harness",
        run="my-agent --task {task} --image {image} --workdir {workdir}",
        model_env={"model": "MY_AGENT_MODEL", "api_key": "MY_AGENT_KEY"},
        timeout=60,
    )
    raw, score, reasoning = harness_module.ManifestHarnessRunner(manifest).run(
        _item(), _target(), BenchmarkConfig()
    )

    assert (score, reasoning) == (0.5, "partial")
    assert calls["command"] == [
        "my-agent",
        "--task",
        "Write a function.",
        "--image",
        "img",
        "--workdir",
        "/tmp/work",
    ]
    assert calls["env"]["MY_AGENT_MODEL"] == "gpt-5"
    assert calls["env"]["MY_AGENT_KEY"] == "k"


def test_builtin_harnesses_registered() -> None:
    expected = {"openhands", "miniswe", "codex", "claude-code", "cursor", "grok", "opencode", "aider", "goose"}
    for name in expected:
        assert harness_module.get_harness(name).name == name


def test_config_args_rendered_into_command(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["stdin"] = kwargs.get("stdin")
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    manifest = harness_module.ManifestHarness(
        name="codex",
        run="codex exec {config_args} -m {model} {task}",
        model_env={"api_key": "SUDOCODE_API_KEY"},
        config_args=(
            "-c model_provider=sudocode",
            "-c model_providers.sudocode.base_url={base_url}",
            "-c model_providers.sudocode.env_key=SUDOCODE_API_KEY",
        ),
        timeout=60,
    )
    target = TargetModelConfig(
        provider="openai", model="gpt-5", api_key="k", base_url="https://api.sudocode.chat/v1"
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), target, "img", Path("/tmp/work")
    )

    assert calls["command"] == [
        "codex",
        "exec",
        "-c",
        "model_provider=sudocode",
        "-c",
        "model_providers.sudocode.base_url=https://api.sudocode.chat/v1",
        "-c",
        "model_providers.sudocode.env_key=SUDOCODE_API_KEY",
        "-m",
        "gpt-5",
        "Write a function.",
    ]
    assert calls["stdin"] == harness_module.subprocess.DEVNULL


def test_manifest_launch_sets_cwd(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls["cwd"] = kwargs.get("cwd")
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={}, timeout=60
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), "img", Path("/tmp/work")
    )
    assert calls["cwd"] == "/tmp/work"
