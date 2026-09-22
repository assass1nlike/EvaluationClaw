"""Tests for the manifest-driven harness runner."""
from __future__ import annotations

import shlex
import threading
from pathlib import Path

import pytest

from evalclaw.runners import harness as harness_module
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    ReferenceTrajectoryStep,
    TargetModelConfig,
    TaskAsset,
    TaskBlueprint,
    TaskDefinition,
    TaskType,
)


@pytest.fixture(autouse=True)
def _mockable_bounded_runner(monkeypatch):
    class Guard:
        def __init__(self, *args):
            pass

        def register(self, *args):
            pass

        def close(self):
            pass

    monkeypatch.setattr(harness_module, "DockerResourceGuard", Guard)
    def run(command, **kwargs):
        kwargs.pop("failure_markers", None)
        return harness_module.subprocess.run(
            command,
            capture_output=True,
            text=True,
            **kwargs,
        )

    monkeypatch.setattr(harness_module, "_run_bounded", run)


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


@pytest.mark.parametrize("caller", ["builder", "environment"])
def test_scoring_service_failure_does_not_reject_task(monkeypatch, tmp_path, caller):
    import json

    from evalclaw.construction import suite
    from evalclaw.execution import environment_claw
    from evalclaw.execution.errors import EvaluationExecutionError

    def blocked(*args, **kwargs):
        raise EvaluationExecutionError("Judge response validation failed")

    monkeypatch.setattr(harness_module, "preflight_harness_environments", blocked)
    item = _item()
    task = TaskDefinition(id=item.id, dimension_id=item.dimension_id, task_type=TaskType.agent,
        title="Task", prompt=item.prompt, environment=item.metadata["agent_env"])
    report = environment_claw.EnvironmentClawReport(enabled=True)
    with pytest.raises(EvaluationExecutionError):
        if caller == "builder":
            suite._preflight_builder_environments([task],
                dimension=EvalDimension(id="d1", name="Work", description="Work", approach="Work"),
                blueprint=TaskBlueprint(id="b1", dimension_id="d1", title="Work"),
                resources=[], config=BenchmarkConfig(), trace_dir=tmp_path)
        else:
            environment_claw._preflight_executable_items(report, [item], BenchmarkConfig(), trace_dir=tmp_path)
    assert not report.blocked_item_ids
    failure = json.loads(next(tmp_path.rglob("failure.json")).read_text())
    assert failure["status"] == "evaluation_blocked"


@pytest.mark.parametrize("phase", ["construction", "execution"])
def test_judge_response_failure_blocks_only_its_item(monkeypatch, tmp_path, phase):
    import json

    from evalclaw.construction import suite
    from evalclaw.execution import environment_claw
    from evalclaw.execution.errors import JudgeResponseError

    visited = []

    def preflight(item, *args, **kwargs):
        visited.append(item.id)
        if item.id == "bad":
            raise JudgeResponseError("Missing criterion: safety")
        return [{"status": "passed", "harness": "openclaw"}]

    monkeypatch.setattr(harness_module, "preflight_harness_environments", preflight)
    items = [_item().model_copy(update={"id": key}) for key in ["bad", "good"]]
    config = BenchmarkConfig(targets=[_target().model_copy(update={"harness": "openclaw"})])
    if phase == "construction":
        tasks = [TaskDefinition(id=i.id, dimension_id=i.dimension_id, task_type=TaskType.agent,
            title="Task", prompt=i.prompt, environment=i.metadata["agent_env"]) for i in items]
        issues, failed, blocked = suite._preflight_builder_environments(tasks,
            dimension=EvalDimension(id="d1", name="Work", description="Work", approach="Work"),
            blueprint=TaskBlueprint(id="b1", dimension_id="d1", title="Work"),
            resources=[], config=config, trace_dir=tmp_path)
        assert issues == [] and failed == set()
        assert blocked == {"bad": "Missing criterion: safety"}
    else:
        report = environment_claw.EnvironmentClawReport(enabled=True)
        environment_claw._preflight_executable_items(report, items, config, trace_dir=tmp_path)
        assert report.blocked_item_ids == ["bad"]
        assert report.probes[0].data["status"] == "evaluation_blocked"
    assert visited == ["bad", "good"]
    assert json.loads((tmp_path / "bad/failure.json").read_text())["status"] == "evaluation_blocked"


@pytest.mark.parametrize("phase", ["construction", "execution"])
@pytest.mark.parametrize("fail_last", [False, True])
def test_pipeline_preflights_every_selected_harness(monkeypatch, tmp_path, phase, fail_last):
    from evalclaw.construction import suite
    from evalclaw.execution import environment_claw

    names = ["openclaw", "openhands", "codex", "claude-code"]
    config = BenchmarkConfig(targets=[
        TargetModelConfig(provider="openai", model="test", harness=name) for name in names
    ])
    calls = []

    class Runner:
        def preflight(self, item, target, config, *, artifact_dir):
            calls.append((item.id, target.harness, artifact_dir))
            if fail_last and target.harness == names[-1]:
                raise RuntimeError("incompatible runtime")
            return {"harness": target.harness, "status": "passed", "baseline_score": 0}

    def unexpected_native(*args):
        raise AssertionError("external targets must use their actual harness preflight")

    monkeypatch.setattr(harness_module, "get_harness", lambda name: Runner())
    monkeypatch.setattr(suite, "build_agent_environment", unexpected_native)
    monkeypatch.setattr(environment_claw, "build_agent_environment", unexpected_native)
    if phase == "construction":
        task = TaskDefinition(
            id="task_1", dimension_id="d1", task_type=TaskType.agent,
            title="Task", prompt="Do the task.", environment={"type": "docker_workspace"},
        )
        issues, failed_ids, blocked = suite._preflight_builder_environments(
            [task], dimension=EvalDimension(id="d1", name="d1", description="d", approach="a"),
            blueprint=TaskBlueprint(id="b1", title="Task"), resources=[],
            config=config, trace_dir=tmp_path,
        )
        assert not blocked
    else:
        report = environment_claw.EnvironmentClawReport(enabled=True)
        environment_claw._preflight_executable_items(
            report, [_item()], config, trace_dir=tmp_path,
        )
        issues, failed_ids = report.blocking_errors, set(report.blocked_item_ids)
        if not fail_last:
            assert [probe.data["harness"] for probe in report.probes] == names

    assert [name for _, name, _ in calls] == names
    assert len({path for _, _, path in calls}) == len(names)
    assert bool(issues) == fail_last
    assert failed_ids == ({"task_1"} if fail_last else set())


def test_harness_prompt_does_not_expose_reference_trajectory() -> None:
    item = _item().model_copy(
        update={
            "reference_trajectory": [
                ReferenceTrajectoryStep(
                    action="Read the hidden solution.",
                    tool="read_file",
                    arguments={"path": "solution.txt"},
                )
            ]
        }
    )

    prompt = harness_module._harness_prompt(item)

    assert prompt == "Write a function."
    assert "hidden solution" not in prompt


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
    calls: dict = {"events": []}

    def fake_prepare(item, config):
        return "img", Path("/tmp/work")

    def fake_score(item, config, image, workdir, *, evidence=None, container_name=None):
        calls["evidence"] = evidence
        calls["score_container"] = container_name
        calls["events"].append("score")
        return 0.5, "partial"

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        if command[1] == "create":
            calls["env"] = kwargs.get("env")
        elif command[1:3] == ["rm", "-f"]:
            calls["events"].append("remove_container")
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    def fake_start(docker, upstream, **kwargs):
        calls["gateway"] = kwargs
        return "evalclaw-net", "evalclaw-gw", "http://evalclaw-gw:18080"

    monkeypatch.setattr(harness_module, "prepare_docker_task", fake_prepare)
    monkeypatch.setattr(harness_module, "score_docker_task", fake_score)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "_start_model_gateway", fake_start)
    monkeypatch.setattr(
        harness_module,
        "_stop_model_gateway",
        lambda *args: calls["events"].append("stop_gateway"),
    )

    manifest = harness_module.ManifestHarness(
        name="my-harness",
        run="my-agent --key {api_key} --task {task} --image {image} --workdir {workdir}",
        model_env={"model": "MY_AGENT_MODEL", "api_key": "MY_AGENT_KEY"},
        timeout=60,
        gateway=True,
    )
    raw, score, reasoning = harness_module.ManifestHarnessRunner(manifest).run(
        _item(), _target(), BenchmarkConfig()
    )

    assert (score, reasoning) == (0.5, "partial")
    create = next(command for command in calls["commands"] if command[1] == "create")
    target_exec = next(
        command
        for command in calls["commands"]
        if command[1] == "exec" and "my-agent" in command[-1]
    )
    assert "/tmp/work:/workspace" in create
    assert create[create.index("-w") + 1] == "/workspace"
    assert "MY_AGENT_MODEL" in create
    assert "MY_AGENT_KEY" in create
    assert all("=gpt-5" not in arg and "=k" not in arg for arg in create)
    assert calls["env"]["MY_AGENT_MODEL"] == "gpt-5"
    assert calls["env"]["MY_AGENT_KEY"] == "evalclaw-gateway"
    assert calls["gateway"]["api_key"] == "k"
    assert calls["evidence"]["target_execution"]["raw_output"] == "done"
    assert calls["evidence"]["target_execution"]["stderr"] == ""
    assert calls["evidence"]["schema_version"] == "evalclaw.evaluator_evidence.v1"
    assert calls["score_container"] == create[create.index("--name") + 1]
    assert calls["events"] == ["score", "remove_container", "stop_gateway"]
    assert target_exec[target_exec.index("--user") + 1] == harness_module._target_container_user()
    assert target_exec[-2] == "-lc"
    assert shlex.split(target_exec[-1].split("; ")[-1]) == [
        "exec", "my-agent", "--key", "evalclaw-gateway", "--task", "Write a function.",
        "--image", "img", "--workdir", "/workspace",
    ]


def test_task_preflight_uses_one_prepared_container_without_target_inference(monkeypatch, tmp_path):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "ready", "stderr": ""})()

    monkeypatch.setattr(harness_module, "prepare_docker_task", lambda *args: ("img", tmp_path))
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(harness_module, "_run_bounded", run)
    monkeypatch.setattr(harness_module.subprocess, "run", run)

    def score(item, config, image, workdir, *, evidence, container_name):
        create = next(command for command in commands if command[1] == "create")
        assert container_name == create[create.index("--name") + 1]
        assert evidence["termination"]["status"] == "preflight"
        assert evidence["target_execution"]["raw_output"] == ""
        return 0, "No answer yet"

    monkeypatch.setattr(harness_module, "score_docker_task", score)
    item = _item()
    item.metadata["agent_env"]["setup_commands"] = ["prepare-fixture"]
    runner = harness_module.ManifestHarnessRunner(harness_module.ManifestHarness(
        name="test", run="must-not-execute", model_env={}, preflight=("check-harness",),
    ))
    assert runner.preflight(item, _target(), BenchmarkConfig())["baseline_score"] == 0
    assert sum(command[1] == "create" for command in commands) == 1
    setup = next(i for i, command in enumerate(commands) if "prepare-fixture" in command[-1])
    check = next(i for i, command in enumerate(commands) if command[-1] == "check-harness")
    assert setup < check
    assert commands[check][commands[check].index("--user") + 1] == harness_module._target_container_user()
    assert not any("must-not-execute" in command[-1] for command in commands)


@pytest.mark.parametrize("returncode,output", [(0, "not JSON"), (1, "Traceback"), (2, '{"score":0}')])
def test_structured_evaluator_failure_is_not_a_model_score(monkeypatch, tmp_path, returncode, output):
    item = _item()
    item.metadata["agent_env"].update({
        "test_command": "evaluate-task", "evaluation": {"result_format": "json_on_stdout"},
    })

    def run(command, **kwargs):
        grading = "evaluate-task" in command[-1]
        return type("Proc", (), {
            "returncode": returncode if grading else 0, "stdout": output if grading else "", "stderr": "",
        })()

    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(harness_module, "_run_bounded", run)
    with pytest.raises(RuntimeError, match="valid result"):
        harness_module.score_docker_task(item, BenchmarkConfig(), "img", tmp_path, container_name="fixture")


def test_manifest_formats_model_environment_value(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        if command[1] == "create":
            calls["env"] = kwargs.get("env")
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="x",
        run="my-agent {task}",
        model_env={"model": "LLM_MODEL"},
        model_template="{provider}/{model}",
    )

    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work")
    )

    create = next(command for command in calls["commands"] if command[1] == "create")
    assert "LLM_MODEL" in create
    assert calls["env"]["LLM_MODEL"] == "openai/gpt-5"


def test_gateway_keeps_upstream_key_out_of_docker_argv(monkeypatch) -> None:
    calls: list[tuple[list[str], dict]] = []

    def fake_docker(docker, args, **kwargs):
        calls.append((args, kwargs))
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(harness_module, "_docker", fake_docker)
    monkeypatch.setattr(harness_module.time, "sleep", lambda _: None)

    network, gateway, _ = harness_module._start_model_gateway(
        "docker",
        "https://api.example.test",
        api_key="secret-key",
        provider="anthropic",
        model="claude-test",
    )

    launch_args, launch_kwargs = next(call for call in calls if call[0][0] == "run")
    assert all("secret-key" not in arg for arg in launch_args)
    assert launch_kwargs["extra_env"]["EVALCLAW_UPSTREAM_API_KEY"] == "secret-key"
    assert launch_args[launch_args.index("--provider") + 1] == "anthropic"
    assert launch_args[launch_args.index("--model") + 1] == "claude-test"
    assert ["network", "connect", network + "-egress", gateway] in [args for args, _ in calls]
    assert not any(args[:3] == ["network", "connect", "bridge"] for args, _ in calls)
    harness_module._stop_model_gateway("docker", network, gateway)
    assert ["network", "rm", network + "-egress"] in [args for args, _ in calls]


def test_manifest_rejects_credential_without_gateway() -> None:
    manifest = harness_module.ManifestHarness(
        name="x", run="agent {task}", model_env={"api_key": "API_KEY"}
    )

    with pytest.raises(RuntimeError, match="must use an API gateway"):
        harness_module.ManifestHarnessRunner(manifest)._validate_target(_target())


@pytest.mark.parametrize("declared", [None, 128, 512, -1])
def test_task_process_limit_is_applied_only_when_declared(declared):
    limits = {} if declared is None else {"pids": declared}
    options = harness_module._task_container_options({"resource_limits": limits})
    if declared is None:
        assert '--pids-limit' not in options
    else:
        assert options[options.index('--pids-limit') + 1] == str(declared)


def test_manifest_rejects_failure_marker_despite_zero_exit(monkeypatch) -> None:
    monkeypatch.setattr(
        harness_module.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Proc", (), {"returncode": 0, "stdout": "ConversationErrorEvent", "stderr": ""}
        )(),
    )
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={},
        failure_markers=("ConversationErrorEvent",),
    )

    with pytest.raises(RuntimeError, match="reported an execution error"):
        harness_module.ManifestHarnessRunner(manifest)._launch(
            _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work")
        )


@pytest.mark.parametrize("kill_fails", [False, True])
def test_manifest_timeout_does_not_expose_command_or_credentials(monkeypatch, kill_fails) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        if command[1] == "kill" and kill_fails:
            raise harness_module.subprocess.TimeoutExpired(command, 120)
        if command[1] == "exec" and "my-agent" in command[-1]:
            calls["target"] = command
            raise harness_module.subprocess.TimeoutExpired(command, 60)
        if command[1:3] == ["rm", "-f"]:
            calls["cleanup"] = command
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={"api_key": "API_KEY"}, timeout=60
    )

    capture = {}
    with pytest.raises(
        harness_module.HarnessTimeoutError, match="timed out after 60 seconds"
    ) as caught:
        harness_module.ManifestHarnessRunner(manifest)._launch(
            _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work"), capture=capture
        )

    assert "API_KEY" not in str(caught.value)
    assert "k" not in str(caught.value)
    harness_module.cleanup_harness_session(capture)
    name = calls["target"][calls["target"].index("sh") - 1]
    assert calls["cleanup"] == ["docker", "rm", "-f", name]
    assert bool(capture.get("cleanup_error")) == kill_fails


@pytest.mark.parametrize(
    "error",
    [
        harness_module.HarnessTimeoutError(
            "x", 60, "partial secret-key", "warning secret-key"
        ),
        harness_module.HarnessExecutionError(
            "Harness 'x' failed", "partial secret-key", "warning secret-key"
        ),
    ],
)
def test_failed_output_is_saved_and_redacted(monkeypatch, tmp_path, error) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setattr(harness_module, "prepare_docker_task", lambda *args: ("img", workdir))
    monkeypatch.setattr(
        harness_module.ManifestHarnessRunner,
        "_preflight",
        lambda *args: [],
    )
    monkeypatch.setattr(
        harness_module.ManifestHarnessRunner,
        "_launch",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        harness_module.ManifestHarnessRunner,
        "_image_identity",
        lambda self, config, image: {"name": image} if image else None,
    )
    artifact_dir = tmp_path / "episode"
    runner = harness_module.ManifestHarnessRunner(
        harness_module.ManifestHarness(name="x", run="agent {task}", model_env={})
    )
    target = _target().model_copy(update={"api_key": "secret-key"})

    with pytest.raises(type(error)):
        runner.run(_item(), target, BenchmarkConfig(), artifact_dir=artifact_dir)

    assert (artifact_dir / "x-output.txt").read_text() == "partial [REDACTED]"
    assert (artifact_dir / "x-stderr.txt").read_text() == "warning [REDACTED]"
    evidence = harness_module.json.loads((artifact_dir / "execution-failure.json").read_text())
    assert evidence["target_execution"]["raw_output"] == "partial [REDACTED]"
    assert evidence["target_execution"]["tool_call_count"] is None
    assert evidence["failure"]["stderr"] == "warning [REDACTED]"


def test_manifest_failure_redacts_credentials(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        if command[1] == "exec" and "my-agent" in command[-1]:
            return type(
                "Proc", (), {"returncode": 1, "stdout": "", "stderr": "failure: secret-key"}
            )()
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        harness_module.subprocess,
        "run",
        fake_run,
    )
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={"api_key": "API_KEY"}
    )
    target = _target().model_copy(update={"api_key": "secret-key"})

    with pytest.raises(RuntimeError) as caught:
        harness_module.ManifestHarnessRunner(manifest)._launch(
            _item(), target, BenchmarkConfig(), "img", Path("/tmp/work")
        )

    assert "secret-key" not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)


def test_openclaw_preserves_cleanup_error_after_successful_stop(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        if command[1] == "exec" and "openclaw agent exec" in command[-1]:
            return type(
                "Proc",
                (),
                {
                    "returncode": 1,
                    "stdout": '{"ok":true,"final":"done"}',
                    "stderr": (
                        "run ended with stopReason=stop\n"
                        "Agent runtime cleanup did not settle"
                    ),
                },
            )()
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        harness_module.subprocess,
        "run",
        fake_run,
    )
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="openclaw", run="openclaw agent exec {task}", model_env={}
    )

    capture = {}
    output = harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work"), capture=capture
    )
    assert output == '{"ok":true,"final":"done"}'
    assert capture["cleanup_error"]


@pytest.mark.parametrize("complete,status", [(False, 200), (True, 503)])
def test_successful_cli_does_not_score_an_interrupted_model_request(monkeypatch, tmp_path, complete, status):
    import subprocess

    output = '{"status":"ok"}'
    monkeypatch.setattr(harness_module.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 0, output, ""))
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(harness_module, "_start_model_gateway", lambda *args, **kwargs:
                        ("network", "gateway", "http://gateway:18080"))
    monkeypatch.setattr(harness_module, "_stop_model_gateway", lambda *args: None)
    events = [{"kind": "request", "id": "last"},
              {"kind": "response", "id": "last", "status": status,
               "complete": complete, "body": ": keep-alive\n"}]
    monkeypatch.setattr(harness_module.ManifestHarnessRunner, "_gateway_evidence",
                        staticmethod(lambda *args: events))
    manifest = harness_module.ManifestHarness(
        name="openclaw", run="openclaw agent exec {task}", model_env={}, gateway=True,
    )
    capture = {}
    with pytest.raises(harness_module.HarnessExecutionError) as caught:
        harness_module.ManifestHarnessRunner(manifest)._launch(
            _item(), _target(), BenchmarkConfig(), "img", tmp_path, capture=capture,
        )
    assert caught.value.stdout == output
    assert capture["model_events"] == events


def test_builtin_harnesses_registered() -> None:
    expected = {"openhands", "miniswe", "codex", "claude-code", "cursor", "grok", "opencode", "aider", "goose", "openclaw"}
    for name in expected:
        assert harness_module.get_harness(name).name == name
    manifests = {manifest.name: manifest for manifest in harness_module._BUILTIN_MANIFESTS}
    assert all(manifests[name].gateway for name in ("codex", "claude-code", "openclaw"))
    assert "--name evalclaw" in manifests["claude-code"].run
    assert "--no-session-persistence" in manifests["claude-code"].run
    assert "--prompt-suggestions false" in manifests["claude-code"].run


def test_config_args_rendered_into_command(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        if command[1] == "exec" and "codex exec" in command[-1]:
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

    target_exec = next(
        command for command in calls["commands"]
        if command[1] == "exec" and "codex exec" in command[-1]
    )
    assert shlex.split(target_exec[-1].split("; ")[-1]) == [
        "exec",
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
        calls.setdefault("commands", []).append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={}, timeout=60
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work")
    )
    create = next(command for command in calls["commands"] if command[1] == "create")
    target_exec = next(
        command for command in calls["commands"]
        if command[1] == "exec" and "my-agent" in command[-1]
    )
    assert create[create.index("-w") + 1] == "/workspace"
    assert "/tmp/work:/workspace" in create
    assert target_exec[-2] == "-lc"
    assert target_exec[-1].split("; ")[-1] == shlex.join(["exec", "my-agent", "Write a function."])


def test_manifest_runs_setup_as_root_and_target_as_host_user(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_bounded(command, **kwargs):
        commands.append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module, "_run_bounded", fake_bounded)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    item = _item().model_copy(
        update={
            "metadata": {
                "agent_env": {
                    "type": "docker_workspace",
                    "setup_commands": ["touch /var/lib/prepared"],
                }
            }
        }
    )

    harness_module.ManifestHarnessRunner(
        harness_module.ManifestHarness(name="x", run="my-agent {task}", model_env={})
    )._launch(item, _target(), BenchmarkConfig(), "img", Path("/tmp/work"), capture={})

    create = next(command for command in commands if command[1] == "create")
    setup = next(command for command in commands if "touch /var/lib/prepared" in command[-1])
    target = next(command for command in commands if "my-agent" in command[-1])
    assert "--user" not in create
    assert setup[setup.index("--user") + 1] == "0:0"
    assert target[target.index("--user") + 1] == harness_module._target_container_user()


def test_manifest_setup_failure_prevents_target_execution(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_bounded(command, **kwargs):
        commands.append(command)
        return type(
            "Proc",
            (),
            {
                "returncode": 1 if "prepare-task" in command[-1] else 0,
                "stdout": "",
                "stderr": "setup failed" if "prepare-task" in command[-1] else "",
            },
        )()

    monkeypatch.setattr(harness_module, "_run_bounded", fake_bounded)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    item = _item().model_copy(
        update={
            "metadata": {
                "agent_env": {
                    "type": "docker_workspace",
                    "setup_commands": ["prepare-task"],
                }
            }
        }
    )

    with pytest.raises(RuntimeError, match="setup failed"):
        harness_module.ManifestHarnessRunner(
            harness_module.ManifestHarness(name="x", run="my-agent {task}", model_env={})
        )._launch(item, _target(), BenchmarkConfig(), "img", Path("/tmp/work"), capture={})

    assert not any("my-agent" in command[-1] for command in commands)


def test_manifest_launch_mounts_harness_image(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={}, timeout=60,
        harness_image="evalclaw-openclaw:latest",
        home="root/.openclaw",
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work")
    )

    create = next(command for command in calls["commands"] if command[1] == "create")
    target_exec = next(
        command for command in calls["commands"]
        if command[1] == "exec" and "my-agent" in command[-1]
    )
    assert "--mount" in create
    assert "type=image,src=evalclaw-openclaw:latest,dst=/opt/harness,readonly" in create
    bootstrap = next(command for command in calls["commands"] if command[-1].startswith('cp -a /opt/harness/root/.openclaw "$HOME/"'))
    assert calls["commands"].index(bootstrap) < calls["commands"].index(target_exec)
    assert 'cp -a' not in target_exec[-1]
    assert "export PATH=/opt/harness/usr/local/bin:$PATH;" in target_exec[-1]


@pytest.mark.parametrize("name", ["openclaw", "codex", "claude-code", "openhands"])
def test_harness_launch_mounts_and_checks_actor_service(monkeypatch, name) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    class FakeActorSession:
        mount = "/tmp/actors:/run/evalclaw-contacts:ro"

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name=name,
        run="my-agent {task}",
        model_env={},
        harness_image="evalclaw-openclaw:latest",
    )

    item = _item()
    item.metadata["agent_env"]["actors"] = [{"id": "alice", "system_prompt": "PRIVATE ROLE"}]
    harness_module.ManifestHarnessRunner(manifest)._launch(
        item,
        _target(),
        BenchmarkConfig(),
        "img",
        Path("/tmp/work"),
        actor_session=FakeActorSession(),
    )

    create = next(command for command in calls["commands"] if command[1] == "create")
    target_exec = next(
        command for command in calls["commands"]
        if command[1] == "exec" and "my-agent" in command[-1]
    )
    assert "/tmp/actors:/run/evalclaw-contacts:ro" in create
    from evalclaw.runners.environment_actors import CONTACT_COMMAND
    assert any(command[-1].endswith(f"{CONTACT_COMMAND} list") for command in calls["commands"])
    assert "PRIVATE ROLE" not in target_exec[-1]


def test_manifest_intervention_uses_runner_side_docker_exec(monkeypatch) -> None:
    action_finished = threading.Event()
    exec_commands: list[list[str]] = []
    capture: dict = {}

    def fake_bounded(command, **kwargs):
        exec_commands.append(command)
        shell_command = command[-1]
        if shell_command == "break-service":
            action_finished.set()
            return type(
                "Proc", (), {"returncode": 0, "stdout": "changed", "stderr": ""}
            )()
        if command[1] == "exec" and "touch /tmp/evalclaw-target-started" in shell_command:
            assert action_finished.wait(1)
            return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": "log"})()
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(harness_module, "_run_bounded", fake_bounded)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    item = _item().model_copy(
        update={
            "metadata": {
                "agent_env": {
                    "type": "docker_workspace",
                    "interventions": [
                        {
                            "id": "failure",
                            "trigger": {"type": "elapsed_time", "after_seconds": 0.01},
                            "action": {
                                "type": "run_command",
                                "command": "break-service",
                                "timeout_seconds": 2,
                            },
                        }
                    ],
                }
            }
        }
    )

    output = harness_module.ManifestHarnessRunner(
        harness_module.ManifestHarness(name="x", run="agent {task}", model_env={})
    )._launch(
        item,
        _target(),
        BenchmarkConfig(),
        "img",
        Path("/tmp/work"),
        capture=capture,
    )

    assert output == "done"
    action = next(command for command in exec_commands if command[-1] == "break-service")
    assert action[action.index("--user") + 1] == "0:0"
    assert action[action.index("--workdir") + 1] == "/workspace"
    assert capture["stderr"] == "log"
    assert capture["interventions"][0]["status"] == "completed"


def test_manifest_launch_routes_model_through_gateway(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        if command[1] == "create":
            calls["env"] = kwargs.get("env")
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    def fake_start(docker, upstream, **kwargs):
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

    create = next(command for command in calls["commands"] if command[1] == "create")
    assert "--network" in create and "evalclaw-net" in create
    assert "OPENAI_BASE_URL" in create
    assert calls["env"]["OPENAI_BASE_URL"] == "http://evalclaw-gw:18080"
    assert calls["stopped"] == ("evalclaw-net", "evalclaw-gw")


def test_gateway_url_is_rendered_into_harness_arguments(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(
        harness_module,
        "_start_model_gateway",
        lambda docker, upstream, **kwargs: (
            "evalclaw-net", "evalclaw-gw", "http://evalclaw-gw:18080"
        ),
    )
    monkeypatch.setattr(harness_module, "_stop_model_gateway", lambda *args: None)
    manifest = harness_module.ManifestHarness(
        name="x",
        run="my-agent {config_args} {task}",
        model_env={},
        config_args=("--base-url={base_url}",),
        gateway=True,
    )

    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), BenchmarkConfig(), "img", Path("/tmp/work")
    )

    target_exec = next(
        command for command in calls["commands"]
        if command[1] == "exec" and "my-agent" in command[-1]
    )
    assert "--base-url=http://evalclaw-gw:18080" in shlex.split(target_exec[-1])


def test_gateway_preserves_declared_internet_access(monkeypatch) -> None:
    calls: dict = {}

    def fake_start(docker, upstream, *, internal=True, **kwargs):
        calls["internal"] = internal
        return "evalclaw-net", "evalclaw-gw", "http://evalclaw-gw:18080"

    monkeypatch.setattr(
        harness_module.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""}
        )(),
    )
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(harness_module, "_start_model_gateway", fake_start)
    monkeypatch.setattr(harness_module, "_stop_model_gateway", lambda *args: None)
    item = _item().model_copy(
        update={"metadata": {"agent_env": {"type": "docker_workspace", "network": "internet"}}}
    )
    manifest = harness_module.ManifestHarness(
        name="x", run="my-agent {task}", model_env={}, gateway=True
    )

    harness_module.ManifestHarnessRunner(manifest)._launch(
        item, _target(), BenchmarkConfig(), "img", Path("/tmp/work")
    )

    assert calls["internal"] is False


def test_manifest_launch_overrides_provider_baseurl_via_config(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    def fake_start(docker, upstream, **kwargs):
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

    shell = next(
        command[-1] for command in calls["commands"]
        if command[1] == "exec" and "openclaw agent exec" in command[-1]
    )
    configuration = next(command[-1] for command in calls["commands"] if "openclaw config set models.providers.deepseek.baseUrl http://evalclaw-gw:18080" in command[-1])
    assert configuration != shell
    assert calls["stopped"] == ("evalclaw-net", "evalclaw-gw")


def test_hidden_file_write_rejects_agent_symlink_escape(monkeypatch, tmp_path) -> None:
    workdir = tmp_path / "work"
    outside = tmp_path / "outside"
    workdir.mkdir()
    outside.mkdir()
    (workdir / "tests").symlink_to(outside, target_is_directory=True)
    item = _item().model_copy(
        update={
            "metadata": {
                "agent_env": {
                    "type": "docker_workspace",
                    "hidden_files": {"tests/hidden.py": "private"},
                }
            }
        }
    )

    with pytest.raises(ValueError, match="symbolic link"):
        harness_module.score_docker_task(item, BenchmarkConfig(), "img", workdir)
    assert not (outside / "hidden.py").exists()


def test_evaluator_stages_episode_evidence_after_target(monkeypatch, tmp_path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    calls: dict = {}

    def fake_bounded(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        if command[1] == "cp" and command[-1].endswith(":/evalclaw-evidence"):
            evidence_file = Path(command[-2][:-2]) / "episode.json"
            calls["evidence"] = evidence_file.read_text(encoding="utf-8")
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(harness_module, "_run_bounded", fake_bounded)
    score, _ = harness_module.score_docker_task(
        _item(),
        BenchmarkConfig(),
        "img",
        workdir,
        evidence={"schema_version": "evalclaw.evaluator_evidence.v1"},
    )

    assert score == 1.0
    assert '"schema_version": "evalclaw.evaluator_evidence.v1"' in calls["evidence"]
    assert any(
        command[1] == "cp" and command[-1].endswith(":/evalclaw-evidence")
        for command in calls["commands"]
    )


def test_evaluator_reuses_container_and_reads_non_workspace_result(monkeypatch, tmp_path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    commands: list[list[str]] = []
    read_paths: list[str] = []
    item = _item().model_copy(
        update={
            "metadata": {
                "agent_env": {
                    "type": "docker_workspace",
                    "test_command": "check-persistent-state",
                    "evaluation": {"result_path": "/tmp/result.json"},
                }
            }
        }
    )

    def fake_bounded(command, **kwargs):
        commands.append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def fake_read(docker, container_name, path, **kwargs):
        assert container_name == "existing-task"
        read_paths.append(path)
        return '{"score": 1, "passed": true}' if path == "/tmp/result.json" else ""

    monkeypatch.setattr(harness_module, "_run_bounded", fake_bounded)
    monkeypatch.setattr(harness_module, "_read_container_file", fake_read)
    score, _ = harness_module.score_docker_task(
        item,
        BenchmarkConfig(),
        "img",
        workdir,
        container_name="existing-task",
    )

    evaluator = next(command for command in commands if "check-persistent-state" in command[-1])
    assert score == 1.0
    assert evaluator[evaluator.index("--user") + 1] == "0:0"
    assert evaluator[evaluator.index("sh") - 1] == "existing-task"
    assert "/tmp/result.json" in read_paths
    assert not any(command[1] == "create" for command in commands)


def test_prepare_copies_public_assets_and_rejects_path_escape(monkeypatch, tmp_path) -> None:
    asset = tmp_path / "input.txt"
    asset.write_text("asset", encoding="utf-8")
    monkeypatch.setattr(
        harness_module,
        "apply_docker_image_selection",
        lambda env, **kwargs: (env, {}),
    )
    monkeypatch.setattr(
        harness_module,
        "build_docker_image_if_requested",
        lambda env, **kwargs: (env, {}),
    )
    item = _item().model_copy(update={"assets": [TaskAsset(path=str(asset))]})

    _, workdir = harness_module.prepare_docker_task(item, BenchmarkConfig())
    try:
        assert (workdir / "input.txt").read_text(encoding="utf-8") == "asset"
    finally:
        harness_module.shutil.rmtree(workdir)

    escaped = _item().model_copy(
        update={"metadata": {"agent_env": {"visible_files": {"../outside": "x"}}}}
    )
    with pytest.raises(ValueError, match="relative"):
        harness_module.prepare_docker_task(escaped, BenchmarkConfig())


def test_harness_rejects_private_runtime_files() -> None:
    item = _item().model_copy(
        update={"metadata": {"agent_env": {"runtime_files": {"server.py": "private"}}}}
    )
    with pytest.raises(RuntimeError, match="runtime_files"):
        harness_module.reject_tool_constraints(item)


def test_tool_image_is_mounted_but_task_image_runs(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    manifest = harness_module.ManifestHarness(
        name="x",
        run="agent {task}",
        model_env={},
        runtime_image="agent-tools:1",
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        _item(), _target(), BenchmarkConfig(), "task-image:1", Path("/tmp/work")
    )

    create = next(command for command in calls["commands"] if command[1] == "create")
    assert "type=image,src=agent-tools:1,dst=/opt/harness,readonly" in create
    assert create[-4] == "task-image:1"


def test_gateway_keeps_task_resource_limits(monkeypatch) -> None:
    calls: dict = {}

    def fake_run(command, **kwargs):
        calls.setdefault("commands", []).append(command)
        return type("Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""})()

    monkeypatch.setattr(harness_module.subprocess, "run", fake_run)
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(
        harness_module,
        "_start_model_gateway",
        lambda docker, upstream, **kwargs: ("network", "gateway", "http://gateway:18080"),
    )
    monkeypatch.setattr(harness_module, "_stop_model_gateway", lambda *args: None)
    item = _item().model_copy(
        update={
            "metadata": {
                "agent_env": {
                    "type": "docker_workspace",
                    "resource_limits": {"memory": "128m", "cpus": "1"},
                }
            }
        }
    )
    manifest = harness_module.ManifestHarness(
        name="x", run="agent {task}", model_env={}, gateway=True
    )
    harness_module.ManifestHarnessRunner(manifest)._launch(
        item, _target(), BenchmarkConfig(), "task-image:1", Path("/tmp/work")
    )

    create = next(command for command in calls["commands"] if command[1] == "create")
    assert create[create.index("--memory") + 1] == "128m"
    assert create[create.index("--cpus") + 1] == "1"
    assert create[create.index("--network") + 1] == "network"


def test_trajectory_collection_skips_nested_symlinks(tmp_path) -> None:
    workdir = tmp_path / "work"
    logs = workdir / "logs"
    logs.mkdir(parents=True)
    (logs / "trace.json").write_text("{}", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    (logs / "leak.txt").symlink_to(secret)
    artifact_dir = tmp_path / "artifacts"
    manifest = harness_module.ManifestHarness(
        name="x", run="agent {task}", model_env={}, trajectory_paths=("logs",)
    )

    harness_module.ManifestHarnessRunner(manifest)._collect_trajectory(workdir, artifact_dir)

    copied = artifact_dir / "trajectory" / "logs"
    assert (copied / "trace.json").read_text(encoding="utf-8") == "{}"
    assert not (copied / "leak.txt").exists()


def test_episode_records_identity_and_timing(monkeypatch, tmp_path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setattr(harness_module, "prepare_docker_task", lambda *args: ("img", workdir))
    monkeypatch.setattr(
        harness_module, "score_docker_task", lambda *args, **kwargs: (1.0, "pass")
    )
    monkeypatch.setattr(harness_module, "resolve_docker_executable", lambda _: "docker")
    monkeypatch.setattr(
        harness_module.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Proc", (), {"returncode": 0, "stdout": "done", "stderr": ""}
        )(),
    )
    monkeypatch.setattr(
        harness_module.ManifestHarnessRunner,
        "_image_identity",
        lambda self, config, image: {"name": image} if image else None,
    )
    artifact_dir = tmp_path / "episode"
    target = _target().model_copy(update={"api_key": None})
    runner = harness_module.ManifestHarnessRunner(
        harness_module.ManifestHarness(name="x", run="agent {task}", model_env={})
    )

    runner.run(_item(), target, BenchmarkConfig(), artifact_dir=artifact_dir)

    episode = harness_module.json.loads((artifact_dir / "episode.json").read_text())
    assert episode["item_id"] == "task_1"
    assert episode["target_id"] == target.id
    assert len(episode["task_sha256"]) == 64
    assert episode["duration_ms"] >= 0
    assert episode["started_at"] <= episode["finished_at"]
    assert episode["timeouts"] == {"harness_seconds": 160, "evaluator_seconds": 600}
