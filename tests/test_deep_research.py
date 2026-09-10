"""Tests for Planner-retained source materials and their downstream reuse."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from evalclaw.cli import app
from evalclaw.construction.resources import _source_context
from evalclaw.pipeline import _persist_package
from evalclaw.planning.task_planner import _execute_planner_tool, _planner_resources
from evalclaw.protocols.tool import ToolCall
from evalclaw.reporting.reporter import build_report
from evalclaw.research.deep_research import render_brief_markdown
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    BenchmarkPackage,
    BenchmarkSource,
    ChallengeEffort,
    EvalDimension,
    EvalRun,
    EvalSpec,
    QcReport,
    ResearchBrief,
    ResearchSourceMaterial,
    SourceKind,
    TaskSuite,
    TaskType,
)


def _sample_brief() -> ResearchBrief:
    return ResearchBrief(
        source_materials=[
            ResearchSourceMaterial(
                title="Seed One",
                url="https://ex.com/seed1",
                content="Complete retained source text.",
            ),
            ResearchSourceMaterial(
                title="Seed Two",
                url="https://ex.com/seed2",
                content="Another retained source.",
            ),
        ],
    )


def test_source_context_reuses_retained_material_without_refetch(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.construction.resources.fetch_url_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not refetch")),
    )

    context = _source_context(
        [
            BenchmarkSource(
                kind=SourceKind.web,
                uri="https://ex.com/seed1",
                title="Seed One",
            )
        ],
        _sample_brief(),
    )

    assert "Complete retained source text." in context


def _minimal_package(research_brief: ResearchBrief | None) -> BenchmarkPackage:
    dimension = EvalDimension(
        id="core", name="Core", description="d", approach="a", challenge_effort=ChallengeEffort.E2
    )
    spec = EvalSpec(id="brief_eval", objective="Evaluate the capability.", dimensions=[dimension])
    item = BenchmarkItem(
        id="item_1",
        dimension_id="core",
        task_type=TaskType.fill_blank,
        prompt="Answer briefly.",
        expected_texts=["ok"],
    )
    run = EvalRun(
        suite=TaskSuite(spec=spec, objective=spec.objective, tasks=[item]),
        qc_report=QcReport(passed_item_ids=[item.id]),
    )
    return BenchmarkPackage(
        goal=spec.objective,
        spec=spec,
        suite=run.suite,
        qc_report=run.qc_report,
        run=run,
        report=build_report(run, research_brief=research_brief),
        research_brief=research_brief,
    )


def test_report_includes_source_materials_section() -> None:
    pkg = _minimal_package(_sample_brief())
    assert "## Benchmark Source Materials" in pkg.report.markdown
    assert "Retained sources: 2" in pkg.report.markdown
    assert "## Benchmark Source Materials" not in _minimal_package(None).report.markdown


def test_persist_package_writes_research_brief_artifacts(tmp_path) -> None:
    pkg = _minimal_package(_sample_brief())
    _persist_package(pkg, BenchmarkConfig(), str(tmp_path), log=lambda _msg: None)

    brief_json = tmp_path / "research_brief.json"
    brief_md = tmp_path / "research_brief.md"
    assert brief_json.exists() and brief_md.exists()
    payload = json.loads(brief_json.read_text(encoding="utf-8"))
    assert payload["source_materials"][0]["url"] == "https://ex.com/seed1"
    md_text = brief_md.read_text(encoding="utf-8")
    assert "# Benchmark Source Materials" in md_text
    assert "https://ex.com/seed1" in md_text
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["research_brief"]["json"] == str(brief_json)
    assert manifest["research_brief"]["markdown"] == str(brief_md)


def test_persist_package_skips_brief_files_when_absent(tmp_path) -> None:
    pkg = _minimal_package(None)
    _persist_package(pkg, BenchmarkConfig(), str(tmp_path), log=lambda _msg: None)
    assert not (tmp_path / "research_brief.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "research_brief" not in manifest


def test_render_brief_markdown_lists_sources() -> None:
    text = render_brief_markdown(_sample_brief())
    assert "# Benchmark Source Materials" in text
    assert "https://ex.com/seed1" in text
    assert "https://ex.com/seed2" in text


def test_planner_resources_omit_research_brief() -> None:
    resources = _planner_resources("instruction text")
    assert "instruction text" in resources
    assert "deepresearch" not in resources


# ---------------------------------------------------------------------------
# Planner search/fetch tools
# ---------------------------------------------------------------------------
def test_planner_search_web_disabled_when_web_research_off() -> None:
    config = BenchmarkConfig(use_web_research=False)
    result = _execute_planner_tool(
        ToolCall(id="c1", name="search_web", arguments={"query": "x"}),
        config,
        max_chars=1000,
        source_materials={},
    )
    assert result.error == "search_disabled"


def test_planner_fetch_url_disabled_when_web_research_off() -> None:
    config = BenchmarkConfig(use_web_research=False)
    result = _execute_planner_tool(
        ToolCall(id="c1", name="fetch_url", arguments={"url": "https://ex.com/a"}),
        config,
        max_chars=1000,
        source_materials={},
    )
    assert result.error == "fetch_disabled"


def test_planner_fetch_url_records_source_material(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.planning.task_planner.fetch_url_text",
        lambda url, max_chars: "fetched body",
    )
    materials: dict = {}
    result = _execute_planner_tool(
        ToolCall(id="c1", name="fetch_url", arguments={"url": "https://ex.com/a"}),
        BenchmarkConfig(use_web_research=True),
        max_chars=1000,
        source_materials=materials,
    )
    assert result.error is None
    assert "https://ex.com/a" in materials
    assert materials["https://ex.com/a"].content == "fetched body"


def test_planner_fetch_url_keeps_longest_content(monkeypatch) -> None:
    def fake_fetch(url, max_chars):
        return "long body content" if url == "https://ex.com/a" else "short"

    monkeypatch.setattr("evalclaw.planning.task_planner.fetch_url_text", fake_fetch)
    materials: dict = {}
    _execute_planner_tool(
        ToolCall(id="c1", name="fetch_url", arguments={"url": "https://ex.com/a"}),
        BenchmarkConfig(use_web_research=True),
        max_chars=1000,
        source_materials=materials,
    )
    _execute_planner_tool(
        ToolCall(id="c2", name="fetch_url", arguments={"url": "https://ex.com/a"}),
        BenchmarkConfig(use_web_research=True),
        max_chars=1000,
        source_materials=materials,
    )
    assert materials["https://ex.com/a"].content == "long body content"


def test_planner_update_plan_edits_document(tmp_path) -> None:
    document = tmp_path / "plan.json"
    document.write_text(
        json.dumps({"objective": "", "constraints": [], "planner_notes": "", "dimensions": []}),
        encoding="utf-8",
    )
    _execute_planner_tool(
        ToolCall(
            id="c1",
            name="update_plan",
            arguments={"operations": [{"op": "set", "path": "objective", "value": "Eval coding"}]},
        ),
        BenchmarkConfig(),
        max_chars=1000,
        source_materials={},
        document_path=str(document),
    )
    _execute_planner_tool(
        ToolCall(
            id="c2",
            name="update_plan",
            arguments={
                "operations": [{"op": "append", "path": "dimensions", "value": {"name": "d1"}}]
            },
        ),
        BenchmarkConfig(),
        max_chars=1000,
        source_materials={},
        document_path=str(document),
    )
    _execute_planner_tool(
        ToolCall(
            id="c3",
            name="update_plan",
            arguments={
                "operations": [
                    {"op": "set", "path": "dimensions.0.task_designs", "value": [{"a": 1}]}
                ]
            },
        ),
        BenchmarkConfig(),
        max_chars=1000,
        source_materials={},
        document_path=str(document),
    )
    merged = json.loads(document.read_text(encoding="utf-8"))
    assert merged["objective"] == "Eval coding"
    assert merged["dimensions"][0]["name"] == "d1"
    assert merged["dimensions"][0]["task_designs"] == [{"a": 1}]


def test_planner_read_plan_reads_document(tmp_path) -> None:
    document = tmp_path / "plan.json"
    document.write_text(
        json.dumps({"objective": "x", "dimensions": [{"name": "d1"}]}), encoding="utf-8"
    )
    result = _execute_planner_tool(
        ToolCall(id="r1", name="read_plan", arguments={"path": "dimensions.0.name"}),
        BenchmarkConfig(),
        max_chars=1000,
        source_materials={},
        document_path=str(document),
    )
    assert result.error is None
    assert "d1" in result.content


def test_cli_task_config_carries_credentials(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_pipeline(goal, config, **kwargs):
        captured["config"] = config
        return _minimal_package(None)

    monkeypatch.setattr("evalclaw.cli.run_pipeline", fake_run_pipeline)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "generate", "-g", "goal", "--no-interactive",
            "--task-config", (
                '{"model": "task-model", "provider": "openai", '
                '"api_key": "task-key", "base_url": "https://task.example/v1", "id": "tm1"}'
            ),
        ],
    )
    assert result.exit_code == 0
    models = captured["config"].task_models
    assert len(models) == 1
    assert models[0].model == "task-model"
    assert models[0].provider == "openai"
    assert models[0].api_key == "task-key"
    assert models[0].base_url == "https://task.example/v1"
    assert models[0].id == "tm1"
