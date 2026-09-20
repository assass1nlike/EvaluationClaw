import copy
import json

import pytest

from evalclaw.execution.contract_capabilities import workspace_projection
from evalclaw.execution.task_runtime import ContractSession, contract_issues, render_messages
from evalclaw.protocols.submission import submission_contract, validate_output_contract
from evalclaw.runners.harness import _harness_prompt
from evalclaw.types import BenchmarkConfig
from tests.test_composable_tasks import TARGET, task


def contract():
    return {"schema_version": "evalclaw.output.v1", "artifacts": [
        {"id": "report", "path": "deliverables/report.json", "format": "json",
         "schema": {"type": "object", "properties": {"done": {"type": "boolean"}}, "required": ["done"]}}]}


def test_same_submission_paths_in_native_cli_and_evaluator_evidence():
    item = task(content={"messages": [{"role": "user", "content": "Do the work."}],
                         "output_contract": contract()}, environment={"image": "test"})
    original = item.model_dump_json()
    native = render_messages(item)[0]["content"]
    projected = workspace_projection(item)
    cli = _harness_prompt(projected)
    # The target's rendered manifest is exactly the evaluator's path authority.
    public = json.loads(native.split("\n\nSubmission requirements:\n")[1])
    assert cli == native
    assert public == submission_contract(item) == submission_contract(projected)
    assert public["artifact_paths"] == {"report": "/workspace/deliverables/report.json"}
    session = ContractSession(item, BenchmarkConfig(), TARGET)
    evidence = session.legacy_evidence({"episode": session.episode.model_dump(mode="json")})
    assert evidence["submission_contract"] == public
    assert item.model_dump_json() == original


@pytest.mark.parametrize("change", [
    {"path": "../answer.json"}, {"path": "/answer.json"}, {"path": "."},
    {"format": "csv"}, {"schema": {"type": "not-a-json-type"}},
])
def test_invalid_submission_contracts_rejected(change):
    value = contract()
    value["artifacts"][0].update(change)
    with pytest.raises(ValueError):
        validate_output_contract(value)


def test_submission_normalizes_duplicates_but_preserves_unversioned_contracts():
    value = contract()
    value["artifacts"].append({"id": "other", "path": "deliverables/./report.json"})
    with pytest.raises(ValueError):
        validate_output_contract(value)
    for old in ({"file": "answer.json"}, {"schema_version": "source-format-v1"}):
        item = task(content={"messages": [{"role": "user", "content": "Native input"}], "output_contract": old})
        assert render_messages(item) == [{"role": "user", "content": "Native input"}]
        assert submission_contract(item) == {}


def test_submission_requires_real_workspace_and_user_input():
    item = task(content={"messages": [{"role": "user", "content": "Work"}], "output_contract": contract()})
    assert contract_issues(item)
    item = task(content={"messages": [{"role": "system", "content": "Work"}],
                         "output_contract": {"schema_version": "evalclaw.output.v1", "response_schema": {"type": "boolean"}}})
    assert contract_issues(item)


def test_dialogue_reset_keeps_policies_and_audit_but_not_earlier_conversation(monkeypatch):
    from evalclaw.execution.task_runtime import run_contract
    from tests.test_composable_tasks import answer
    captured = []
    def model(messages, *args, **kwargs):
        captured.append(copy.deepcopy(messages))
        return answer("private earlier output" if len(captured) == 1 else "42")
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    item = task(content={"messages": [{"role": "system", "content": "Keep policy"},
                                     {"role": "user", "content": "First assignment"}]},
                interaction={"protocol": "dialogue", "reset_between_turns": True,
                             "turns": [{"role": "user", "content": "New assignment"}]})
    result = run_contract(item, BenchmarkConfig(), TARGET)
    assert result.error is None
    assert result.episode.outputs == ["private earlier output", "42"]
    assert [m["content"] for m in captured[1]] == ["Keep policy", "New assignment"]
    assert result.episode.usage["target_calls"] == 2
    assert len([e for e in result.episode.events if e.kind == "session_reset"]) == 1
