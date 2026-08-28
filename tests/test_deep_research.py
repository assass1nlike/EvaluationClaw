"""Tests for the deep-research loop and its pipeline integration.

Follows the monkeypatch style of tests/test_core_smoke.py: no real network,
no real LLM calls.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from evalclaw.cli import app
from evalclaw.construction.resources import _source_context
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
    BenchmarkItem,
    BenchmarkPackage,
    BenchmarkSource,
    ChallengeEffort,
    EvalDimension,
    EvalRun,
    EvalSpec,
    QcReport,
    ResearchBrief,
    ResearchDifficultyFactor,
    ResearchDimension,
    ResearchEvidence,
    ResearchSourceMaterial,
    ResearchSourceRecommendation,
    ResearchTaskPattern,
    ScaleBudget,
    SourceKind,
    TaskSuite,
    TaskType,
)
from tests.config_helpers import dummy_config_kwargs

SYNTHESIS_JSON = json.dumps(
    {
        "dimensions": [
            {
                "name": "statute_interpretation",
                "measurement_target": "Apply statutory text to facts.",
                "boundary": "Exclude tax filing mechanics.",
                "task_shapes": ["fact pattern with conflicting provisions"],
            },
            {
                "name": "deduction_analysis",
                "measurement_target": "Compute allowable deductions.",
                "boundary": "Exclude investment advice.",
                "task_shapes": ["structured deduction calculation"],
            },
        ],
        "difficulty_factors": [
            {
                "factor": "conflicting jurisdictional rules",
                "observable_signal": "selects and applies the controlling rule",
                "design_implication": "include explicit jurisdiction context",
            }
        ],
        "task_patterns": [
            {
                "name": "grounded tax case",
                "description": "Apply a cited rule to a concrete case.",
                "suitable_task_types": ["generation"],
                "scoring_direction": "rubric checks rule selection and reasoning",
            }
        ],
        "source_recommendations": [
            {"title": "IRS Pub 17", "url": "https://ex.com/pub17", "why_useful": "authoritative rules"}
        ],
        "evidence": [
            {
                "observation": "Tax guidance distinguishes statutory interpretation from deduction calculation.",
                "design_implication": "keep these as separate dimensions",
                "source_urls": ["https://ex.com/pub17"],
            }
        ],
        "challenge_effort_anchors": {"E1": "single rule lookup", "E3": "multi-jurisdiction planning"},
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
        **dummy_config_kwargs(),
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


def test_gather_round_retries_failed_search_and_records_attempts(monkeypatch, tmp_path) -> None:
    calls = 0

    def fake_web_search(query, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise deep_research.SearchBackendError("temporary search failure")
        return SearchResult(
            content="search result",
            citations=[{"url": "https://example.test/source", "title": "Source"}],
        )

    monkeypatch.setattr(deep_research, "web_search", fake_web_search)
    monkeypatch.setattr(deep_research, "fetch_url_text", lambda url, **kwargs: None)

    material, citations = deep_research._gather_round(
        ["q1"],
        _research_config(),
        set(),
        trace_dir=tmp_path,
    )

    assert calls == 3
    assert len(material) == 1
    assert len(citations) == 1
    search_trace = json.loads((tmp_path / "searches.json").read_text(encoding="utf-8"))
    assert [attempt["status"] for attempt in search_trace[0]["attempts"]] == [
        "failed",
        "failed",
        "completed",
    ]


def test_gather_round_does_not_retry_a_valid_empty_result(monkeypatch, tmp_path) -> None:
    calls = 0

    def fake_web_search(query, **kwargs):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(deep_research, "web_search", fake_web_search)

    material, citations = deep_research._gather_round(
        ["q1"],
        _research_config(),
        set(),
        trace_dir=tmp_path,
    )

    assert calls == 1
    assert material == []
    assert citations == []
    search_trace = json.loads((tmp_path / "searches.json").read_text(encoding="utf-8"))
    assert search_trace[0]["status"] == "no_results"


def test_gather_round_records_all_failed_search_attempts(monkeypatch, tmp_path) -> None:
    calls = 0

    def fake_web_search(query, **kwargs):
        nonlocal calls
        calls += 1
        raise deep_research.SearchBackendError("search unavailable")

    monkeypatch.setattr(deep_research, "web_search", fake_web_search)

    with pytest.raises(deep_research.SearchBackendError):
        deep_research._gather_round(["q1"], _research_config(), set(), trace_dir=tmp_path)

    assert calls == deep_research.SEARCH_MAX_ATTEMPTS
    search_trace = json.loads((tmp_path / "searches.json").read_text(encoding="utf-8"))
    assert len(search_trace[0]["attempts"]) == deep_research.SEARCH_MAX_ATTEMPTS
    assert all(attempt["status"] == "failed" for attempt in search_trace[0]["attempts"])


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
        dimensions=[
            ResearchDimension(
                name="subskill_a",
                measurement_target="First capability.",
                boundary="Keep it distinct.",
                task_shapes=["grounded case"],
            )
        ],
        difficulty_factors=[
            ResearchDifficultyFactor(
                factor="ambiguous evidence",
                observable_signal="states uncertainty",
                design_implication="include incomplete inputs",
            )
        ],
        task_patterns=[
            ResearchTaskPattern(
                name="grounded answer",
                description="Answer from retained evidence.",
                suitable_task_types=["generation"],
                scoring_direction="rubric",
            )
        ],
        source_recommendations=[
            ResearchSourceRecommendation(title="Seed One", url="https://ex.com/seed1", why_useful="grounding"),
            ResearchSourceRecommendation(title="Seed Two", url="https://ex.com/seed2", why_useful="examples"),
        ],
        evidence=[
            ResearchEvidence(
                observation="The source contains a relevant rule.",
                design_implication="use a source-grounded prompt",
                source_urls=["https://ex.com/seed1"],
            )
        ],
        source_materials=[
            ResearchSourceMaterial(
                title="Seed One",
                url="https://ex.com/seed1",
                content="Complete retained source text.",
            )
        ],
        challenge_effort_anchors={"E1": "lookup", "E3": "expert synthesis"},
    )


# ---------------------------------------------------------------------------
# Graceful no-run conditions
# ---------------------------------------------------------------------------
def test_deep_research_returns_none_without_research_key() -> None:
    config = _research_config(research_api_key=None)
    assert run_deep_research("evaluate tax law reasoning", config) is None


def test_deep_research_returns_none_when_search_backend_disabled() -> None:
    assert run_deep_research("goal", _research_config(search_backend="none")) is None


# ---------------------------------------------------------------------------
# Loop control
# ---------------------------------------------------------------------------
def test_deep_research_stops_when_reflection_reports_no_gaps(monkeypatch) -> None:
    fake_llm, counts = _scripted_call_llm(
        {
            "query": '{"queries": ["q1", "q2"]}',
            "compress": '{"evidence": [{"observation": "finding one", "design_implication": "use a grounded task", "source_urls": ["https://ex.com/1"]}]}',
            "reflect": '{"done": true, "gaps": [], "follow_up_queries": []}',
            "synthesize": SYNTHESIS_JSON,
        }
    )
    monkeypatch.setattr(deep_research, "call_llm", fake_llm)
    search_calls: list[str] = []
    _patch_search(monkeypatch, search_calls)

    brief = run_deep_research(
        "evaluate tax law reasoning",
        _research_config(use_web_research=False),
    )

    assert brief is not None
    assert counts["reflect"] == 1  # stopped after round 1
    assert counts["compress"] == 1
    assert counts["synthesize"] == 1
    assert search_calls == ["q1", "q2"]
    assert [t.name for t in brief.dimensions] == ["statute_interpretation", "deduction_analysis"]
    assert brief.challenge_effort_anchors["E3"] == "multi-jurisdiction planning"
    assert brief.evidence[0].observation.startswith("Tax guidance")
    assert brief.source_materials
    assert brief.source_materials[0].content.startswith("page text of https://ex.com/")


def test_deep_research_runs_follow_up_round_then_stops(monkeypatch) -> None:
    fake_llm, counts = _scripted_call_llm(
        {
            "query": '{"queries": ["q1"]}',
            "compress": '{"evidence": [{"observation": "a finding", "design_implication": "use it", "source_urls": []}]}',
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
            "compress": '{"evidence": [{"observation": "a finding", "design_implication": "use it", "source_urls": []}]}',
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
            return '{"evidence": [{"observation": "tax reasoning finding", "design_implication": "use a grounded task", "source_urls": ["https://ex.com/1"]}]}'
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
    assert brief.evidence and "tax reasoning finding" in brief.evidence[0].observation
    assert brief.source_recommendations and brief.source_recommendations[0].url.startswith("https://ex.com/")
    assert "Best-effort" in brief.research_notes


def test_parse_brief_tolerates_partial_and_loose_shapes() -> None:
    brief = _parse_brief(
        {
            "dimensions": [{"name": "structured", "measurement_target": "d"}],
            "difficulty_factors": [{"factor": "ambiguity", "observable_signal": "uncertainty", "design_implication": "test it"}],
            "challenge_effort_anchors": [{"level": "E2", "meaning": "intermediate"}],
            "evidence": [{"observation": "c", "design_implication": "test it", "source_urls": []}],
        }
    )
    assert [t.name for t in brief.dimensions] == ["structured"]
    assert brief.challenge_effort_anchors == {"E2": "intermediate"}
    assert brief.source_recommendations == []  # missing field validates as empty


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
    assert '"dimensions": [' in resources
    assert '"name": "subskill_a"' in resources
    assert '"E3": "expert synthesis"' in resources
    assert '"evidence": [' in resources
    assert '"source_material_index": [' in resources
    assert '"content_chars": 30' in resources
    assert "Complete retained source text." not in resources
    # field guide is appended so the planner does not guess brief field semantics
    assert "Field meanings for the Benchmark Design Research brief above" in resources
    assert "source_material_index: a list of {title, url, content_chars}" in resources
    assert "challenge_effort_anchors: what E1-E3 construction effort means" in resources


def test_planner_resources_mark_deepresearch_directory_empty_when_absent() -> None:
    resources = _planner_resources("goal", BenchmarkConfig())

    assert '<DIRECTORY path="resources/deepresearch" empty="true" />' in resources
    assert 'path="resources/deepresearch/brief.json"' not in resources


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


def test_report_includes_research_brief_section() -> None:
    pkg = _minimal_package(_sample_brief())
    assert "## Benchmark Design Research" in pkg.report.markdown
    assert "Candidate dimensions: 1" in pkg.report.markdown
    assert "Source recommendations: 2" in pkg.report.markdown
    # Without a brief the section is absent.
    assert "## Benchmark Design Research" not in _minimal_package(None).report.markdown


def test_persist_package_writes_research_brief_artifacts(tmp_path) -> None:
    pkg = _minimal_package(_sample_brief())
    _persist_package(pkg, BenchmarkConfig(), str(tmp_path), log=lambda _msg: None)

    brief_json = tmp_path / "research_brief.json"
    brief_md = tmp_path / "research_brief.md"
    assert brief_json.exists() and brief_md.exists()
    payload = json.loads(brief_json.read_text(encoding="utf-8"))
    assert payload["dimensions"][0]["name"] == "subskill_a"
    md_text = brief_md.read_text(encoding="utf-8")
    assert "# Benchmark Design Research Brief" in md_text
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
        "## Candidate Dimensions",
        "## Difficulty Factors",
        "## Task Patterns",
        "## Source Recommendations",
        "## Design Evidence",
        "## Challenge Effort Anchors",
        "## Research Notes",
    ]:
        assert heading in text


def test_compact_brief_context_is_compact() -> None:
    brief = _sample_brief()
    context = compact_brief_context(brief)
    assert set(context) == {
        "dimensions",
        "difficulty_factors",
        "task_patterns",
        "source_recommendations",
        "evidence",
        "source_material_index",
        "challenge_effort_anchors",
    }
    assert "content" not in context["source_material_index"][0]


# ---------------------------------------------------------------------------
# Pipeline + CLI wiring
# ---------------------------------------------------------------------------
def test_pipeline_attaches_and_persists_brief(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("evalclaw.pipeline.run_deep_research", lambda goal, config, **kwargs: _sample_brief())
    monkeypatch.setattr("evalclaw.pipeline.translate_goal_to_english", lambda goal, config: goal)
    dimension = EvalDimension(
        id="summarization",
        name="Summarization",
        description="Summarize meeting notes.",
        approach="Use grounded meeting-note prompts.",
    )
    spec = EvalSpec(objective="Evaluate summarization", dimensions=[dimension])
    item = BenchmarkItem(
        id="summary_1",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Summarize the supplied meeting notes and preserve all decisions.",
        rubric="Score factual coverage and concision.",
    )
    suite = TaskSuite(spec=spec, objective=spec.objective, tasks=[item])
    qc_report = QcReport(passed_item_ids=[item.id], quality_score=1.0)
    construction_config: dict = {}

    def build_benchmark(goal, config, **kwargs):
        construction_config["value"] = config
        return spec, suite, qc_report

    monkeypatch.setattr("evalclaw.pipeline.build_benchmark_suite_with_qc_loop", build_benchmark)
    config = BenchmarkConfig(
        use_deep_research=True,
        use_web_research=False,
        use_hf_discovery=False,
        run_targets=False,
        environment_claw=False,
        scale_budget=ScaleBudget.low,
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
    assert pkg.research_brief.dimensions[0].name == "subskill_a"
    assert (tmp_path / "research_brief.json").exists()
    assert (tmp_path / "research_brief.md").exists()
    assert "## Benchmark Design Research" in pkg.report.markdown
    run_dir = next((tmp_path / "debug" / "runs").iterdir())
    used_config = construction_config["value"]
    assert used_config.planner_debug_dir == str(run_dir / "planner")
    assert used_config.task_builder_debug_dir == str(run_dir / "task-builder")


@pytest.mark.parametrize(
    "config_kwargs",
    [
        {},
        {"research_model": "dummy-research", "research_api_key": "dummy", "search_backend": "none"},
    ],
    ids=["research-role-missing", "search-backend-none"],
)
def test_pipeline_fails_when_requested_deep_research_is_unavailable(
    monkeypatch,
    config_kwargs,
) -> None:
    monkeypatch.setattr("evalclaw.pipeline.translate_goal_to_english", lambda goal, config: goal)
    monkeypatch.setattr(
        "evalclaw.pipeline.build_benchmark_suite_with_qc_loop",
        lambda *args, **kwargs: pytest.fail("benchmark construction must not start after research failure"),
    )
    config = BenchmarkConfig(
        use_deep_research=True,
        run_targets=False,
        environment_claw=False,
        **config_kwargs,
    )

    with pytest.raises(RuntimeError, match="Deep research was requested"):
        run_pipeline(
            "Evaluate research failure handling",
            config,
            log=lambda _msg: None,
            progress=lambda _msg: None,
            interactive=False,
        )


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
    assert captured["config"].use_web_research is False
    assert captured["config"].max_research_iterations == 5

    result = runner.invoke(app, ["generate", "-g", "goal", "--no-interactive"])
    assert result.exit_code == 0
    assert captured["config"].use_deep_research is False
    assert captured["config"].use_web_research is False
    assert captured["config"].targets == []
    assert captured["config"].run_targets is False

    result = runner.invoke(
        app,
        ["generate", "-g", "goal", "--no-interactive", "--web-research"],
    )
    assert result.exit_code == 0
    assert captured["config"].use_web_research is True

    result = runner.invoke(
        app,
        [
            "generate", "-g", "goal", "--no-interactive",
            "--planner-model", "planner-model", "--planner-api-key", "planner-key",
            "--task-builder-model", "builder-model", "--task-builder-api-key", "builder-key",
            "--qc-model", "qc-model", "--qc-api-key", "qc-key",
            "--task-model", "task-model",
            "--research-model", "research-model", "--research-api-key", "research-key",
            "--loop3-model", "loop3-model", "--loop3-api-key", "loop3-key",
        ],
    )
    assert result.exit_code == 0
    assert captured["config"].planner_model == "planner-model"
    assert captured["config"].task_builder_model == "builder-model"
    assert captured["config"].qc_model == "qc-model"
    assert captured["config"].task_models[0].model == "task-model"
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
