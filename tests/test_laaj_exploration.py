from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall, ToolSpec
from evalclaw.quality import laaj as laaj_module
from evalclaw.quality import laaj_exploration as module
from evalclaw.runners import environment_actors, harness
from evalclaw.types import (
    AnalysisIteration,
    AnalysisReport,
    BenchmarkConfig,
    EvalSpec,
    TargetModelConfig,
    TaskSuite,
)
from tests.test_harness_runtime import _task
from tests.test_laaj import _response


def _suite(item=None):
    return TaskSuite(objective="Test contacts", spec=EvalSpec(objective="Test contacts"), tasks=[item or _task()])


def _call(manager, operation, **kwargs):
    result = manager.handle(ToolCall(id="call", name=module.LAAJ_EXPLORE_TOOL.name,
                                    arguments={"operation": operation, **kwargs}))
    assert result.error is None, result.content
    return json.loads(result.content)


@pytest.mark.parametrize("fail", [False, True])
def test_laaj_exploration_is_available_and_always_closed(monkeypatch, tmp_path, fail):
    closed = []
    budgets = []

    class Experiments:
        def __init__(self, *args):
            pass

        def handle(self, call):
            return "experiment result"

        def close(self):
            closed.append(True)

    def loop(*args, **kwargs):
        budgets.append(kwargs["max_tool_calls"])
        tool = kwargs["additional_tools"][0]
        assert kwargs["tool_handlers"][tool.name](None) == "experiment result"
        if fail:
            raise RuntimeError("judge disconnected")
        return _response()

    monkeypatch.setattr(laaj_module, "LaajExploration", Experiments)
    monkeypatch.setattr(laaj_module, "_run_laaj_tool_loop", loop)
    config = BenchmarkConfig(laaj_model="judge", laaj_api_key="test", laaj_tool_calls_per_item=600)
    if fail:
        with pytest.raises(RuntimeError, match="judge disconnected"):
            laaj_module.evaluate_with_laaj("goal", _suite(), None, config, trace_dir=tmp_path)
    else:
        report = laaj_module.evaluate_with_laaj("goal", _suite(), None, config, trace_dir=tmp_path)
        assert (report.correctness.score, report.faithfulness.score, report.diversity.score) == (4, 5, 3)
    assert budgets == [600] * len(closed)
    assert len(closed) == (laaj_module.LAAJ_MAX_ATTEMPTS if fail else 2)


def test_native_tools_probe_scope_and_cleanup(monkeypatch, tmp_path):
    made = []

    class Native:
        def __init__(self, item, config):
            self.item = item
            self.closed = False
            made.append(self)

        def observation(self):
            return self.item.prompt

        def tool_specs(self):
            return [ToolSpec(name="read_file"), ToolSpec(name="final")]

        def step(self, action):
            return SimpleNamespace(observation="contents", error=None, done=False)

        def evaluate_with_evidence(self, evidence):
            self.evidence = evidence
            return "trial checked"

        def _write_final_answer(self, answer):
            self.written_answer = answer

        def state(self):
            return {"final_answer": getattr(self, "written_answer", "")}

        def score(self):
            return 0.5

        def cleanup(self):
            self.closed = True

    monkeypatch.setattr(module, "build_agent_environment", Native)
    item = _task()
    item.metadata["agent_env"]["actors"] = []
    probe = item.model_copy(update={"prompt": "probe copy"}, deep=True)
    analysis = AnalysisReport(iterations=[AnalysisIteration(iteration=1, suite=_suite(probe))])
    manager = module.LaajExploration(_suite(item), analysis, BenchmarkConfig(), tmp_path)
    try:
        opened = _call(manager, "open", item_id=item.id, scope="probe", iteration=1)
        assert opened["observation"] == "probe copy"
        sid = opened["session_id"]
        _call(manager, "action", session_id=sid, action={"action": "read_file", "args": {"path": "a"}})
        trial = _call(manager, "evaluate", session_id=sid, final_answer="trial")
        assert trial["score"] == 0.5
        assert made[0].evidence["target_execution"]["tool_call_count"] == 1
        assert made[0].evidence["target_execution"]["trace"][0]["tool_call"]["name"] == "read_file"
        assert made[0].evidence["target"]["id"] == "laaj-experiment"
        assert made[0].written_answer == "trial"
        assert made[0].evidence["target_execution"]["final_state"] == {"final_answer": "trial"}
        reset = _call(manager, "reset", session_id=sid)
        assert reset["session_id"] != sid and made[0].closed
        assert item.prompt != probe.prompt
    finally:
        manager.close()
    assert all(e.closed for e in made)


def test_timeout_preserves_output_and_closes_environment(monkeypatch, tmp_path):
    closed = []

    def run(command, timeout):
        raise subprocess.TimeoutExpired(command, timeout, output=b"partial stdout", stderr=b"partial stderr")

    environment = SimpleNamespace(
        observation=lambda: "ready", tool_specs=lambda: [],
        run_external_command=run, cleanup=lambda: closed.append(True),
    )
    monkeypatch.setattr(module, "build_agent_environment", lambda *_: environment)
    item = _task()
    item.metadata["agent_env"]["actors"] = []
    manager = module.LaajExploration(_suite(item), None, BenchmarkConfig(), tmp_path)
    sid = _call(manager, "open", item_id=item.id)["session_id"]
    result = manager.handle(ToolCall(id="timeout", name=module.LAAJ_EXPLORE_TOOL.name, arguments={
        "operation": "command", "session_id": sid, "perspective": "reviewer", "command": "long-command",
    }))
    assert result.error == "exploration_failed"
    record = json.loads((tmp_path / sid / "experiment.json").read_text())
    assert record["operations"][0]["error"]["stdout"] == "partial stdout"
    assert record["operations"][0]["error"]["stderr"] == "partial stderr"
    assert record["closed_at"] and closed == [True]
    assert manager.sessions[sid].ended
    manager.close()
    assert closed == [True]


def test_all_components_close_even_when_controller_stop_fails(monkeypatch):
    closed = []
    environment = SimpleNamespace(cleanup=lambda: closed.append("environment"))
    monkeypatch.setattr(module, "build_agent_environment", lambda *_: environment)
    monkeypatch.setattr(harness, "cleanup_harness_session", lambda *_: closed.append("harness"))
    item = _task()
    item.metadata["agent_env"]["actors"] = []
    experiment = module.TaskExperiment(item, BenchmarkConfig(), "", None)

    def stop():
        raise RuntimeError("stop failed")

    experiment.controller = SimpleNamespace(stop=stop)
    experiment.actors = SimpleNamespace(
        runtime=SimpleNamespace(closed=SimpleNamespace(is_set=lambda: False)),
        close=lambda: closed.append("actors"),
    )
    with pytest.raises(RuntimeError, match="stop failed"):
        experiment.close()
    assert closed == ["actors", "environment", "harness"]


def test_vm_exploration_requires_private_creation_spec(monkeypatch):
    seen = []
    closed = []

    def build(item, config):
        seen.append(item.metadata["agent_env"])
        return SimpleNamespace(cleanup=lambda: closed.append(True))

    monkeypatch.setattr(module, "build_agent_environment", build)
    item = _task()
    item.metadata["agent_env"] = {"type": "vm", "bridge_url": "http://shared", "vm_id": "existing"}
    with pytest.raises(ValueError, match="creation specification"):
        module.TaskExperiment(item, BenchmarkConfig(), "", None)
    assert not seen
    item.metadata["agent_env"]["vm"] = {"image": "test"}
    original = item.model_dump_json()
    experiment = module.TaskExperiment(item, BenchmarkConfig(), "", None)
    experiment.close()
    assert "bridge_url" not in seen[0] and "vm_id" not in seen[0]
    assert seen[0]["requires_vm"] and seen[0]["destroy_vm_on_cleanup"]
    assert item.model_dump_json() == original and closed == [True]


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires local Docker images")
@pytest.mark.parametrize("name", ["openclaw", "openhands", "codex", "claude-code"])
def test_real_exploration_target_permissions_actor_reset_and_original_scorer(monkeypatch, tmp_path, name):
    calls = []

    def reply(messages, *args, **kwargs):
        calls.append(len(messages))
        value = "ack:" + messages[-1]["content"]
        return TargetToolModelResponse(adapter="openai", content=value, tool_calls=[],
                                       assistant_message={"role": "assistant", "content": value}, raw_response={})

    monkeypatch.setattr(environment_actors, "call_target_model_with_tools", reply)
    runner = harness.ManifestHarnessRunner(replace(
        harness.get_harness(name)._manifest, gateway=False, model_env={}, run="never-invoke-target",
    ))
    monkeypatch.setattr(harness, "get_harness", lambda _: runner)
    config = BenchmarkConfig(actor_model="test", actor_provider="openai", targets=[TargetModelConfig(
        provider="anthropic" if name == "claude-code" else "openai", model="test", harness=name,
    )])
    item = _task()
    item.metadata["agent_env"]["interventions"] = [{
        "id": "change", "trigger": {"type": "condition", "command": "test -f trigger", "poll_interval_seconds": 0.1},
        "action": {"type": "run_command", "command": "printf changed > event.txt", "timeout_seconds": 5},
    }]
    original = item.model_dump_json()
    manager = module.LaajExploration(_suite(item), None, config, tmp_path)
    try:
        sid = _call(manager, "open", item_id=item.id)["session_id"]
        solved = _call(manager, "command", session_id=sid, command="python3 solve.py")
        assert solved["returncode"] == 0 and solved["stdout"].strip() == "done"
        changed = _call(manager, "command", session_id=sid, command="touch trigger; for i in 1 2 3 4 5; do test -f event.txt && break; sleep 1; done; cat event.txt")
        assert changed["stdout"] == "changed"
        scored = _call(manager, "evaluate", session_id=sid)
        assert scored["score"] == 1 and scored["reviewer_access"] is False
        e = json.loads((tmp_path / sid / "evaluator-evidence.json").read_text())
        assert e["interventions"][0]["status"] == "completed"
        assert len(e["actors"]["interactions"]) == 2 and calls == [1, 3]
        assert e["purpose"] == "laaj_exploration"
        new_id = _call(manager, "reset", session_id=sid)["session_id"]
        clean = _call(manager, "command", session_id=new_id, command="test ! -e answer.txt && test ! -e event.txt")
        assert clean["returncode"] == 0
        private = _call(manager, "command", session_id=new_id, perspective="reviewer", command="cat sealed.txt")
        assert private["stdout"] == "private fixture"
        baseline = _call(manager, "evaluate", session_id=new_id)
        assert baseline["score"] == 0 and baseline["reviewer_access"] is True
        assert item.model_dump_json() == original
    finally:
        manager.close()
    assert manager.sessions == {}


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires local Docker images")
def test_real_native_submission_materializes_answer_and_episode_evidence(tmp_path):
    item = _task()
    item.metadata["agent_env"] = {
        "type": "docker_workspace", "image": "python:3.11", "auto_select_image": False,
        "timeout": 30, "max_steps": 3, "pull_image": False,
        "visible_files": {"answer.txt": ""},
        "hidden_files": {"evaluate.py": """import json
from pathlib import Path
evidence = json.loads(Path('/evalclaw-evidence/episode.json').read_text())
answer = json.loads(Path('/tmp/evalclaw_final_answer.json').read_text())['answer']
assert evidence['purpose'] == 'laaj_exploration'
assert evidence['target_execution']['final_response'] == answer
assert evidence['target_execution']['final_state']['final_answer'] == answer
assert evidence['target_execution']['tool_call_count'] == 1
score = int(answer == 'finished' and Path('answer.txt').read_text() == '42')
print(json.dumps({'score': score, 'passed': bool(score)}))
"""},
        "test_command": "python3 evaluate.py", "evaluation": {"result_format": "json_on_stdout"},
    }
    manager = module.LaajExploration(_suite(item), None, BenchmarkConfig(), tmp_path)
    try:
        sid = _call(manager, "open", item_id=item.id)["session_id"]
        _call(manager, "action", session_id=sid, action={
            "action": "write_file", "args": {"path": "answer.txt", "content": "42"},
        })
        result = _call(manager, "evaluate", session_id=sid, final_answer="finished")
        assert result["score"] == 1 and result["reviewer_access"] is False
    finally:
        manager.close()
