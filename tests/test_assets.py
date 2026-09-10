from pathlib import Path

from evalclaw.execution.runner import run_item
from evalclaw.protocols.assets import build_asset_user_content
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkItem,
    TargetModelConfig,
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
        expected_texts=["yes"],
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
    assert captured["user_content"][0]["text"] == "Look at Image 1 and answer yes or no."
    assert captured["user_content"][1] == {"type": "text", "text": "Image 1"}
    assert captured["user_content"][2]["type"] == "image_url"


def test_agent_asset_content_uses_environment_filename(tmp_path: Path) -> None:
    image_path = tmp_path / "private" / "scene.png"
    image_path.parent.mkdir()
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    item = BenchmarkItem(
        id="agent_item",
        dimension_id="vision",
        task_type=TaskType.agent,
        prompt=f"Inspect {image_path}.",
        assets=[{"path": str(image_path)}],
    )

    content = build_asset_user_content(item, item.prompt, "openai")

    assert str(image_path) not in content[0]["text"]
    assert content[0]["text"] == "Inspect scene.png."
    assert content[1] == {"type": "text", "text": "scene.png"}
