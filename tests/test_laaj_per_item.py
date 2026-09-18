import json

import pytest

from evalclaw.quality import laaj
from evalclaw.types import AnalysisReport, BenchmarkConfig, TaskAsset
from tests.test_laaj import _response, _suite


def test_individual_judgment_has_only_one_task_and_persists_reasoning(monkeypatch, tmp_path):
    suite = _suite()
    suite.tasks = suite.tasks[1:2]
    requests = []

    def judge(messages, **kwargs):
        requests.append(json.loads(messages[0].content))
        return _response()

    monkeypatch.setattr(laaj, "call_llm", judge)
    result = laaj._evaluate_laaj_item(
        "Evaluate both skills", suite, BenchmarkConfig(laaj_model="judge", laaj_api_key="test"),
        trace_dir=tmp_path,
    )
    assert len(requests) == 1
    assert requests[0]["item"]["id"] == "item_2"
    assert "benchmark" not in requests[0]
    assert "analyser_output" not in requests[0]
    assert result.item_id == "item_2"
    assert result.correctness.score == 4
    assert json.loads((tmp_path / "result.json").read_text()) == result.model_dump(mode="json")


def test_failed_item_is_not_scored_zero(monkeypatch, tmp_path):
    suite = _suite()
    suite.tasks = suite.tasks[:1]
    monkeypatch.setattr(laaj, "call_llm", lambda *args, **kwargs: "{}")
    with pytest.raises(RuntimeError, match="item_1"):
        laaj._evaluate_laaj_item(
            "Goal", suite, BenchmarkConfig(laaj_model="judge", laaj_api_key="test"),
            trace_dir=tmp_path,
        )
    assert not (tmp_path / "result.json").exists()
    assert json.loads((tmp_path / "error.json").read_text())["attempts"] == 1


def test_per_item_means_are_computed_and_overall_cannot_override_them(monkeypatch, tmp_path):
    requests = []
    scores = {"item_1": (2, 3), "item_2": (4, 5), "item_3": (1, 1)}

    def judge(messages, **kwargs):
        assert len(messages) == 1
        request = json.loads(messages[0].content)
        requests.append(request)
        if "item" in request:
            assert "analyser_output" not in request
            return json.dumps({
                name: {"score": score, "reasoning": request["item"]["id"] + " evidence"}
                for name, score in zip(("correctness", "faithfulness"),
                                       scores[request["item"]["id"]])
            })
        assert "analyser_output" in request
        # Extraneous model-generated aggregates must never replace the arithmetic means.
        return _response(analyser=True)

    monkeypatch.setattr(laaj, "call_llm", judge)
    report = laaj.evaluate_with_laaj(
        "Goal", _suite(), AnalysisReport(analysis="Supported weaknesses"),
        BenchmarkConfig(laaj_model="judge", laaj_api_key="test"), trace_dir=tmp_path,
    )
    assert len(requests) == 4
    assert {r["item"]["id"] for r in requests[:-1]} == set(scores)
    assert len(requests[-1]["benchmark"]["items"]) == 3
    assert "clarity" not in report.model_dump()
    assert all("clarity" not in item.model_dump() for item in report.item_results)
    assert report.correctness.score == pytest.approx(7 / 3)
    assert report.faithfulness.score == 3
    assert report.diversity.score == 3
    assert report.systematicness.score == 4
    assert report.credibility.score == 3
    assert len(report.item_results) == 3
    assert {r.item_id for r in report.item_results} == set(scores)
    assert len(list((tmp_path / "items").glob('*/result.json'))) == 3


def test_failed_overall_retry_does_not_repeat_item_judgments(monkeypatch):
    judged = []
    overall = []

    def judge(messages, **kwargs):
        request = json.loads(messages[0].content)
        if "item" in request:
            judged.append(request["item"]["id"])
            return _response()
        overall.append(request)
        return "{}" if len(overall) == 1 else _response()

    monkeypatch.setattr(laaj, "call_llm", judge)
    report = laaj.evaluate_with_laaj(
        "Goal", _suite(), None, BenchmarkConfig(laaj_model="judge", laaj_api_key="test"),
    )
    assert len(judged) == len(set(judged)) == 3
    assert len(overall) == 2
    assert report.correctness.score == 4


def test_exhausted_item_failure_does_not_produce_partial_average(monkeypatch, tmp_path):
    calls = []

    def judge(messages, **kwargs):
        request = json.loads(messages[0].content)
        calls.append(request["item"]["id"])
        return _response() if request["item"]["id"] == "item_1" else "{}"

    monkeypatch.setattr(laaj, "call_llm", judge)
    with pytest.raises(RuntimeError):
        laaj.evaluate_with_laaj(
            "Goal", _suite(), None, BenchmarkConfig(laaj_model="judge", laaj_api_key="test"),
            trace_dir=tmp_path,
        )
    assert len(calls) == 9
    assert len(list((tmp_path / "items").glob('*/result.json'))) == 1
    assert len(list((tmp_path / "items").glob('*/error.json'))) == 2


@pytest.mark.parametrize("score", [0, 6, 2.5, True, "4"])
def test_invalid_item_score_is_retried_instead_of_averaged(monkeypatch, score):
    calls = []

    def judge(messages, **kwargs):
        calls.append(True)
        data = json.loads(_response())
        if len(calls) == 1:
            data["correctness"]["score"] = score
        return json.dumps(data)

    monkeypatch.setattr(laaj, "call_llm", judge)
    suite = _suite()
    suite.tasks = suite.tasks[:1]
    result = laaj._evaluate_laaj_item(
        "Goal", suite, BenchmarkConfig(laaj_model="judge", laaj_api_key="test"), trace_dir=None,
    )
    assert len(calls) == 2
    assert result.correctness.score == 4


def test_single_item_image_is_available_to_judge(monkeypatch, tmp_path):
    suite = _suite()
    suite.tasks = suite.tasks[:1]
    suite.tasks[0].assets = [TaskAsset(path=str(tmp_path / "chart.png"))]
    captured = []

    def loop(request, supplied_suite, config, **kwargs):
        captured.append(kwargs)
        assert len(supplied_suite.tasks) == 1
        assert len(request["item"]["assets"]) == 1
        return _response()

    monkeypatch.setattr(laaj, "_run_laaj_tool_loop", loop)
    laaj._evaluate_laaj_item(
        "Goal", suite, BenchmarkConfig(laaj_model="judge", laaj_api_key="test"), trace_dir=None,
    )
    assert captured[0]["include_agent_tools"] is True
    assert captured[0]["additional_tools"] == []
