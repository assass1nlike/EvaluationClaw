from __future__ import annotations

import io
import json
import shutil
import tarfile
import zipfile

import pytest

from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.quality import contamination as module
from evalclaw.quality import contamination_tools as tool_module
from evalclaw.quality import laaj as laaj_module
from evalclaw.research.backends import SearchResult
from evalclaw.types import BenchmarkConfig, ContaminationItemResult, ContaminationReport, TaskType
from tests.test_laaj import _suite

PASSAGE = (
    "The observatory must reconcile the twelve sensor records before publishing the nightly summary. "
    "Two calibrations conflict: the later record corrects the gain but deliberately leaves the older "
    "offset intact. Identify the affected measurements and compute the corrected total without losing provenance."
)


def _config(**kwargs):
    return BenchmarkConfig(laaj_model="judge", laaj_api_key="dummy", **kwargs)


def _task_suite():
    suite = _suite()
    suite.tasks = suite.tasks[:1]
    suite.tasks[0].prompt = PASSAGE
    return suite


def _call(name, **args):
    return ToolCall(id=name, name=name, arguments=args)


def _model(monkeypatch, steps, score=2):
    remaining = iter(steps)
    calls = []
    def model(messages, **kwargs):
        calls.append({"messages": list(messages), **kwargs})
        if kwargs["system_prompt"] == module.CONTAMINATION_JUDGE_PROMPT:
            content = json.dumps({"score": score, "reasoning": "The cited original source exposes the solution."})
            tool_calls = []
        else:
            step = next(remaining)
            tool_calls = step if isinstance(step, list) else []
            content = "" if tool_calls else json.dumps(step)
        message = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = [{"id": call.id, "type": "function", "function": {
                "name": call.name, "arguments": json.dumps(call.arguments),
            }} for call in tool_calls]
        return TargetToolModelResponse(adapter="openai_compatible", content=content,
                                       tool_calls=tool_calls, assistant_message=message, raw_response={})
    monkeypatch.setattr(laaj_module, "call_orchestrator_with_tools", model)
    return calls


def _done(**updates):
    return {"summary": "Examined the available source leads.", "limitations": [], "unresolved_urls": [], **updates}


def test_agent_follows_landing_page_then_continues_to_a_second_source(monkeypatch, tmp_path):
    steps = [
        [_call("search_web", query="distinctive observatory calibration problem")],
        [_call("list_url_links", url="https://source.example/index")],
        [_call("fetch_url", url="https://source.example/problem")],
        [_call("read_source", source_id="source_1", offset=8500)],
        [_call("confirm_overlap", source_id="source_1", text=PASSAGE)],
        [_call("search_web", query='"deliberately leaves the older offset intact"')],
        [_call("fetch_url", url="https://other.example/problem")],
        [_call("confirm_overlap", source_id="source_2", text=PASSAGE)], _done(),
    ]
    calls = _model(monkeypatch, steps)
    monkeypatch.setattr(tool_module, "web_search", lambda *a, **k: SearchResult(content="lead", citations=[{"url": "https://source.example/index"}]))
    monkeypatch.setattr(tool_module, "fetch_url_links", lambda *a, **k: {"links": [{"url": "https://source.example/problem"}]})
    monkeypatch.setattr(tool_module, "fetch_url_text", lambda *a, **k: "x" * 9000 + "\n" + PASSAGE.replace(" ", "\n"))
    report = module.evaluate_contamination("Goal", _task_suite(), _config(), trace_dir=tmp_path, log=lambda _: None)
    result = report.items[0]
    assert result.status == "matched"
    assert len(result.matches) == 2
    assert len(result.queries) == 2
    assert result.tool_calls == 8
    assert report.conditional_score == 2
    assert report.confirmed_overlap_fraction == 1
    assert len(json.loads(calls[-1]["messages"][0]["content"])["matches"]) == 2
    evidence = json.loads((tmp_path / "item-0001/research.json").read_text())
    assert len(evidence["tool_trace"]) == 8
    assert evidence["sources"]["source_1"]["text"].endswith(PASSAGE.replace(" ", "\n"))
    assert ContaminationReport.model_validate_json((tmp_path / "report.json").read_text()) == report


@pytest.mark.parametrize("archive_type", ["zip", "tar"])
def test_downloads_archive_member_without_extracting_paths(monkeypatch, tmp_path, archive_type):
    archive_path = tmp_path / f"source.{archive_type}"
    if archive_type == "zip":
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("../../escaped.txt", PASSAGE)
    else:
        with tarfile.open(archive_path, "w") as archive:
            info = tarfile.TarInfo("../../escaped.txt")
            data = PASSAGE.encode()
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(tool_module, "download_url_file", lambda *a, **k: {"path": str(archive_path)})
    _model(monkeypatch, [[_call("download_source", url="https://source.example/archive")],
                         [_call("confirm_overlap", source_id="source_1", text=PASSAGE)], _done()])
    report = module.evaluate_contamination("Goal", _task_suite(), _config(), trace_dir=tmp_path / "trace", log=lambda _: None)
    assert report.items[0].matches[0].source_location == "../../escaped.txt"
    assert not (tmp_path / "escaped.txt").exists()
    assert report.conditional_score == 2


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext not installed")
def test_pdf_extraction(tmp_path):
    stream = f"BT /F1 8 Tf 10 100 Td ({PASSAGE}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 5000 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    pdf += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    assert tool_module.normalize(tool_module._document_text(pdf, tmp_path)) == PASSAGE


@pytest.mark.parametrize("invalid", ["short", "case_changed", "invented", "source_missing"])
def test_only_substantial_exact_original_overlap_is_confirmed(tmp_path, invalid):
    result = ContaminationItemResult(item_id="item_1", status="no_confirmed_match")
    tools = tool_module.ContaminationResearchTools(_task_suite().tasks[0], _config(), result, tmp_path)
    source_id = tools._register("https://source.example", "unrelated" if invalid == "source_missing" else PASSAGE)
    text = {"short": "The observatory", "case_changed": PASSAGE.upper(), "invented": "Invented " * 50}.get(invalid, PASSAGE)
    assert tools.dispatch(_call("confirm_overlap", source_id=source_id, text=text)).error
    assert not result.matches


def test_agent_file_match_and_no_search_summary_shortcut(monkeypatch, tmp_path):
    suite = _task_suite()
    item = suite.tasks[0]
    item.prompt = "Inspect the environment."
    item.task_type = TaskType.agent
    item.metadata["agent_env"] = {"type": "docker_workspace", "visible_files": {"brief.md": PASSAGE}}
    monkeypatch.setattr(tool_module, "web_search", lambda *a, **k: SearchResult(content=PASSAGE, citations=[]))
    monkeypatch.setattr(tool_module, "fetch_url_text", lambda *a, **k: PASSAGE)
    _model(monkeypatch, [
        [_call("inspect_agent_environment", item_ids=[item.id])],
        [_call("read_task_file", item_id=item.id, area="visible", path="brief.md")],
        [_call("search_web", query="observatory")],
        [_call("confirm_overlap", source_id="invented", text=PASSAGE, area="visible", path="brief.md")],
        [_call("fetch_url", url="https://source.example")],
        [_call("confirm_overlap", source_id="source_1", text=PASSAGE, area="visible", path="brief.md")], _done(),
    ])
    report = module.evaluate_contamination("Goal", suite, _config(), trace_dir=tmp_path, log=lambda _: None)
    assert len(report.items[0].matches) == 1
    assert report.items[0].matches[0].task_path == "brief.md"
    assert report.items[0].limitations


def test_budget_answers_all_tool_ids_and_allows_final_summary(monkeypatch, tmp_path):
    calls = _model(monkeypatch, [
        [_call("search_web", query="first"), _call("fetch_url", url="https://source.example")],
        _done(unresolved_urls=["https://source.example"]),
    ])
    monkeypatch.setattr(tool_module, "web_search", lambda *a, **k: SearchResult(content="", citations=[]))
    monkeypatch.setattr(tool_module, "fetch_url_text", lambda *a, **k: pytest.fail("Over-budget tool executed"))
    report = module.evaluate_contamination("Goal", _task_suite(), _config(contamination_max_tool_calls=1), trace_dir=tmp_path, log=lambda _: None)
    result = report.items[0]
    assert result.stop_reason == "budget_exhausted"
    assert result.tool_calls == 1
    assert result.unresolved_urls == ["https://source.example"]
    assert result.contamination is None
    assert len([m for m in calls[-1]["messages"] if m["role"] == "tool"]) == 2
    assert calls[-1]["tools"] == []


def test_final_format_repair_does_not_restart_research_budget(monkeypatch, tmp_path):
    _model(monkeypatch, [[_call("search_web", query="source")], {"bad": True}, _done()])
    monkeypatch.setattr(tool_module, "web_search", lambda *a, **k: SearchResult(content="", citations=[]))
    report = module.evaluate_contamination("Goal", _task_suite(), _config(), trace_dir=tmp_path, log=lambda _: None)
    assert report.items[0].tool_calls == 1
    assert report.items[0].status == "no_confirmed_match"
    assert report.conditional_score is None


def test_tool_failure_allows_adaptation_and_model_failure_preserves_matches(monkeypatch, tmp_path):
    _model(monkeypatch, [
        [_call("fetch_url", url="https://blocked.example")],
        [_call("fetch_url", url="https://working.example")],
        [_call("confirm_overlap", source_id="source_1", text=PASSAGE)],
    ])
    monkeypatch.setattr(tool_module, "fetch_url_text", lambda url, **k: None if url == "https://blocked.example" else PASSAGE)
    report = module.evaluate_contamination("Goal", _task_suite(), _config(), trace_dir=tmp_path, log=lambda _: None)
    assert report.items[0].status == "failed"
    assert len(report.items[0].matches) == 1
    assert (tmp_path / "item-0001/research.json").exists()


def test_query_and_source_limits_are_independent_of_total_tool_budget(monkeypatch, tmp_path):
    result = ContaminationItemResult(item_id="item_1", status="no_confirmed_match")
    tools = tool_module.ContaminationResearchTools(_task_suite().tasks[0], _config(contamination_max_queries=1, contamination_max_sources=1), result, tmp_path)
    monkeypatch.setattr(tool_module, "web_search", lambda *a, **k: SearchResult(content="", citations=[]))
    monkeypatch.setattr(tool_module, "fetch_url_text", lambda *a, **k: PASSAGE)
    assert not tools.dispatch(_call("search_web", query="first")).error
    assert tools.dispatch(_call("search_web", query="second")).error
    assert not tools.dispatch(_call("fetch_url", url="https://one.example")).error
    assert not tools.dispatch(_call("fetch_url", url="https://one.example")).error
    assert tools.dispatch(_call("fetch_url", url="https://two.example")).error
    assert len(tools.sources) == 1


@pytest.mark.parametrize("score", [0, 6, 3.5, "3"])
def test_invalid_judge_score_does_not_erase_match_evidence(monkeypatch, score):
    _model(monkeypatch, [[_call("fetch_url", url="https://source.example")],
                         [_call("confirm_overlap", source_id="source_1", text=PASSAGE)], _done()], score=score)
    monkeypatch.setattr(tool_module, "fetch_url_text", lambda *a, **k: PASSAGE)
    report = module.evaluate_contamination("Goal", _task_suite(), _config(), log=lambda _: None)
    assert report.confirmed_overlap_fraction == 1
    assert report.conditional_score is None


@pytest.mark.parametrize("enabled", [True, False])
def test_pipeline_runs_contamination_by_default_and_supports_opt_out(monkeypatch, tmp_path, enabled):
    from evalclaw import pipeline
    from evalclaw.types import EvalRun, LaajReport, QcReport
    from tests.test_laaj import _response

    suite = _suite()
    qc = QcReport(passed_item_ids=[item.id for item in suite.tasks])
    monkeypatch.setattr(pipeline, "translate_goal_to_english", lambda goal, config: goal)
    monkeypatch.setattr(pipeline, "build_benchmark_suite_with_qc_loop", lambda *a, **k: (suite.spec, suite, qc))
    monkeypatch.setattr(pipeline, "run_eval", lambda *a, **k: EvalRun(suite=suite, qc_report=qc))
    laaj = LaajReport(model="judge", evaluated_item_ids=[], total_item_count=3, **json.loads(_response()))
    monkeypatch.setattr(pipeline, "evaluate_with_laaj", lambda *a, **k: laaj)
    calls = []
    contamination = ContaminationReport(model="judge", search_backend="gemini", total_item_count=3,
                                        max_queries_per_item=12, max_sources_per_item=20, source_character_limit=100_000)
    def evaluate(*args, **kwargs):
        calls.append(kwargs)
        return contamination
    monkeypatch.setattr(pipeline, "evaluate_contamination", evaluate)
    package = pipeline._run_pipeline("Evaluate both skills.", _config(**({} if enabled else {"contamination_enabled": False})),
                                     interactive=False, debug_run_dir=tmp_path, log=lambda _: None)
    assert len(calls) == int(enabled)
    assert package.laaj.contamination == (contamination if enabled else None)
    assert LaajReport.model_validate_json((tmp_path / "laaj.json").read_text()).contamination == package.laaj.contamination


def test_cli_contamination_options_reach_configuration():
    from typer.main import get_command

    from evalclaw.cli import app
    command = get_command(app).commands["generate"]
    context = command.make_context("generate", [], resilient_parsing=True)
    assert context.params["contamination_enabled"] is True
    assert context.params["contamination_max_tool_calls"] == BenchmarkConfig().contamination_max_tool_calls
    context = command.make_context("generate", ["--no-contamination", "--contamination-min-overlap-chars", "300",
                                              "--contamination-max-tool-calls", "60"], resilient_parsing=True)
    assert context.params["contamination_enabled"] is False
    assert context.params["contamination_min_overlap_chars"] == 300
    assert context.params["contamination_max_tool_calls"] == 60


def test_sampled_no_match_is_unscored_and_agent_state_is_isolated(monkeypatch):
    suite = _suite()
    urls = {"item_1": "https://one.example", "item_3": "https://two.example"}

    def research(request, *args, **kwargs):
        call = _call("fetch_url", url=urls[request["item"]["id"]])
        result = kwargs["tool_handlers"][call.name](call)
        kwargs["on_tool_result"](call, result)
        return json.dumps(_done())

    monkeypatch.setattr(module, "_run_laaj_tool_loop", research)
    monkeypatch.setattr(tool_module, "fetch_url_text", lambda *a, **k: "Unrelated original content.")
    report = module.evaluate_contamination("Goal", suite, _config(contamination_sample_size=2), log=lambda _: None)
    assert [item.item_id for item in report.items] == ["item_1", "item_3"]
    assert report.items[0].checked_urls == ["https://one.example"]
    assert report.items[1].checked_urls == ["https://two.example"]
    assert all(item.status == "no_confirmed_match" for item in report.items)
    assert report.conditional_score is None


def test_report_displays_research_outcome_and_conditional_score(monkeypatch):
    from evalclaw.reporting.reporter import build_report
    from evalclaw.reporting.viewer import build_report_viewer_html
    from evalclaw.types import BenchmarkPackage, EvalRun, LaajReport, QcReport
    from tests.test_laaj import _response

    _model(monkeypatch, [[_call("fetch_url", url="https://source.example")],
                         [_call("confirm_overlap", source_id="source_1", text=PASSAGE)],
                         _done(unresolved_urls=["https://unresolved.example"])])
    monkeypatch.setattr(tool_module, "fetch_url_text", lambda *a, **k: PASSAGE)
    suite = _task_suite()
    contamination = module.evaluate_contamination("Goal", suite, _config(), log=lambda _: None)
    laaj = LaajReport(model="judge", evaluated_item_ids=[], total_item_count=1,
                      contamination=contamination, **json.loads(_response()))
    run = EvalRun(suite=suite, qc_report=QcReport())
    report = build_report(run, laaj=laaj)
    package = BenchmarkPackage(goal="Goal", spec=suite.spec, suite=suite, qc_report=run.qc_report,
                               run=run, laaj=laaj, report=report)
    assert BenchmarkPackage.model_validate_json(package.model_dump_json()).laaj.contamination == contamination
    assert "https://unresolved.example" in report.markdown
    assert "agent_finished" in report.markdown
    assert "2.00/5" in report.markdown
    assert "https://unresolved.example" in build_report_viewer_html(package)
