from pathlib import Path

import pytest

from evalclaw.execution.runner import run_eval, run_item
from evalclaw.protocols.assets import target_supports_image_input
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    EvalSpec,
    QcReport,
    TargetModelConfig,
    TaskSuite,
    TaskType,
)


def _image_item(path: Path) -> BenchmarkItem:
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return BenchmarkItem(
        id="vision_item",
        dimension_id="vision_reasoning",
        task_type=TaskType.fill_blank,
        prompt=f"Look at {path} and answer yes or no.",
        assets=[{"path": str(path)}],
        expected_text="yes",
    )


def test_runner_sends_asset_content_to_target(monkeypatch, tmp_path: Path) -> None:
    item = _image_item(tmp_path / "image.png")
    config = BenchmarkConfig(
        targets=[TargetModelConfig(provider="openai", model="gpt-5", api_key="dummy")],
        run_targets=True,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "evalclaw.execution.runner._target_has_credentials",
        lambda *args, **kwargs: (True, "OPENAI_API_KEY"),
    )

    def fake_call_target_model(prompt, target, **kwargs):
        captured.update(kwargs)
        return "yes"

    monkeypatch.setattr("evalclaw.execution.runner.call_target_model", fake_call_target_model)

    result = run_item(item, config)

    assert result.score == 1.0
    assert isinstance(captured["user_content"], list)
    assert captured["user_content"][0]["type"] == "text"
    assert captured["user_content"][1] == {"type": "text", "text": f"Asset path: {item.assets[0].path}"}
    assert captured["user_content"][2]["type"] == "image_url"


def test_deepseek_target_rejects_image_asset(tmp_path: Path) -> None:
    item = _image_item(tmp_path / "image.png")
    config = BenchmarkConfig(
        targets=[
            TargetModelConfig(
                provider="openai_compatible",
                model="deepseek-chat",
                api_key="dummy",
            )
        ],
        run_targets=True,
    )

    with pytest.raises(ValueError, match="not known to support image input"):
        run_item(item, config)


def test_azure_vision_deployments_support_image_input() -> None:
    for deployment, expected in [
        ("azure/gpt-4o", True),
        ("azure/gpt-4o-mini", True),
        ("azure/gpt-5.5", True),
        ("azure/o4-mini", True),
        ("azure/DeepSeek-V3-0324", False),
    ]:
        target = TargetModelConfig(provider="azure", model=deployment, api_key="dummy")
        assert target_supports_image_input(target) is expected, deployment


def test_run_eval_reports_incompatible_asset_target(tmp_path: Path) -> None:
    item = _image_item(tmp_path / "image.png")
    suite = TaskSuite(spec=EvalSpec(objective="Evaluate image reasoning."), objective="Evaluate image reasoning.", tasks=[item])
    qc_report = QcReport(passed_item_ids=[item.id])
    config = BenchmarkConfig(
        targets=[TargetModelConfig(provider="deepseek", model="deepseek-chat", api_key="dummy")],
        run_targets=True,
    )

    with pytest.raises(ValueError, match=r"Asset item\(s\): vision_item"):
        run_eval(suite, qc_report, config)
