from __future__ import annotations

import json

from evalclaw.pipeline import _persist_package
from evalclaw.planning.planner import translate_report_markdown
from evalclaw.reporting.reporter import build_report
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    BenchmarkPackage,
    EvalDimension,
    EvalRun,
    EvalSpec,
    QcReport,
    TaskSuite,
    TaskType,
)


def _package() -> BenchmarkPackage:
    dimension = EvalDimension(
        id="dimension",
        name="Dimension",
        description="A test dimension.",
        approach="Use one choice task.",
    )
    spec = EvalSpec(
        id="translation_eval",
        objective="Evaluate the task.",
        dimensions=[dimension],
        task_types=[TaskType.choice],
    )
    item = BenchmarkItem(
        id="item",
        dimension_id=dimension.id,
        task_type=TaskType.choice,
        prompt="Choose one.",
        choices=[{"id": "A", "text": "Correct"}, {"id": "B", "text": "Wrong"}],
        correct_choice_ids=["A"],
    )
    suite = TaskSuite(spec=spec, objective=spec.objective, tasks=[item])
    run = EvalRun(suite=suite, qc_report=QcReport(passed_item_ids=[item.id]))
    return BenchmarkPackage(
        goal=spec.objective,
        spec=spec,
        suite=suite,
        qc_report=run.qc_report,
        run=run,
        report=build_report(run),
        created_at="2026-01-01T00:00:00+00:00",
    )


def test_translate_report_markdown_uses_planner(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_call_llm(messages, **kwargs):
        captured["messages"] = messages
        captured.update(kwargs)
        return "# 翻译后的报告"

    monkeypatch.setattr("evalclaw.planning.planner.call_llm", fake_call_llm)

    result = translate_report_markdown(
        "# Report\n\nScore: 1",
        "Chinese",
        BenchmarkConfig(planner_model="planner", planner_api_key="key"),
    )

    assert result == "# 翻译后的报告"
    assert captured["model"] == "planner"
    assert "Target language: Chinese" in captured["messages"][0].content


def test_persist_package_writes_translated_report(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "evalclaw.pipeline.translate_report_markdown",
        lambda markdown, language, config, *, trace_dir: "# 翻译报告",
    )
    package = _package()
    config = BenchmarkConfig(
        output_dir=str(tmp_path),
        report_language="zh-CN",
        planner_model="planner",
        planner_api_key="key",
    )

    _persist_package(package, config, str(tmp_path), lambda _: None)

    translated = tmp_path / "evalclaw_2026-01-01T000000_0000_zh-CN.md"
    assert translated.is_file()
    assert "# 翻译报告" in translated.read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["translated_report"] == str(translated)
    assert "translated_markdown_report" in package.report.markdown
