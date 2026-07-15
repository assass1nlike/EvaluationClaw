from __future__ import annotations

import json

from evalclaw.construction.research import run_task_builder_research
from evalclaw.construction.resources import _select_blueprint_sources
from evalclaw.construction.suite import build_task_suite
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.research.backends import SearchResult
from evalclaw.types import (
    AgentEnvironmentType,
    BenchmarkConfig,
    ChallengeEffort,
    EvalDimension,
    EvalSpec,
    TaskType,
)
from tests.blueprint_factory import make_blueprint


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


def test_blueprint_source_search_requires_explicit_research_need(monkeypatch) -> None:
    calls = 0

    def fake_search(*args, **kwargs):
        nonlocal calls
        calls += 1
        return SearchResult(content="unused", citations=[])

    monkeypatch.setattr("evalclaw.construction.resources.web_search", fake_search)
    dimension = EvalDimension(
        id="self_contained",
        name="Self contained",
        description="Evaluate a self-contained capability.",
        approach="Generate the fixture locally.",
        needs_research=False,
    )
    blueprint = make_blueprint(
        "self_contained_blueprint",
        dimension.id,
        "Self contained",
        task_type=TaskType.open_generation,
        content="Self-contained task.",
        source_plan={"search_queries": ["this query must not run"]},
    )

    sources = _select_blueprint_sources(
        dimension,
        blueprint,
        BenchmarkConfig(orchestrator_api_key="dummy", use_web_research=True),
    )

    assert sources == []
    assert calls == 0


def test_planner_suggested_urls_are_available_without_an_extra_search() -> None:
    dimension = EvalDimension(
        id="grounded",
        name="Grounded",
        description="Use a Planner-vetted source.",
        approach="Build questions from the supplied source.",
        needs_research=False,
    )
    blueprint = make_blueprint(
        "grounded_blueprint",
        dimension.id,
        "Grounded questions",
        task_type=TaskType.short_answer,
        content="One source-grounded question.",
        source_plan={
            "strategy": "source_backed",
            "suggested_urls": ["https://example.com/reference"],
        },
    )

    sources = _select_blueprint_sources(
        dimension,
        blueprint,
        BenchmarkConfig(use_web_research=False),
    )

    assert [source.uri for source in sources] == ["https://example.com/reference"]


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

    monkeypatch.setattr("evalclaw.construction.research.call_orchestrator_with_tools", fake_call)
    monkeypatch.setattr(
        "evalclaw.construction.research.web_search",
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
            task_builder_research_max_calls=2,
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

    monkeypatch.setattr("evalclaw.construction.research.call_orchestrator_with_tools", fake_call)
    monkeypatch.setattr(
        "evalclaw.construction.research.fetch_url_text",
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
            task_builder_research_max_calls=2,
        ),
    )

    assert raw == '{"tasks": []}'
    assert captured[1][1]["role"] == "assistant"
    assert captured[1][2]["role"] == "user"
    assert captured[1][2]["content"][0]["type"] == "tool_result"
    assert captured[1][2]["content"][0]["tool_use_id"] == "fetch_1"


def test_e4_task_builder_enables_research_loop(monkeypatch) -> None:
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
                                "workspace": {
                                    "start_room": "office",
                                    "rooms": {"office": ["brief"], "mailroom": []},
                                    "goal": {"outgoing_bin": ["brief"]},
                                },
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

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_research", fake_research)
    monkeypatch.setattr("evalclaw.construction.suite._select_blueprint_sources", lambda *args, **kwargs: [])
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
    blueprint = make_blueprint(
        "research_blueprint",
        dimension.id,
        "Research workflow",
        task_type=TaskType.agent_interaction,
        content="Research workflow.",
        challenge_effort=ChallengeEffort.E4,
        environment_type=AgentEnvironmentType.workspace,
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            orchestrator_api_key="dummy",
            use_web_research=True,
            search_backend="keyless",
        ),
    )

    assert suite.tasks[0].challenge_effort == ChallengeEffort.E4
    assert captured["payload"]["task_plan"]["blueprint"]["id"] == "research_blueprint"
    assert "E4 construction effort" in captured["system_prompt"]


def test_qc_repair_skips_research_and_preserves_unreported_task(monkeypatch) -> None:
    llm_payloads: list[dict] = []
    research_calls = 0

    def task_payload(task_id: str, task_index: int, prompt: str) -> dict:
        return {
            "id": task_id,
            "dimension_id": "agent_research",
            "task_type": "agent_interaction",
            "challenge_effort": "E4",
            "title": f"Task {task_index}",
            "prompt": prompt,
            "environment": {
                "type": "workspace",
                "workspace": {
                    "start_room": "office",
                    "rooms": {"office": [f"brief_{task_index}"], "mailroom": []},
                    "goal": {"outgoing_bin": [f"brief_{task_index}"]},
                },
            },
            "scoring": {"pass_criteria": "The requested result is complete."},
            "metadata": {
                "builder_blueprint_id": f"research_blueprint_{task_index}",
                "challenge_effort_self_assessment": {
                    "requested_effort": "E4",
                    "meets_requested_effort": True,
                    "rationale": "The task uses a realistic state and deterministic oracle.",
                },
            },
        }

    previous_tasks = [
        task_payload("task_1", 1, "Original prompt with a scoring defect."),
        task_payload("task_2", 2, "Keep this prompt byte-for-byte."),
    ]

    def fake_research(*args, **kwargs):
        nonlocal research_calls
        research_calls += 1
        raise AssertionError("QC repair must not repeat web research")

    def fake_call_llm(messages, *args, **kwargs):
        payload = json.loads(messages[0].content)
        llm_payloads.append(payload)
        return json.dumps(
            {
                "tasks": [
                    task_payload(
                        "task_1",
                        1,
                        "Original prompt with the scoring defect repaired.",
                    )
                ]
            }
        )

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_research", fake_research)
    monkeypatch.setattr("evalclaw.construction.suite.call_llm", fake_call_llm)
    monkeypatch.setattr(
        "evalclaw.construction.suite._select_blueprint_sources", lambda *args, **kwargs: []
    )
    dimension = EvalDimension(
        id="agent_research",
        name="Agent research",
        description="Evaluate evidence-grounded agent work.",
        approach="Use executable tasks.",
        challenge_effort=ChallengeEffort.E4,
    )
    spec = EvalSpec(
        objective="Evaluate evidence-grounded agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent_interaction],
    )
    blueprints = [
        make_blueprint(
            f"research_blueprint_{index}",
            dimension.id,
            f"Research workflow {index}",
            task_type=TaskType.agent_interaction,
            content=f"Research workflow scenario {index}.",
            challenge_effort=ChallengeEffort.E4,
            environment_type=AgentEnvironmentType.workspace,
            metadata={"content_focus": f"scenario {index}"},
        )
        for index in (1, 2)
    ]
    revision = {
        dimension.id: {
            "previous_tasks": previous_tasks,
            "qc_issues": [
                {
                    "item_id": "task_1",
                    "message": "The scoring contract does not check the requested result.",
                }
            ],
        }
    }

    suite = build_task_suite(
        spec,
        blueprints,
        BenchmarkConfig(
            orchestrator_api_key="dummy",
            use_web_research=True,
            search_backend="keyless",
            task_builder_max_workers=1,
        ),
        revision_context_by_dimension=revision,
    )

    assert research_calls == 0
    assert len(llm_payloads) == 1
    assert llm_payloads[0]["revision"]["previous_tasks"][0]["id"] == "task_1"
    assert [task.id for task in suite.tasks] == ["task_1"]
    assert suite.tasks[0].prompt == "Original prompt with the scoring defect repaired."
