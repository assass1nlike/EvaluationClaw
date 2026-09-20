from __future__ import annotations

import json
import types
import subprocess

from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall, ToolSpec, object_schema
from evalclaw.runners import agent as agent_module
from evalclaw.types import BenchmarkConfig, BenchmarkItem, TargetModelConfig, TaskType


class EvidenceEnvironment:
    max_steps = 1
    steps = 0
    invalid_actions = 0
    done = False
    final_answer = ""
    interventions: list[dict] = []

    def tool_specs(self):
        return [
            ToolSpec(
                name="final",
                description="Finish.",
                parameters=object_schema({"answer": {"type": "string"}}),
            )
        ]

    def action_schema(self):
        return "Use final."

    def observation(self):
        return "ready"

    def step(self, action):
        self.steps += 1
        self.done = True
        self.final_answer = str(action.get("args", {}).get("answer") or "")
        return types.SimpleNamespace(observation="done", done=True, error=None)

    def score(self):
        return 0.75 if hasattr(self, "evidence") else 0.0

    def summary(self):
        return "complete"

    def state(self):
        return {"environment": "test", "done": self.done}

    def evaluate_with_evidence(self, evidence):
        self.evidence = evidence


def test_native_settlement_precedes_final_evaluator(monkeypatch):
    env = EvidenceEnvironment()
    env.interventions = [{"id": "settle", "trigger": {"type": "episode_end"},
                          "action": {"command": "settle"}}]
    steps = []
    def control(command, timeout):
        steps.append("settled")
        return subprocess.CompletedProcess([], 0, "before: pending; after: settled", "")
    env.run_external_command = control
    def evaluate(evidence):
        steps.append("graded")
        env.evidence = evidence
    env.evaluate_with_evidence = evaluate
    monkeypatch.setattr(agent_module, "call_target_model", lambda *a, **kw: '{"action":"final","args":{"answer":"done"}}')
    item = BenchmarkItem(id="native-settle", task_type="agent", prompt="Finish.")
    agent_module._run_agent_interaction_json_actions(item, TargetModelConfig(provider="mock", model="test"),
                                                    BenchmarkConfig(), environment=env)
    assert steps == ["settled", "graded"]
    assert env.evidence["interventions"][0]["status"] == "completed"


def test_native_final_evaluator_receives_complete_target_trace(monkeypatch) -> None:
    env = EvidenceEnvironment()
    monkeypatch.setattr(
        agent_module,
        "call_target_model",
        lambda *args, **kwargs: '{"action":"final","args":{"answer":"finished"}}',
    )
    item = BenchmarkItem(
        id="agent-evidence",
        dimension_id="agent",
        task_type=TaskType.agent,
        prompt="Finish.",
        metadata={"agent_env": {"type": "docker_workspace"}},
    )
    target = TargetModelConfig(provider="mock", model="model", api_key="secret-value")

    raw, score, _ = agent_module._run_agent_interaction_json_actions(
        item, target, BenchmarkConfig(), environment=env
    )

    assert score == 0.75
    assert env.evidence["schema_version"] == "evalclaw.evaluator_evidence.v1"
    assert env.evidence["target_execution"]["final_response"] == "finished"
    assert env.evidence["target_execution"]["tool_call_count"] == 1
    assert env.evidence["target_execution"]["trace"] == json.loads(raw)["trace"]
    assert "secret-value" not in json.dumps(env.evidence)


def test_native_tool_runner_exposes_raw_provider_response(monkeypatch) -> None:
    env = EvidenceEnvironment()
    raw_provider_response = {"id": "response-1", "usage": {"output_tokens": 12}}
    monkeypatch.setattr(
        agent_module,
        "call_target_model_with_tools",
        lambda *args, **kwargs: TargetToolModelResponse(
            adapter="openai",
            content="finished",
            tool_calls=[ToolCall(id="call-1", name="final", arguments={"answer": "done"})],
            assistant_message={"role": "assistant", "content": "finished"},
            raw_response=raw_provider_response,
        ),
    )
    item = BenchmarkItem(
        id="native-evidence",
        dimension_id="agent",
        task_type=TaskType.agent,
        prompt="Finish.",
        metadata={"agent_env": {"type": "docker_workspace"}},
    )

    agent_module._run_agent_interaction_native_tools(
        item,
        TargetModelConfig(provider="openai", model="model"),
        BenchmarkConfig(),
        environment=env,
    )

    assert env.evidence["target_execution"]["model_responses"] == [
        raw_provider_response
    ]
