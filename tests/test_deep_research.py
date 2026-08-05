"""Tests for the deep-research loop and its pipeline integration.

Follows the monkeypatch style of tests/test_core_smoke.py: no real network,
no real LLM calls.
"""
from __future__ import annotations

import json

from typer.testing import CliRunner

from evalclaw.cli import app
from evalclaw.generation.generator import _select_research_sources
from evalclaw.pipeline import _persist_package, run_pipeline
from evalclaw.planning.task_planner import _planner_resources
from evalclaw.prompts.research import (
    RESEARCH_COMPRESS_SYSTEM_PROMPT,
    RESEARCH_QUERY_SYSTEM_PROMPT,
    RESEARCH_REFLECT_SYSTEM_PROMPT,
    RESEARCH_SYNTHESIS_SYSTEM_PROMPT,
)
from evalclaw.reporting.reporter import build_report
from evalclaw.research import deep_research
from evalclaw.research.backends import SearchResult
from evalclaw.research.deep_research import (
    _parse_brief,
    compact_brief_context,
    render_brief_markdown,
    run_deep_research,
)
from evalclaw.sources.hf_discovery import discover_hf_datasets
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    BenchmarkPackage,
    ChallengeEffort,
    EvalDimension,
    EvalRun,
    EvalSpec,
    QcReport,
    ResearchBenchmarkNote,
    ResearchBrief,
    ResearchSeedSource,
    ResearchTaxonomyEntry,
    ScaleBudget,
    SourceKind,
    TaskType,
)

SYNTHESIS_JSON = json.dumps(
    {
        "field_overview": "Tax law reasoning spans statutes, regulations, and case application.",
        "taxonomy": [
            {"name": "statute_interpretation", "description": "Apply statutory text to facts."},
            {"name": "deduction_analysis", "description": "Compute allowable deductions."},
        ],
        "existing_benchmarks": [
            {"name": "TaxBench", "url": "https://ex.com/taxbench", "known_weaknesses": ["small"]}
        ],
        "seed_sources": [
            {"title": "IRS Pub 17", "url": "https://ex.com/pub17", "why_useful": "authoritative rules"}
        ],
        "exemplar_items": [{"prompt": "Is X deductible?", "answer": "No", "notes": ""}],
        "challenge_effort_anchors": {"E1": "single rule lookup", "E4": "multi-jurisdiction planning"},
        "citations": [{"claim": "TaxBench exists", "url": "https://ex.com/taxbench"}],
        "research_notes": "coverage is US-centric",
    }
)


def _scripted_call_llm(script: dict):
    """Build a fake call_llm that dispatches on the system prompt and counts calls."""
    counts = {"query": 0, "compress": 0, "reflect": 0, "synthesize": 0}

    def fake_call_llm(messages, **kwargs):
        system = kwargs.get("system")
        if system is RESEARCH_QUERY_SYSTEM_PROMPT:
            counts["query"] += 1
            return script["query"]
        if system is RESEARCH_COMPRESS_SYSTEM_PROMPT:
            counts["compress"] += 1
            return script["compress"]
        if system is RESEARCH_REFLECT_SYSTEM_PROMPT:
            counts["reflect"] += 1
            reflect = script["reflect"]
            return reflect[min(counts["reflect"] - 1, len(reflect) - 1)] if isinstance(reflect, list) else reflect
        if system is RESEARCH_SYNTHESIS_SYSTEM_PROMPT:
            counts["synthesize"] += 1
            return script["synthesize"]
        raise AssertionError(f"unexpected system prompt: {str(system)[:60]}")

    return fake_call_llm, counts


def _research_config(**overrides) -> BenchmarkConfig:
    defaults = dict(
        orchestrator_api_key="dummy",
        use_web_research=True,
        use_hf_discovery=False,
        search_backend="keyless",
        max_research_iterations=3,
    )
    defaults.update(overrides)
    return BenchmarkConfig(**defaults)


def _patch_search(monkeypatch, calls: list[str]) -> None:
    def fake_web_search(query, **kwargs):
        calls.append(query)
        return SearchResult(
            content=f"synth for {query}",
            citations=[{"url": f"https://ex.com/{len(calls)}", "title": f"Cite {len(calls)}"}],
        )

    monkeypatch.setattr(deep_research, "web_search", fake_web_search)
    monkeypatch.setattr(deep_research, "fetch_url_text", lambda url, **kwargs: f"page text of {url}")


def test_gather_round_caps_fetch_attempts_when_fetches_fail(monkeypatch) -> None:
    fetch_calls: list[str] = []

    def fake_web_search(query, **kwargs):
        return SearchResult(
            content=f"synth for {query}",
            citations=[
                {"url": f"https://source.example/{query}/{index}", "title": "Source"}
                for index in range(5)
            ],
        )

    def fake_fetch(url, **kwargs):
        fetch_calls.append(url)
        return None

    monkeypatch.setattr(deep_research, "web_search", fake_web_search)
    monkeypatch.setattr(deep_research, "fetch_url_text", fake_fetch)

    material, citations = deep_research._gather_round(
        ["q1", "q2"],
        _research_config(),
        set(),
    )

    assert len(fetch_calls) == deep_research.MAX_FETCHES_PER_ROUND
    assert len(material) == 2
    assert len(citations) == 10


def test_hf_discovery_stops_after_service_failure(monkeypatch) -> None:
    calls = 0

    class FailingApi:
        def list_datasets(self, *, search, limit):
            nonlocal calls
            calls += 1
            raise TimeoutError("hub unavailable")

    monkeypatch.setattr("huggingface_hub.HfApi", lambda: FailingApi())
    dimension = EvalDimension(
        id="healthcare",
        name="Healthcare deception",
        description="Evaluate deception in healthcare settings.",
        approach="Source-grounded tasks.",
        research_queries=["query one", "query two"],
    )

    assert discover_hf_datasets(dimension, limit=3) == []
    assert calls == 1


def _sample_brief() -> ResearchBrief:
    return ResearchBrief(
        field_overview="Overview of the domain.",
        taxonomy=[ResearchTaxonomyEntry(name="subskill_a", description="First capability.")],
        existing_benchmarks=[ResearchBenchmarkNote(name="BenchA", url="https://ex.com/a")],
        seed_sources=[
            ResearchSeedSource(title="Seed One", url="https://ex.com/seed1", why_useful="grounding"),
            ResearchSeedSource(title="Seed Two", url="https://ex.com/seed2", why_useful="examples"),
        ],
        challenge_effort_anchors={"E1": "lookup", "E4": "expert synthesis"},
    )


# ---------------------------------------------------------------------------
# Graceful no-run conditions
# ---------------------------------------------------------------------------
def test_deep_research_returns_none_without_orchestrator_key() -> None:
    config = _research_config(orchestrator_api_key=None)
    assert run_deep_research("evaluate tax law reasoning", config) is None


def test_deep_research_returns_none_when_search_disabled() -> None:
    assert run_deep_research("goal", _research_config(search_backend="none")) is None
    assert run_deep_research("goal", _research_config(use_web_research=False)) is None


# ---------------------------------------------------------------------------
# Loop control
# ---------------------------------------------------------------------------
def test_deep_research_stops_when_reflection_reports_no_gaps(monkeypatch) -> None:
    fake_llm, counts = _scripted_call_llm(
        {
            "query": '{"queries": ["q1", "q2"]}',
            "compress": '{"findings": ["finding one (source: https://ex.com/1)"]}',
            "reflect": '{"done": true, "gaps": [], "follow_up_queries": []}',
            "synthesize": SYNTHESIS_JSON,
        }
    )
    monkeypatch.setattr(deep_research, "call_llm", fake_llm)
    search_calls: list[str] = []
    _patch_search(monkeypatch, search_calls)

    brief = run_deep_research("evaluate tax law reasoning", _research_config())

    assert brief is not None
    assert counts["reflect"] == 1  # stopped after round 1
    assert counts["compress"] == 1
    assert counts["synthesize"] == 1
    assert search_calls == ["q1", "q2"]
    assert brief.field_overview.startswith("Tax law reasoning")
    assert [t.name for t in brief.taxonomy] == ["statute_interpretation", "deduction_analysis"]
    assert brief.challenge_effort_anchors["E4"] == "multi-jurisdiction planning"


def test_deep_research_runs_follow_up_round_then_stops(monkeypatch) -> None:
    fake_llm, counts = _scripted_call_llm(
        {
            "query": '{"queries": ["q1"]}',
            "compress": '{"findings": ["a finding"]}',
            "reflect": [
                '{"done": false, "gaps": ["missing benchmarks"], "follow_up_queries": ["q_follow"]}',
                '{"done": true, "gaps": [], "follow_up_queries": []}',
            ],
            "synthesize": SYNTHESIS_JSON,
        }
    )
    monkeypatch.setattr(deep_research, "call_llm", fake_llm)
    search_calls: list[str] = []
    _patch_search(monkeypatch, search_calls)

    brief = run_deep_research("goal", _research_config())

    assert brief is not None
    assert counts["reflect"] == 2
    assert search_calls == ["q1", "q_follow"]


def test_deep_research_stops_at_max_iterations(monkeypatch) -> None:
    fake_llm, counts = _scripted_call_llm(
        {
            "query": '{"queries": ["q1"]}',
            "compress": '{"findings": ["a finding"]}',
            # Reflection never satisfied: would loop forever without the cap.
            "reflect": '{"done": false, "gaps": ["more"], "follow_up_queries": ["again"]}',
            "synthesize": SYNTHESIS_JSON,
        }
    )
    monkeypatch.setattr(deep_research, "call_llm", fake_llm)
    search_calls: list[str] = []
    _patch_search(monkeypatch, search_calls)

    brief = run_deep_research("goal", _research_config(max_research_iterations=2))

    assert brief is not None
    assert counts["reflect"] == 2
    assert counts["compress"] == 2
    assert counts["synthesize"] == 1


def test_deep_research_synthesis_failure_builds_best_effort_brief(monkeypatch) -> None:
    def fake_call_llm(messages, **kwargs):
        system = kwargs.get("system")
        if system is RESEARCH_QUERY_SYSTEM_PROMPT:
            return '{"queries": ["q1"]}'
        if system is RESEARCH_COMPRESS_SYSTEM_PROMPT:
            return '{"findings": ["tax reasoning finding"]}'
        if system is RESEARCH_REFLECT_SYSTEM_PROMPT:
            return '{"done": true}'
        if system is RESEARCH_SYNTHESIS_SYSTEM_PROMPT:
            raise RuntimeError("synthesis model unavailable")
        raise AssertionError("unexpected prompt")

    monkeypatch.setattr(deep_research, "call_llm", fake_call_llm)
    search_calls: list[str] = []
    _patch_search(monkeypatch, search_calls)

    brief = run_deep_research("evaluate tax law reasoning", _research_config())

    assert brief is not None
    assert "tax reasoning finding" in brief.field_overview
    assert brief.seed_sources and brief.seed_sources[0].url.startswith("https://ex.com/")
    assert brief.citations
    assert "Best-effort" in brief.research_notes


def test_parse_brief_tolerates_partial_and_loose_shapes() -> None:
    brief = _parse_brief(
        {
            "field_overview": "x",
            "taxonomy": ["loose_string_entry", {"name": "structured", "description": "d"}],
            "existing_benchmarks": ["NamedOnly"],
            "challenge_effort_anchors": [{"level": "E2", "meaning": "intermediate"}],
            "citations": [{"claim": "c", "url": "u"}],
        }
    )
    assert [t.name for t in brief.taxonomy] == ["loose_string_entry", "structured"]
    assert brief.existing_benchmarks[0].name == "NamedOnly"
    assert brief.challenge_effort_anchors == {"E2": "intermediate"}
    assert brief.seed_sources == []  # missing field validates as empty


# ---------------------------------------------------------------------------
# Planner integration
# ---------------------------------------------------------------------------
def test_planner_resources_include_research_brief() -> None:
    config = BenchmarkConfig(
        research_brief=_sample_brief(),
    )

    resources = _planner_resources("Evaluate tax law reasoning", config)

    assert 'path="resources/instruction.md"' in resources
    assert 'path="resources/deepresearch/brief.json"' in resources
    assert '"field_overview": "Overview of the domain."' in resources
    assert '"name": "subskill_a"' in resources
    assert '"name": "BenchA"' in resources
    assert '"E4": "expert synthesis"' in resources


def test_planner_resources_mark_deepresearch_directory_empty_when_absent() -> None:
    resources = _planner_resources("goal", BenchmarkConfig())

    assert '<DIRECTORY path="resources/deepresearch" empty="true" />' in resources
    assert 'path="resources/deepresearch/brief.json"' not in resources


# ---------------------------------------------------------------------------
# Generator integration
# ---------------------------------------------------------------------------
def _dimension(needs_research: bool = True) -> EvalDimension:
    return EvalDimension(
        id="statute_interpretation",
        name="Statute interpretation",
        description="Apply statutes to facts.",
        approach="Grounded questions.",
        needs_research=needs_research,
        research_queries=["tax statute interpretation dataset"],
    )


def test_generator_prefers_brief_seed_sources(monkeypatch) -> None:
    import evalclaw.generation.generator as generator_module

    def fake_web_search(query, **kwargs):
        return SearchResult(
            content="web synth",
            citations=[{"url": "https://ex.com/web-found", "title": "Web Found"}],
        )

    monkeypatch.setattr(generator_module, "web_search", fake_web_search)
    config = BenchmarkConfig(
        orchestrator_api_key="dummy",
        use_hf_discovery=False,
        use_web_research=True,
        max_research_sources=3,
        research_brief=_sample_brief(),
    )

    sources = _select_research_sources(_dimension(), config)

    assert [s.uri for s in sources[:2]] == ["https://ex.com/seed1", "https://ex.com/seed2"]
    assert all(s.kind == SourceKind.web for s in sources[:2])
    assert sources[0].notes == "grounding"
    assert any(s.uri == "https://ex.com/web-found" for s in sources)  # web search still fills the rest


def test_generator_seed_sources_respect_cap_and_no_research_dimensions() -> None:
    config = BenchmarkConfig(
        use_hf_discovery=False,
        use_web_research=False,
        max_research_sources=1,
        research_brief=_sample_brief(),
    )
    sources = _select_research_sources(_dimension(needs_research=False), config)
    assert [s.uri for s in sources] == ["https://ex.com/seed1"]


# ---------------------------------------------------------------------------
# Reporting + persistence
# ---------------------------------------------------------------------------
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
        expected_text="ok",
    )
    run = EvalRun(
        dataset=BenchmarkDataset(spec=spec, items=[item]),
        qc_report=QcReport(passed_item_ids=[item.id]),
    )
    return BenchmarkPackage(
        goal=spec.objective,
        spec=spec,
        dataset=run.dataset,
        qc_report=run.qc_report,
        run=run,
        report=build_report(run, research_brief=research_brief),
        research_brief=research_brief,
    )


def test_report_includes_research_brief_section() -> None:
    pkg = _minimal_package(_sample_brief())
    assert "## Research Brief" in pkg.report.markdown
    assert "Known benchmarks surveyed: 1" in pkg.report.markdown
    assert "Seed sources collected: 2" in pkg.report.markdown
    # Without a brief the section is absent.
    assert "## Research Brief" not in _minimal_package(None).report.markdown


def test_persist_package_writes_research_brief_artifacts(tmp_path) -> None:
    pkg = _minimal_package(_sample_brief())
    _persist_package(pkg, BenchmarkConfig(), str(tmp_path), log=lambda _msg: None)

    brief_json = tmp_path / "research_brief.json"
    brief_md = tmp_path / "research_brief.md"
    assert brief_json.exists() and brief_md.exists()
    payload = json.loads(brief_json.read_text(encoding="utf-8"))
    assert payload["field_overview"] == "Overview of the domain."
    md_text = brief_md.read_text(encoding="utf-8")
    assert "# Research Brief" in md_text
    assert "subskill_a" in md_text
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["research_brief"]["json"] == str(brief_json)
    assert manifest["research_brief"]["markdown"] == str(brief_md)


def test_persist_package_skips_brief_files_when_absent(tmp_path) -> None:
    pkg = _minimal_package(None)
    _persist_package(pkg, BenchmarkConfig(), str(tmp_path), log=lambda _msg: None)
    assert not (tmp_path / "research_brief.json").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "research_brief" not in manifest


def test_render_brief_markdown_covers_all_sections() -> None:
    brief = _parse_brief(json.loads(SYNTHESIS_JSON))
    text = render_brief_markdown(brief)
    for heading in [
        "## Field Overview",
        "## Taxonomy",
        "## Existing Benchmarks",
        "## Seed Sources",
        "## Exemplar Items",
        "## Challenge Effort Anchors",
        "## Citations",
        "## Research Notes",
    ]:
        assert heading in text


def test_compact_brief_context_is_compact() -> None:
    brief = _sample_brief()
    context = compact_brief_context(brief)
    assert set(context) == {"field_overview", "taxonomy", "existing_benchmarks", "challenge_effort_anchors"}


# ---------------------------------------------------------------------------
# Pipeline + CLI wiring
# ---------------------------------------------------------------------------
def test_pipeline_attaches_and_persists_brief(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("evalclaw.pipeline.run_deep_research", lambda goal, config, **kwargs: _sample_brief())
    config = BenchmarkConfig(
        use_deep_research=True,
        use_web_research=False,
        use_hf_discovery=False,
        task_builder="local",
        run_targets=False,
        environment_claw=False,
        scale_budget=ScaleBudget.low,  # keep the fallback dataset small so QC stays fast
        output_dir=str(tmp_path),
    )

    pkg = run_pipeline(
        "Evaluate the capability to summarize meeting notes",
        config,
        log=lambda _msg: None,
        progress=lambda _msg: None,
        interactive=False,
    )

    assert pkg.research_brief is not None
    assert pkg.research_brief.field_overview == "Overview of the domain."
    assert (tmp_path / "research_brief.json").exists()
    assert (tmp_path / "research_brief.md").exists()
    assert "## Research Brief" in pkg.report.markdown


def test_cli_deep_research_flags_wire_into_config(monkeypatch) -> None:
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
            "--deep-research", "--max-research-iterations", "5",
        ],
    )
    assert result.exit_code == 0
    assert captured["config"].use_deep_research is True
    assert captured["config"].max_research_iterations == 5

    result = runner.invoke(app, ["generate", "-g", "goal", "--no-interactive"])
    assert result.exit_code == 0
    assert captured["config"].use_deep_research is False
    assert captured["config"].targets == []
    assert captured["config"].run_targets is False

    result = runner.invoke(
        app,
        [
            "generate", "-g", "goal", "--no-interactive",
            "--planner-model", "planner-model", "--planner-api-key", "planner-key",
            "--task-builder-model", "builder-model", "--task-builder-api-key", "builder-key",
            "--qc-model", "qc-model", "--qc-api-key", "qc-key",
            "--judge-model", "judge-model", "--judge-api-key", "judge-key",
            "--research-model", "research-model", "--research-api-key", "research-key",
            "--loop3-model", "loop3-model", "--loop3-api-key", "loop3-key",
        ],
    )
    assert result.exit_code == 0
    assert captured["config"].planner_model == "planner-model"
    assert captured["config"].task_builder_model == "builder-model"
    assert captured["config"].qc_model == "qc-model"
    assert captured["config"].judge_model == "judge-model"
    assert captured["config"].research_model == "research-model"
    assert captured["config"].loop3_model == "loop3-model"

    result = runner.invoke(
        app,
        [
            "generate", "-g", "goal", "--no-interactive",
            "--model", "mock-target", "--target-provider", "mock",
        ],
    )
    assert result.exit_code == 0
    assert [target.model for target in captured["config"].targets] == ["mock-target"]
    assert captured["config"].run_targets is True

    result = runner.invoke(
        app,
        ["generate", "-g", "goal", "--no-interactive", "--max-research-iterations", "0"],
    )
    assert result.exit_code == 1
