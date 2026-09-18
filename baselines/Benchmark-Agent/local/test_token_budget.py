import asyncio
import json
from types import SimpleNamespace

import pytest

from utils import core
from utils.agent_utils import Agent
from local import self_evaluate


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("model,budget", [("openai/deepseek-flash", 300000), ("gpt-5.1", None)])
def test_agent_request_budget(monkeypatch, asynchronous, model, budget):
    seen = []
    reply = object()

    def call(**kwargs):
        seen.append(kwargs)
        return reply

    async def async_call(**kwargs):
        return call(**kwargs)

    monkeypatch.setattr(core, "completion", call)
    monkeypatch.setattr(core, "acompletion", async_call)
    chain = core.MetaChain()
    args = dict(agent=Agent(model=model, instructions="test"), history=[], context_variables={},
                model_override=None, stream=False, debug=False)
    result = asyncio.run(chain.get_chat_completion_async(**args)) if asynchronous else chain.get_chat_completion(**args)
    assert result is reply
    assert len(seen) == 1
    assert seen[0].get("max_tokens") == budget
    expected_timeout = 7200 if model == "openai/deepseek-flash" else None
    assert seen[0].get("timeout") == expected_timeout
    assert seen[0].get("request_timeout") == expected_timeout


def test_selftest_budget_applies_to_answer_judge_and_manifest(monkeypatch, tmp_path):
    (tmp_path / "agents").mkdir()
    item = {"subtask_id": "st_01", "dataset_id": "test", "idx": 0,
            "sample": {"input": {"question": "Compute 1+1."}, "output": {"answer": "2"}}}
    (tmp_path / "evaluation.json").write_text(json.dumps([item]))
    (tmp_path / "agents/grounding_agent.json").write_text(json.dumps({"context_variables": {
        "subtasks": [{"id": "st_01", "answer_type": "free_form"}]}}))
    seen = []
    replies = iter(["2", '{"correct": true, "reason": "Correct sum."}'])

    def call(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(id="test", choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=next(replies)))])

    monkeypatch.setattr(self_evaluate, "completion", call)
    monkeypatch.setattr("sys.argv", ["self_evaluate.py", "--run-dir", str(tmp_path), "--workers", "1"])
    self_evaluate.main()
    assert len(seen) == 2
    assert all(request["max_tokens"] == 300000 for request in seen)
    assert all(request["timeout"] == 7200 for request in seen)
    assert json.loads((tmp_path / "selftest/config.json").read_text())["max_tokens"] == 300000
    assert json.loads((tmp_path / "selftest/config.json").read_text())["timeout_seconds"] == 7200
    assert json.loads((tmp_path / "selftest/summary.json").read_text())["correct"] == 1
