"""Contract acceptance through public construction, execution and review paths."""
import json
import os
from types import SimpleNamespace

import pytest

from evalclaw.construction.suite import build_task_suite
from evalclaw.execution.contract_capabilities import binding_issues
from evalclaw.execution.runner import run_eval
from evalclaw.execution.task_runtime import ContractSession, preflight_contract, run_contract
from evalclaw.protocols.task_definition import VerificationCase
from evalclaw.protocols.task_view import definition_text, definition_view
from evalclaw.protocols.tool import ToolCall, ToolSpec
from evalclaw.quality.analysis import _task_context
from evalclaw.quality.laaj_exploration import ContractExperiment
from evalclaw.quality.qc import run_qc_gate
from evalclaw.types import BenchmarkConfig, ChallengeEffort, EvalDimension, EvalSpec, TaskType
from tests.blueprint_factory import make_blueprint
from tests.config_helpers import dummy_config_kwargs, save_task_builder_response
from tests.test_composable_tasks import TARGET, Service, answer, service_task, task


def test_builder_to_execution_and_review(monkeypatch, tmp_path):
    candidate = task(challenge_effort="E2")
    raw = candidate.model_dump(mode="json", exclude={"id", "dimension_id", "source"})
    def builder(payload, **kwargs):
        return save_task_builder_response(payload, json.dumps({"tasks": [raw], "resources": []})), []
    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", builder)
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: answer())
    dim = EvalDimension(id="d", name="Test", description="Arithmetic", approach="Exact", challenge_effort=ChallengeEffort.E2)
    spec = EvalSpec(objective="Arithmetic", dimensions=[dim], task_types=[TaskType.generation])
    bp = make_blueprint("b", "d", "Test", task_type=TaskType.generation, challenge_effort=ChallengeEffort.E2)
    config = BenchmarkConfig(**{**dummy_config_kwargs(), "qc_api_key": None}, targets=[TARGET], output_dir=str(tmp_path),
                             use_web_research=False, task_builder_repair_attempts=0)
    suite = build_task_suite(spec, [bp], config)
    assert len(suite.tasks) == 1, suite.construction_notes
    assert suite.tasks[0].prompt == ""
    qc = run_qc_gate(suite, config)
    assert qc.passed_item_ids == [suite.tasks[0].id]
    result = run_eval(suite, qc, config).results[0]
    assert result.error is None
    assert result.score == 1
    assert _task_context(suite)[0]["task_definition"]["content"]["messages"][0]["content"] == "Reply 42."
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: pytest.fail("trial must not invoke target"))
        trial = ContractExperiment(suite.tasks[0], config, TARGET.id, tmp_path / "trial")
        try:
            assert trial.perform({"operation": "evaluate", "final_answer": "42"})["metrics"][0]["value"] == 1
        finally:
            trial.close()


def test_malformed_scoring_rejected_early():
    with pytest.raises(ValueError):
        task(evaluation={"metrics": [{"id": "score"}], "scorers": [{"id": "s", "kind": "exact", "metrics": ["score"]}]})
    with pytest.raises(ValueError):
        task(reference_answer="ignored answer")
    item = task()
    item.evaluation.scalar = None
    assert binding_issues(item, BenchmarkConfig(analyser_api_key="fake"), TARGET)
    assert not binding_issues(item, BenchmarkConfig(), TARGET)


def test_native_workspace_end_and_preflight(monkeypatch):
    from evalclaw.execution.docker_agent_env import DockerAgentStepOutcome
    class Environment:
        interventions = []
        done = False
        steps = 0
        def tool_specs(self): return [ToolSpec(name="finish", parameters={"type": "object", "properties": {}})]
        def state(self): return {"steps": self.steps}
        def step(self, action):
            self.done = True
            self.steps += 1
            return DockerAgentStepOutcome("Done", done=True)
        def cleanup(self): pass
        def preflight(self, **kwargs): raise RuntimeError("broken grader")
    monkeypatch.setattr("evalclaw.execution.agent_envs.build_agent_environment", lambda *a: Environment())
    item = task(environment={"image": "test", "max_steps": 1})
    with pytest.raises(RuntimeError, match="broken grader"):
        preflight_contract(item, BenchmarkConfig(), TARGET)
    calls = []
    def model(*a, **kw):
        calls.append(1)
        assert len(calls) == 1
        return answer("42", [ToolCall(id="c", name="finish")])
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    result = run_contract(item, BenchmarkConfig(), TARGET)
    assert result.error is None
    assert result.episode.usage["target_calls"] == 1


def test_setup_does_not_start_target_budget_or_interventions(monkeypatch):
    started = []
    class Environment:
        done = False
        def tool_specs(self): return []
        def state(self): return {}
        def cleanup(self): pass
    monkeypatch.setattr("evalclaw.execution.agent_envs.build_agent_environment", lambda *a: Environment())
    monkeypatch.setattr("evalclaw.runners.agent._start_interventions", lambda env: started.append(env))
    session = ContractSession(task(environment={"image": "test"}), BenchmarkConfig(), TARGET)
    try:
        session.prepare()
        assert session.started is None
        assert started == []
        session.run_trial([{"content": "42"}])
        assert session.started is not None
        assert len(started) == 1
    finally:
        session.close()


def test_complete_message_trial_and_no_second_submission(tmp_path):
    item = task()
    item.evaluation.scorers[0].response_view = "completed_message"
    trial = ContractExperiment(item, BenchmarkConfig(targets=[TARGET]), TARGET.id, tmp_path)
    try:
        assert trial.perform({"operation": "evaluate", "final_answer": "42"})["metrics"][0]["value"] == 1
        assert trial.runtime.episode.final_messages[-1]["content"] == "42"
        assert any(e.origin == "trial_target" for e in trial.runtime.episode.events)
        with pytest.raises(ValueError):
            trial.perform({"operation": "evaluate", "final_answer": "42"})
    finally:
        trial.close()


def test_scripted_dialogue_uses_protocol_and_verifies_bad_answers(monkeypatch):
    item = task(interaction={"protocol": "dialogue", "turns": [{"role": "user", "content": "Final answer?"}]})
    item.evaluation.verification_cases = [
        VerificationCase(
            id="positive", responses=[{"content": "Thinking"}, {"content": "42"}], expected_metrics={"accuracy": (1, 1)})]
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: pytest.fail("must not call target"))
    preflight_contract(item, BenchmarkConfig(), TARGET)
    item.evaluation.verification_cases[0].responses[-1].content = "wrong"
    with pytest.raises(ValueError, match="positive"):
        preflight_contract(item, BenchmarkConfig(), TARGET)


@pytest.mark.parametrize("reset", [False, True])
def test_cli_dialogue_projection_preserves_stages_and_scores_transcript(monkeypatch, tmp_path, reset):
    from evalclaw.runners.harness import ManifestHarness, ManifestHarnessRunner
    runner = ManifestHarnessRunner(ManifestHarness(name="test", run="test", session_run="test {session_id}", model_env={}))
    def launch(projected, target, config, **kwargs):
        stages = projected.workflow.stages
        assert [s.environment for s in stages] == ["fresh", "reuse", "reuse"]
        assert [s.context for s in stages[:2]] == ["fresh", "fresh" if reset else "continue"]
        assert [s.prompt for s in stages[:2]] == ["Reply 42.", "What did you do?"]
        evidence = {"target_execution": {"final_response": "42", "tool_call_count": 2},
                    "stages": [{"prompt": "Reply 42.", "output": "working", "context": "fresh"},
                               {"prompt": "What did you do?", "output": "42", "context": "fresh" if reset else "continue"}]}
        score, reason = kwargs["evaluation_callback"](SimpleNamespace(), "image", tmp_path, evidence, "container")
        return "transcript", score, reason
    monkeypatch.setattr(runner, "run", launch)
    monkeypatch.setattr("evalclaw.runners.harness.get_harness", lambda name: runner)
    target = TARGET.model_copy(update={"harness": "openclaw"})
    item = task(environment={"image": "test"}, interaction={"protocol": "dialogue", "reset_between_turns": reset,
                "turns": [{"role": "user", "content": "What did you do?"}]})
    result = run_contract(item, BenchmarkConfig(targets=[target]), target, trace_dir=tmp_path)
    assert result.error is None
    assert result.episode.outputs == ["working", "42"]
    assert len(result.episode.final_messages) == (2 if reset else 4)
    assert len([e for e in result.episode.events if e.kind == "dialogue_stage"]) == 2
    assert result.score == 1


def test_cli_continuation_requires_session_support(monkeypatch):
    from evalclaw.runners.harness import ManifestHarness, ManifestHarnessRunner
    runner = ManifestHarnessRunner(ManifestHarness(name="test", run="test", model_env={}))
    monkeypatch.setattr("evalclaw.runners.harness.get_harness", lambda name: runner)
    target = TARGET.model_copy(update={"harness": "openclaw"})
    item = task(environment={"image": "test"}, interaction={"protocol": "dialogue",
                "turns": [{"role": "user", "content": "Continue"}]})
    assert binding_issues(item, BenchmarkConfig(), target)
    item.interaction.reset_between_turns = True
    assert not binding_issues(item, BenchmarkConfig(), target)


def test_dialogue_binding_checks_do_not_materialize_inputs(monkeypatch):
    from evalclaw.runners.harness import ManifestHarness, ManifestHarnessRunner
    runner = ManifestHarnessRunner(ManifestHarness(name="fixture", run="test", session_run="test {session_id}", model_env={}))
    monkeypatch.setattr("evalclaw.runners.harness.get_harness", lambda name: runner)
    monkeypatch.setattr("evalclaw.execution.task_runtime.render_messages", lambda *a, **kw: pytest.fail("static check must not read input files"))
    target = TARGET.model_copy(update={"harness": "openclaw"})
    interaction = {"protocol": "dialogue", "turns": [{"role": "user", "content": "Continue"}]}
    assert not binding_issues(task(environment={"image": "test"}, interaction=interaction), BenchmarkConfig(), target)
    assert binding_issues(service_task(interaction=interaction), BenchmarkConfig(), target)


def test_native_dialogue_delivers_followup_after_final_without_resetting_workspace(monkeypatch):
    class Environment:
        interventions = []
        done = False
        steps = 0
        max_steps = 5
        final_answer = ""
        state_value = 0
        def tool_specs(self): return [ToolSpec(name="final", parameters={"type": "object"})]
        def state(self): return {"value": self.state_value}
        def step(self, action):
            self.done = True
            self.steps += 1
            self.state_value = 7
            return SimpleNamespace(observation="Submitted", done=True, error=None)
        def cleanup(self): pass
    env = Environment()
    monkeypatch.setattr("evalclaw.execution.agent_envs.build_agent_environment", lambda *a: env)
    item = task(environment={"image": "test"}, interaction={"protocol": "dialogue", "reset_between_turns": True,
               "turns": [{"role": "user", "content": "Now report your progress"}]})
    session = ContractSession(item, BenchmarkConfig(), TARGET)
    try:
        session.prepare()
        session.run_trial([{"content": "first", "tool_calls": [{"id": "submit", "name": "final"}]}, {"content": "42"}])
        assert session.episode.outputs == ["first", "42"]
        assert session.episode.final_state == {"value": 7}
        assert session.episode.usage["tool_calls"] == 1
        assert env.steps == 1
        assert session.legacy_evidence({"episode": session.episode.model_dump(mode="json")})["target_execution"]["final_response"] == "42"
    finally:
        session.close()


def test_qc_accepts_supported_cli_workflow_and_checks_native_limitations(monkeypatch):
    from evalclaw.execution.contract_capabilities import native_workflow_issues, workspace_projection
    item = workspace_projection(task(dimension_id="d", environment={"image": "test"},
                interaction={"protocol": "dialogue", "turns": [{"role": "user", "content": "Report progress"}]}))
    from evalclaw.types import TaskSuite
    suite = TaskSuite(spec=EvalSpec(objective="test", dimensions=[EvalDimension(id="d", name="D", description="D", approach="D")]),
                      objective="test", tasks=[item])
    monkeypatch.setattr("evalclaw.quality.qc._static_item_issues", lambda *a: [])
    config = BenchmarkConfig(use_llm_qc=False, targets=[TARGET.model_copy(update={"harness": "openclaw"})])
    assert run_qc_gate(suite, config).passed_item_ids == [item.id]
    assert native_workflow_issues(item) == []
    from evalclaw.types import EnvironmentInterventionSpec
    item.environment.interventions = [EnvironmentInterventionSpec(id="end", trigger={"type": "episode_end"}, action={"command": "true"})]
    assert native_workflow_issues(item)


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires local Docker image")
@pytest.mark.parametrize("reset", [False, True])
def test_real_cli_dialogue_keeps_workspace_and_session_semantics(monkeypatch, tmp_path, reset):
    from evalclaw.runners.harness import ManifestHarness, ManifestHarnessRunner
    runner = ManifestHarnessRunner(ManifestHarness(name="fixture", run="python3 solve.py {task}",
        session_run="python3 solve.py {task} {session_id}", model_env={}))
    monkeypatch.setattr("evalclaw.runners.harness.get_harness", lambda name: runner)
    target = TARGET.model_copy(update={"harness": "openclaw"})
    item = task(content={"messages": [{"role": "user", "content": "Do the first part."}]},
        environment={"image": "python:3.11", "auto_select_image": False, "network": "none",
            "visible_files": {"solve.py": """import json, sys
from pathlib import Path
p = Path('sessions.json')
sessions = json.loads(p.read_text()) if p.exists() else []
sessions.append(sys.argv[2])
p.write_text(json.dumps(sessions))
print('first part completed' if len(sessions) == 1 else '42')
"""}}, interaction={"protocol": "dialogue", "reset_between_turns": reset,
                     "turns": [{"role": "user", "content": "Now report."}]})
    item.evaluation.scorers[0].strip = True  # This fixture prints newline-terminated CLI output.
    result = run_contract(item, BenchmarkConfig(targets=[target]), target, trace_dir=tmp_path)
    assert result.error is None, result.error
    assert result.score == 1
    assert result.episode.outputs == ["first part completed\n", "42\n"]
    stages = result.episode.artifacts["native_evaluator_evidence"]["stages"]
    assert (stages[0]["session_id"] != stages[1]["session_id"]) is reset
    assert len(result.episode.final_messages) == (2 if reset else 4)


def test_cli_contract_reuses_harness_and_new_scorer(monkeypatch, tmp_path):
    from evalclaw.runners.harness import ManifestHarness, ManifestHarnessRunner
    runner = ManifestHarnessRunner(ManifestHarness(name="test", run="test", model_env={}))
    calls = []
    def launch(item, target, config, **kwargs):
        calls.append(item)
        assert item.prompt == "Reply 42."
        assert item.content is None
        evidence = {"target_execution": {"final_response": "42", "tool_call_count": 2}, "termination": {"status": "completed"}}
        score, reason = kwargs["evaluation_callback"](SimpleNamespace(), "image", tmp_path, evidence, "container")
        assert score == 1
        return "native CLI transcript", score, reason
    monkeypatch.setattr(runner, "run", launch)
    monkeypatch.setattr("evalclaw.runners.harness.get_harness", lambda name: runner)
    target = TARGET.model_copy(update={"harness": "openclaw"})
    item = task(environment={"image": "test"})
    result = run_contract(item, BenchmarkConfig(targets=[target]), target, trace_dir=tmp_path)
    assert result.error is None
    assert result.score == 1
    assert result.episode.outputs == ["42"]
    assert item.content is not None
    assert item.prompt == ""
    assert len(calls) == 1


def test_unsupported_roles_and_asset_permissions_are_explicit():
    from evalclaw.execution.task_runtime import contract_issues
    item = task(interaction={"participants": [{"id": "ghost", "role": "simulator"}]})
    assert contract_issues(item)
    item = task(environment={"image": "test"}, assets=[{"path": "x", "id": "x", "writable": False}])
    assert binding_issues(item, BenchmarkConfig(), TARGET)


def test_definition_view_is_bounded_and_complete_content_reachable():
    item = service_task()
    text = "core implementation\n" * 30000
    item.environment.service.files = {"large.py": text}
    view = definition_view(item)
    entry = view["environment"]["service"]["files"]["large.py"]
    assert len(json.dumps(view)) < 10000
    assert definition_text(item, entry["definition_path"]) == text


def test_trial_target_permissions_and_budget_are_enforced():
    item = service_task(interaction={"protocol": "tool_loop", "participants": [{"id": "model", "role": "target", "tools": []}],
                                     "budget": {"tool_calls": 1}})
    session = ContractSession(item, BenchmarkConfig(), TARGET, component_factory=Service)
    try:
        session.prepare()
        session.trial_submit(calls=[ToolCall(id="c", name="increment")])
        assert session.environment.state == 0
        assert session.episode.usage["tool_calls"] == 1
        assert session.episode.events[-1].data["error"]
    finally:
        session.close()


def test_journal_restarts_with_episode_and_preserves_controller_view(tmp_path):
    for _ in range(2):
        session = ContractSession(task(), BenchmarkConfig(), TARGET, tmp_path)
        session.prepare()
        session.run_trial([{"content": "42"}])
        controller_events = session.controller_events(0)
        assert any(e["kind"] == "model_response" and e["origin"] == "target" for e in controller_events)
        assert any(e.origin == "trial_target" for e in session.episode.events)
        session.close()
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert len(events) == len(session.episode.events)
    assert len({e["id"] for e in events}) == len(events)


def test_qc_can_read_complete_component_definition(monkeypatch):
    from evalclaw.quality.llm_checks import _llm_qc
    from tests.test_laaj import _suite
    item = service_task()
    item.environment.service.files = {"check.py": "native scoring implementation"}
    suite = _suite().model_copy(update={"tasks": [item]})
    requests = []
    def model(messages, **kwargs):
        assert kwargs["model"] == "qc-model"
        requests.append(messages)
        if len(requests) == 1:
            sample = json.loads(messages[0]["content"])["items"][0]
            assert sample["task_definition"]["content"] == item.content.model_dump(mode="json", exclude_defaults=True)
            assert "reference_trajectory" not in sample
            assert "prompt" not in sample
            return answer("", [ToolCall(id="read", name="read_task_file", arguments={
                "item_id": item.id, "area": "definition", "path": "/environment/service/files/check.py"})])
        result = json.loads(messages[-1]["content"])
        assert result["content"] == "native scoring implementation"
        return answer('{"issues": []}')
    monkeypatch.setattr("evalclaw.quality.laaj.call_orchestrator_with_tools", model)
    config = BenchmarkConfig(qc_model="qc-model", qc_api_key="fake", use_llm_qc=True)
    assert _llm_qc(suite, config) == []
    assert len(requests) == 2
    from evalclaw.quality.laaj_tools import read_task_file
    missing = read_task_file(ToolCall(id="bad", name="read_task_file", arguments={
        "item_id": item.id, "area": "definition", "path": "/content/messages/99"}), suite)
    assert missing.error == "task_file_not_found"


def test_cli_lifecycle_preserves_native_record_and_unknown_usage(monkeypatch, tmp_path):
    from evalclaw.runners import harness
    runner = harness.ManifestHarnessRunner(harness.ManifestHarness(name="test", run="test", model_env={}))
    cleaned = []
    backend = SimpleNamespace(kind="docker_workspace", prepare=lambda: ("image", tmp_path),
                              cleanup=lambda directory: cleaned.append(directory))
    monkeypatch.setattr(harness, "environment_backend", lambda *a: backend)
    monkeypatch.setattr(harness, "get_harness", lambda name: runner)
    monkeypatch.setattr(harness, "cleanup_harness_session", lambda capture: None)
    monkeypatch.setattr(runner, "_launch", lambda *a, **kw: "42")
    monkeypatch.setattr(runner, "_collect_trajectory", lambda *a: None)
    monkeypatch.setattr(runner, "_image_identity", lambda *a: {"id": "sha256:test"})
    target = TARGET.model_copy(update={"harness": "test"})
    result = run_contract(task(environment={"image": "test"}), BenchmarkConfig(), target, trace_dir=tmp_path)
    assert result.error is None
    assert result.score == 1
    assert "tool_calls" not in result.episode.usage
    assert json.loads((tmp_path / "native-episode.json").read_text())["harness"] == "test"
    assert json.loads((tmp_path / "episode.json").read_text())["bindings"]["runtime"] == "evalclaw.contract.v2"
    assert cleaned == [tmp_path]


def test_preflight_preserves_evaluation_service_failure(monkeypatch):
    from evalclaw.construction.suite import _preflight_builder_environments
    from evalclaw.execution.errors import EvaluationExecutionError, JudgeResponseError
    dimension = EvalDimension(id="d", name="Test", description="Test", approach="Test")
    blueprint = make_blueprint("b", "d", "Test")
    def fail(*a, **kw):
        raise EvaluationExecutionError("scoring endpoint unavailable")
    monkeypatch.setattr("evalclaw.execution.task_runtime.preflight_contract", fail)
    with pytest.raises(EvaluationExecutionError):
        _preflight_builder_environments([task()], dimension=dimension, blueprint=blueprint,
                                        resources=[], config=BenchmarkConfig(targets=[TARGET]))
    def invalid(*a, **kw):
        raise JudgeResponseError("malformed judge output")
    monkeypatch.setattr("evalclaw.execution.task_runtime.preflight_contract", invalid)
    issues, failed, blocked = _preflight_builder_environments([task()], dimension=dimension,
        blueprint=blueprint, resources=[], config=BenchmarkConfig(targets=[TARGET]))
    assert not issues and not failed
    assert blocked == {"test": "malformed judge output"}


def test_simulated_results_enforce_target_tool_permission():
    item = task(interaction={"protocol": "model", "controller_prompt": "Control", "controller_actions": ["tool_result"],
                             "participants": [{"id": "model", "role": "target", "tools": []}]})
    session = ContractSession(item, BenchmarkConfig(), TARGET)
    session.tools = [ToolSpec(name="restricted", parameters={"type": "object"})]
    session.pending["call"] = ToolCall(id="call", name="restricted")
    result = session.control({"action": "tool_result", "call_id": "call", "content": "Forged success"})
    assert result["error"]
    assert result["content"] == ""
    assert session.episode.usage["tool_calls"] == 1


@pytest.mark.parametrize("kind", ["llm", "agent"])
@pytest.mark.parametrize("exhausted", [False, True])
def test_native_judge_empty_responses_are_not_task_defects(monkeypatch, tmp_path, kind, exhausted):
    from evalclaw.execution.errors import JudgeResponseError
    from evalclaw.models.llm import LLMFinalContentMissingError
    item = task(evaluation={"metrics": [{"id": "quality", "minimum": 0, "maximum": 1}],
                            "scorers": [{"id": "judge", "kind": kind, "instructions": "Score the answer", "metrics": ["quality"]}]})
    calls = []
    def model(*args, **kwargs):
        calls.append(kwargs)
        if exhausted or len(calls) < 3:
            raise LLMFinalContentMissingError("reasoning only")
        return answer('{"metrics": [{"metric": "quality", "value": 1}]}')
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    session = ContractSession(item, BenchmarkConfig(task_models=[TARGET]), TARGET, tmp_path)
    try:
        session.prepare()
        session.run_trial([{"content": "42"}])
        if exhausted:
            with pytest.raises(JudgeResponseError):
                session.require_valid_scoring()
            assert session.episode.metrics[0].status == "error"
        else:
            session.require_valid_scoring()
            assert session.episode.metrics[0].value == 1
        assert len(calls) == 3
    finally:
        session.close()


@pytest.mark.parametrize("kind", ["llm", "agent"])
def test_preflight_continues_after_exhausted_empty_judge(monkeypatch, tmp_path, kind):
    from evalclaw.construction.suite import _preflight_builder_environments
    from evalclaw.models.llm import LLMFinalContentMissingError

    calls = []
    def model(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) <= 3:
            raise LLMFinalContentMissingError("reasoning only")
        return answer('{"metrics": [{"metric": "quality", "value": 1}]}')

    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    items = [task(id=item_id, evaluation={
        "metrics": [{"id": "quality", "minimum": 0, "maximum": 1}],
        "scorers": [{"id": "judge", "kind": kind, "instructions": "Score the answer", "metrics": ["quality"]}],
        "verification_cases": [{"id": "answer", "responses": [{"content": "42"}],
                                "expected_metrics": {"quality": [0, 1]}}],
    }) for item_id in ("blocked", "valid")]
    issues, failed, blocked = _preflight_builder_environments(
        items, dimension=EvalDimension(id="d", name="Test", description="Test", approach="Test"),
        blueprint=make_blueprint("b", "d", "Test"), resources=[],
        config=BenchmarkConfig(targets=[TARGET], task_models=[TARGET]), trace_dir=tmp_path,
    )
    assert len(calls) == 4
    assert not issues and not failed
    assert set(blocked) == {"blocked"}


@pytest.mark.parametrize("kind", ["llm", "agent"])
def test_judge_repairs_scores_and_preserves_service_errors(monkeypatch, kind):
    from evalclaw.execution.errors import EvaluationExecutionError, JudgeResponseError
    item = task(evaluation={"metrics": [{"id": "quality", "minimum": 0, "maximum": 1}],
                            "scorers": [{"id": "judge", "kind": kind, "instructions": "Score the answer", "metrics": ["quality"]}]})
    session = ContractSession(item, BenchmarkConfig(task_models=[TARGET]), TARGET)
    replies = iter([answer('{"metrics": []}'), answer('{"metrics": [{"metric": "quality", "value": 1}]}')])
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: next(replies))
    session.prepare()
    session.run_trial([{"content": "42"}])
    session.require_valid_scoring()
    assert session.episode.metrics[0].value == 1
    session.close()
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: answer("invalid"))
    session = ContractSession(item, BenchmarkConfig(task_models=[TARGET]), TARGET)
    try:
        session.prepare()
        session.run_trial([{"content": "42"}])
        with pytest.raises(JudgeResponseError):
            session.require_valid_scoring()
    finally:
        session.close()
    def offline(*a, **kw):
        raise OSError("endpoint offline")
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", offline)
    session = ContractSession(item, BenchmarkConfig(task_models=[TARGET]), TARGET)
    try:
        session.prepare()
        session.run_trial([{"content": "42"}])
        with pytest.raises(EvaluationExecutionError) as exc:
            session.require_valid_scoring()
        assert not isinstance(exc.value, JudgeResponseError)
    finally:
        session.close()


@pytest.mark.skipif(os.environ.get("EVALCLAW_TEST_COMPONENT_DOCKER") != "1", reason="explicit Docker integration test")
def test_real_workspace_preflight_and_declared_verification(monkeypatch, tmp_path):
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: pytest.fail("trial must not invoke target"))
    item = task(environment={"image": "python:3.11-slim", "preflight_commands": ["python -c 'assert 2+2 == 4'"],
                             "verification_cases": [{"id": "positive", "commands": ["python -c 'assert 2+2 == 4'"],
                                                     "final_answer": "42", "min_score": 1, "max_score": 1}]})
    preflight_contract(item, BenchmarkConfig(targets=[TARGET], docker_auto_select_image=False), TARGET, tmp_path)
    item.environment.verification_cases[0].final_answer = "wrong"
    with pytest.raises(ValueError, match="positive"):
        preflight_contract(item, BenchmarkConfig(targets=[TARGET], docker_auto_select_image=False), TARGET)
