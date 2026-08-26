"""Task asset validation and provider-native image input builders."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from ..types import BenchmarkItem, TargetModelConfig, TaskAsset


def is_image_asset(asset: TaskAsset) -> bool:
    mime_type = mimetypes.guess_type(asset.path)[0] or ""
    return mime_type.startswith("image/")


def target_supports_image_input(target: TargetModelConfig) -> bool:
    provider = target.provider.lower()
    model = target.model.lower()
    if provider in {"mock", "test"}:
        return True
    if provider == "deepseek" or model.startswith("deepseek-"):
        return False
    if provider in {"anthropic", "claude"} or model.startswith("claude-"):
        return True
    if provider in {"gemini", "google"} or model.startswith("gemini"):
        return True
    if provider == "openai":
        return model.startswith(
            ("gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4", "chatgpt-")
        )
    if provider == "azure":
        deployment = model.split("/", 1)[-1]
        return deployment.startswith(
            ("gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-5", "o3", "o4", "chatgpt-")
        )
    if provider == "mistral" or model.startswith(("pixtral-", "mistral-medium")):
        return True
    return provider == "openai_compatible"


def image_input_unsupported_reason(target: TargetModelConfig) -> str | None:
    if target_supports_image_input(target):
        return None
    return (
        f"Target model '{target.id}' ({target.provider}/{target.model}) is not known to support "
        "image input. Choose a vision-capable target model or remove the task assets."
    )


def _image_data_uri(asset: TaskAsset) -> str:
    path = Path(asset.path)
    if not path.is_file():
        raise ValueError(f"Asset path does not exist or is not a file: {asset.path!r}.")
    mime_type = mimetypes.guess_type(path.name)[0] or ""
    if not mime_type.startswith("image/"):
        raise ValueError(f"Native target calls support image assets only: {asset.path!r}.")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{data}"


def build_asset_user_content(
    item: BenchmarkItem,
    prompt_text: str,
    provider: str,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    for asset in item.assets:
        data_uri = _image_data_uri(asset)
        blocks.append({"type": "text", "text": f"Asset path: {asset.path}"})
        if provider.lower() in {"anthropic", "claude"}:
            header, data = data_uri.split(",", 1)
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": header[5:].split(";", 1)[0],
                        "data": data,
                    },
                }
            )
        else:
            blocks.append(
                {"type": "image_url", "image_url": {"url": data_uri, "detail": "auto"}}
            )
    return blocks


__all__ = [
    "build_asset_user_content",
    "image_input_unsupported_reason",
    "is_image_asset",
    "target_supports_image_input",
]
