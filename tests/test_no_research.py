import json

import pytest

from evalclaw.construction import research as builder
from evalclaw.construction.resources import _select_blueprint_sources
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.planning.task_planner import _audit_plan
from evalclaw.protocols.tool import ToolCall
from evalclaw.types import BenchmarkConfig, EvalDimension, EvalSpec
from tests.blueprint_factory import make_blueprint, make_plan
from tests.config_helpers import dummy_config_kwargs


@pytest.mark.parametrize("name", [
    "read_research_source", "search_sources", "load_source", "fetch_url", "list_url_links", "download_files",
])
def test_no_research_rejects_resource_tools(name):
    result = builder._execute_task_builder_tool(
        ToolCall(id="call", name=name, arguments={}),
        BenchmarkConfig(use_web_research=False), max_chars=1000,
    )
    assert result.error == "research_disabled"


def test_no_research_removes_source_tools_from_builder(monkeypatch, tmp_path):
    def model(messages, *, tools, **kwargs):
        names = {tool.name for tool in tools}
        assert not names.intersection({t.name for t in builder.TASK_BUILDER_SOURCE_TOOLS})
        assert not names.intersection({"search_sources", "load_source"})
        assert {"run_python", "read_candidate", "update_candidate"} <= names
        return TargetToolModelResponse(
            adapter="openai", content='{"tasks":[]}', tool_calls=[], raw_response={},
            assistant_message={"role": "assistant", "content": '{"tasks":[]}'},
        )
    monkeypatch.setattr(builder, "call_orchestrator_with_tools", model)
    config = BenchmarkConfig(**dummy_config_kwargs(), use_web_research=False, output_dir=str(tmp_path))
    raw, _ = builder.run_task_builder_tools({}, system_prompt="test", config=config, include_source_tools=True)
    assert json.loads(raw) == {"tasks": []}


def test_no_research_accepts_generated_plan_and_rejects_sources_and_aids():
    dimension = EvalDimension(id="d", name="D", description="D", approach="test")
    spec = EvalSpec(id="test", objective="Test", dimensions=[dimension])
    blueprint = make_blueprint("b", "d", "Task")
    plan = make_plan(spec, [blueprint])
    assert not _audit_plan(plan, use_web_research=False)
    plan.dimensions[0].task_designs[0].builder_resource_urls = ["https://example.com/data"]
    assert _audit_plan(plan, use_web_research=False)
    sourced = make_blueprint("s", "d", "Task", source_plan={
        "strategy": "adapted", "suggested_urls": ["https://example.com/data"],
    })
    with pytest.raises(ValueError):
        _select_blueprint_sources(dimension, sourced, BenchmarkConfig(use_web_research=False))
