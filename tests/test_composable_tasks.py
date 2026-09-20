import copy
import json
import os
from pathlib import Path

import pytest

from evalclaw.construction.parsing import _task_from_raw
from evalclaw.execution.task_runtime import ContractSession, render_messages, run_contract
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.task_definition import MetricResult
from evalclaw.protocols.tool import ToolCall
from evalclaw.types import BenchmarkConfig, BenchmarkItem, TargetModelConfig, TaskDefinition


def task(**updates):
    values = dict(id="test", title="Task", content={"messages": [{"role": "user", "content": "Reply 42."}]},
        evaluation={"references": [{"id": "answer", "kind": "answer", "value": "42", "semantics": "exhaustive"}],
                    "metrics": [{"id": "accuracy", "minimum": 0, "maximum": 1}],
                    "scorers": [{"id": "checker", "kind": "exact", "references": ["answer"], "metrics": ["accuracy"]}],
                    "scalar": {"metric": "accuracy", "minimum": 0, "maximum": 1}})
    return BenchmarkItem(**{**values, **updates})


TARGET = TargetModelConfig(id="target", provider="openai", model="test", api_key="not-a-real-key")


def answer(text="42", calls=()):
    message = {"role": "assistant", "content": text}
    return TargetToolModelResponse("openai", text, list(calls), message,
                                   {"choices": [{"message": message}], "usage": {"total_tokens": 3}})


def test_exact_context_and_independent_scoring(monkeypatch, tmp_path):
    item = task(task_type="choice", content={"messages": [
        {"role": "system", "content": "Native instructions"},
        {"role": "user", "content": "Earlier question", "origin": "seeded_context"},
        {"role": "assistant", "content": "Earlier answer", "origin": "seeded_context"},
        {"role": "user", "content": "Native question, with options embedded."}]})
    captured = []
    def model(messages, *args, **kwargs):
        captured.extend(copy.deepcopy(messages))
        return answer()
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    result = run_contract(item, BenchmarkConfig(), TARGET, trace_dir=tmp_path)
    assert result.error is None
    assert result.score == 1
    assert [m["content"] for m in captured] == ["Native instructions", "Earlier question", "Earlier answer", "Native question, with options embedded."]
    assert result.episode.outputs == ["42"]
    assert result.episode.events[0].origin == "task"
    assert json.loads((tmp_path / "episode.json").read_text())["metrics"][0]["value"] == 1
    restored = BenchmarkItem.model_validate_json(item.model_dump_json())
    assert restored.content == item.content
    assert restored.evaluation == item.evaluation
    assert "source_definition" not in restored.model_dump()


def test_builder_can_author_and_parse_same_contract():
    item = task()
    raw = item.model_dump(mode="json", exclude={"source", "id", "dimension_id"})
    parsed = _task_from_raw(raw, "builder-task", default_dimension_id="dimension")
    assert parsed.content == item.content
    assert parsed.evaluation == item.evaluation
    from evalclaw.quality.static_checks import _static_item_issues
    assert not _static_item_issues(item)


def test_asset_visibility_digest_and_full_context(tmp_path):
    import hashlib
    path = tmp_path / "long.txt"
    text = "begin\n" + "x" * 300000 + "\nend"
    path.write_text(text)
    item = task(assets=[{"id": "document", "path": str(path), "sha256": hashlib.sha256(text.encode()).hexdigest()}],
                content={"messages": [{"role": "user", "content": [{"type": "asset", "asset_id": "document"}]}]})
    assert render_messages(item)[0]["content"] == text
    item.assets[0].visibility = ["judge"]
    with pytest.raises(PermissionError):
        render_messages(item)
    item.assets[0].visibility = ["target"]
    path.write_text("modified")
    with pytest.raises(ValueError, match="digest"):
        render_messages(item)


class Service:
    methods = {"initialize", "finalize", "call_tool", "checkpoint", "restore", "score"}
    instances = []
    def __init__(self, spec, assets=(), **kwargs):
        self.calls = []
        self.state = 0
        self.closed = False
        self.instances.append(self)
    def call(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "initialize":
            return {"state": 0, "tools": [{"name": "increment", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}]}
        if method == "call_tool":
            self.state += 1
            return {"content": str(self.state)}
        if method == "checkpoint":
            return {"counter": self.state}
        if method == "restore":
            self.state = params["checkpoint"]["counter"]
            return {}
        if method == "finalize":
            return {"state": self.state, "artifacts": {"exported": True}}
        if method == "score":
            assert params["episode"]["artifacts"]["exported"]
            return {"metrics": [{"metric": "utility", "value": params["episode"]["final_state"]},
                                {"metric": "attack_success", "value": 0}]}
        raise AssertionError(method)
    def close(self):
        self.closed = True


def service_task(**updates):
    return task(environment={"type": "tool_service", "service": {"image": "test", "version": "1", "command": ["service"]},
                             "capabilities": ["checkpoint"]},
                evaluation={"metrics": [{"id": "utility"}, {"id": "attack_success", "direction": "lower"}],
                            "scorers": [{"id": "native", "kind": "environment", "metrics": ["utility", "attack_success"]}],
                            "scalar": {"metric": "utility", "minimum": 0, "maximum": 1}}, **updates)


def test_native_service_lifecycle_scoring_and_permissions(monkeypatch):
    item = service_task(interaction={"protocol": "tool_loop"})
    responses = iter([answer("", [ToolCall(id="c1", name="increment")]), answer()])
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **k: next(responses))
    session = ContractSession(item, BenchmarkConfig(), TARGET, component_factory=Service)
    session.prepare()
    original = session.environment
    session.run()
    assert session.episode.final_state == 1
    session.evaluate()
    assert [(m.metric, m.value) for m in session.episode.metrics] == [("utility", 1), ("attack_success", 0)]
    # Scoring uses a new environment service, never the target's mutable instance.
    assert [c[0] for c in original.calls] == ["initialize", "call_tool", "finalize"]
    assert session.episode.usage["tool_calls"] == 1
    session.close()
    assert original.closed


@pytest.mark.parametrize("missing", ["finalize", "call_tool", "restore", "score"])
def test_missing_environment_methods_fail_before_target(missing):
    class IncompleteService(Service):
        methods = Service.methods - {missing}
    session = ContractSession(service_task(), BenchmarkConfig(), TARGET, component_factory=IncompleteService)
    try:
        with pytest.raises(ValueError, match=missing):
            session.prepare()
        assert not session.episode.outputs
        assert "target_calls" not in session.episode.usage
    finally:
        session.close()


def test_missing_original_scorer_is_representable_but_not_executable(monkeypatch):
    item = task(evaluation={"metrics": [{"id": "native"}], "scorers": [{
        "id": "original", "kind": "component", "metrics": ["native"], "component": {
            "status": "not_provided", "unavailable_reason": "Original scoring package not supplied"}}]})
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **k: pytest.fail("must not call"))
    result = run_contract(item, BenchmarkConfig(), TARGET)
    assert result.execution["stage"] == "preflight"
    assert "Original scoring package not supplied" in result.error
    assert not result.episode.outputs


@pytest.mark.parametrize("returncode,structured,required,valid", [
    (0, True, True, True), (1, True, True, True), (0, False, False, True),
    (1, False, False, True), (2, True, True, False), (0, False, True, False),
])
def test_script_failure_is_not_a_valid_zero_score(returncode, structured, required, valid):
    from evalclaw.execution.evaluation import require_valid_evaluator_execution
    result = {"returncode": returncode, "evaluator": {"structured": structured}, "stderr": "diagnostic"}
    evaluation = {"result_format": "json_on_stdout"} if required else {}
    if valid:
        require_valid_evaluator_execution(result, evaluation)
    else:
        with pytest.raises(RuntimeError):
            require_valid_evaluator_execution(result, evaluation)


def test_branch_restores_only_requested_state_and_keeps_audit():
    item = service_task(interaction={"protocol": "model", "controller_prompt": "Audit", "controller_actions": [
        "message", "checkpoint", "branch", "reset_session", "end"], "budget": {"branches": 2}})
    session = ContractSession(item, BenchmarkConfig(actor_model="test"), TARGET, component_factory=Service)
    session.prepare()
    session.control({"action": "checkpoint", "id": "start", "scopes": ["conversation"]})
    session.control({"action": "message", "message": {"role": "user", "content": "Branch input"}})
    session.tool_call(ToolCall(id="c1", name="increment"))
    count = len(session.episode.events)
    session.control({"action": "branch", "id": "start", "branch": "second"})
    assert len(session.messages) == 1
    assert session.environment.state == 1
    assert session.episode.usage["tool_calls"] == 1
    assert session.episode.usage["branches"] == 1
    assert len(session.episode.events) == count + 1
    with pytest.raises(PermissionError):
        session.control({"action": "register_tools", "tools": []})
    session.close()


def test_budget_preserves_partial_response_and_scorer_errors(monkeypatch):
    item = task(interaction={"protocol": "dialogue", "turns": [{"role": "user", "content": "Continue"}],
                            "budget": {"target_calls": 1}})
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **k: answer())
    result = run_contract(item, BenchmarkConfig(), TARGET)
    assert result.error is None
    assert result.episode.termination == "budget_exhausted"
    assert result.raw_response == "42"
    assert result.score == 1
    item.evaluation.scorers[0].kind = "llm"
    result = run_contract(item, BenchmarkConfig(task_models=[TARGET]), TARGET)
    assert result.error
    assert result.episode.metrics[0].status == "error"
    assert result.execution["scalar_available"] is False


def test_unsupported_prefill_fails_before_model_call(monkeypatch):
    item = task(content={"messages": [{"role": "user", "content": "Say 42"},
                                     {"role": "assistant", "content": "4", "origin": "prefill"}]})
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **k: pytest.fail("must not call"))
    result = run_contract(item, BenchmarkConfig(), TARGET)
    assert result.execution["stage"] == "preflight"
    assert "prefill" in result.error
    assert not result.episode.outputs


def test_conflicting_input_sources_rejected():
    with pytest.raises(ValueError):
        task(prompt="Different prompt")
    with pytest.raises(ValueError):
        task(evaluation={"metrics": [{"id": "a"}], "scorers": [{"id": "s", "kind": "exact", "metrics": ["b"]}]})


def test_legacy_definition_compatibility_is_a_view():
    item = BenchmarkItem(id="a", task_type="fill_blank", prompt="Original")
    definition = TaskDefinition(id="a", task_type="fill_blank", title="Saved title", prompt="Original", resource_ids=["resource"])
    copied = item.model_copy(update={"source_definition": definition, "prompt": "Edited"})
    assert copied.source_definition is copied
    assert copied.prompt == "Edited"
    assert copied.title == "Saved title"
    assert copied.resource_ids == ["resource"]
    assert item.prompt == "Original"


@pytest.mark.skipif(os.environ.get("EVALCLAW_TEST_COMPONENT_DOCKER") != "1", reason="explicit Docker integration test")
def test_real_container_service_and_laaj_exploration(monkeypatch, tmp_path):
    from evalclaw.quality.laaj_exploration import ContractExperiment
    item = service_task(interaction={"protocol": "tool_loop"})
    spec = item.environment.service
    spec.image = "python:3.11-slim"
    spec.command = ["python", "-u", "/component/service.py"]
    spec.files = {"service.py": (Path(__file__).parent / "fixtures" / "task_service.py").read_text()}
    responses = iter([answer("", [ToolCall(id="c1", name="increment")]), answer()])
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **k: next(responses))
    result = run_contract(item, BenchmarkConfig(), TARGET, trace_dir=tmp_path / "run")
    assert result.error is None
    assert result.score == 1
    assert (tmp_path / "run" / "outputs" / "result.txt").read_text() == "1"
    experiment = ContractExperiment(item, BenchmarkConfig(targets=[TARGET]), TARGET.id, tmp_path / "laaj")
    try:
        experiment.perform({"operation": "action", "action": {"action": "increment", "args": {}}})
        judged = experiment.perform({"operation": "evaluate", "final_answer": "42"})
        assert judged["metrics"][0]["value"] == 1
        assert experiment.runtime.episode.events[-1].origin == "judge"
        assert result.episode.final_state == 1
    finally:
        experiment.close()


def test_actor_roles_keep_separate_histories_and_tools(monkeypatch):
    item = service_task(interaction={"protocol": "tool_loop", "actor_contact_tool": "contact", "participants": [
        {"id": "alice", "role": "actor", "system_prompt": "You are Alice", "tools": ["increment"]},
        {"id": "bob", "role": "actor", "system_prompt": "You are Bob", "tools": []},
    ]})
    config = BenchmarkConfig(actor_model="test", actor_provider="openai", actor_api_key="fake")
    requests = []
    def model(messages, target, tools, **kwargs):
        requests.append((copy.deepcopy(messages), [t.name for t in tools], kwargs["system_prompt"]))
        return answer("acknowledged")
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    session = ContractSession(item, config, TARGET, component_factory=Service)
    session.prepare()
    try:
        session.actor_call("alice", "private to Alice")
        session.actor_call("bob", "private to Bob")
        session.actor_call("alice", "second Alice message")
        assert requests[0][1] == ["increment"]
        assert requests[1][1] == []
        assert requests[1][0] == [{"role": "user", "content": "private to Bob"}]
        assert len(requests[2][0]) == 3
        assert requests[2][0][0]["content"] == "private to Alice"
        assert session.episode.outputs == []
    finally:
        session.close()


def test_micro_metric_uses_constraint_denominator():
    from evalclaw.execution.suite_metrics import aggregate_metrics
    from evalclaw.protocols.task_definition import EpisodeRecord
    from evalclaw.types import EvalSpec, ItemResult, TaskSuite
    items = [task(id="a"), task(id="b")]
    suite = TaskSuite(spec=EvalSpec(objective="test"), objective="test", tasks=items,
                      evaluation_plan=[{"id": "constraints", "metric": "", "aggregation": "micro",
                                        "numerator": "passed", "denominator": "count"}])
    results = [ItemResult(item_id=i.id, target_id="target", episode=EpisodeRecord(task_id=i.id, task_digest="test",
        metrics=[MetricResult(metric="passed", value=p), MetricResult(metric="count", value=n)]))
        for i, p, n in zip(items, [1, 3], [1, 9])]
    assert aggregate_metrics(suite, results)[0]["value"] == .4


def test_prefill_is_separate_from_generated_output(monkeypatch):
    item = task(content={"messages": [{"role": "user", "content": "Answer"},
        {"role": "assistant", "content": "4", "origin": "prefill"}]})
    item.evaluation.scorers[0].response_view = "completed_message"
    target = TARGET.model_copy(update={"capabilities": ["prefill"], "prefill_format": "prefix_flag"})
    def model(messages, *args, **kwargs):
        assert messages[-1] == {"role": "assistant", "content": "4", "prefix": True}
        return answer("2")
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    result = run_contract(item, BenchmarkConfig(), target)
    assert result.error is None
    assert result.raw_response == "2"
    assert result.episode.outputs == ["2"]
    assert result.episode.final_messages[-1]["content"] == "42"
    assert result.score == 1


def test_program_controller_simulated_tools_and_branches(monkeypatch):
    tool = {"name": "lookup", "parameters": {"type": "object", "properties": {}}}
    class Controller(Service):
        methods = {"next"}
        def call(self, method, params):
            assert method == "next"
            state = params["state"] or 0
            actions = [
                [{"action": "register_tools", "tools": [tool]},
                 {"action": "checkpoint", "id": "before"}, {"action": "target"}],
                [{"action": "tool_result", "call_id": "c", "content": "simulated answer"}, {"action": "target"}],
                [{"action": "branch", "id": "before", "branch": "alternative"}, {"action": "target"}, {"action": "end"}],
            ][state]
            return {"state": state + 1, "actions": actions}
    item = task(interaction={"protocol": "program", "controller": {"image": "test", "version": "1", "command": ["controller"]},
        "controller_actions": ["register_tools", "checkpoint", "target", "tool_result", "branch", "end"]})
    responses = iter([answer("", [ToolCall(id="c", name="lookup")]), answer("first branch"), answer("42")])
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **k: next(responses))
    session = ContractSession(item, BenchmarkConfig(), TARGET, component_factory=Controller)
    try:
        session.prepare()
        session.run()
        session.evaluate()
        assert session.episode.termination == "completed"
        assert session.episode.usage["target_calls"] == 3
        assert session.episode.usage["tool_calls"] == 1
        assert session.episode.usage["branches"] == 1
        assert session.episode.outputs == ["", "first branch", "42"]
        assert any(e.origin == "controller_simulation" for e in session.episode.events)
        assert [m["content"] for m in session.messages] == ["Reply 42.", "42"]
        assert session.episode.metrics[0].value == 1
    finally:
        session.close()


def test_model_controller_receives_only_authorized_events(monkeypatch):
    item = task(interaction={"protocol": "model", "controller_prompt": "Drive the task", "controller_actions": ["target", "end"],
                             "controller_observations": ["task", "target"]})
    calls = []
    def model(messages, target, tools, **kwargs):
        if target.model == "controller":
            calls.append(copy.deepcopy(messages))
            action = "target" if len(calls) == 1 else "end"
            return answer("", [ToolCall(id=str(len(calls)), name="control", arguments={"action": action})])
        return answer()
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    result = run_contract(item, BenchmarkConfig(actor_model="controller"), TARGET)
    assert result.error is None
    assert result.score == 1
    first_events = json.loads(calls[0][-1]["content"])["events"]
    assert first_events[0]["kind"] == "input"
    later_events = json.loads(calls[1][-1]["content"])["events"]
    assert any(e["kind"] == "model_response" for e in later_events)
    assert all(e["origin"] in {"task", "target"} for e in first_events + later_events)


def test_composed_scores_are_explicit_and_judges_do_not_see_other_scores(monkeypatch):
    item = task(evaluation={"references": [{"id": "answer", "kind": "answer", "value": "42"}],
        "metrics": [{"id": "a"}, {"id": "b"}, {"id": "combined"}],
        "scorers": [
            {"id": "first", "kind": "exact", "metrics": ["a"], "references": ["answer"]},
            {"id": "second", "kind": "component", "metrics": ["b"],
             "component": {"image": "test", "version": "1", "command": ["score"]}},
            {"id": "combine", "kind": "aggregate", "metrics": ["combined"],
             "depends_on": ["a", "b"], "weights": {"a": .3, "b": .7}}],
        "scalar": {"metric": "combined", "minimum": 0, "maximum": 1}})
    class Scorer(Service):
        def call(self, method, params):
            assert params["episode"]["metrics"] == []
            assert not any(e["origin"] == "judge" for e in params["episode"]["events"])
            return {"metrics": [{"metric": "b", "value": 0}]}
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **k: answer())
    session = ContractSession(item, BenchmarkConfig(), TARGET, component_factory=Scorer)
    try:
        session.prepare()
        session.run()
        session.evaluate()
        assert session.episode.metrics[-1].value == .3
    finally:
        session.close()


def test_likelihood_never_substitutes_generation(monkeypatch):
    import httpx

    from evalclaw.models.likelihood import continuation_likelihood
    requests = []
    def post(self, url, **kwargs):
        requests.append(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"text": "prefix answer", "logprobs": {
            "text_offset": [0, 6], "token_logprobs": [None, -1.5]}}]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", post)
    result = continuation_likelihood([{"role": "user", "content": "prefix"}], [" answer"], TARGET)
    assert result[0]["log_likelihood"] == -1.5
    assert requests[0]["max_tokens"] == 0
    assert requests[0]["echo"] is True


@pytest.mark.parametrize("budget,requests,termination", [
    ({"target_calls": 1}, 1, "budget_exhausted"),
    ({"target_tokens": 2}, 1, "budget_exhausted"),
    ({"target_calls": 2}, 2, "completed"),
])
def test_likelihood_records_each_request_and_respects_budget(monkeypatch, budget, requests, termination):
    item = task(content={"messages": [{"role": "user", "content": "Prefix"}],
                         "operation": "continuation_likelihood", "continuations": [" A", " B"]},
                interaction={"protocol": "response", "budget": {**budget, "wall_time_seconds": 60}})
    target = TARGET.model_copy(update={"capabilities": ["continuation_likelihood"]})
    seen = []
    def likelihood(messages, continuations, target, **kwargs):
        assert 0 < kwargs["timeout_s"] <= 60
        seen.extend(continuations)
        return [{"continuation": continuations[0], "log_likelihood": -1, "raw": {"usage": {"total_tokens": 3}}}]
    monkeypatch.setattr("evalclaw.models.likelihood.continuation_likelihood", likelihood)
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **k: pytest.fail("must not generate"))
    result = run_contract(item, BenchmarkConfig(), target)
    assert result.error is None
    assert len(seen) == requests
    assert result.episode.usage["target_calls"] == requests
    assert result.episode.usage["target_tokens"] == 3 * requests
    assert result.episode.termination == termination
    assert len(result.episode.outputs[0]) == requests
