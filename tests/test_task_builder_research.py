from __future__ import annotations

import json

from evalclaw.agent.research import run_task_builder_research
from evalclaw.agent.suite import build_agent_task_suite
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.research.backends import SearchResult
from evalclaw.types import (
    AgentTaskBlueprint,
    BenchmarkConfig,
    BenchmarkMode,
    ChallengeEffort,
    EvalDimension,
    EvalSpec,
    TaskType,
)


def _openai_tool_response(call: ToolCall) -> TargetToolModelResponse:
    return TargetToolModelResponse(
        adapter="openai",
        content="",
        tool_calls=[call],
        assistant_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
            ],
        },
        raw_response={},
    )


def test_task_builder_research_executes_search_and_returns_final_json(monkeypatch) -> None:
    captured: list[dict] = []
    responses = iter(
        [
            _openai_tool_response(
                ToolCall(
                    id="search_1",
                    name="search_web",
                    arguments={"query": "reproducible service failure benchmark"},
                )
            ),
            TargetToolModelResponse(
                adapter="openai",
                content='{"tasks": []}',
                tool_calls=[],
                assistant_message={"role": "assistant", "content": '{"tasks": []}'},
                raw_response={},
            ),
        ]
    )

    def fake_call(messages, **kwargs):
        captured.append({"messages": json.loads(json.dumps(messages)), "kwargs": kwargs})
        return next(responses)

    monkeypatch.setattr("evalclaw.agent.research.call_orchestrator_with_tools", fake_call)
    monkeypatch.setattr(
        "evalclaw.agent.research.web_search",
        lambda query, **kwargs: SearchResult(
            content=f"Evidence for {query}",
            citations=[{"url": "https://example.com/benchmark", "title": "Benchmark"}],
        ),
    )

    raw, notes = run_task_builder_research(
        {"blueprint": {"id": "service_blueprint"}},
        system_prompt="Build a task.",
        config=BenchmarkConfig(
            orchestrator_model="gpt-5",
            orchestrator_api_key="test-key",
            use_web_research=True,
            search_backend="keyless",
            agent_task_builder_research_max_calls=2,
        ),
    )

    assert raw == '{"tasks": []}'
    assert any("tool call(s)" in note for note in notes)
    assert captured[0]["kwargs"]["tools"]
    tool_messages = captured[1]["messages"]
    assert any(message.get("role") == "tool" for message in tool_messages)
    assert "Evidence for reproducible service failure benchmark" in json.dumps(tool_messages)


def test_task_builder_research_uses_anthropic_tool_result_blocks(monkeypatch) -> None:
    captured: list[list[dict]] = []
    responses = iter(
        [
            TargetToolModelResponse(
                adapter="anthropic",
                content="",
                tool_calls=[ToolCall(id="fetch_1", name="fetch_url", arguments={"url": "https://example.com"})],
                assistant_message={
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "fetch_1", "name": "fetch_url", "input": {"url": "https://example.com"}}
                    ],
                },
                raw_response={},
            ),
            TargetToolModelResponse(
                adapter="anthropic",
                content='{"tasks": []}',
                tool_calls=[],
                assistant_message={"role": "assistant", "content": [{"type": "text", "text": '{"tasks": []}'}]},
                raw_response={},
            ),
        ]
    )

    def fake_call(messages, **kwargs):
        captured.append(json.loads(json.dumps(messages)))
        return next(responses)

    monkeypatch.setattr("evalclaw.agent.research.call_orchestrator_with_tools", fake_call)
    monkeypatch.setattr(
        "evalclaw.agent.research.fetch_url_text",
        lambda url, **kwargs: "Public source text.",
    )

    raw, _ = run_task_builder_research(
        {"blueprint": {"id": "gui_blueprint"}},
        system_prompt="Build a task.",
        config=BenchmarkConfig(
            orchestrator_model="claude-opus-4-6",
            orchestrator_api_key="test-key",
            use_web_research=True,
            search_backend="keyless",
            agent_task_builder_research_max_calls=2,
        ),
    )

    assert raw == '{"tasks": []}'
    assert captured[1][1]["role"] == "assistant"
    assert captured[1][2]["role"] == "user"
    assert captured[1][2]["content"][0]["type"] == "tool_result"
    assert captured[1][2]["content"][0]["tool_use_id"] == "fetch_1"


def test_e4_agent_task_builder_enables_research_loop(monkeypatch) -> None:
    captured: dict = {}

    def fake_research(payload, *, system_prompt, config):
        captured["payload"] = payload
        captured["system_prompt"] = system_prompt
        return (
            json.dumps(
                {
                    "tasks": [
                        {
                            "id": "research_task",
                            "dimension_id": "agent_research",
                            "challenge_effort": "E4",
                            "title": "Research task",
                            "prompt": "Inspect the workspace and produce the requested result.",
                            "environment": {
                                "type": "workspace",
                                "workspace": {"start_room": "office", "rooms": {"office": ["brief"]}},
                            },
                            "scoring": {"pass_criteria": "The requested result is complete."},
                            "metadata": {
                                "challenge_effort_self_assessment": {
                                    "requested_effort": "E4",
                                    "meets_requested_effort": True,
                                    "rationale": "The task uses a realistic state and a multi-constraint oracle.",
                                }
                            },
                        }
                    ]
                }
            ),
            ["task-builder research used 1 tool call(s), total=1"],
        )

    monkeypatch.setattr("evalclaw.agent.suite.run_task_builder_research", fake_research)
    monkeypatch.setattr("evalclaw.agent.suite._select_blueprint_sources", lambda *args, **kwargs: [])
    dimension = EvalDimension(
        id="agent_research",
        name="Agent research",
        description="Evaluate evidence-grounded agent work.",
        approach="Use an executable workspace task.",
        challenge_effort=ChallengeEffort.E4,
    )
    spec = EvalSpec(
        objective="Evaluate evidence-grounded agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent_interaction],
    )
    blueprint = AgentTaskBlueprint(
        id="research_blueprint",
        dimension_id=dimension.id,
        title="Research workflow",
        expected_task_count=1,
    )

    suite = build_agent_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            benchmark_mode=BenchmarkMode.agent,
            orchestrator_api_key="dummy",
            use_web_research=True,
            search_backend="keyless",
        ),
    )

    assert suite.tasks[0].challenge_effort == ChallengeEffort.E4
    assert captured["payload"]["task_plan"]["construction"]["id"] == "research_blueprint"
    assert "E4 construction effort" in captured["system_prompt"]
