"""Task asset validation and provider-native image input builders."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from ..types import BenchmarkItem, TaskAsset, TaskType


def environment_asset_guest_path(asset: TaskAsset) -> str:
    """Return the target-visible workspace path for one host-side task asset."""
    return Path(asset.path).name


def environment_asset_sources(assets: list[TaskAsset]) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for asset in assets:
        guest_path = environment_asset_guest_path(asset)
        if not guest_path:
            raise ValueError(f"Asset path has no filename: {asset.path!r}.")
        if guest_path in sources:
            raise ValueError(
                f"Environment asset filenames must be unique: {guest_path!r}."
            )
        sources[guest_path] = Path(asset.path)
    return sources


def is_image_asset_path(path: str | Path) -> bool:
    mime_type = mimetypes.guess_type(Path(path).name)[0] or ""
    return mime_type.startswith("image/")


def asset_label(index: int) -> str:
    return f"Image {index}"


def replace_non_agent_asset_references(text: str, assets: list[TaskAsset]) -> str:
    """Replace host-side asset references with stable labels for native tasks."""
    replacements: list[tuple[str, str]] = []
    basenames: dict[str, int] = {}
    for asset in assets:
        basename = Path(asset.path.strip()).name
        if basename:
            basenames[basename] = basenames.get(basename, 0) + 1
    for index, asset in enumerate(assets, 1):
        path = asset.path.strip()
        if not path:
            continue
        label = asset_label(index)
        replacements.append((path, label))
        basename = Path(path).name
        if basename and basenames.get(basename) == 1 and basename != path:
            replacements.append((basename, label))
    for reference, label in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(reference, label)
    return text


def replace_agent_asset_references(text: str, assets: list[TaskAsset]) -> str:
    """Replace host-side asset references with their environment-visible paths."""
    replacements: list[tuple[str, str]] = []
    for asset in assets:
        path = asset.path.strip()
        if not path:
            continue
        guest_path = environment_asset_guest_path(asset)
        replacements.append((path, guest_path))
        basename = Path(path).name
        if basename and basename != path:
            replacements.append((basename, guest_path))
    for reference, guest_path in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(reference, guest_path)
    return text


def _image_data_uri(asset: TaskAsset) -> str:
    path = Path(asset.path)
    if not path.is_file():
        raise ValueError(f"Asset path does not exist or is not a file: {asset.path!r}.")
    mime_type = mimetypes.guess_type(path.name)[0] or ""
    if not is_image_asset_path(path):
        raise ValueError(f"Native target calls support image assets only: {asset.path!r}.")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{data}"


def build_asset_user_content(
    item: BenchmarkItem,
    prompt_text: str,
    provider: str,
) -> list[dict[str, Any]]:
    is_agent = item.task_type == TaskType.agent
    visible_prompt = (
        replace_agent_asset_references(prompt_text, item.assets)
        if is_agent
        else replace_non_agent_asset_references(prompt_text, item.assets)
    )
    blocks: list[dict[str, Any]] = [{"type": "text", "text": visible_prompt}]
    for index, asset in enumerate(item.assets, 1):
        data_uri = _image_data_uri(asset)
        reference = (
            environment_asset_guest_path(asset)
            if is_agent
            else asset_label(index)
        )
        blocks.append({"type": "text", "text": reference})
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
    "asset_label",
    "build_asset_user_content",
    "environment_asset_guest_path",
    "environment_asset_sources",
    "is_image_asset_path",
    "replace_agent_asset_references",
    "replace_non_agent_asset_references",
]
