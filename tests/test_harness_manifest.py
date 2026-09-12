"""Tests for the manifest-driven harness runner."""
from __future__ import annotations

import shlex
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
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module, "prepare_docker_task", fake_prepare)
    monkeypatch.setattr(harness_module, "score_docker_task", fake_score)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
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
    command = calls["command"]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "/tmp/work:/workspace" in command
    assert command[command.index("-w") + 1] == "/workspace"
    assert "MY_AGENT_MODEL=gpt-5" in command
    assert "MY_AGENT_KEY=k" in command
    assert command[-2] == "-lc"
    assert shlex.split(command[-1]) == [
        "my-agent", "--task", "Write a function.", "--image", "img", "--workdir", "/workspace",
    ]


def test_builtin_harnesses_registered() -> None:
    expected = {"openhands", "miniswe", "codex", "claude-code", "cursor", "grok", "opencode", "aider", "goose", "openclaw"}
    for name in expected:
        assert harness_module.get_harness(name).name == name


def test_config_args_rendered_into_command(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["stdin"] = kwargs.get("stdin")
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="codex",
        run="codex exec {config_args} -m {model} {task}",
        model_env={"api_key": "OPENAI_API_KEY"},
        config_args=(
            "-c model_provider=evalclaw",
            "-c model_providers.evalclaw.base_url={base_url}",
            "-c model_providers.evalclaw.env_key=OPENAI_API_KEY",
        ),
        timeout=60,
    )
    target = TargetModelConfig(
        provider="openai", model="gpt-5", api_key="k", base_url="https://api.openai.com/v1"
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), target, BenchmarkConfig(), "img", Path("/tmp/work")
    )

    assert shlex.split(calls["command"][-1]) == [
        "codex",
        "exec",
        "-c",
        "model_provider=evalclaw",
        "-c",
        "model_providers.evalclaw.base_url=https://api.openai.com/v1",
        "-c",
        "model_providers.evalclaw.env_key=OPENAI_API_KEY",
        "-m",
        "gpt-5",
        "Write a function.",
    ]
    assert calls["stdin"] == harness_module.subprocess.DEVNULL


def test_manifest_launch_runs_in_container(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={}, timeout=60
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work")
    )
    command = calls["command"]
    assert command[command.index("-w") + 1] == "/workspace"
    assert "/tmp/work:/workspace" in command
    assert command[-2:] == ["-lc", shlex.join(["my-agent", "Write a function."])]


def test_manifest_launch_mounts_harness_image(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={}, timeout=60,
        harness_image="evalclaw-openclaw:latest",
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work")
    )

    command = calls["command"]
    assert "--mount" in command
    assert "type=image,src=evalclaw-openclaw:latest,dst=/opt/harness,readonly" in command
    assert command[-1].startswith("cp -a /opt/harness/root/.openclaw /root/")
    assert "export PATH=/opt/harness/usr/local/bin:$PATH;" in command[-1]


def test_manifest_launch_routes_model_through_gateway(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    def fake_start(docker, upstream):
        return "evalclaw-net", "evalclaw-gw", "http://evalclaw-gw:18080"

    def fake_stop(docker, network, gateway):
        calls["stopped"] = (network, gateway)

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(harness_module, "_start_model_gateway", fake_start)
    monkeypatch.setattr(harness_module, "_stop_model_gateway", fake_stop)

    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={"base_url": "OPENAI_BASE_URL"},
        timeout=60, gateway=True,
    )
    target = TargetModelConfig(
        provider="openai", model="gpt-5", api_key="k", base_url="https://api.deepseek.com"
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), target, BenchmarkConfig(), "img", Path("/tmp/work")
    )

    command = calls["command"]
    assert "--network" in command and "evalclaw-net" in command
    assert "OPENAI_BASE_URL=http://evalclaw-gw:18080" in command
    assert calls["stopped"] == ("evalclaw-net", "evalclaw-gw")


def test_manifest_launch_overrides_provider_baseurl_via_config(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    def fake_start(docker, upstream):
        return "evalclaw-net", "evalclaw-gw", "http://evalclaw-gw:18080"

    def fake_stop(docker, network, gateway):
        calls["stopped"] = (network, gateway)

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(harness_module, "_start_model_gateway", fake_start)
    monkeypatch.setattr(harness_module, "_stop_model_gateway", fake_stop)

    manifest = harness_module.ManifestHarness(
        name="openclaw", run="openclaw agent exec --model deepseek/{model} {task}",
        model_env={"api_key": "DEEPSEEK_API_KEY"}, harness_image="evalclaw-openclaw:latest",
        gateway=True, gateway_provider="deepseek",
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work")
    )

    shell = calls["command"][-1]
    assert "openclaw config set models.providers.deepseek.baseUrl http://evalclaw-gw:18080" in shell
    assert calls["stopped"] == ("evalclaw-net", "evalclaw-gw")
