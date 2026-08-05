import json

from evalclaw.quality.qc import run_qc_gate
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    TaskType,
)


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
    dataset = BenchmarkDataset(
        spec=EvalSpec(
            objective="Evaluate source-grounded medical reasoning.",
            dimensions=[dimension],
            task_types=[TaskType.generation],
        ),
        items=[
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
        dataset,
        BenchmarkConfig(orchestrator_api_key="dummy"),
        trace_dir=trace_dir,
    )

    assert (trace_dir / "llm-response.txt").read_text(encoding="utf-8") == raw_response
    assert json.loads((trace_dir / "dataset.json").read_text(encoding="utf-8"))["items"][0][
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
