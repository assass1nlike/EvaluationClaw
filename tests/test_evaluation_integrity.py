from __future__ import annotations

import json
import os
import subprocess
import uuid

import pytest
from pydantic import ValidationError

from evalclaw.execution import runner
from evalclaw.execution.agent_envs import build_agent_environment
from evalclaw.execution.errors import EvaluationExecutionError
from evalclaw.execution.judge_protocol import DialogueTurn, JudgeScore
from evalclaw.models import llm
from evalclaw.runners.harness import (
    DockerWorkspaceBackend,
    ManifestHarness,
    ManifestHarnessRunner,
    cleanup_harness_session,
)
from evalclaw.types import BenchmarkConfig, BenchmarkItem, JudgeToolRef, TargetModelConfig, TaskType


def config():
    return BenchmarkConfig(
        targets=[TargetModelConfig(id="target", provider="mock", model="target")],
        task_models=[TargetModelConfig(provider="mock", model="reviewer", api_key="test")],
        judge_double_pass=False,
    )


def item(task_type=TaskType.multi_turn):
    return BenchmarkItem(id="case", dimension_id="d", task_type=task_type,
        prompt="Start", rubric="Award one point for each of three constraints.",
        metadata={"task_agent": {"agent_role": "dialogue_simulator",
            "system_prompt": "You are a coworker. Speak only plain text.",
            "interaction": {"max_turns": 2, "followup_instruction": "Ask for a revision."}}})


@pytest.mark.parametrize("content", [None, ""])
def test_completed_empty_text_is_preserved(content):
    response = {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}
    assert llm._extract_litellm_content(response, allow_empty=True) == ""


@pytest.mark.parametrize("choice", [
    {"message": {"role": "assistant", "content": None}, "finish_reason": None},
    {"message": {"role": "assistant", "content": None}, "finish_reason": "length"},
    {"message": {"role": "assistant"}, "finish_reason": "stop"},
    {"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "x"}]}, "finish_reason": "stop"},
    {"message": {"role": "assistant", "content": None, "refusal": "refused"}, "finish_reason": "stop"},
])
def test_missing_or_nontext_responses_are_not_silence(choice):
    with pytest.raises(ValueError):
        llm._extract_litellm_content({"choices": [choice]}, allow_empty=True)


@pytest.mark.parametrize("raw,total,expected", [(3, 3, 1), (4, 5, .8), (7, 10, .7), (0, 3, 0)])
def test_scoring_uses_declared_denominator(raw, total, expected):
    assert runner._score_from_judge_data({"score_raw": raw, "score_max": total, "reasoning": "Checked."})[0] == expected


@pytest.mark.parametrize("data", [
    {"score": 5}, {"score_raw": 3, "reasoning": "No denominator"},
    {"score_raw": 6, "score_max": 5, "reasoning": "Out of range"},
    {"score_raw": 0, "score_max": 0, "reasoning": "Zero denominator"},
    {"score_raw": float("nan"), "score_max": 5, "reasoning": "NaN"},
    {"score_raw": True, "score_max": 5, "reasoning": "Boolean"},
    {"score_raw": 3, "score_max": 3, "reasoning": " "},
])
def test_invalid_scores_cannot_become_numeric_grades(data):
    with pytest.raises(ValidationError):
        JudgeScore.model_validate(data)


@pytest.mark.parametrize("data", [{"done": "false", "turn": "Next"}, {"done": False}, {"done": True, "turn": "Next"}])
def test_dialogue_stop_protocol_is_unambiguous(data):
    with pytest.raises(ValidationError):
        DialogueTurn.model_validate(data)


def test_role_reply_is_repaired_before_delivery(monkeypatch):
    replies = iter(["Please revise.", '{"done":false,"turn":"Please revise."}'])
    requests = []

    def model(messages, **kwargs):
        requests.append((list(messages), kwargs))
        return next(replies)

    monkeypatch.setattr(runner, "call_llm", model)
    task = item()
    turn, error = runner._task_agent_next_turn(task, [], config(), step_index=1)
    assert turn == "Please revise." and error is None
    assert len(requests) == 2 and all(kwargs["expect_json"] for _, kwargs in requests)
    payload = json.loads(requests[0][0][0].content)
    assert payload["item"]["metadata"]["task_agent"]["system_prompt"] == task.metadata["task_agent"]["system_prompt"]
    assert requests[0][1]["system"] != task.metadata["task_agent"]["system_prompt"]


def test_failed_role_keeps_transcript_and_never_calls_judge(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_target_has_credentials", lambda *a: (True, ""))
    monkeypatch.setattr(runner, "call_target_model", lambda *a, **k: "Already answered")
    monkeypatch.setattr(runner, "call_llm", lambda *a, **k: "not JSON")
    monkeypatch.setattr(runner, "_judge_item", lambda *a, **k: pytest.fail("Incomplete dialogue was graded"))
    result = runner._run_item(item(), config(), "target", trace_dir=tmp_path)
    assert result.error and result.execution["termination"]["status"] == "failed"
    assert json.loads(result.raw_response)[-1] == {"role": "assistant", "content": "Already answered"}
    evidence = json.loads((tmp_path / "execution-failure.json").read_text())
    assert evidence["target_execution"]["history"] == json.loads(result.raw_response)


def test_failed_second_judge_does_not_average_invalid_score(monkeypatch):
    replies = iter(['{"score_raw":3,"score_max":3,"reasoning":"All passed"}', '{"score":5}', '{"score":5}'])
    monkeypatch.setattr(runner, "call_llm", lambda *a, **k: next(replies))
    with pytest.raises(EvaluationExecutionError):
        runner._judge_item(item(TaskType.generation), "answer", config().model_copy(update={"judge_double_pass": True}))


def test_multi_turn_executes_each_checker_and_keeps_evidence(monkeypatch, tmp_path):
    task = item()
    task.metadata["task_agent"]["interaction"] = {"max_turns": 1, "user_turns": ["Next"]}
    task.judge_tools = [JudgeToolRef(tool="python_tests", config={"test_code": f"payload = {{model_output}}\n# checker {n}"}) for n in range(2)]
    monkeypatch.setattr(runner, "call_target_model", lambda *a, **k: "")
    codes = []

    def execute(code, **kwargs):
        codes.append(code)
        return 0, "x" * 1000 + str(len(codes)), ""

    monkeypatch.setattr(runner, "run_python_sandbox", execute)

    def judge(task, response, cfg, **kwargs):
        transcript = json.loads(response)
        assert [m["content"] for m in transcript if m["role"] == "assistant"] == ["", ""]
        assert len(kwargs["external_evidence"]) == 2
        assert [e["stdout"][-1] for e in kwargs["external_evidence"]] == ["1", "2"]
        return 1, "Checked both"

    monkeypatch.setattr(runner, "_judge_item", judge)
    _, score, _ = runner._run_multi_turn(task, config().targets[0], config(), trace_dir=tmp_path)
    assert score == 1 and len(codes) == 2 and codes[0] != codes[1]
    assert len(json.loads((tmp_path / "judge-tool-evidence.json").read_text())) == 2


@pytest.fixture
def seeded_image(tmp_path):
    if os.environ.get("EVALCLAW_DOCKER_TESTS") != "1":
        pytest.skip("requires local Docker")
    name = "evalclaw-integrity-" + uuid.uuid4().hex[:12]
    (tmp_path / "Dockerfile").write_text("""FROM python:3.11-slim
RUN mkdir -p /workspace/data /workspace/private && echo original > /workspace/public.txt && echo fixture > /workspace/data/input.txt && echo secret > /workspace/private/secret.txt && chmod 0700 /workspace/private && chmod 0600 /workspace/private/secret.txt && ln -s /tmp /workspace/link
""")
    subprocess.run(["docker", "build", "--network", "none", "-t", name, str(tmp_path)], capture_output=True, text=True, check=True)
    try:
        yield name
    finally:
        subprocess.run(["docker", "image", "rm", name], capture_output=True, check=True)


def environment_task(image):
    return BenchmarkItem(id="env", dimension_id="d", task_type=TaskType.agent, prompt="Work",
        metadata={"agent_env": {"type": "docker_workspace", "image": image,
            "auto_select_image": False, "pull_image": False, "timeout": 30,
            "visible_files": {"public.txt": "override", "nested/public.txt": "new"},
            "hidden_files": {"grade.py": "print('0')"}, "test_command": "python3 grade.py"}})


def test_real_workspace_overlay_keeps_image_files_and_permissions(seeded_image):
    task = environment_task(seeded_image)
    task.metadata["agent_env"]["readiness_checks"] = [
        "test -r data/input.txt && test ! -r private/secret.txt && test -w nested && test -w public.txt",
    ]
    cfg = config()
    backend = DockerWorkspaceBackend(task, cfg)
    image, workdir = backend.prepare()
    capture = {}
    harness = ManifestHarnessRunner(ManifestHarness(name="fixture", run="true", model_env={}))
    try:
        assert (workdir / "data/input.txt").read_text().strip() == "fixture"
        assert (workdir / "public.txt").read_text() == "override"
        harness._launch(task, cfg.targets[0], cfg, image, workdir, capture=capture, preflight_only=True)
        proc = subprocess.run(["docker", "exec", capture["container_name"], "stat", "-c", "%u:%g:%a", "/workspace/private/secret.txt"], capture_output=True, text=True, check=True)
        assert proc.stdout.strip() == "0:0:600"
        assert len(capture["readiness_checks"]) == 1
    finally:
        cleanup_harness_session(capture)
        backend.cleanup(workdir)
    assert not workdir.exists()


def test_real_overlay_rejects_image_symlink(seeded_image):
    task = environment_task(seeded_image)
    task.metadata["agent_env"]["visible_files"] = {"link/escape.txt": "must not follow"}
    with pytest.raises(RuntimeError, match="workspace preparation failed"):
        DockerWorkspaceBackend(task, config()).prepare()


def test_real_readiness_and_preflight_are_distinct(seeded_image):
    task = environment_task(seeded_image)
    task.metadata["agent_env"]["preflight_commands"] = ["exit 17"]
    cfg = config()
    backend = DockerWorkspaceBackend(task, cfg)
    image, workdir = backend.prepare()
    harness = ManifestHarnessRunner(ManifestHarness(name="fixture", run="true", model_env={}))
    capture = {}
    try:
        with pytest.raises(RuntimeError, match="Environment check failed"):
            harness._launch(task, cfg.targets[0], cfg, image, workdir, capture=capture, preflight_only=True)
    finally:
        cleanup_harness_session(capture)
        backend.cleanup(workdir)
    image, workdir = backend.prepare()
    capture = {}
    try:
        assert harness._launch(task, cfg.targets[0], cfg, image, workdir, capture=capture) == ""
        assert "environment_checks" not in capture
    finally:
        cleanup_harness_session(capture)
        backend.cleanup(workdir)
    native = build_agent_environment(task, cfg)
    try:
        # Initial setup succeeds; only the disposable preflight runs this check.
        with pytest.raises(RuntimeError, match="Environment check failed"):
            native.preflight()
    finally:
        native.cleanup()
    task.metadata["agent_env"]["readiness_checks"] = ["test -r /missing-input"]
    with pytest.raises(RuntimeError, match="Environment check failed"):
        build_agent_environment(task, cfg)


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires local Docker")
def test_real_checker_reads_serialized_dialogue_and_can_write_report():
    task = item()
    task.judge_tools = [JudgeToolRef(tool="python_tests", config={"test_code": '''import json
payload = {model_output}
messages = json.loads(payload)
assert messages[1]["content"] == 'a "quoted" reply\\n第二行'
with open('report.json', 'w') as f:
    json.dump({"satisfied": 3, "total": 3}, f)
print(open('report.json').read())
'''})]
    transcript = json.dumps([{"role": "user", "content": "Request"},
                             {"role": "assistant", "content": 'a "quoted" reply\n第二行'}])
    evidence = runner._judge_tool_evidence(task, transcript, config())
    assert evidence[0]["returncode"] == 0, evidence[0]["stderr"]
    assert json.loads(evidence[0]["stdout"]) == {"satisfied": 3, "total": 3}
