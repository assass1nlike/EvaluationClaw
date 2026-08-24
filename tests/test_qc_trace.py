import json

from evalclaw.quality.qc import run_qc_gate
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    TaskSuite,
    TaskType,
)
from tests.config_helpers import dummy_config_kwargs


def test_qc_trace_persists_model_exchange_and_complete_report(tmp_path, monkeypatch) -> None:
    raw_response = json.dumps(
        {
            "issues": [
                {
                    "item_id": "medical_1",
                    "severity": "warning",
                    "category": "clarity",
                    "message": "The source boundary should be stated explicitly.",
                    "suggested_action": "Name the evidence the answer may use.",
                }
            ],
            "summary": "One warning.",
        }
    )
    monkeypatch.setattr(
        "evalclaw.quality.llm_checks.call_llm",
        lambda *args, **kwargs: raw_response,
    )
    dimension = EvalDimension(
        id="medical",
        name="Medical",
        description="Evaluate a medical response.",
        approach="Use a source-grounded generation task.",
        task_types=[TaskType.generation],
    )
    suite = TaskSuite(
        spec=EvalSpec(
            objective="Evaluate source-grounded medical reasoning.",
            dimensions=[dimension],
            task_types=[TaskType.generation],
        ),
        objective="Evaluate source-grounded medical reasoning.",
        tasks=[
            BenchmarkItem(
                id="medical_1",
                dimension_id="medical",
                task_type=TaskType.generation,
                prompt="Explain the conclusion using only the supplied evidence.",
                rubric="Score factual accuracy and evidence use.",
            )
        ],
    )
    trace_dir = tmp_path / "debug" / "qc" / "run" / "00-initial"

    report = run_qc_gate(
        suite,
        BenchmarkConfig(**dummy_config_kwargs()),
        trace_dir=trace_dir,
    )

    assert (trace_dir / "llm-response.txt").read_text(encoding="utf-8") == raw_response
    assert json.loads((trace_dir / "suite.json").read_text(encoding="utf-8"))["tasks"][0][
        "id"
    ] == "medical_1"
    request = json.loads((trace_dir / "llm-request.json").read_text(encoding="utf-8"))
    assert request["request"]["items"][0]["id"] == "medical_1"
    parsed = json.loads(
        (trace_dir / "llm-parsed-response.json").read_text(encoding="utf-8")
    )
    assert parsed["issues"][0]["message"] == (
        "The source boundary should be stated explicitly."
    )
    saved_report = json.loads((trace_dir / "report.json").read_text(encoding="utf-8"))
    assert saved_report["issues"][0]["message"] == report.issues[0].message
    assert saved_report["issues"][0]["suggested_action"] == report.issues[0].suggested_action
    diagnostics = json.loads((trace_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["status"] == "completed"


def test_llm_qc_omits_choice_rubric(monkeypatch) -> None:
    captured: dict = {}

    def fake_call(messages, **_kwargs):
        captured.update(json.loads(messages[0].content))
        return '{"issues": [], "summary": "No issues."}'

    monkeypatch.setattr("evalclaw.quality.llm_checks.call_llm", fake_call)
    dimension = EvalDimension(
        id="arithmetic",
        name="Arithmetic",
        description="Arithmetic accuracy",
        approach="Use exact calculations.",
        task_types=[TaskType.choice],
    )
    item = BenchmarkItem(
        id="arithmetic_1",
        dimension_id=dimension.id,
        task_type=TaskType.choice,
        prompt="What is two plus two?",
        choices=[{"id": "A", "text": "3"}, {"id": "B", "text": "4"}],
        correct_choice_ids=["B"],
        rubric="This must not be used by QC.",
    )

    run_qc_gate(
        TaskSuite(
            spec=EvalSpec(
                objective="Evaluate arithmetic",
                dimensions=[dimension],
                task_types=[TaskType.choice],
            ),
            objective="Evaluate arithmetic",
            tasks=[item],
        ),
        BenchmarkConfig(**dummy_config_kwargs()),
    )

    assert captured["items"][0]["rubric"] is None
