import json

import pytest

from evalclaw.construction import research as builder
from evalclaw.construction import resources
from evalclaw.construction.suite import _task_builder_payload
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.planning import skill_loader
from evalclaw.planning import task_planner as tp
from evalclaw.protocols.tool import ToolCall
from evalclaw.research import authoritative as auth
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkSource,
    EvalDimension,
    EvalSpec,
    ResearchBrief,
    SourceKind,
    TaskType,
)
from tests.blueprint_factory import make_blueprint, make_plan
from tests.config_helpers import dummy_config_kwargs


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

    materials = {}
    load = tp._execute_planner_tool(
        ToolCall(id="c2", name="load_source", arguments={"ref": "hf://datasets/openai/gsm8k"}),
        BenchmarkConfig(),
        max_chars=1000,
        source_materials=materials,
    )
    assert load.error is None
    assert json.loads(load.content)["content"] == "raw content"
    assert materials["hf://datasets/openai/gsm8k"].content == "raw content"


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


def test_planner_renders_research_sections_without_appending_conflicting_mode() -> None:
    template = "head<RESEARCH_TOOLS>normal tools</RESEARCH_TOOLS>middle<RESEARCH_GUIDANCE>normal guidance</RESEARCH_GUIDANCE>tail"
    assert skill_loader._research_sections(template, False) == "headnormal toolsmiddlenormal guidancetail"
    assert skill_loader._research_sections(template, True) == (
        "head" + auth.RESEARCH_POLICY + "middle" + skill_loader._AUTHORITATIVE_RESEARCH_GUIDANCE + "tail"
    )


def _no_open_web(*args, **kwargs):
    pytest.fail("Restricted-source construction must not call open-web research.")


@pytest.mark.parametrize("ref,kind", [
    ("hf://datasets/openai/gsm8k", SourceKind.hf_dataset),
    ("https://en.wikipedia.org/wiki/Logic", SourceKind.web),
    ("https://arxiv.org/abs/2110.14168", SourceKind.web),
])
def test_planner_raw_snapshot_reaches_builder_without_refetch(monkeypatch, ref, kind):
    original = "Original dataset or article content. " * 150
    monkeypatch.setattr(tp, "load_source", lambda *args, **kwargs: original)
    materials = {}
    cfg = BenchmarkConfig(ablation_authoritative_research=True)
    loaded = tp._execute_planner_tool(
        ToolCall(id="load", name="load_source", arguments={"ref": ref}),
        cfg, max_chars=10000, source_materials=materials,
    )
    assert loaded.error is None
    cfg.research_brief = ResearchBrief(source_materials=list(materials.values()))
    monkeypatch.setattr(resources, "fetch_url_text", _no_open_web)
    monkeypatch.setattr(resources, "load_source", _no_open_web)
    source = BenchmarkSource(kind=kind, uri=ref, title="Source")
    context = resources._source_context([source], cfg.research_brief, authoritative_research=True)
    assert context == f"--- Source ---\nURI: {ref}\n{original[:3000]}"
    result = builder._execute_task_builder_tool(
        ToolCall(id="read", name="read_research_source", arguments={"url": ref, "offset": 3000}),
        cfg, max_chars=10000,
    )
    assert result.error is None
    assert json.loads(result.content)["content"] == original[3000:]


@pytest.mark.parametrize("name", ["search_web", "fetch_url", "list_url_links", "download_files"])
def test_restricted_mode_rejects_open_web_dispatch(monkeypatch, name):
    monkeypatch.setattr(builder, "web_search", _no_open_web)
    monkeypatch.setattr(builder, "fetch_url_text", _no_open_web)
    monkeypatch.setattr(builder, "fetch_url_links", _no_open_web)
    monkeypatch.setattr(builder, "download_url_file", _no_open_web)
    cfg = BenchmarkConfig(ablation_authoritative_research=True)
    call = ToolCall(id="call", name=name, arguments={"query": "logic", "url": "https://example.com"})
    result = builder._execute_task_builder_tool(call, cfg, max_chars=1000)
    assert result.error == "research_mode_restricted"
    if name in {"search_web", "fetch_url"}:
        result = tp._execute_planner_tool(call, cfg, max_chars=1000, source_materials={})
        assert result.error == "research_mode_restricted"


def test_builder_exposes_catalog_tools_instead_of_web_tools(monkeypatch, tmp_path):
    def call_model(messages, *, tools, **kwargs):
        names = {tool.name for tool in tools}
        assert {"search_sources", "load_source", "read_research_source"} <= names
        assert not names.intersection({"search_web", "fetch_url", "list_url_links", "download_files"})
        return TargetToolModelResponse(adapter="openai", content='{"tasks":[]}', tool_calls=[],
                                       assistant_message={"role": "assistant", "content": '{"tasks":[]}'}, raw_response={})
    monkeypatch.setattr(builder, "call_orchestrator_with_tools", call_model)
    cfg = BenchmarkConfig(**dummy_config_kwargs(), ablation_authoritative_research=True, output_dir=str(tmp_path))
    result, _ = builder.run_task_builder_tools({}, system_prompt="test", config=cfg, include_source_tools=True)
    assert json.loads(result) == {"tasks": []}


def test_builder_catalog_search_and_raw_loading(monkeypatch):
    ref = "hf://datasets/openai/gsm8k"
    candidate = {"ref": ref, "title": "GSM8K", "kind": "hf_dataset"}
    monkeypatch.setattr(builder, "search_sources", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr(builder, "load_source", lambda *args, **kwargs: "raw rows")
    cfg = BenchmarkConfig(ablation_authoritative_research=True)
    state = {}
    for name, args, expected in [
        ("search_sources", {"query": "math"}, [candidate]),
        ("load_source", {"ref": ref}, None),
        ("read_research_source", {"url": ref}, None),
    ]:
        result = builder._execute_task_builder_tool(ToolCall(id=name, name=name, arguments=args),
                                                    cfg, max_chars=1000, tool_state=state)
        assert result.error is None
        data = json.loads(result.content)
        if expected is not None:
            assert data == expected
        else:
            assert data["content"] == "raw rows"


def test_source_preparation_uses_only_catalog_without_research_llm(monkeypatch):
    ref = "hf://datasets/openai/gsm8k"
    candidate = {"ref": ref, "title": "GSM8K", "kind": "hf_dataset"}
    calls = []
    def search(query, **kwargs):
        calls.append(query)
        return [candidate]
    monkeypatch.setattr(resources, "search_sources", search)
    monkeypatch.setattr(resources, "web_search", _no_open_web)
    monkeypatch.setattr(resources, "fetch_url_text", _no_open_web)
    monkeypatch.setattr(resources, "load_source", lambda *args, **kwargs: "raw rows")
    dimension = EvalDimension(id="math", name="Math", description="Math", approach="test", needs_research=True)
    blueprint = make_blueprint("math", "math", "Math", source_plan={
        "strategy": "imported_dataset", "suggested_urls": [ref], "search_queries": ["math"],
    })
    cfg = BenchmarkConfig(ablation_authoritative_research=True)
    sources = resources._select_blueprint_sources(dimension, blueprint, cfg)
    assert calls == ["math"]
    assert [source.uri for source in sources] == [ref]
    assert resources._source_context(sources, authoritative_research=True) == f"--- {ref} ---\nURI: {ref}\nraw rows"


@pytest.mark.parametrize("ref", ["https://example.com/data", "https://example.com/en.wikipedia.org/wiki/Logic"])
def test_unsupported_sources_rejected_in_plan_and_builder(monkeypatch, ref):
    with pytest.raises(ValueError):
        auth.load_source(ref)
    dimension = EvalDimension(id="logic", name="Logic", description="Logic", approach="test")
    spec = EvalSpec(id="test", objective="Logic", dimensions=[dimension])
    blueprint = make_blueprint("logic", "logic", "Logic", task_type=TaskType.generation,
                               source_plan={"strategy": "adapted", "suggested_urls": [ref]})
    plan = make_plan(spec, [blueprint])
    assert tp._audit_plan(plan, authoritative_research=True)
    cfg = BenchmarkConfig(ablation_authoritative_research=True)
    with pytest.raises(ValueError):
        resources._select_blueprint_sources(dimension, blueprint, cfg)
    with pytest.raises(ValueError):
        _task_builder_payload(spec, dimension, blueprint, "", None, config=cfg)


def test_failed_raw_load_does_not_become_source_content(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("source unavailable")
    monkeypatch.setattr(tp, "load_source", unavailable)
    materials = {}
    result = tp._execute_planner_tool(
        ToolCall(id="load", name="load_source", arguments={"ref": "hf://datasets/openai/gsm8k"}),
        BenchmarkConfig(ablation_authoritative_research=True), max_chars=1000, source_materials=materials,
    )
    assert result.error is not None
    assert materials == {}


@pytest.mark.parametrize("role", ["planner", "builder"])
def test_raw_content_pages_reconstruct_one_snapshot(monkeypatch, role):
    original = 'A "quoted" record\n' * 500
    calls = []
    def load(ref, **kwargs):
        calls.append(ref)
        return original
    monkeypatch.setattr(tp if role == "planner" else builder, "load_source", load)
    cfg = BenchmarkConfig(ablation_authoritative_research=True)
    state = {}
    ref = "hf://datasets/openai/gsm8k"
    offset = 0
    pages = []
    while offset is not None:
        call = ToolCall(id="load", name="load_source", arguments={"ref": ref, "offset": offset})
        if role == "planner":
            result = tp._execute_planner_tool(call, cfg, max_chars=1000, source_materials=state)
        else:
            result = builder._execute_task_builder_tool(call, cfg, max_chars=1000, tool_state=state)
        assert result.error is None
        assert len(result.content) <= 1000
        page = json.loads(result.content)
        pages.append(page["content"])
        offset = page["next_offset"]
    assert "".join(pages) == original
    assert calls == [ref]


@pytest.mark.parametrize("ref", [
    "hf://datasets/openai/gsm8k", "https://en.wikipedia.org/wiki/Logic", "https://arxiv.org/abs/2110.14168",
])
def test_unavailable_catalog_source_raises_instead_of_returning_error_as_text(monkeypatch, ref):
    def unavailable(*args, **kwargs):
        raise OSError("offline")
    monkeypatch.setattr(auth.httpx, "get", unavailable)
    with pytest.raises(RuntimeError):
        auth.load_source(ref)


def test_builder_payload_exposes_retained_assistance_for_generated_tasks(monkeypatch):
    ref = "https://en.wikipedia.org/wiki/Logic"
    materials = {}
    monkeypatch.setattr(tp, "load_source", lambda *args, **kwargs: "retained original")
    cfg = BenchmarkConfig(ablation_authoritative_research=True)
    tp._execute_planner_tool(ToolCall(id="load", name="load_source", arguments={"ref": ref}),
                             cfg, max_chars=1000, source_materials=materials)
    cfg.research_brief = ResearchBrief(source_materials=list(materials.values()))
    dimension = EvalDimension(id="logic", name="Logic", description="Logic", approach="test")
    spec = EvalSpec(id="test", objective="Logic", dimensions=[dimension])
    blueprint = make_blueprint("logic", "logic", "Logic")
    blueprint.task_designs[0].builder_resource_urls = [ref]
    payload = _task_builder_payload(spec, dimension, blueprint, "", None, config=cfg)
    assert payload["resources"]["source_material_index"] == [
        {"url": ref, "title": "", "characters": len("retained original")},
    ]
    assert payload["resources"]["research_policy"] == auth.RESEARCH_POLICY
    blueprint.task_designs[0].builder_resource_urls = ["https://example.com/other-source"]
    with pytest.raises(ValueError):
        _task_builder_payload(spec, dimension, blueprint, "", None, config=cfg)
