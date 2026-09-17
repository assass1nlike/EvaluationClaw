from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from evalclaw.execution import agent_judge as module
from evalclaw.execution.agent_envs import build_agent_environment
from evalclaw.execution.judge_sandbox import JudgeSandbox
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.runners.harness import DockerWorkspaceBackend
from evalclaw.types import (
    AgentEnvironmentSpec,
    AgentJudgeSpec,
    BenchmarkConfig,
    BenchmarkItem,
    TargetModelConfig,
    TaskDefinition,
    TaskType,
)


def _item(mode="judge", **overrides):
    return BenchmarkItem(id="judge-task", task_type=TaskType.agent, dimension_id="work",
        prompt="Write the requested answer.", metadata={"agent_env": {
            "type": "docker_workspace", "image": "python:3.11", "auto_select_image": False,
            "pull_image": False, "max_steps": 5, "timeout": 30,
            "visible_files": {"answer.txt": "initial"},
            "hidden_files": {"evaluate.py": "import json\nfrom pathlib import Path\nprint(json.dumps({'score': int(Path('answer.txt').read_text() == 'submitted')}))"},
            "test_command": "python3 evaluate.py" if mode == "hybrid" else "",
            "evaluation": {"result_format": "json_on_stdout"},
            "judge": {"mode": mode, "instructions": "Review the submitted work.",
                      "criteria": [{"id": "quality", "rubric": "0: no completion; 0.8: substantial completion; 1: complete"}],
                      **overrides},
        }})


def _config():
    return BenchmarkConfig(task_models=[TargetModelConfig(id="reviewer", provider="openai", model="test")])


def _response(*, calls=(), content=""):
    return TargetToolModelResponse(adapter="openai_compatible", content=content, tool_calls=list(calls),
        assistant_message={"role": "assistant", "content": content,
                           **({"tool_calls": [c.model_dump() for c in calls]} if calls else {})}, raw_response={})


def _judge_model(command="cat answer.txt", score=0.8):
    turns = []

    def model(messages, **kwargs):
        turns.append(kwargs)
        if len(turns) == 1:
            return _response(calls=[
                ToolCall(id="episode", name="read_evidence", arguments={"kind": "episode"}),
                ToolCall(id="inspect", name="review_command", arguments={"command": command}),
            ])
        return _response(content=json.dumps({"status": "scored", "criteria": [
            {"id": "quality", "score": score, "reasoning": "Observed the submitted work.", "evidence": ["inspect", "episode"]},
        ]}))

    return model


class FakeSandbox:
    name, image = "review-copy", "snapshot"

    def __init__(self, *args):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def command(self, command, timeout=120):
        return subprocess.CompletedProcess(command, 0, "submitted", "")


@pytest.mark.parametrize("mode,weight,gate,script_score,expected", [
    ("judge", None, False, 0.0, 0.8),
    ("hybrid", 0.25, False, 1.0, 0.85),
    ("hybrid", 0.25, True, 0.5, 0.0),
])
def test_scoring_rules_evidence_and_persistence(monkeypatch, tmp_path, mode, weight, gate, script_score, expected):
    sandbox = FakeSandbox()
    monkeypatch.setattr(module, "JudgeSandbox", lambda *_: sandbox)
    monkeypatch.setattr(module, "call_orchestrator_with_tools", _judge_model())
    calls = []

    def script():
        calls.append(True)
        return script_score, "script checked"

    item = _item(mode, **({"script_weight": weight, "script_gate": gate} if mode == "hybrid" else {}))
    score, details = module.score_with_agent(item, _config(), "original", {"target_execution": {}}, script,
                                           artifact_dir=tmp_path)
    assert score == pytest.approx(expected)
    assert calls == ([True] if mode == "hybrid" else [])
    assert sandbox.closed
    record = json.loads((tmp_path / "review.json").read_text())
    assert record["status"] == "scored" and record["tool_calls"] == 2
    assert record["tools"][1]["output"]["stdout"] == "submitted"
    assert json.loads(details)["criteria"][0]["evidence"] == ["inspect", "episode"]


@pytest.mark.parametrize("answer", [
    {"status": "ungradable", "reason": "Missing required audit log"},
    {"status": "scored", "criteria": [{"id": "quality", "score": 1, "reasoning": "claim", "evidence": ["invented"]}]},
    {"status": "scored", "criteria": [{"id": "quality", "score": 2, "reasoning": "claim", "evidence": ["inspect"]}]},
])
def test_judge_failure_does_not_become_target_zero(monkeypatch, tmp_path, answer):
    sandbox = FakeSandbox()
    monkeypatch.setattr(module, "JudgeSandbox", lambda *_: sandbox)
    monkeypatch.setattr(module, "call_orchestrator_with_tools", lambda *a, **kw: _response(content=json.dumps(answer)))
    with pytest.raises(module.EvaluationExecutionError):
        module.score_with_agent(_item(), _config(), "original", {}, lambda: (1, ""), artifact_dir=tmp_path)
    record = json.loads((tmp_path / "review.json").read_text())
    assert record["status"] == "failed" and "score" not in record
    assert sandbox.closed


def test_contract_validation_and_model_selection(tmp_path):
    with pytest.raises(ValidationError):
        AgentJudgeSpec.model_validate(_item("hybrid").metadata["agent_env"]["judge"])
    with pytest.raises(ValidationError):
        AgentEnvironmentSpec.model_validate({**_item().metadata["agent_env"], "type": "vm"})
    with pytest.raises(module.EvaluationExecutionError, match="task-model"):
        module.score_with_agent(_item(), BenchmarkConfig(), "unused", {}, lambda: (0, ""), artifact_dir=tmp_path)
    item = _item()
    item.metadata["task_model_id"] = "unknown"
    with pytest.raises(ValueError, match="Unknown task_model_id"):
        module.score_with_agent(item, _config(), "unused", {}, lambda: (0, ""), artifact_dir=tmp_path)


def test_builder_packaging_preserves_judge_contract_without_inventing_script():
    from evalclaw.construction.packaging import pack_task_item
    from evalclaw.types import EvalDimension

    item = _item()
    task = TaskDefinition(id=item.id, dimension_id=item.dimension_id, task_type=TaskType.agent,
                          title="Review work", prompt=item.prompt,
                          environment=AgentEnvironmentSpec.model_validate(item.metadata["agent_env"]))
    packed = pack_task_item(task, EvalDimension(id="work", name="Work", description="Work", approach="Assess work"), resource_by_id={})
    assert packed.metadata["agent_env"]["judge"]["criteria"][0]["id"] == "quality"
    assert packed.metadata["agent_env"]["test_command"] == ""
    assert packed.metadata["task_agent"]["scoring"]["method"] == "judge_agent"
    assert packed.metadata["agent_task_package"]["evaluation"]["method"] == "judge_agent"
    assert "run_tests" not in packed.metadata["agent_task_package"]["trajectory_requirements"]["required_tools"]


def test_budget_exhaustion_and_failed_command_keep_diagnostics(monkeypatch, tmp_path):
    sandbox = FakeSandbox()
    monkeypatch.setattr(module, "JudgeSandbox", lambda *_: sandbox)
    monkeypatch.setattr(module, "call_orchestrator_with_tools", lambda *a, **kw: _response(calls=[
        ToolCall(id="inspect", name="review_command", arguments={"command": "inspect"}),
    ]))
    config = _config().model_copy(update={"agent_judge_tool_max_calls": 1})
    with pytest.raises(RuntimeError, match="exhausting") as error:
        module.score_with_agent(_item(), config, "source", {"target_execution": {"raw_output": {"trace": []}}},
                                lambda: (0, ""), artifact_dir=tmp_path)
    assert error.value.execution_evidence["stage"] == "evaluation"
    assert isinstance(error.value.execution_evidence["target_execution"]["raw_output"], str)
    assert sandbox.closed


def test_failed_snapshot_resumes_original_and_releases_registered_resources(monkeypatch):
    from evalclaw.execution import judge_sandbox
    registered = []
    cleaned = []

    class Guard:
        def __init__(self, *args):
            pass

        def register(self, kind, name):
            registered.append((kind, name))

        def close(self):
            cleaned.extend(registered)

    monkeypatch.setattr(judge_sandbox, "DockerResourceGuard", Guard)
    monkeypatch.setattr(judge_sandbox, "resolve_docker_executable", lambda _: "docker")
    sandbox = JudgeSandbox("docker", "original", "/workspace")

    def docker_call(args, **kwargs):
        if args[0] == "inspect":
            return SimpleNamespace(stdout=json.dumps([{"State": {"Running": True, "Paused": False}}]))
        if args[0] == "commit":
            raise RuntimeError("snapshot failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sandbox, "docker_call", docker_call)
    with pytest.raises(RuntimeError, match="snapshot failed"):
        with sandbox:
            pytest.fail("failed snapshot became available")
    assert ("resume", "original") in cleaned
    assert ("image", sandbox.image) in cleaned and ("container", sandbox.name) in cleaned


def test_native_factory_disables_target_judging_and_returns_judge_score(monkeypatch, tmp_path):
    from evalclaw.execution import agent_envs
    captured = {}
    environment = SimpleNamespace(_container_name="source", judge_artifact_dir=tmp_path, evaluator_runs=[])

    def build(config, **kwargs):
        captured.update(config)
        return environment

    monkeypatch.setattr(agent_envs.DockerWorkspaceAgentEnvironment, "from_config", build)
    monkeypatch.setattr(module, "score_with_agent", lambda *a, **kw: (0.8, "judged"))
    result = build_agent_environment(_item(), _config())
    assert captured["expose_test_tool"] is False and captured["auto_evaluate_on_final"] is False
    assert result.judge_evaluator({}) == "judged"
    assert result.last_test["score"] == 0.8


def test_image_results_are_attached_to_the_judge_turn(monkeypatch, tmp_path):
    import base64

    sandbox = FakeSandbox()
    sandbox.workdir = "/workspace"
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jF1cAAAAASUVORK5CYII=")

    def copy(args, **kwargs):
        Path(args[-1]).write_bytes(png)
        return SimpleNamespace(returncode=0)

    sandbox.docker_call = copy
    monkeypatch.setattr(module, "JudgeSandbox", lambda *_: sandbox)
    turns = 0

    def model(messages, **kwargs):
        nonlocal turns
        turns += 1
        if turns == 1:
            return _response(calls=[ToolCall(id="image", name="view_image", arguments={"path": "result.png"})])
        parts = messages[-1]["content"]
        assert any(part.get("type") == "image_url" for part in parts)
        image_result = json.loads(next(m["content"] for m in messages if m.get("role") == "tool"))
        return _response(content=json.dumps({"status": "scored", "criteria": [
            {"id": "quality", "score": 0.8, "reasoning": "Inspected the image.", "evidence": [image_result["evidence_id"]]},
        ]}))

    monkeypatch.setattr(module, "call_orchestrator_with_tools", model)
    score, _ = module.score_with_agent(_item(), _config(), "original", {}, lambda: (0, ""), artifact_dir=tmp_path)
    assert score == 0.8 and list((tmp_path / "images").glob("*.png"))


def test_judge_can_page_and_cite_using_only_tool_result_text(monkeypatch, tmp_path):
    import uuid

    sandbox = FakeSandbox()
    sandbox.command = lambda *a: subprocess.CompletedProcess(a, 0, "x" * 20000, "")
    monkeypatch.setattr(module, "JudgeSandbox", lambda *_: sandbox)
    turns = 0
    source_id = None

    def model(messages, **kwargs):
        nonlocal turns, source_id
        turns += 1
        if turns == 1:
            return _response(calls=[ToolCall(id=uuid.uuid4().hex, name="review_command",
                                             arguments={"command": "cat large-result.txt"})])
        # Only result bodies are available to this simulated model; protocol ids are not.
        body = json.loads([m["content"] for m in messages if m.get("role") == "tool"][-1])
        if turns == 2:
            source_id = body["evidence_id"]
            assert body["next_offset"] is not None
            return _response(calls=[ToolCall(id=uuid.uuid4().hex, name="read_review_output",
                arguments={"call_id": source_id, "offset": body["next_offset"]})])
        assert body["source_evidence_id"] == source_id and body["next_offset"] is None
        return _response(content=json.dumps({"status": "scored", "criteria": [
            {"id": "quality", "score": 0.8, "reasoning": "Read both pages.",
             "evidence": [source_id, body["evidence_id"]]},
        ]}))

    monkeypatch.setattr(module, "call_orchestrator_with_tools", model)
    score, _ = module.score_with_agent(_item(), _config(), "original", {}, lambda: (0, ""), artifact_dir=tmp_path)
    assert score == 0.8 and turns == 3


def test_invalid_citation_feedback_exposes_valid_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "JudgeSandbox", FakeSandbox)
    turns = 0

    def model(messages, **kwargs):
        nonlocal turns
        turns += 1
        if turns == 1:
            return _response(calls=[ToolCall(id="opaque", name="review_command", arguments={"command": "ls"})])
        refs = ["made-up"]
        if turns == 3:
            feedback = json.loads(messages[-1]["content"])
            assert feedback["invalid_evidence_ids"] == refs
            refs = feedback["valid_evidence_ids"]
        return _response(content=json.dumps({"status": "scored", "criteria": [
            {"id": "quality", "score": 0.8, "reasoning": "Inspected files.", "evidence": refs},
        ]}))

    monkeypatch.setattr(module, "call_orchestrator_with_tools", model)
    score, _ = module.score_with_agent(_item(), _config(), "original", {}, lambda: (0, ""), artifact_dir=tmp_path)
    assert score == 0.8 and turns == 3


def test_model_failure_is_an_evaluation_error_with_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "JudgeSandbox", FakeSandbox)
    def unavailable(*args, **kwargs):
        raise ConnectionError("service unavailable")
    monkeypatch.setattr(module, "call_orchestrator_with_tools", unavailable)
    with pytest.raises(module.EvaluationExecutionError) as error:
        module.score_with_agent(_item(), _config(), "original", {}, lambda: (0, ""), artifact_dir=tmp_path)
    assert isinstance(error.value.__cause__, ConnectionError)
    assert error.value.execution_evidence["stage"] == "evaluation"
    assert json.loads((tmp_path / "review.json").read_text())["status"] == "failed"


def test_command_timeout_keeps_partial_evidence_and_allows_recovery(monkeypatch, tmp_path):
    sandbox = FakeSandbox()

    def command(command, timeout=120):
        if command == "wide search":
            raise subprocess.TimeoutExpired(command, timeout, output=b"partial", stderr=b"unfinished")
        return subprocess.CompletedProcess(command, 0, "submitted", "")

    sandbox.command = command
    monkeypatch.setattr(module, "JudgeSandbox", lambda *_: sandbox)
    turns = 0

    def model(messages, **kwargs):
        nonlocal turns
        turns += 1
        if turns == 1:
            return _response(calls=[ToolCall(id="timeout", name="review_command",
                arguments={"command": "wide search", "timeout_seconds": 1})])
        if turns == 2:
            body = module.extract_json(messages[-1]["content"])
            assert body["error"] == "command_timeout" and "evidence_id" not in body
            assert json.loads(body["content"])["stdout"] == "partial"
            return _response(calls=[
                ToolCall(id="partial", name="read_review_output", arguments={"call_id": body["output_id"]}),
                ToolCall(id="inspect", name="review_command", arguments={"command": "cat answer.txt"}),
            ])
        if turns == 3:
            body = json.loads([m["content"] for m in messages if m.get("tool_call_id") == "partial"][0])
            assert json.loads(body["content"])["complete"] is False
            refs = ["timeout"]
        else:
            feedback = json.loads(messages[-1]["content"])
            assert feedback["invalid_evidence_ids"] == ["timeout"]
            assert set(feedback["valid_evidence_ids"]) == {"partial", "inspect"}
            refs = ["inspect"]
        return _response(content=json.dumps({"status": "scored", "criteria": [
            {"id": "quality", "score": 0.8, "reasoning": "Checked submitted file.", "evidence": refs},
        ]}))

    monkeypatch.setattr(module, "call_orchestrator_with_tools", model)
    score, _ = module.score_with_agent(_item(), _config(), "original", {}, lambda: (0, ""), artifact_dir=tmp_path)
    assert score == 0.8 and turns == 4
    record = json.loads((tmp_path / "review.json").read_text())
    assert record["status"] == "scored"
    assert record["tools"][0]["output"]["stderr"] == "unfinished"
    assert record["tools"][0]["result"]["error"] == "command_timeout"


def test_timeout_cleanup_failure_blocks_evaluation(monkeypatch):
    monkeypatch.setattr("evalclaw.execution.judge_sandbox.resolve_docker_executable", lambda _: "docker")
    sandbox = JudgeSandbox("docker", "original", "/workspace")
    calls = []

    def docker_call(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(args, 1)
        raise RuntimeError("container unreachable")

    monkeypatch.setattr(sandbox, "docker_call", docker_call)
    with pytest.raises(module.EvaluationExecutionError, match="Failed to stop"):
        sandbox.command("sleep 60", 1)
    assert len(calls) == 2


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires local Docker")
def test_real_timeout_cleans_children_and_preserves_other_review_processes():
    env = build_agent_environment(_item(), _config())
    try:
        env.step({"action": "write_file", "args": {"path": "answer.txt", "content": "submitted"}})
        with JudgeSandbox(_config().docker_executable, env._container_name, "/workspace") as sandbox:
            sandbox.command("sleep 300 >/dev/null 2>&1 & echo $! > /tmp/service.pid")
            with pytest.raises(subprocess.TimeoutExpired) as error:
                sandbox.command("echo $$ > /tmp/parent.pid; sleep 300 & echo $! > /tmp/child.pid; echo partial; wait", 2)
            assert "partial" in error.value.stdout
            result = sandbox.command("""python3 - <<'PY'
from pathlib import Path
import os
for name in ('parent', 'child'):
    pid = Path('/tmp/' + name + '.pid').read_text().strip()
    status = Path('/proc/' + pid + '/stat')
    assert not status.exists() or status.read_text().split()[2] == 'Z'
os.kill(int(Path('/tmp/service.pid').read_text()), 0)
print(Path('answer.txt').read_text())
PY""")
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == "submitted"
        assert env.run_external_command("cat answer.txt", 10).stdout == "submitted"
    finally:
        env.cleanup()


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires local Docker")
@pytest.mark.parametrize("mode", ["judge", "hybrid"])
def test_real_native_judge_reads_final_state_without_altering_it(monkeypatch, tmp_path, mode):
    item = _item(mode, **({"script_weight": 0.25} if mode == "hybrid" else {}))
    monkeypatch.setattr(module, "call_orchestrator_with_tools", _judge_model(
        "cat answer.txt; cat /tmp/target-state; printf reviewer-change > answer.txt; printf changed > /tmp/target-state",
    ))
    env = build_agent_environment(item, _config())
    try:
        env.judge_artifact_dir = tmp_path
        outcome = env.step({"action": "write_file", "args": {"path": "answer.txt", "content": "submitted"}})
        assert not outcome.error
        assert env.run_external_command("printf original > /tmp/target-state", 10).returncode == 0
        details = env.evaluate_with_evidence({"target_execution": {"final_response": "finished"}})
        assert env.score() == pytest.approx(0.85 if mode == "hybrid" else 0.8)
        assert json.loads(details)["judge_score"] == 0.8
        assert env.run_external_command("cat answer.txt; cat /tmp/target-state", 10).stdout == "submittedoriginal"
        record = json.loads((tmp_path / "review.json").read_text())
        assert record["tools"][1]["output"]["stdout"] == "submittedoriginal"
    finally:
        env.cleanup()


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires local Docker")
def test_real_snapshot_copies_writable_mounts_and_permissions(monkeypatch, tmp_path):
    from evalclaw.runners.harness import (
        ManifestHarness,
        ManifestHarnessRunner,
        cleanup_harness_session,
    )

    item = _item()
    item.metadata["agent_env"]["setup_commands"] = ["chmod 0400 answer.txt; printf original > /tmp/target-state"]
    config = _config()
    backend = DockerWorkspaceBackend(item, config)
    image, workspace = backend.prepare()
    capture = {}
    runner = ManifestHarnessRunner(ManifestHarness(name="fixture", run="unused", model_env={}))
    target = TargetModelConfig(provider="openai", model="test")
    try:
        runner._launch(item, target, config, image, workspace, capture=capture, preflight_only=True)
        with JudgeSandbox(config.docker_executable, capture["container_name"], "/workspace") as sandbox:
            state = sandbox.command("stat -c '%u:%g:%a' answer.txt; cat /tmp/target-state")
            assert state.returncode == 0
            proc = subprocess.run(["docker", "exec", capture["container_name"], "stat", "-c", "%u:%g:%a", "/workspace/answer.txt"],
                                  capture_output=True, text=True, check=True)
            original_stat = proc.stdout
            assert state.stdout == original_stat + "original"
            sandbox.command("chmod 0600 answer.txt; printf modified > answer.txt; printf modified > /tmp/target-state")
        assert (workspace / "answer.txt").read_text() == "initial"
        proc = subprocess.run(["docker", "exec", capture["container_name"], "cat", "/tmp/target-state"],
                              capture_output=True, text=True, check=True)
        assert proc.stdout == "original"
    finally:
        cleanup_harness_session(capture)
        backend.cleanup(workspace)


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires local Docker")
def test_real_external_runner_and_native_preflight_use_judge(monkeypatch, tmp_path):
    from evalclaw.runners.harness import ManifestHarness, ManifestHarnessRunner

    item = _item()
    config = _config()
    target = TargetModelConfig(provider="openai", model="test")
    runner = ManifestHarnessRunner(ManifestHarness(
        name="fixture", run="sh -lc 'printf submitted > answer.txt; printf finished'", model_env={},
    ))
    monkeypatch.setattr(module, "call_orchestrator_with_tools", _judge_model())
    assert runner.preflight(item, target, config, artifact_dir=tmp_path / "preflight")["status"] == "passed"
    monkeypatch.setattr(module, "call_orchestrator_with_tools", _judge_model())
    raw, score, reason = runner.run(item, target, config, artifact_dir=tmp_path / "run")
    assert raw == "finished" and score == 0.8
    assert json.loads(reason)["judge_score"] == 0.8
    review = json.loads((tmp_path / "run/judge/review.json").read_text())
    assert review["tools"][1]["output"]["stdout"] == "submitted"
    episode = json.loads((tmp_path / "run/judge/episode.json").read_text())
    assert episode["target_execution"]["final_response"] == "finished"
    monkeypatch.setattr(module, "call_orchestrator_with_tools", _judge_model())
    env = build_agent_environment(item, config)
    try:
        env.judge_artifact_dir = tmp_path / "native-preflight"
        assert env.preflight().source == "judge_agent"
    finally:
        env.cleanup()
