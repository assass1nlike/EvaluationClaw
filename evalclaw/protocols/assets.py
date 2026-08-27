"""Task asset validation and provider-native image input builders."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from ..types import BenchmarkItem, TaskAsset


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
    "environment_asset_guest_path",
    "environment_asset_sources",
]
