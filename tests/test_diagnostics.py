import json
from types import SimpleNamespace

import pytest

from evalclaw.execution.environment_claw import run_environment_claw
from evalclaw.execution.runner import run_eval
from evalclaw.models.llm import LLMOutputTruncatedError, _call_litellm
from evalclaw.pipeline import run_pipeline
from evalclaw.quality.qc import run_qc_gate
from evalclaw.research.backends import SearchResult
from evalclaw.research.deep_research import run_deep_research
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    ItemResult,
    QcReport,
    ResearchBrief,
    TargetModelConfig,
    TaskSuite,
    TaskType,
)


def _suite(*item_ids: str) -> TaskSuite:
    dimension = EvalDimension(
        id="dimension",
        name="Dimension",
        description="Measure the capability.",
        approach="Use direct tasks.",
        target_item_count=len(item_ids),
    )
    return TaskSuite(
        spec=EvalSpec(objective="Evaluate capability", dimensions=[dimension]),
        objective="Evaluate capability",
        tasks=[
            BenchmarkItem(
                id=item_id,
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt=f"Solve {item_id}.",
                rubric="Score correctness.",
            )
            for item_id in item_ids
        ],
    )


def test_pipeline_failure_keeps_redacted_config(monkeypatch, tmp_path) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("construction failed with Bearer runtime-token")

    monkeypatch.setattr("evalclaw.pipeline._run_pipeline", fail)
    config = BenchmarkConfig(output_dir=str(tmp_path), planner_api_key="secret-key")

    with pytest.raises(RuntimeError, match="construction failed"):
        run_pipeline("goal", config)

    run_dir = next((tmp_path / "debug" / "runs").iterdir())
    saved_config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    assert saved_config["planner_api_key"] == "[REDACTED]"
    assert (run_dir / "failure.json").is_file()
    assert "runtime-token" not in (run_dir / "failure.json").read_text(encoding="utf-8")


def test_truncated_litellm_response_is_persisted(monkeypatch, tmp_path) -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content="partial response"),
            )
        ],
        usage={"completion_tokens": 10},
    )
    monkeypatch.setattr("litellm.completion", lambda **kwargs: response)

    with pytest.raises(LLMOutputTruncatedError) as raised:
        _call_litellm(
            model="test-model",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=10,
            retry_on_truncation=False,
            trace_dir=tmp_path,
        )

    assert raised.value.raw_response["choices"][0]["message"]["content"] == "partial response"
    trace = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert trace["status"] == "truncated"
    assert trace["response"]["usage"]["completion_tokens"] == 10


def test_deep_research_persists_round_and_brief(monkeypatch, tmp_path) -> None:
    from evalclaw.prompts.research import (
        RESEARCH_COMPRESS_SYSTEM_PROMPT,
        RESEARCH_QUERY_SYSTEM_PROMPT,
        RESEARCH_REFLECT_SYSTEM_PROMPT,
    )

    def fake_json(config, system, payload, **kwargs):
        if system == RESEARCH_QUERY_SYSTEM_PROMPT:
            return {"queries": ["query"]}
        if system == RESEARCH_COMPRESS_SYSTEM_PROMPT:
            return {
                "evidence": [
                    {
                        "observation": "Observed behavior.",
                        "design_implication": "Test it.",
                        "source_urls": ["https://example.test/source"],
                    }
                ]
            }
        if system == RESEARCH_REFLECT_SYSTEM_PROMPT:
            return {"done": True, "gaps": [], "follow_up_queries": []}
        return {"research_notes": "Complete."}

    monkeypatch.setattr("evalclaw.research.deep_research._call_orchestrator_json", fake_json)
    monkeypatch.setattr(
        "evalclaw.research.deep_research.web_search",
        lambda *args, **kwargs: SearchResult(
            content="Search summary",
            citations=[{"url": "https://example.test/source", "title": "Source"}],
        ),
    )
    monkeypatch.setattr(
        "evalclaw.research.deep_research.fetch_url_text",
        lambda *args, **kwargs: "Fetched source body.",
    )
    config = BenchmarkConfig(
        research_model="research-model",
        research_api_key="research-key",
        search_backend="keyless",
        use_hf_discovery=False,
        max_research_iterations=1,
    )

    brief = run_deep_research("goal", config, trace_dir=tmp_path)

    assert brief is not None
    assert (tmp_path / "round-01" / "searches.json").is_file()
    assert (tmp_path / "round-01" / "fetches.json").is_file()
    assert (tmp_path / "round-01" / "result.json").is_file()
    assert (tmp_path / "brief.json").is_file()


def test_qc_failure_persists_all_attempts(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "evalclaw.quality.llm_checks.call_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider failed")),
    )
    config = BenchmarkConfig(
        qc_model="qc-model",
        qc_api_key="qc-key",
        output_dir=str(tmp_path),
    )

    with pytest.raises(RuntimeError, match="LLM QC failed"):
        run_qc_gate(_suite("item"), config, trace_dir=tmp_path / "qc")

    diagnostics = json.loads((tmp_path / "qc" / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["status"] == "failed"
    assert len(diagnostics["attempts"]) == 3
    assert (tmp_path / "qc" / "suite.json").is_file()


def test_environment_preflight_report_survives_blocking_failure(monkeypatch, tmp_path) -> None:
    class FailedEnvironment:
        def preflight(self):
            raise RuntimeError("evaluator unavailable")

        def state(self):
            return {"environment": "code_sandbox", "status": "failed"}

        def cleanup(self):
            return None

    monkeypatch.setattr("evalclaw.execution.environment_claw._probe_docker", lambda *args: None)
    monkeypatch.setattr("evalclaw.execution.environment_claw._probe_docker_images", lambda *args: None)
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.build_agent_environment",
        lambda *args: FailedEnvironment(),
    )
    item = _suite("item").tasks[0].model_copy(
        update={"metadata": {"agent_env": {"type": "code_sandbox"}}}
    )
    config = BenchmarkConfig(
        output_dir=str(tmp_path),
        run_targets=True,
        targets=[TargetModelConfig(id="target", provider="openai", model="model")],
    )

    _, report = run_environment_claw([item], config)

    assert report.blocking_errors
    trace_dir = next((tmp_path / "debug" / "environment").iterdir())
    saved = json.loads((trace_dir / "report.json").read_text(encoding="utf-8"))
    assert saved["blocking_errors"]
    assert (trace_dir / "item" / "state.json").is_file()


def test_runner_persists_each_completed_item(monkeypatch, tmp_path) -> None:
    calls = 0

    def fake_run_item(item, config, target_id, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return ItemResult(item_id=item.id, target_id=target_id, raw_response="ok", score=1.0)

    monkeypatch.setattr("evalclaw.execution.runner._run_item", fake_run_item)
    suite = _suite("first", "second")
    config = BenchmarkConfig(
        output_dir=str(tmp_path),
        targets=[TargetModelConfig(id="target", provider="openai", model="model")],
    )

    with pytest.raises(KeyboardInterrupt):
        run_eval(
            suite,
            QcReport(passed_item_ids=["first", "second"]),
            config,
        )

    trace_dir = next((tmp_path / "debug" / "runner").iterdir())
    assert (trace_dir / "target" / "first" / "result.json").is_file()
    assert not (trace_dir / "target" / "second" / "result.json").exists()
