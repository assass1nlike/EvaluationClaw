import pytest

from evalclaw.execution.runner import run_eval, run_item
from evalclaw.generation.generator import generate_dimension_items
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    EvalDimension,
    EvalSpec,
    QcReport,
    TargetModelConfig,
    TaskSuite,
    TaskType,
)


def test_fallback_generation_attaches_multimodal_metadata() -> None:
    dimension = EvalDimension(
        id="vision_reasoning",
        name="Vision reasoning",
        description="Evaluate image understanding and visual reasoning.",
        approach="Use attached images and ask questions grounded in the visual evidence.",
        task_types=[TaskType.generation],
        target_item_count=1,
    )
    spec = EvalSpec(
        objective="Evaluate multimodal image reasoning.",
        dimensions=[dimension],
        task_types=[TaskType.generation],
    )
    config = BenchmarkConfig(use_hf_discovery=False, use_web_research=False)

    items, _, _ = generate_dimension_items(spec, dimension, 1, config)

    multimodal = items[0].metadata["multimodal"]
    assert multimodal["schema_version"] == "evalclaw.multimodal.v1"
    assert multimodal["modalities"] == ["image"]
    assert multimodal["assets"][0]["kind"] == "image"
    assert multimodal["content"][0]["type"] == "text"
    assert multimodal["content"][1]["type"] == "asset"


def test_runner_sends_multimodal_content_to_target(monkeypatch) -> None:
    item = BenchmarkItem(
        id="vision_item",
        dimension_id="vision_reasoning",
        task_type=TaskType.fill_blank,
        prompt="Look at the image and answer yes or no.",
        expected_text="yes",
        metadata={
            "multimodal": {
                "schema_version": "evalclaw.multimodal.v1",
                "modalities": ["image"],
                "assets": [
                    {
                        "id": "image_1",
                        "kind": "image",
                        "uri": "data:image/svg+xml;base64,PHN2Zy8+",
                        "mime_type": "image/svg+xml",
                    }
                ],
                "content": [
                    {"type": "text", "text": "Look at the image and answer yes or no."},
                    {"type": "asset", "asset_id": "image_1", "detail": "high"},
                ],
                "scoring": {"method": "accuracy"},
            }
        },
    )
    config = BenchmarkConfig(
        targets=[TargetModelConfig(provider="openai", model="gpt-5", api_key="dummy")],
        run_targets=True,
    )
    captured: dict[str, object] = {}

    def fake_has_credentials(target_id, cfg):
        return True, "OPENAI_API_KEY"

    def fake_call_target_model(prompt, target, **kwargs):
        captured.update(kwargs)
        return "yes"

    monkeypatch.setattr("evalclaw.execution.runner._target_has_credentials", fake_has_credentials)
    monkeypatch.setattr("evalclaw.execution.runner.call_target_model", fake_call_target_model)

    result = run_item(item, config)

    assert result.score == 1.0
    assert isinstance(captured["user_content"], list)
    assert captured["user_content"][0]["type"] == "text"
    assert captured["user_content"][1]["type"] == "image_url"


def test_deepseek_target_rejects_multimodal_item_before_call() -> None:
    item = BenchmarkItem(
        id="vision_item",
        dimension_id="vision_reasoning",
        task_type=TaskType.fill_blank,
        prompt="Look at the image and answer yes or no.",
        expected_text="yes",
        metadata={
            "multimodal": {
                "schema_version": "evalclaw.multimodal.v1",
                "modalities": ["image"],
                "assets": [
                    {
                        "id": "image_1",
                        "kind": "image",
                        "uri": "data:image/svg+xml;base64,PHN2Zy8+",
                        "mime_type": "image/svg+xml",
                    }
                ],
            }
        },
    )
    config = BenchmarkConfig(
        targets=[TargetModelConfig(provider="openai_compatible", model="deepseek-chat", api_key="dummy")],
        run_targets=True,
    )

    with pytest.raises(ValueError, match="not known to support native multimodal input"):
        run_item(item, config)


def test_azure_vision_deployments_support_multimodal() -> None:
    from evalclaw.protocols.multimodal import target_supports_multimodal_input
    from evalclaw.types import TargetModelConfig

    for deployment, expected in [
        ("azure/gpt-4o", True),
        ("azure/gpt-4o-mini", True),
        ("azure/gpt-5.5", True),
        ("azure/o4-mini", True),
        ("azure/DeepSeek-V3-0324", False),
    ]:
        target = TargetModelConfig(provider="azure", model=deployment, api_key="dummy")
        assert target_supports_multimodal_input(target) is expected, deployment


def test_run_eval_reports_multimodal_incompatible_target() -> None:
    spec = EvalSpec(objective="Evaluate image reasoning.")
    item = BenchmarkItem(
        id="vision_item",
        dimension_id="vision_reasoning",
        task_type=TaskType.fill_blank,
        prompt="Look at the image and answer yes or no.",
        expected_text="yes",
        metadata={
            "multimodal": {
                "schema_version": "evalclaw.multimodal.v1",
                "modalities": ["image"],
                "assets": [
                    {
                        "id": "image_1",
                        "kind": "image",
                        "uri": "data:image/svg+xml;base64,PHN2Zy8+",
                        "mime_type": "image/svg+xml",
                    }
                ],
            }
        },
    )
    suite = TaskSuite(spec=spec, objective=spec.objective, tasks=[item])
    qc_report = QcReport(passed_item_ids=[item.id])
    config = BenchmarkConfig(
        targets=[TargetModelConfig(provider="deepseek", model="deepseek-chat", api_key="dummy")],
        run_targets=True,
    )

    with pytest.raises(ValueError, match="Multimodal item\\(s\\): vision_item"):
        run_eval(suite, qc_report, config)
