import json

import pytest

from evalclaw.execution.evaluation import parse_evaluator_result
from evalclaw.execution.plan import build_execution_plan
from evalclaw.execution.runner import run_eval
from evalclaw.planning.loop import format_human_review_overview
from evalclaw.reporting.artifacts import write_lm_eval_artifacts
from evalclaw.reporting.viewer import _viewer_payload
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    BenchmarkPackage,
    ChallengeEffort,
    EvalDimension,
    EvalReport,
    EvalRun,
    EvalSpec,
    ItemResult,
    QcReport,
    TargetModelConfig,
    TaskType,
    safe_challenge_effort,
)


def _dataset() -> BenchmarkDataset:
    dimension = EvalDimension(
        id="core",
        name="Core",
        description="Evaluate core behavior.",
        approach="Use several scoring protocols.",
        target_item_count=5,
    )
    spec = EvalSpec(objective="Evaluate core behavior.", dimensions=[dimension])
    return BenchmarkDataset(
        spec=spec,
        items=[
            BenchmarkItem(
                id="mc",
                dimension_id="core",
                task_type=TaskType.choice,
                prompt="Choose the correct answer.",
                choices=[{"id": "A", "text": "First"}, {"id": "B", "text": "Second"}],
                correct_choice_ids=["A"],
            ),
            BenchmarkItem(
                id="short",
                dimension_id="core",
                task_type=TaskType.fill_blank,
                prompt="Return the expected token.",
                expected_text="token",
            ),
            BenchmarkItem(
                id="agent",
                dimension_id="core",
                task_type=TaskType.agent,
                prompt="Complete the workspace task.",
                rubric="Score the final workspace state.",
            ),
            BenchmarkItem(
                id="rejected",
                dimension_id="core",
                task_type=TaskType.choice,
                prompt="This item must not execute or export.",
                choices=[{"id": "A", "text": "First"}, {"id": "B", "text": "Second"}],
                correct_choice_ids=["B"],
            ),
        ],
    )


def _package(dataset: BenchmarkDataset, qc_report: QcReport) -> BenchmarkPackage:
    results = [
        ItemResult(item_id=item.id, target_id="target", raw_response="ok", score=1.0)
        for item in dataset.items
    ]
    return BenchmarkPackage(
        goal="Evaluate core behavior.",
        spec=dataset.spec,
        dataset=dataset,
        qc_report=qc_report,
        run=EvalRun(dataset=dataset, qc_report=qc_report, results=results),
        report=EvalReport(title="Report", markdown="Report", summaries=[]),
    )


def test_evaluator_result_prefers_structured_partial_score() -> None:
    result = parse_evaluator_result(
        returncode=1,
        stdout="target-controlled output",
        stderr="",
        result_json=json.dumps({"score": 0.6, "passed": False, "details": "three checks passed"}),
    )

    assert result.score == pytest.approx(0.6)
    assert result.passed is False
    assert result.details == "three checks passed"
    assert result.source == "result_json"


def test_evaluator_result_accepts_numeric_score_file() -> None:
    result = parse_evaluator_result(
        returncode=1,
        stdout="",
        stderr="",
        score_text="0.6\n",
    )

    assert result.score == pytest.approx(0.6)
    assert result.passed is False
    assert result.source == "score_file"


def test_evaluator_result_ignores_stdout_score_unless_explicitly_enabled() -> None:
    default_result = parse_evaluator_result(
        returncode=1,
        stdout='{"score": 1.0, "passed": true}',
        stderr="evaluation failed",
    )
    opted_in_result = parse_evaluator_result(
        returncode=1,
        stdout='{"score": 1.0, "passed": true}',
        stderr="",
        allow_stdout_score=True,
    )

    assert default_result.score == 0.0
    assert default_result.source == "returncode"
    assert opted_in_result.score == 1.0
    assert opted_in_result.source == "stdout"


@pytest.mark.parametrize(
    ("qc_report", "message"),
    [
        (QcReport(passed_item_ids=["mc", "mc"]), "contains duplicates"),
        (QcReport(rejected_item_ids=["missing"]), "contains unknown items"),
        (
            QcReport(passed_item_ids=["mc"], rejected_item_ids=["mc"]),
            "both passed and rejected",
        ),
    ],
)
def test_execution_plan_rejects_ambiguous_qc_ids(qc_report: QcReport, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_execution_plan(_dataset(), qc_report)


def test_direct_runner_and_lm_eval_share_the_accepted_item_view(monkeypatch, tmp_path) -> None:
    dataset = _dataset()
    qc_report = QcReport(
        passed_item_ids=["mc", "short", "agent"],
        rejected_item_ids=["rejected"],
    )
    target = TargetModelConfig(id="target", provider="openai", model="test-model")
    config = BenchmarkConfig(
        targets=[target],
        run_targets=True,
        use_web_research=False,
        use_hf_discovery=False,
    )

    monkeypatch.setattr(
        "evalclaw.execution.runner._run_item",
        lambda item, config, target_id: ItemResult(
            item_id=item.id,
            target_id=target_id,
            raw_response="ok",
            score=1.0,
        ),
    )

    run = run_eval(dataset, qc_report, config)
    plan = build_execution_plan(dataset, qc_report)
    artifacts = write_lm_eval_artifacts(plan.dataset, tmp_path)
    exported_ids: set[str] = set()
    for key, path in artifacts.items():
        if key.startswith("jsonl_"):
            exported_ids.update(json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines())
    metadata = json.loads(artifacts["metadata"].read_text(encoding="utf-8"))

    assert {result.item_id for result in run.results} == set(plan.accepted_item_ids)
    assert exported_ids == {"mc", "short"}
    assert set(metadata["unsupported_item_ids"]) == {"agent"}
    assert exported_ids | set(metadata["unsupported_item_ids"]) == set(plan.accepted_item_ids)
    assert "rejected" not in exported_ids


def test_mixed_lm_eval_export_splits_scoring_protocols(tmp_path) -> None:
    plan = build_execution_plan(
        _dataset(),
        QcReport(passed_item_ids=["mc", "short", "agent"], rejected_item_ids=["rejected"]),
    )
    artifacts = write_lm_eval_artifacts(plan.dataset, tmp_path)

    multiple_choice_yaml = artifacts["yaml_multiple_choice"].read_text(encoding="utf-8")
    exact_match_yaml = artifacts["yaml_exact_match"].read_text(encoding="utf-8")

    assert "output_type: multiple_choice" in multiple_choice_yaml
    assert "metric: acc" in multiple_choice_yaml
    assert "output_type: generate_until" in exact_match_yaml
    assert "metric: exact_match" in exact_match_yaml


def test_package_round_trip_hydrates_run_context_without_duplicate_serialization() -> None:
    dataset = _dataset()
    qc_report = QcReport(passed_item_ids=[item.id for item in dataset.items])
    package = _package(dataset, qc_report)

    payload = package.model_dump(mode="json")
    assert "dataset" not in payload["run"]
    assert "qc_report" not in payload["run"]

    restored = BenchmarkPackage.model_validate(payload)

    assert restored.run.dataset == restored.dataset
    assert restored.run.qc_report == restored.qc_report


def test_viewer_payload_is_bounded() -> None:
    dataset = _dataset()
    qc_report = QcReport(passed_item_ids=[item.id for item in dataset.items])
    package = _package(dataset, qc_report)

    payload = _viewer_payload(package, item_limit=1, result_limit=1)
    truncation = payload["diagnostics"]["viewer_truncation"]

    assert truncation == {
        "items_embedded": 1,
        "items_total": 4,
        "results_embedded": 1,
        "results_total": 4,
    }
    assert payload["diagnostics"]["used_items"] == 4
    assert len(payload["package"]["dataset"]["items"]) == 1
    assert len(payload["diagnostics"]["result_records"]) == 1


def test_viewer_does_not_treat_rejected_results_as_evaluated() -> None:
    dataset = _dataset()
    qc_report = QcReport(passed_item_ids=[], rejected_item_ids=[item.id for item in dataset.items])
    package = _package(dataset, qc_report)

    payload = _viewer_payload(package, item_limit=1, result_limit=1)

    assert payload["diagnostics"]["used_items"] == 0
    assert payload["diagnostics"]["viewer_truncation"]["results_embedded"] == 0
    assert payload["diagnostics"]["viewer_truncation"]["results_total"] == 0
    assert payload["diagnostics"]["result_records"] == []


def test_human_review_does_not_treat_empty_passed_ids_as_all_ready() -> None:
    dataset = _dataset()
    overview = format_human_review_overview(
        dataset,
        QcReport(passed_item_ids=[], rejected_item_ids=[item.id for item in dataset.items]),
        BenchmarkConfig(),
    )

    assert "Ready items: 0" in overview
    assert "| `core` Core | 5 | 0 | - |" in overview


def test_challenge_effort_does_not_accept_old_level_words() -> None:
    assert safe_challenge_effort("E1") == ChallengeEffort.E1
    assert safe_challenge_effort("easy", ChallengeEffort.E3) == ChallengeEffort.E3
    assert safe_challenge_effort("hard", ChallengeEffort.E1) == ChallengeEffort.E1
    assert safe_challenge_effort("E4", ChallengeEffort.E2) == ChallengeEffort.E2
    with pytest.raises(ValueError):
        ChallengeEffort("E4")
