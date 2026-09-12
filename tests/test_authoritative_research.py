import json

import pytest

from evalclaw.planning import task_planner as tp
from evalclaw.planning.skill_loader import benchmark_planner_system_prompt
from evalclaw.protocols.tool import ToolCall
from evalclaw.research import authoritative as auth
from evalclaw.types import BenchmarkConfig


def test_search_sources_combines_catalog_and_dedupes(monkeypatch) -> None:
    monkeypatch.setattr(
        auth,
        "_search_curated",
        lambda query, limit: [
            {"kind": "hf_dataset", "ref": "hf://datasets/openai/gsm8k", "title": "GSM8K", "description": "d"},
            {"kind": "hf_dataset", "ref": "hf://datasets/openai/gsm8k", "title": "GSM8K", "description": "d"},
        ],
    )
    monkeypatch.setattr(auth, "_search_hf", lambda query, limit: [])
    monkeypatch.setattr(auth, "_search_wikipedia", lambda query, limit: [])
    monkeypatch.setattr(auth, "_search_arxiv", lambda query, limit: [])

    results = auth.search_sources("math", limit=8)

    assert [candidate["ref"] for candidate in results] == ["hf://datasets/openai/gsm8k"]


def test_load_source_dispatches_by_ref(monkeypatch) -> None:
    monkeypatch.setattr(auth, "_hf_dataset_rows", lambda dataset_id, limit: "row1\nrow2")
    monkeypatch.setattr(auth, "_wikipedia_text", lambda title, max_chars=4000: "wiki text")
    monkeypatch.setattr(auth, "_arxiv_abstract", lambda arxiv_id, max_chars=4000: "arxiv abstract")

    assert auth.load_source("hf://datasets/openai/gsm8k") == "row1\nrow2"
    assert auth.load_source("https://en.wikipedia.org/wiki/GSM8K") == "wiki text"
    assert auth.load_source("https://arxiv.org/abs/2110.14168") == "arxiv abstract"
    with pytest.raises(ValueError, match="Unsupported source ref"):
        auth.load_source("https://example.com/not-a-source")


def test_execute_planner_tool_search_and_load(monkeypatch) -> None:
    monkeypatch.setattr(
        tp,
        "search_sources",
        lambda query, limit=8: [{"kind": "hf_dataset", "ref": "hf://datasets/openai/gsm8k", "title": "GSM8K"}],
    )
    monkeypatch.setattr(tp, "load_source", lambda ref, limit=5: "raw content")

    search = tp._execute_planner_tool(
        ToolCall(id="c1", name="search_sources", arguments={"query": "math"}),
        BenchmarkConfig(),
        max_chars=1000,
        source_materials={},
    )
    assert search.error is None
    assert "hf://datasets/openai/gsm8k" in search.content

    load = tp._execute_planner_tool(
        ToolCall(id="c2", name="load_source", arguments={"ref": "hf://datasets/openai/gsm8k"}),
        BenchmarkConfig(),
        max_chars=1000,
        source_materials={},
    )
    assert load.error is None
    assert json.loads(load.content)["content"] == "raw content"


def test_planner_tool_list_selects_research_mode() -> None:
    read_tool = tp._planner_read_tool(False)
    write_tool = tp._planner_write_tool(False)

    authoritative = tp._planner_tool_list(
        BenchmarkConfig(ablation_authoritative_research=True),
        read_tool=read_tool,
        write_tool=write_tool,
    )
    assert [tool.name for tool in authoritative] == ["search_sources", "load_source", "read_plan", "update_plan"]

    web = tp._planner_tool_list(
        BenchmarkConfig(use_web_research=True, search_backend="ablation-keyless"),
        read_tool=read_tool,
        write_tool=write_tool,
    )
    assert [tool.name for tool in web] == ["search_web", "fetch_url", "read_plan", "update_plan"]

    none = tp._planner_tool_list(
        BenchmarkConfig(use_web_research=False),
        read_tool=read_tool,
        write_tool=write_tool,
    )
    assert [tool.name for tool in none] == ["read_plan", "update_plan"]

    default = tp._planner_tool_list(
        BenchmarkConfig(),
        read_tool=read_tool,
        write_tool=write_tool,
    )
    assert [tool.name for tool in default] == ["search_web", "fetch_url", "read_plan", "update_plan"]


def test_system_prompt_appends_authoritative_note() -> None:
    prompt = benchmark_planner_system_prompt("BASE", authoritative_research=True)
    assert "search_sources" in prompt
    assert "load_source" in prompt
    assert "imported_dataset" in prompt
    assert benchmark_planner_system_prompt("BASE", authoritative_research=False).count("RESEARCH_MODE") == 0
