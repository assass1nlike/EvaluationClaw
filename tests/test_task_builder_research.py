from __future__ import annotations

import json

import pytest

from evalclaw.construction.research import (
    _append_tool_results,
    _execute_task_builder_tool,
    run_task_builder_tools,
)
from evalclaw.construction.resources import _select_blueprint_sources
from evalclaw.construction.suite import build_task_suite
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall, ToolResult
from evalclaw.research.backends import SearchBackendError, SearchResult, SearchTimeoutError
from evalclaw.types import (
    AgentEnvironmentType,
    BenchmarkConfig,
    ChallengeEffort,
    EvalDimension,
    EvalSpec,
    ResearchBrief,
    ResearchSourceMaterial,
    TaskType,
)
from tests.blueprint_factory import make_blueprint
from tests.config_helpers import dummy_config_kwargs


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


def test_responses_tool_result_is_appended_as_function_output() -> None:
    messages = [{"role": "user", "content": "Look up the source."}]
    response = TargetToolModelResponse(
        adapter="openai_responses",
        content="",
        tool_calls=[ToolCall(id="call_1", name="lookup", arguments={"query": "source"})],
        assistant_message={
            "responses_output": [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": '{"query":"source"}',
                }
            ]
        },
        raw_response={},
    )

    _append_tool_results(
        messages,
        response,
        [ToolResult(tool_call_id="call_1", name="lookup", content="result")],
    )

    assert messages[1]["type"] == "function_call"
    assert messages[2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "result",
    }


def test_generated_blueprint_never_collects_sources(monkeypatch) -> None:
    calls = 0

    def fake_search(*args, **kwargs):
        nonlocal calls
        calls += 1
        return SearchResult(content="unused", citations=[])

    monkeypatch.setattr("evalclaw.construction.resources.web_search", fake_search)
    dimension = EvalDimension(
        id="generated",
        name="Generated",
        description="Evaluate a generated capability.",
        approach="Generate the fixture locally.",
        needs_research=True,
    )
    blueprint = make_blueprint(
        "generated_blueprint",
        dimension.id,
        "Generated",
        task_type=TaskType.generation,
        content="Generated task.",
        source_plan={
            "strategy": "generated",
            "search_queries": ["this query must not run"],
            "suggested_urls": ["https://example.com/this-must-not-be-used"],
        },
    )

    sources = _select_blueprint_sources(
        dimension,
        blueprint,
        BenchmarkConfig(**dummy_config_kwargs(), use_web_research=True),
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
        task_type=TaskType.fill_blank,
        content="One source-grounded question.",
        source_plan={
            "strategy": "reused",
            "suggested_urls": ["https://example.com/reference"],
        },
    )

    sources = _select_blueprint_sources(
        dimension,
        blueprint,
        BenchmarkConfig(use_web_research=False),
    )

    assert [source.uri for source in sources] == ["https://example.com/reference"]


def _required_source_search_case():
    dimension = EvalDimension(
        id="grounded",
        name="Grounded",
        description="Build source-grounded tasks.",
        approach="Search for authoritative material.",
        needs_research=True,
        research_queries=["dimension fallback query"],
    )
    blueprint = make_blueprint(
        "grounded_blueprint",
        dimension.id,
        "Grounded questions",
        source_plan={
            "strategy": "adapted",
            "search_queries": ["task design query"],
        },
    )
    return dimension, blueprint


def test_required_source_search_rejects_disabled_backend() -> None:
    dimension, blueprint = _required_source_search_case()

    with pytest.raises(RuntimeError, match="search_backend='none'"):
        _select_blueprint_sources(
            dimension,
            blueprint,
            BenchmarkConfig(
                **dummy_config_kwargs(),
                use_web_research=True,
                search_backend="none",
            ),
        )


def test_required_source_search_rejects_missing_research_role_key() -> None:
    dimension, blueprint = _required_source_search_case()

    with pytest.raises(RuntimeError, match="Research role has no API key"):
        _select_blueprint_sources(
            dimension,
            blueprint,
            BenchmarkConfig(use_web_research=True, search_backend="keyless"),
        )


def test_required_gemini_source_search_rejects_missing_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    dimension, blueprint = _required_source_search_case()

    with pytest.raises(RuntimeError, match="Gemini search requires"):
        _select_blueprint_sources(
            dimension,
            blueprint,
            BenchmarkConfig(
                **dummy_config_kwargs(),
                use_web_research=True,
                search_backend="gemini",
            ),
        )


def test_source_search_retries_timeout_without_dimension_fallback(monkeypatch) -> None:
    queries: list[str] = []

    def fake_search(query, **kwargs):
        queries.append(query)
        if len(queries) < 3:
            raise SearchTimeoutError("timed out")
        return SearchResult(
            content="result",
            citations=[{"url": "https://example.com/source", "title": "Source"}],
        )

    monkeypatch.setattr("evalclaw.construction.resources.web_search", fake_search)
    dimension, blueprint = _required_source_search_case()

    sources = _select_blueprint_sources(
        dimension,
        blueprint,
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=True,
            search_backend="keyless",
        ),
    )

    assert queries == ["task design query"] * 3
    assert [source.uri for source in sources] == ["https://example.com/source"]


def test_source_search_raises_after_timeout_retry_limit(monkeypatch) -> None:
    queries: list[str] = []

    def fake_search(query, **kwargs):
        queries.append(query)
        raise SearchTimeoutError("timed out")

    monkeypatch.setattr("evalclaw.construction.resources.web_search", fake_search)
    dimension, blueprint = _required_source_search_case()

    with pytest.raises(RuntimeError, match="timed out after 3 attempts"):
        _select_blueprint_sources(
            dimension,
            blueprint,
            BenchmarkConfig(
                **dummy_config_kwargs(),
                use_web_research=True,
                search_backend="keyless",
            ),
        )

    assert queries == ["task design query"] * 3


def test_source_search_surfaces_api_error_without_fallback(monkeypatch) -> None:
    queries: list[str] = []

    def fake_search(query, **kwargs):
        queries.append(query)
        raise SearchBackendError("API unavailable")

    monkeypatch.setattr("evalclaw.construction.resources.web_search", fake_search)
    dimension, blueprint = _required_source_search_case()

    with pytest.raises(RuntimeError, match="API unavailable"):
        _select_blueprint_sources(
            dimension,
            blueprint,
            BenchmarkConfig(
                **dummy_config_kwargs(),
                use_web_research=True,
                search_backend="keyless",
            ),
        )

    assert queries == ["task design query"]


def test_task_builder_tools_execute_search_and_return_final_json(monkeypatch, tmp_path) -> None:
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

    raw, notes = run_task_builder_tools(
        {"blueprint": {"id": "service_blueprint"}},
        system_prompt="Build a task.",
        config=BenchmarkConfig(
            task_builder_model="gpt-5",
            task_builder_api_key="test-key",
            use_web_research=True,
            search_backend="keyless",
            task_builder_tool_max_calls=2,
        ),
        include_source_tools=True,
        debug_dir=tmp_path / "tool-trace",
    )

    assert raw == '{"tasks": []}'
    assert any("tool call(s)" in note for note in notes)
    assert captured[0]["kwargs"]["tools"]
    tool_messages = captured[1]["messages"]
    assert any(message.get("role") == "tool" for message in tool_messages)
    assert "Evidence for reproducible service failure benchmark" in json.dumps(tool_messages)
    traces = sorted((tmp_path / "tool-trace").glob("tool-round-*.json"))
    assert len(traces) == 2
    first_trace = json.loads(traces[0].read_text(encoding="utf-8"))
    assert first_trace["parsed_tool_calls"][0]["name"] == "search_web"


def test_task_builder_downloads_into_its_own_asset_directory(monkeypatch, tmp_path) -> None:
    responses = iter(
        [
            _openai_tool_response(
                ToolCall(
                    id="download_1",
                    name="download_files",
                    arguments={"urls": ["https://example.com/image.png"]},
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
    destinations = []

    monkeypatch.setattr(
        "evalclaw.construction.research.call_orchestrator_with_tools",
        lambda *args, **kwargs: next(responses),
    )

    def fake_download(url, destination_dir, *, max_bytes, timeout=30.0):
        destinations.append(destination_dir)
        return {
            "source_url": url,
            "resolved_url": url,
            "path": str(destination_dir / "image.png"),
            "filename": "image.png",
            "media_type": "image/png",
            "size_bytes": 4,
        }

    monkeypatch.setattr("evalclaw.construction.research.download_url_file", fake_download)

    raw, _ = run_task_builder_tools(
        {"task_plan": {"builder_job_id": "vision/job"}},
        system_prompt="Build a task.",
        config=BenchmarkConfig(
            task_builder_model="gpt-5",
            task_builder_api_key="test-key",
            output_dir=str(tmp_path),
        ),
        include_source_tools=True,
    )

    assert raw == '{"tasks": []}'
    assert destinations == [tmp_path.resolve() / "assets" / "task-builder" / "vision_job"]


def test_task_builder_can_read_retained_deep_research_source() -> None:
    result = _execute_task_builder_tool(
        ToolCall(
            id="read_1",
            name="read_research_source",
            arguments={"url": "https://example.com/source"},
        ),
        BenchmarkConfig(
            research_brief=ResearchBrief(
                source_materials=[
                    ResearchSourceMaterial(
                        title="Retained source",
                        url="https://example.com/source",
                        content="Full retained evidence for task construction.",
                    )
                ]
            )
        ),
        max_chars=50_000,
    )

    assert result.error is None
    assert "Full retained evidence for task construction." in result.content


def test_task_builder_can_download_multiple_file_types(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, object, int]] = []

    def fake_download(url, destination_dir, *, max_bytes, timeout=30.0):
        calls.append((url, destination_dir, max_bytes))
        if url.endswith("missing.csv"):
            raise RuntimeError("not found")
        return {
            "source_url": url,
            "resolved_url": url,
            "path": str(destination_dir / url.rsplit("/", 1)[-1]),
            "filename": url.rsplit("/", 1)[-1],
            "media_type": "application/octet-stream",
            "size_bytes": 4,
        }

    monkeypatch.setattr("evalclaw.construction.research.download_url_file", fake_download)

    result = _execute_task_builder_tool(
        ToolCall(
            id="download_1",
            name="download_files",
            arguments={
                "urls": [
                    "https://example.com/image.png",
                    "https://example.com/data.zip",
                    "https://example.com/missing.csv",
                ]
            },
        ),
        BenchmarkConfig(),
        max_chars=50_000,
        work_dir=tmp_path,
    )

    content = json.loads(result.content)
    assert result.error is None
    assert [file["filename"] for file in content["files"]] == ["image.png", "data.zip"]
    assert content["errors"][0]["url"] == "https://example.com/missing.csv"
    assert [call[0] for call in calls] == [
        "https://example.com/image.png",
        "https://example.com/data.zip",
        "https://example.com/missing.csv",
    ]
    assert calls[1][2] == calls[0][2] - 4


def test_task_builder_can_run_python_and_create_assets(tmp_path) -> None:
    result = _execute_task_builder_tool(
        ToolCall(
            id="python_1",
            name="run_python",
            arguments={
                "code": (
                    "from pathlib import Path\n"
                    "Path('values.csv').write_text('x,y\\n1,2\\n', encoding='utf-8')\n"
                    "print(sum(range(5)))\n"
                )
            },
        ),
        BenchmarkConfig(),
        max_chars=50_000,
        work_dir=tmp_path,
    )

    content = json.loads(result.content)
    asset_path = tmp_path.resolve() / "values.csv"
    assert result.error is None
    assert content["exit_code"] == 0
    assert content["stdout"].strip() == "10"
    assert content["files"] == [str(asset_path)]
    assert content["working_directory"] == str(tmp_path)
    assert asset_path.read_text(encoding="utf-8") == "x,y\n1,2\n"


def test_task_builder_tools_recover_missing_final_content(monkeypatch) -> None:
    captured: list[dict] = []
    responses = iter(
        [
            TargetToolModelResponse(
                adapter="openai",
                content="",
                tool_calls=[],
                assistant_message={"role": "assistant", "content": ""},
                raw_response={},
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

    raw, _ = run_task_builder_tools(
        {"blueprint": {"id": "service_blueprint"}},
        system_prompt="Build a task.",
        config=BenchmarkConfig(
            task_builder_model="deepseek-v4-flash",
            task_builder_api_key="test-key",
            task_builder_base_url="https://api.deepseek.com",
            use_web_research=True,
            search_backend="keyless",
        ),
        include_source_tools=True,
    )

    assert raw == '{"tasks": []}'
    assert len(captured) == 2
    assert captured[1]["kwargs"]["tools"] == []
    assert captured[1]["kwargs"].get("expect_json", False) is False


def test_task_builder_tools_use_anthropic_tool_result_blocks(monkeypatch) -> None:
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

    raw, _ = run_task_builder_tools(
        {"blueprint": {"id": "gui_blueprint"}},
        system_prompt="Build a task.",
        config=BenchmarkConfig(
            task_builder_model="claude-opus-4-6",
            task_builder_api_key="test-key",
            use_web_research=True,
            search_backend="keyless",
            task_builder_tool_max_calls=2,
        ),
        include_source_tools=True,
    )

    assert raw == '{"tasks": []}'
    assert captured[1][1]["role"] == "assistant"
    assert captured[1][2]["role"] == "user"
    assert captured[1][2]["content"][0]["type"] == "tool_result"
    assert captured[1][2]["content"][0]["tool_use_id"] == "fetch_1"


def test_reused_task_builder_enables_tools_when_web_search_is_disabled(monkeypatch) -> None:
    captured: dict = {}

    def fake_tools(payload, *, system_prompt, config, include_source_tools):
        captured["payload"] = payload
        captured["system_prompt"] = system_prompt
        captured["include_source_tools"] = include_source_tools
        return (
            json.dumps(
                {
                    "resources": [
                        {
                            "kind": "web",
                            "uri": "https://example.com/source",
                            "title": "Retained source",
                        }
                    ],
                    "tasks": [
                        {
                            "id": "research_task",
                            "dimension_id": "agent_research",
                            "challenge_effort": "E2",
                            "title": "Research task",
                            "prompt": "Inspect the workspace and produce the requested result.",
                            "resource_ids": ["resource_1"],
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
                                    "requested_effort": "E2",
                                    "meets_requested_effort": True,
                                    "rationale": "The task uses a realistic state and a multi-constraint oracle.",
                                }
                            },
                        }
                    ]
                }
            ),
            ["task-builder used 1 tool call(s), total=1"],
        )

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", fake_tools)
    monkeypatch.setattr("evalclaw.construction.suite._select_blueprint_sources", lambda *args, **kwargs: [])
    dimension = EvalDimension(
        id="agent_research",
        name="Agent research",
        description="Evaluate evidence-grounded agent work.",
        approach="Use an executable workspace task.",
        challenge_effort=ChallengeEffort.E2,
        needs_research=True,
    )
    spec = EvalSpec(
        objective="Evaluate evidence-grounded agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "research_blueprint",
        dimension.id,
        "Research workflow",
        task_type=TaskType.agent,
        content="Research workflow.",
        challenge_effort=ChallengeEffort.E2,
        environment_type=AgentEnvironmentType.workspace,
        source_plan={
            "strategy": "reused",
            "suggested_urls": ["https://example.com/source"],
        },
    )

    suite = build_task_suite(
        spec,
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=False,
        ),
    )

    assert suite.tasks[0].challenge_effort == ChallengeEffort.E2
    assert captured["include_source_tools"] is True
    assert captured["payload"]["task_plan"]["builder_job_id"] == "research_blueprint"
    assert captured["payload"]["resources"]["deep_research"] == {}


def test_generated_task_builder_receives_only_general_tools(monkeypatch) -> None:
    captured: dict = {}

    def fake_tools(payload, *, system_prompt, config, include_source_tools):
        captured["payload"] = payload
        captured["include_source_tools"] = include_source_tools
        return (
            json.dumps(
                {
                    "resources": [],
                    "tasks": [
                        {
                            "task_type": "fill_blank",
                            "title": "Generated task",
                            "prompt": "Provide the exact generated answer requested by this task.",
                            "expected_text": "answer",
                            "metadata": {
                                "challenge_effort_self_assessment": {
                                    "requested_effort": "E3",
                                    "meets_requested_effort": True,
                                    "rationale": "The task is constructed directly from the TaskDesign.",
                                }
                            },
                        }
                    ],
                }
            ),
            [],
        )

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", fake_tools)
    dimension = EvalDimension(
        id="generated",
        name="Generated",
        description="Evaluate generated material.",
        approach="Construct a task directly.",
        challenge_effort=ChallengeEffort.E3,
        needs_research=True,
        task_types=[TaskType.fill_blank],
    )
    blueprint = make_blueprint(
        "generated_blueprint",
        dimension.id,
        "Generated task",
        task_type=TaskType.fill_blank,
        source_plan={"strategy": "generated"},
    )

    suite = build_task_suite(
        EvalSpec(
            objective="Evaluate generated material.",
            dimensions=[dimension],
            task_types=[TaskType.fill_blank],
        ),
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            use_web_research=True,
            search_backend="keyless",
            research_brief=ResearchBrief(
                source_materials=[
                    ResearchSourceMaterial(
                        title="Unrelated retained source",
                        url="https://example.com/unrelated",
                        content="This must not reach generated construction.",
                    )
                ]
            ),
        ),
    )

    assert suite.resources == []
    assert captured["include_source_tools"] is False
    assert captured["payload"]["resources"]["available"] == []
    assert captured["payload"]["resources"]["deep_research"] == {}
    assert "No external sources" in captured["payload"]["resources"]["context"]


def test_qc_repair_skips_tools_and_preserves_unreported_task(monkeypatch) -> None:
    llm_payloads: list[dict] = []
    tool_calls = 0

    def task_payload(task_id: str, task_index: int, prompt: str) -> dict:
        return {
            "id": task_id,
            "dimension_id": "agent_research",
            "task_type": "agent",
            "challenge_effort": "E3",
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
                "builder_job_id": f"research_blueprint_{task_index}",
                "challenge_effort_self_assessment": {
                    "requested_effort": "E3",
                    "meets_requested_effort": True,
                    "rationale": "The task uses a realistic state and deterministic oracle.",
                },
            },
        }

    previous_tasks = [
        task_payload("task_1", 1, "Original prompt with a scoring defect."),
        task_payload("task_2", 2, "Keep this prompt byte-for-byte."),
    ]

    def fake_tools(*args, **kwargs):
        nonlocal tool_calls
        tool_calls += 1
        raise AssertionError("QC repair must not use construction tools")

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

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", fake_tools)
    monkeypatch.setattr("evalclaw.construction.suite.call_llm", fake_call_llm)
    monkeypatch.setattr(
        "evalclaw.construction.suite._select_blueprint_sources", lambda *args, **kwargs: []
    )
    dimension = EvalDimension(
        id="agent_research",
        name="Agent research",
        description="Evaluate evidence-grounded agent work.",
        approach="Use executable tasks.",
        challenge_effort=ChallengeEffort.E3,
    )
    spec = EvalSpec(
        objective="Evaluate evidence-grounded agents.",
        dimensions=[dimension],
        task_types=[TaskType.agent],
    )
    blueprints = [
        make_blueprint(
            f"research_blueprint_{index}",
            dimension.id,
            f"Research workflow {index}",
            task_type=TaskType.agent,
            content=f"Research workflow scenario {index}.",
            challenge_effort=ChallengeEffort.E3,
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
            **dummy_config_kwargs(),
            use_web_research=True,
            search_backend="keyless",
            task_builder_max_workers=1,
        ),
        revision_context_by_dimension=revision,
    )

    assert tool_calls == 0
    assert len(llm_payloads) == 1
    assert llm_payloads[0]["revision"]["previous_tasks"][0]["id"] == "task_1"
    assert [task.id for task in suite.tasks] == ["task_1"]
    assert suite.tasks[0].prompt == "Original prompt with the scoring defect repaired."
