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
