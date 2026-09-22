import errno
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from evalclaw.execution import memory_usage, sandbox


def test_cgroup_disappearing_device_defers_admission(monkeypatch):
    monkeypatch.setattr(memory_usage.subprocess, "check_output", lambda *a, **k: "container\n")
    def read(path, *a, **k):
        raise OSError(errno.ENODEV, "cgroup removed")
    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(memory_usage.MemorySamplePending):
        memory_usage.container_usage("docker")


@pytest.mark.parametrize("failure", [
    memory_usage.MemorySamplePending("transition"), subprocess.TimeoutExpired("docker ps", 30),
])
def test_transient_memory_sample_blocks_admission_then_recovers(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(memory_usage, "process_usage", lambda *a: (10, {}))
    def measure(*args):
        raise failure
    monkeypatch.setattr(memory_usage, "container_usage", measure)
    assert memory_usage.sample_usage(tmp_path, "docker") == (2**63 - 1, 0)
    monkeypatch.setattr(memory_usage, "container_usage", lambda *a: (20, 1))
    used, available = memory_usage.sample_usage(tmp_path, "docker")
    assert used == 30 and available > 0


def test_permanent_memory_sampling_error_is_not_hidden(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_usage, "process_usage", lambda *a: (10, {}))
    def measure(*args):
        raise PermissionError("denied")
    monkeypatch.setattr(memory_usage, "container_usage", measure)
    with pytest.raises(memory_usage.MemoryBudgetError):
        memory_usage.sample_usage(tmp_path, "docker")


@pytest.mark.parametrize("code,timed_out,returncode", [
    ('print("ok")', False, 0),
    ('raise SystemExit(124)', False, 124),
    ('import time; print("started", flush=True); time.sleep(10)', True, 124),
])
def test_python_runtime_budget_is_enforced_inside_sandbox(code, timed_out, returncode):
    result = subprocess.run([sys.executable, "-I", "-c", sandbox._PYTHON_RUNNER, "0.5"],
                            input=code, text=True, capture_output=True, timeout=5)
    payload = json.loads(result.stdout)
    assert payload["timed_out"] == timed_out and payload["returncode"] == returncode
    if timed_out:
        assert payload["stdout"] == "started\n"


@pytest.mark.parametrize("infrastructure_timeout", [False, True])
def test_python_sandbox_separates_startup_and_code_time_and_cleans(monkeypatch, infrastructure_timeout):
    registered, closed = [], []
    monkeypatch.setattr(sandbox, "docker_status", lambda **kw: SimpleNamespace(available=True))
    monkeypatch.setattr(sandbox, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(sandbox, "acquire_image", lambda value, **kw: value)
    monkeypatch.setattr(sandbox, "docker_subprocess_env", lambda _: {})
    monkeypatch.setattr(sandbox, "DockerResourceGuard", lambda *a: SimpleNamespace(
        register=lambda *a: registered.append(a), close=lambda: closed.append(True)))
    def run(command, **kwargs):
        assert kwargs["timeout"] == 130 and command[-1] == "10"
        assert command[command.index("--name") + 1] == registered[0][1]
        if infrastructure_timeout:
            raise subprocess.TimeoutExpired(command, 130)
        return subprocess.CompletedProcess(command, 0, json.dumps(dict(
            returncode=124, stdout="partial", stderr="", timed_out=True)), "")
    monkeypatch.setattr(sandbox.subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        sandbox.run_python_sandbox("anything", timeout=10)
    assert caught.value.timeout == (130 if infrastructure_timeout else 10)
    assert closed == [True]


@pytest.mark.parametrize("declared,expected", [(None, 10), (180, 180)])
def test_python_judge_honours_declared_suite_time(monkeypatch, declared, expected):
    from evalclaw.execution import runner
    from evalclaw.types import BenchmarkConfig, JudgeToolRef
    settings = {'test_code': 'print({model_output})'}
    if declared is not None:
        settings['timeout_seconds'] = declared
    tool = JudgeToolRef(tool='python_tests', config=settings)
    def execute(code, **kwargs):
        assert kwargs['timeout'] == expected
        return 0, 'ok', ''
    monkeypatch.setattr(runner, 'run_python_sandbox', execute)
    assert runner._python_test_evidence(None, 'answer', BenchmarkConfig(), tool=tool)['passed']


@pytest.mark.parametrize("value", [0, -1, True, '180', 1.5, None])
def test_python_judge_rejects_invalid_time_budget(value):
    from pydantic import ValidationError
    from evalclaw.types import JudgeToolRef
    with pytest.raises(ValidationError):
        JudgeToolRef(tool='python_tests', config={'timeout_seconds': value})


@pytest.mark.parametrize("message,expected", [
    ("litellm.MidStreamFallbackError: connection reset by peer", True),
    ("The final model response was interrupted before completion", False),
    ("wrong answer", False),
])
def test_runner_retries_only_transient_target_transport_failures(message, expected):
    from evalclaw.execution.runner import _retryable_target_failure
    from evalclaw.types import ItemResult

    result = ItemResult(
        item_id="item", target_id="target", error=message,
        execution={"stage": "target_execution"},
    )
    assert _retryable_target_failure(result) is expected


def test_runner_does_not_replay_a_completed_task_for_judge_transport_failure():
    from evalclaw.execution.runner import _retryable_target_failure
    from evalclaw.types import ItemResult

    result = ItemResult(
        item_id="item", target_id="target",
        error="APIConnectionError: connection reset by peer",
        execution={"stage": "evaluation"},
    )
    assert not _retryable_target_failure(result)
