import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from agents.shared.agent_sandbox import DockerSandbox, SandboxSpec
from local.eval_runtime import RecordedDockerSandbox, infrastructure_errors


def test_dedicated_endpoint_does_not_inherit_default_context(monkeypatch, tmp_path):
    from local import eval_docker
    endpoint = tmp_path / "docker.sock"
    endpoint.touch()
    monkeypatch.setattr(eval_docker, "SOCKET", endpoint)
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setenv("DOCKER_CONTEXT", "default")
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setenv("DOCKER_CERT_PATH", "/old/cert")
    eval_docker.use_dedicated_docker()
    assert eval_docker.os.environ["DOCKER_HOST"] == "unix://" + str(endpoint)
    assert all(name not in eval_docker.os.environ for name in
               ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"))


def test_preflight_rejects_shared_docker_before_other_checks():
    from local.eval_runtime import check_host
    with patch("local.eval_runtime.subprocess.check_output", return_value="/data3/docker\n"):
        with pytest.raises(RuntimeError):
            check_host()


def test_start_failure_is_recorded_without_retry_or_suppression():
    with TemporaryDirectory() as directory:
        logs = Path(directory) / "episodes/test/cli_harness"
        sandbox = RecordedDockerSandbox(SandboxSpec("test", "test", "", ""), logs)
        error = subprocess.TimeoutExpired(["docker", "run"], 120)
        with patch.object(DockerSandbox, "start", side_effect=error) as start:
            with pytest.raises(subprocess.TimeoutExpired) as raised:
                sandbox.start(12, "token", {"MODEL": "test"})
        assert raised.value is error
        start.assert_called_once_with(12, "token", {"MODEL": "test"})
        events = infrastructure_errors(directory)
        assert len(events) == 1
        assert events[0]["stage"] == "start"
        assert events[0]["timeout_seconds"] == 120


def test_model_timeout_preserves_command_budget_and_is_not_startup_failure():
    with TemporaryDirectory() as directory:
        logs = Path(directory) / "episodes/test/cli_harness"
        sandbox = RecordedDockerSandbox(SandboxSpec("test", "test", "", ""), logs)
        with patch.object(DockerSandbox, "exec", side_effect=subprocess.TimeoutExpired("command", 3600)) as execute:
            with pytest.raises(subprocess.TimeoutExpired):
                sandbox.exec("original command", 3600)
        execute.assert_called_once_with("original command", 3600)
        assert infrastructure_errors(directory) == []
        assert json.loads((logs / "sandbox-events.jsonl").read_text())["stage"] == "exec"


def test_successful_teardown_is_called_once():
    with TemporaryDirectory() as directory:
        sandbox = RecordedDockerSandbox(SandboxSpec("test", "test", "", ""), Path(directory))
        with patch.object(DockerSandbox, "stop") as stop:
            sandbox.stop()
        stop.assert_called_once_with()
        assert "error" not in json.loads((Path(directory) / "sandbox-events.jsonl").read_text())
