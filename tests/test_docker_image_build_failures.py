from __future__ import annotations

import json
import subprocess

import pytest

from evalclaw.construction import research
from evalclaw.execution import docker_images as images
from evalclaw.execution.errors import EvaluationExecutionError
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.types import BenchmarkConfig
from tests.config_helpers import dummy_config_kwargs


@pytest.fixture
def build_context(monkeypatch, tmp_path):
    monkeypatch.setenv(images.DOCKER_BUILD_DIR_ENV_VAR, str(tmp_path / "builds"))
    monkeypatch.setattr(images, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(images, "docker_subprocess_env", lambda _: {})
    context = tmp_path / "context"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\nCOPY missing /file\n")
    return context


@pytest.mark.parametrize("entrypoint", ["builder", "environment"])
@pytest.mark.parametrize("failure", ["recipe", "timeout", "daemon", "launch", "signal"])
def test_build_failure_classification_and_logs(monkeypatch, build_context, entrypoint, failure):
    calls = []

    def run(command, **kwargs):
        calls.append(command[1])
        if command[1] == "info":
            return subprocess.CompletedProcess(command, int(failure == "daemon"), "", "health")
        assert command[1] == "build"
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial", stderr=b"building")
        if failure == "launch":
            raise OSError("cannot launch")
        return subprocess.CompletedProcess(command, -9 if failure == "signal" else 1, "partial", "build error")

    monkeypatch.setattr(images.subprocess, "run", run)
    expected = images.DockerImageBuildError if failure == "recipe" else images.DockerBuildExecutionError
    with pytest.raises(expected) as caught:
        if entrypoint == "builder":
            images.build_docker_image_from_context(build_context, tag="custom", timeout_s=12)
        else:
            images.build_docker_image_if_requested({
                "image_build": {
                    "enabled": True, "tag": "custom", "rebuild": True,
                    "context_dir": str(build_context),
                },
            }, timeout_s=12)
    log, = (build_context.parent / "builds/logs").iterdir()
    record = json.loads((log / "result.json").read_text())
    assert record["image"] == "custom"
    assert record["timeout_s"] == 12
    assert record["timed_out"] is (failure == "timeout")
    assert record["exit_code"] == ({"recipe": 1, "daemon": 1, "signal": -9}.get(failure))
    assert (log / "stdout.log").read_text() == ("" if failure == "launch" else "partial")
    assert (log / "stderr.log").read_text() == {
        "timeout": "building", "launch": "",
    }.get(failure, "build error")
    assert str(log) in str(caught.value)
    assert isinstance(caught.value, EvaluationExecutionError) is (failure != "recipe")
    assert calls == (["build", "info"] if failure in {"recipe", "daemon"} else ["build"])


@pytest.mark.parametrize("reference", ["custom", "custom:latest", "docker.io/library/custom:latest"])
def test_builder_repairs_failed_image_before_using_it(monkeypatch, build_context, reference):
    state = {}
    calls = []
    healthy_build = False

    def run(command, **kwargs):
        assert command[1] in {"build", "info"}
        return subprocess.CompletedProcess(command, int(command[1] == "build" and not healthy_build), "", "COPY error")

    def check(image, command, **kwargs):
        calls.append(kwargs["allow_pull"])
        return images.DockerImageCheckResult(image, command, 0)

    monkeypatch.setattr(images.subprocess, "run", run)
    monkeypatch.setattr(research, "run_docker_image_check", check)
    monkeypatch.setattr(research, "start_inspection_container", lambda *a, **kw: pytest.fail("failed image used"))

    def tool(name, args):
        return research._execute_task_builder_tool(
            ToolCall(id=name, name=name, arguments=args), BenchmarkConfig(),
            work_dir=build_context, tool_state=state, max_chars=50_000,
        )

    build = {"dockerfile_path": "Dockerfile", "tag": "custom"}
    assert tool("build_image", build).error == "image_build_failed"
    assert tool("run_image_check", {"image": reference, "command": "true"}).error == "tool_error"
    assert tool("start_inspect_container", {"image": reference}).error == "tool_error"
    assert calls == []
    # A public image is still usable while the custom build needs repair.
    assert tool("run_image_check", {"image": "python:3.11-slim", "command": "true"}).error is None
    healthy_build = True
    assert tool("build_image", build).error is None
    assert tool("run_image_check", {"image": reference, "command": "true"}).error is None
    assert calls == [True, False]
    # A failed rebuild must not accidentally use the previous image under the same tag.
    healthy_build = False
    assert tool("build_image", build).error == "image_build_failed"
    assert tool("run_image_check", {"image": reference, "command": "true"}).error == "tool_error"
    assert calls == [True, False]


def test_builder_build_timeout_is_fatal(monkeypatch, build_context):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr="exporting")

    monkeypatch.setattr(images.subprocess, "run", timeout)
    with pytest.raises(images.DockerBuildExecutionError):
        research._execute_task_builder_tool(
            ToolCall(id="build", name="build_image", arguments={"dockerfile_path": "Dockerfile"}),
            BenchmarkConfig(), work_dir=build_context, tool_state={}, max_chars=1000,
        )


@pytest.mark.parametrize("tag", ["private-image:1", ""])
@pytest.mark.parametrize("failure", ["recipe", "timeout", "daemon", "launch", "signal"])
def test_commit_failure_registers_local_image_and_never_downloads_it(monkeypatch, build_context, tag, failure):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "info":
            return subprocess.CompletedProcess(command, int(failure == "daemon"), b"", b"")
        assert command[1] == "commit"
        assert kwargs["timeout"] == 7200
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if failure == "launch":
            raise OSError("launch failed")
        return subprocess.CompletedProcess(command, -9 if failure == "signal" else 1, "", "commit failed")
    monkeypatch.setattr(images.subprocess, "run", run)
    monkeypatch.setattr(research, "start_inspection_container", lambda *a, **kw: pytest.fail("download after failed commit"))
    state = {"inspect_container": "container", "last_image": tag,
             "local_images": {research._builder_image_key(tag): True} if tag else {}}
    config = BenchmarkConfig(docker_build_timeout_s=7200)
    call = ToolCall(id="commit", name="commit_inspect_container", arguments={"tag": tag})
    if failure == "recipe":
        result = research._execute_task_builder_tool(call, config, tool_state=state, max_chars=1000)
        assert result.error == "image_build_failed"
    else:
        with pytest.raises(images.DockerBuildExecutionError):
            research._execute_task_builder_tool(call, config, tool_state=state, max_chars=1000)
    image = commands[0][-1]
    assert state["last_image"] == ""
    assert state["inspect_container"] == "container"
    assert state["local_images"][research._builder_image_key(image)] is False
    rejected = research._execute_task_builder_tool(
        ToolCall(id="inspect", name="start_inspect_container", arguments={"image": image}),
        config, work_dir=build_context, tool_state=state, max_chars=1000,
    )
    assert rejected.error == "tool_error"
    # Retrying a recoverable commit publishes the image only on success.
    monkeypatch.setattr(images.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 0, "sha256:ok", ""))
    monkeypatch.setattr(research, "stop_inspection_container", lambda *a, **kw: None)
    recovered = research._execute_task_builder_tool(
        ToolCall(id="commit", name="commit_inspect_container", arguments={"tag": image}),
        config, tool_state=state, max_chars=1000,
    )
    assert recovered.error is None
    assert state["last_image"] == image
    assert state["local_images"][research._builder_image_key(image)] is True
    assert "inspect_container" not in state


@pytest.mark.parametrize("requested,expected", [(900, 5400), (7200, 7200), (None, 5400)])
def test_builder_cannot_shorten_runtime_build_allowance(monkeypatch, build_context, requested, expected):
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == expected
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(images.subprocess, "run", timeout)
    args = {"dockerfile_path": "Dockerfile"}
    if requested is not None:
        args["timeout_s"] = requested
    with pytest.raises(images.DockerBuildExecutionError):
        research._execute_task_builder_tool(
            ToolCall(id="build", name="build_image", arguments=args),
            BenchmarkConfig(docker_build_timeout_s=5400),
            work_dir=build_context, tool_state={}, max_chars=1000,
        )


def test_timeout_stops_tool_loop_before_following_image_check(monkeypatch, build_context):
    config = BenchmarkConfig(**dummy_config_kwargs(), output_dir=str(build_context.parent))
    monkeypatch.setattr(research, "task_builder_work_dir", lambda *a: build_context)
    calls = [
        ToolCall(id="build", name="build_image", arguments={"dockerfile_path": "Dockerfile", "tag": "custom"}),
        ToolCall(id="check", name="run_image_check", arguments={"image": "custom", "command": "true"}),
    ]
    model_calls = []

    def model(*a, **kw):
        model_calls.append(True)
        return TargetToolModelResponse(
            adapter="openai", content="", tool_calls=calls,
            assistant_message={"role": "assistant", "content": ""}, raw_response={},
        )

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr="exporting")

    monkeypatch.setattr(research, "call_orchestrator_with_tools", model)
    monkeypatch.setattr(images.subprocess, "run", timeout)
    monkeypatch.setattr(research, "run_docker_image_check", lambda *a, **kw: pytest.fail("check after timeout"))
    with pytest.raises(images.DockerBuildExecutionError):
        research.run_task_builder_tools(
            {}, system_prompt="Build a task", config=config,
            include_source_tools=False, include_image_tools=True,
        )
    assert model_calls == [True]


@pytest.mark.parametrize("inspection", [False, True])
def test_local_image_start_disables_implicit_docker_pull(monkeypatch, build_context, inspection):
    from types import SimpleNamespace

    commands = []
    acquired = []

    def acquire(image, **kwargs):
        acquired.append(kwargs["allow_pull"])
        return image

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "container", "")

    monkeypatch.setattr(images, "acquire_image", acquire)
    monkeypatch.setattr(images, "image_pull_options", lambda: [])
    monkeypatch.setattr(images, "run_bounded", run)
    monkeypatch.setattr(images.subprocess, "run", run)
    monkeypatch.setattr(images, "DockerResourceGuard", lambda *a: SimpleNamespace(register=lambda *a: None, close=lambda: None))
    if inspection:
        images.start_inspection_container("custom", network="none", allow_pull=False)
    else:
        images.run_docker_image_check("custom", "true", allow_pull=False)
    assert acquired == [False]
    assert len(commands) == 1
    assert commands[0][commands[0].index("--pull") + 1] == "never"
