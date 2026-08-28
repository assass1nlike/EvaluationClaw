from __future__ import annotations

import json
from concurrent.futures import CancelledError
from pathlib import Path
from threading import Event

import pytest

from evalclaw.construction.research import (
    TaskBuilderCallError,
    _append_tool_results,
    _execute_task_builder_tool,
    run_task_builder_tools,
    summarize_task_builder_truncation,
    task_builder_work_dir,
)
from evalclaw.construction.resources import _select_blueprint_sources
from evalclaw.construction.suite import build_task_suite
from evalclaw.execution.docker_images import DockerImageBuildResult, DockerImageCheckResult
from evalclaw.models.llm import LLMOutputTruncatedError, TargetToolModelResponse
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


def test_task_builder_truncation_summary_describes_only_interrupted_output(
    monkeypatch, tmp_path
) -> None:
    captured = {}

    def fake_call(messages, **kwargs):
        captured["input"] = json.loads(messages[0].content)
        captured["kwargs"] = kwargs
        return "One replacement summary."

    monkeypatch.setattr("evalclaw.construction.research.call_llm", fake_call)
    error = LLMOutputTruncatedError(
        "truncated",
        raw_response={
            "choices": [
                {
                    "message": {
                        "reasoning_content": "New reasoning and completed file work.",
                        "content": "",
                    }
                }
            ]
        },
    )
    summary = summarize_task_builder_truncation(
        error,
        config=BenchmarkConfig(task_builder_model="deepseek-v4-flash", task_builder_api_key="key"),
        debug_dir=tmp_path,
    )

    assert summary == "One replacement summary."
    assert captured["input"] == {
        "interrupted_assistant_output": "New reasoning and completed file work.",
    }
    assert captured["kwargs"]["reduce_reasoning_effort"] is True
    assert captured["kwargs"]["retry_on_truncation"] is False
    saved = json.loads((tmp_path / "truncation-summary-01.json").read_text(encoding="utf-8"))
    assert saved == {"summary": summary}


def test_task_builder_truncation_recovery_preserves_tool_history(monkeypatch) -> None:
    calls: list[list[dict]] = []

    def fake_model(messages, **kwargs):
        calls.append(json.loads(json.dumps(messages)))
        if len(calls) == 1:
            raise LLMOutputTruncatedError("truncated", partial_output="first reasoning")
        if len(calls) == 2:
            return _openai_tool_response(
                ToolCall(id="call_1", name="run_python", arguments={"code": "print(1)"})
            )
        if len(calls) == 3:
            raise LLMOutputTruncatedError("truncated", partial_output="second reasoning")
        return TargetToolModelResponse(
            adapter="openai",
            content='{"tasks": []}',
            tool_calls=[],
            assistant_message={"role": "assistant", "content": '{"tasks": []}'},
            raw_response={},
        )

    monkeypatch.setattr(
        "evalclaw.construction.research.call_orchestrator_with_tools",
        fake_model,
    )
    monkeypatch.setattr(
        "evalclaw.construction.research.summarize_task_builder_truncation",
        lambda error, **kwargs: f"summary: {error.partial_output}",
    )
    monkeypatch.setattr(
        "evalclaw.construction.research._execute_task_builder_tool",
        lambda call, *args, **kwargs: ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="created fixture.json",
        ),
    )

    response, _ = run_task_builder_tools(
        {"goal": "Build one task."},
        system_prompt="Build the task.",
        config=BenchmarkConfig(
            **dummy_config_kwargs(),
            task_builder_truncation_retries=3,
        ),
        include_source_tools=False,
    )

    assert response == '{"tasks": []}'
    assert [message.get("role") for message in calls[3]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert calls[3][1]["content"] == "summary: first reasoning"
    assert calls[3][3]["tool_calls"][0]["id"] == "call_1"
    assert calls[3][4] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "created fixture.json",
    }
    assert calls[3][5]["content"] == "summary: second reasoning"


def test_task_builder_call_failure_has_separate_retries(monkeypatch) -> None:
    calls: list[list[dict]] = []

    def fail_once_then_complete(messages, **kwargs):
        calls.append(json.loads(json.dumps(messages)))
        if len(calls) == 1:
            raise RuntimeError("model service temporarily unavailable")
        return TargetToolModelResponse(
            adapter="openai",
            content='{"tasks": []}',
            tool_calls=[],
            assistant_message={"role": "assistant", "content": '{"tasks": []}'},
            raw_response={},
        )

    monkeypatch.setattr(
        "evalclaw.construction.research.call_orchestrator_with_tools",
        fail_once_then_complete,
    )

    raw, notes = run_task_builder_tools(
        {"goal": "Build one task."},
        system_prompt="Build the task.",
        config=BenchmarkConfig(
            **dummy_config_kwargs(),
            task_builder_call_retries=1,
            task_builder_repair_attempts=0,
        ),
        include_source_tools=False,
    )

    assert raw == '{"tasks": []}'
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert any("model call failed; retrying (1/1)" in note for note in notes)


def test_task_builder_call_failure_does_not_consume_structure_repairs(monkeypatch) -> None:
    calls = 0

    def always_fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("model service unavailable")

    monkeypatch.setattr(
        "evalclaw.construction.research.call_orchestrator_with_tools",
        always_fail,
    )

    with pytest.raises(TaskBuilderCallError, match="after 1 retry attempt"):
        run_task_builder_tools(
            {"goal": "Build one task."},
            system_prompt="Build the task.",
            config=BenchmarkConfig(
                **dummy_config_kwargs(),
                task_builder_call_retries=1,
                task_builder_repair_attempts=5,
            ),
            include_source_tools=False,
        )

    assert calls == 2


def test_stopped_task_builder_does_not_execute_requested_tool(monkeypatch) -> None:
    stop_event = Event()
    tool_executed = False

    def fake_model(*args, **kwargs):
        stop_event.set()
        return _openai_tool_response(
            ToolCall(id="call_1", name="run_python", arguments={"code": "print(1)"})
        )

    def fake_tool(*args, **kwargs):
        nonlocal tool_executed
        tool_executed = True
        raise AssertionError("cancelled TaskBuilder executed a tool")

    monkeypatch.setattr(
        "evalclaw.construction.research.call_orchestrator_with_tools",
        fake_model,
    )
    monkeypatch.setattr(
        "evalclaw.construction.research._execute_task_builder_tool",
        fake_tool,
    )

    with pytest.raises(CancelledError, match="another job failed"):
        run_task_builder_tools(
            {"goal": "Build one task."},
            system_prompt="Build the task.",
            config=BenchmarkConfig(**dummy_config_kwargs()),
            include_source_tools=False,
            stop_event=stop_event,
        )

    assert not tool_executed


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


def test_task_builder_build_image_persists_context_and_returns_relative_reference(monkeypatch, tmp_path) -> None:
    dockerfile = tmp_path / "custom.Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\nCOPY requirements.txt /tmp/requirements.txt\n", encoding="utf-8")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pytest==8.4.1\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_build(context_dir, **kwargs):
        captured["context_dir"] = context_dir
        captured["kwargs"] = kwargs
        return DockerImageBuildResult(
            image="evalclaw-builder:test",
            built=True,
            dockerfile=(context_dir / "Dockerfile").read_text(encoding="utf-8"),
            context_dir=str(context_dir),
            detail="built",
        )

    monkeypatch.setattr(
        "evalclaw.construction.research.build_docker_image_from_context",
        fake_build,
    )
    state: dict[str, object] = {}
    result = _execute_task_builder_tool(
        ToolCall(
            id="build_1",
            name="build_image",
            arguments={
                "dockerfile_path": str(dockerfile),
                "context_files": [
                    {
                        "source_path": str(requirements),
                        "target_path": "requirements.txt",
                    }
                ],
                "tag": "evalclaw-builder:test",
            },
        ),
        BenchmarkConfig(output_dir=str(tmp_path)),
        max_chars=50_000,
        work_dir=tmp_path,
        tool_state=state,
    )

    payload = json.loads(result.content)
    context_dir = captured["context_dir"]
    assert result.error is None
    assert payload["image"] == "evalclaw-builder:test"
    assert payload["image_build"]["context_dir"] == ".image-build/build-01"
    assert (context_dir / "Dockerfile").read_text(encoding="utf-8").startswith("FROM python")
    assert (context_dir / "requirements.txt").read_text(encoding="utf-8") == "pytest==8.4.1\n"
    assert (tmp_path / ".image-build" / "manifests" / "build-01.json").is_file()
    assert state["last_image"] == "evalclaw-builder:test"

    second = _execute_task_builder_tool(
        ToolCall(
            id="build_2",
            name="build_image",
            arguments={"dockerfile_path": str(dockerfile)},
        ),
        BenchmarkConfig(output_dir=str(tmp_path)),
        max_chars=50_000,
        work_dir=tmp_path,
        tool_state=state,
    )
    assert second.error is None
    assert (tmp_path / ".image-build" / "build-02" / "Dockerfile").is_file()
    assert (tmp_path / ".image-build" / "manifests" / "build-02.json").is_file()


def test_task_builder_run_image_check_reports_result(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "evalclaw.construction.research.run_docker_image_check",
        lambda image, command, **kwargs: DockerImageCheckResult(
            image=image,
            command=command,
            exit_code=1,
            stdout="",
            stderr="pytest is missing",
        ),
    )
    result = _execute_task_builder_tool(
        ToolCall(
            id="check_1",
            name="run_image_check",
            arguments={"command": "python -c 'import pytest'"},
        ),
        BenchmarkConfig(output_dir=str(tmp_path)),
        max_chars=50_000,
        work_dir=tmp_path,
        tool_state={"last_image": "evalclaw-builder:test"},
    )

    payload = json.loads(result.content)
    assert result.error == "image_check_failed"
    assert payload["image"] == "evalclaw-builder:test"
    assert payload["exit_code"] == 1
    assert payload["stderr"] == "pytest is missing"


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
    assert all(item["kwargs"]["max_tokens"] == 65_536 for item in captured)
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

    def fake_tools(payload, *, system_prompt, config, include_source_tools, stop_event):
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

    def fake_tools(payload, *, system_prompt, config, include_source_tools, stop_event):
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


def test_environment_preflight_failure_enters_task_builder_repair(monkeypatch) -> None:
    payloads: list[dict] = []

    def fake_tools(payload, **kwargs):
        payloads.append(payload)
        environment = {
            "type": "code_sandbox",
            "hidden_files": {"tests.py": "raise SystemExit(0)\n"},
            "test_command": "python3 tests.py",
        }

        def task(title: str, *, include_environment: bool = True) -> dict:
            result = {
                "task_type": "agent",
                "title": title,
                "prompt": f"Create {title.lower().replace(' ', '_')}.py and run the evaluator.",
                "scoring": {
                    "method": "executable_test",
                    "pass_criteria": "The evaluator exits successfully.",
                },
                "metadata": {
                    "challenge_effort_self_assessment": {
                        "requested_effort": "E3",
                        "meets_requested_effort": True,
                        "rationale": "The task requires implementation and execution verification.",
                    }
                },
            }
            if include_environment:
                result["environment"] = environment
            return result

        return (
            json.dumps(
                {
                    "resources": [],
                    "tasks": [
                        task(
                            "First executable task",
                            include_environment=len(payloads) > 1,
                        ),
                        task("Second executable task"),
                    ],
                }
            ),
            [],
        )

    preflight_calls = 0
    preflight_task_counts: list[int] = []

    def fake_preflight(tasks, **kwargs):
        nonlocal preflight_calls
        preflight_calls += 1
        preflight_task_counts.append(len(tasks))
        if preflight_calls == 1:
            return [f"task #1 ({tasks[0].id}): environment preflight failed: missing evaluator"], {
                tasks[0].id
            }
        return [], set()

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", fake_tools)
    monkeypatch.setattr("evalclaw.construction.suite.require_docker_available", lambda **kwargs: None)
    monkeypatch.setattr("evalclaw.construction.suite._preflight_builder_environments", fake_preflight)
    dimension = EvalDimension(
        id="execution",
        name="Execution",
        description="Evaluate code execution.",
        approach="Use an executable task.",
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "execution_task",
        dimension.id,
        "Execution task",
        task_type=TaskType.agent,
        count=2,
        environment_type=AgentEnvironmentType.code_sandbox,
    )

    suite = build_task_suite(
        EvalSpec(
            objective="Evaluate code execution.",
            dimensions=[dimension],
            task_types=[TaskType.agent],
        ),
        [blueprint],
        BenchmarkConfig(
            **dummy_config_kwargs(),
            task_builder_max_workers=1,
            task_builder_repair_attempts=1,
        ),
    )

    assert len(suite.tasks) == 2
    assert len(payloads) == 2
    assert preflight_task_counts == [1, 2]
    assert any(
        "environment preflight failed" in issue
        for issue in payloads[1]["repair"]["issues"]
    )


def test_builder_host_path_in_container_prompt_enters_repair(monkeypatch, tmp_path) -> None:
    payloads: list[dict] = []
    config = BenchmarkConfig(
        **dummy_config_kwargs(),
        output_dir=str(tmp_path),
        environment_preflight=False,
        task_builder_max_workers=1,
        task_builder_repair_attempts=1,
    )
    asset_path = (
        task_builder_work_dir(config, "execution_task") / "TASK.md"
    )
    asset_path.parent.mkdir(parents=True)
    asset_path.write_text("Implement the requested program.\n", encoding="utf-8")

    def fake_tools(payload, **kwargs):
        payloads.append(payload)
        prompt_path = str(asset_path) if len(payloads) == 1 else asset_path.name
        return (
            json.dumps(
                {
                    "resources": [],
                    "tasks": [
                        {
                            "task_type": "agent",
                            "title": "Executable task",
                            "prompt": f"Read {prompt_path} and implement the requested program.",
                            "assets": [{"path": str(asset_path)}],
                            "environment": {
                                "type": "code_sandbox",
                                "test_command": "python3 verify.py",
                            },
                            "scoring": {
                                "method": "executable_test",
                                "pass_criteria": "The evaluator exits successfully.",
                            },
                            "metadata": {
                                "challenge_effort_self_assessment": {
                                    "requested_effort": "E3",
                                    "meets_requested_effort": True,
                                    "rationale": "The task requires implementation and execution verification.",
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
        id="execution",
        name="Execution",
        description="Evaluate code execution.",
        approach="Use an executable task.",
        task_types=[TaskType.agent],
    )
    blueprint = make_blueprint(
        "execution_task",
        dimension.id,
        "Execution task",
        task_type=TaskType.agent,
        environment_type=AgentEnvironmentType.code_sandbox,
    )

    suite = build_task_suite(
        EvalSpec(
            objective="Evaluate code execution.",
            dimensions=[dimension],
            task_types=[TaskType.agent],
        ),
        [blueprint],
        config,
    )

    assert len(suite.tasks) == 1
    assert len(payloads) == 2
    assert any(
        "Builder-host paths" in issue
        for issue in payloads[1]["repair"]["issues"]
    )


def test_qc_repair_edits_file_with_tools_and_preserves_best_copy(monkeypatch, tmp_path) -> None:
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

    best_snapshot: dict = {}

    def fake_tools(payload, **kwargs):
        nonlocal tool_calls
        tool_calls += 1
        llm_payloads.append(payload)
        assert "previous_tasks" not in payload["revision"]
        candidate_path = Path(payload["revision"]["path"])
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        best_snapshot.update(
            json.loads((candidate_path.parent / "best.json").read_text(encoding="utf-8"))
        )
        if tool_calls == 1:
            candidate["tasks"][0]["prompt"] = ""
        else:
            assert payload["repair"]["issues"]
            assert "previous_response" not in payload["repair"]
            candidate["tasks"][0]["prompt"] = (
                "Original prompt with the scoring defect repaired."
            )
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        return '{"status":"saved"}', []

    monkeypatch.setattr("evalclaw.construction.suite.run_task_builder_tools", fake_tools)
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
            output_dir=str(tmp_path),
        ),
        revision_context_by_dimension=revision,
    )

    assert tool_calls == 2
    assert len(llm_payloads) == 2
    assert set(llm_payloads[0]["revision"]) == {"path", "qc_issues", "instruction"}
    assert [task["id"] for task in best_snapshot["tasks"]] == ["task_1"]
    assert best_snapshot["tasks"][0]["prompt"] == "Original prompt with a scoring defect."
    assert [task.id for task in suite.tasks] == ["task_1"]
    assert suite.tasks[0].prompt == "Original prompt with the scoring defect repaired."
