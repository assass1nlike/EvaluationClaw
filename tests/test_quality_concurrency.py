import json
from threading import Barrier

import pytest

from evalclaw.quality import contamination, laaj
from evalclaw.quality.llm_checks import _llm_qc_sample
from evalclaw.types import BenchmarkConfig
from tests.test_laaj import _response, _suite


@pytest.mark.parametrize("stage", ["laaj", "contamination"])
def test_all_sampled_items_start_concurrently_and_keep_order(monkeypatch, tmp_path, stage):
    suite = _suite()
    # Exceed the default ThreadPoolExecutor limit: every item must reach the
    # barrier before any can finish, so a fixed worker cap fails this test.
    suite.tasks = [suite.tasks[0].model_copy(update={"id": f"task_{i}"}) for i in range(40)]
    barrier = Barrier(len(suite.tasks), timeout=10)
    config = BenchmarkConfig(laaj_model="judge", laaj_api_key="test", laaj_sample_size=40)
    sampled, _ = _llm_qc_sample(suite, 40)
    expected_ids = [item.id for item in sampled]

    def judge(messages, **kwargs):
        request = json.loads(messages[0].content)
        if "item" in request:
            barrier.wait()
        return _response()

    def research(request, *args, **kwargs):
        barrier.wait()
        return json.dumps({"summary": request["item"]["id"], "limitations": [], "unresolved_urls": []})

    monkeypatch.setattr(laaj, "call_llm", judge)
    monkeypatch.setattr(contamination, "_run_laaj_tool_loop", research)
    if stage == "laaj":
        report = laaj.evaluate_with_laaj("Goal", suite, None, config, trace_dir=tmp_path)
        results = report.item_results
        paths = [tmp_path / "items" / f"item-{i:04d}" / "result.json" for i in range(1, 41)]
        assert report.correctness.score == 4
    else:
        report = contamination.evaluate_contamination(
            "Goal", suite, config, trace_dir=tmp_path, log=lambda _: None,
        )
        results = report.items
        paths = [tmp_path / f"item-{i:04d}" / "result.json" for i in range(1, 41)]
        assert all(item.status == "not_searchable" for item in results)
        assert [item.research_summary for item in results] == expected_ids
        assert json.loads((tmp_path / "report.json").read_text()) == report.model_dump(mode="json")
    assert [result.item_id for result in results] == expected_ids
    assert [json.loads(path.read_text())["item_id"] for path in paths] == expected_ids


@pytest.mark.parametrize("stage", ["laaj", "contamination"])
def test_item_failure_preserves_other_concurrent_results(monkeypatch, tmp_path, stage):
    suite = _suite()
    config = BenchmarkConfig(laaj_model="judge", laaj_api_key="test")
    barrier = Barrier(len(suite.tasks), timeout=10)
    attempts = {}

    def evaluate(request):
        item_id = request["item"]["id"]
        attempts[item_id] = attempts.get(item_id, 0) + 1
        if attempts[item_id] == 1:
            barrier.wait()
        if item_id == "item_1":
            raise RuntimeError("item failed")

    def judge(messages, **kwargs):
        request = json.loads(messages[0].content)
        if "item" in request:
            evaluate(request)
        return _response()

    def research(request, *args, **kwargs):
        evaluate(request)
        return json.dumps({"summary": "Completed research."})

    monkeypatch.setattr(laaj, "call_llm", judge)
    monkeypatch.setattr(contamination, "_run_laaj_tool_loop", research)
    if stage == "laaj":
        report = laaj.evaluate_with_laaj("Goal", suite, None, config, trace_dir=tmp_path)
        assert set(report.item_errors) == {"item_1"}
        assert set(report.evaluated_item_ids) == {"item_2", "item_3"}
        assert report.correctness is None and report.faithfulness is None
        assert report.diversity is not None and report.overall_error is None
        assert attempts == {"item_1": 3, "item_2": 1, "item_3": 1}
        assert (tmp_path / "items/item-0001/error.json").exists()
        paths = [tmp_path / "items" / f"item-{i:04d}/result.json" for i in (2, 3)]
    else:
        report = contamination.evaluate_contamination(
            "Goal", suite, config, trace_dir=tmp_path, log=lambda _: None,
        )
        assert [item.status for item in report.items] == ["failed", "not_searchable", "not_searchable"]
        assert json.loads((tmp_path / "item-0001/result.json").read_text())["status"] == "failed"
        paths = [tmp_path / f"item-{i:04d}/result.json" for i in (2, 3)]
    sampled, _ = _llm_qc_sample(suite, len(suite.tasks))
    assert [json.loads(path.read_text())["item_id"] for path in paths] == [item.id for item in sampled[1:]]
