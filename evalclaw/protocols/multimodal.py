"""Standardized multimodal item metadata and provider-specific content builders."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from ..types import BenchmarkItem, TargetModelConfig

MULTIMODAL_METADATA_KEY = "multimodal"
MULTIMODAL_SCHEMA_VERSION = "evalclaw.multimodal.v1"
MULTIMODAL_KEYWORDS = (
    "multimodal",
    "vision",
    "visual",
    "image",
    "photo",
    "picture",
    "diagram",
    "chart",
    "plot",
    "screenshot",
    "ocr",
    "audio",
    "video",
)
MULTIMODAL_NEGATIVE_PATTERNS = (
    "no multimodal",
    "not multimodal",
    "without multimodal",
    "do not include any multimodal",
    "do not include multimodal",
    "no image",
    "no images",
    "without images",
    "code-only",
    "code only",
)

MULTIMODAL_SCHEMA: dict[str, Any] = {
    "schema_version": MULTIMODAL_SCHEMA_VERSION,
    "modalities": ["image"],
    "assets": [
        {
            "id": "image_1",
            "kind": "image",
            "uri": "https://example.com/image.png",
            "mime_type": "image/png",
            "caption": "Optional caption for generation and QC.",
            "alt_text": "Optional alt text for provider fallbacks.",
        }
    ],
    "content": [
        {"type": "text", "text": "Analyze the attached image and answer the question."},
        {"type": "asset", "asset_id": "image_1", "detail": "high"},
    ],
    "scoring": {
        "method": "judge_score",
        "rubric": "Score the answer against the visual evidence in the image.",
    },
}

MULTIMODAL_GENERATION_GUIDANCE = """\
If a dimension requires multimodal evaluation, the generation worker must emit
metadata.multimodal as a JSON object using schema_version evalclaw.multimodal.v1.

Required fields:
- schema_version: evalclaw.multimodal.v1
- modalities: ["image"] or ["image", "text"]; the current target adapter does not send audio or video natively
- assets: list of media assets with stable ids and source information
- content: ordered multimodal prompt parts; use text parts and asset references
- scoring: the scoring guidance for the item, including rubric or pass/fail rules

For image tasks, use asset kind "image" and include either a public URL, a data
URI, or a local file path that can be resolved by the runner. The text prompt
must explain what the model should inspect and what the answer should focus on.
If the item is multiple-choice or short-answer, keep the question text concise
and make sure the visual evidence is necessary for a correct answer.
"""


def text_requests_multimodal(text: str) -> bool:
    """Return whether text explicitly asks for non-text/modal input."""
    lowered = text.lower()
    if any(pattern in lowered for pattern in MULTIMODAL_NEGATIVE_PATTERNS):
        return False
    return any(keyword in lowered for keyword in MULTIMODAL_KEYWORDS)


def get_multimodal_spec(item: BenchmarkItem) -> dict[str, Any] | None:
    spec = item.metadata.get(MULTIMODAL_METADATA_KEY)
    return spec if isinstance(spec, dict) else None


def has_multimodal_assets(item: BenchmarkItem) -> bool:
    spec = get_multimodal_spec(item)
    if not spec:
        return False
    assets = spec.get("assets")
    return isinstance(assets, list) and any(isinstance(asset, dict) for asset in assets)


def target_supports_multimodal_input(target: TargetModelConfig) -> bool:
    """Return whether a target model is known to accept native multimodal input."""
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
            (
                "gpt-4o",
                "gpt-4.1",
                "gpt-5",
                "o3",
                "o4",
                "chatgpt-",
            )
        )
    if provider == "azure":
        # Azure deployments are user-named; match on the deployment segment
        # (model is stored as "azure/<deployment>").
        deployment = model.split("/", 1)[-1]
        return deployment.startswith(
            (
                "gpt-4o",
                "gpt-4.1",
                "gpt-4-turbo",
                "gpt-5",
                "o3",
                "o4",
                "chatgpt-",
            )
        )
    if provider in {"mistral"} or model.startswith(("pixtral-", "mistral-medium")):
        return True
    if provider == "openai_compatible":
        # Custom OpenAI-compatible gateways may point to vision-capable local or
        # hosted models. Known non-vision providers are handled above.
        return True
    return False


def multimodal_unsupported_reason(target: TargetModelConfig) -> str | None:
    if target_supports_multimodal_input(target):
        return None
    return (
        f"Target model '{target.id}' ({target.provider}/{target.model}) is not known to support "
        "native multimodal input. Choose a vision-capable target model, or remove multimodal "
        "requirements from this evaluation."
    )


def _asset_map(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = spec.get("assets")
    if not isinstance(assets, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, asset in enumerate(assets, 1):
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("id") or f"asset_{index}")
        result[asset_id] = asset
    return result


def _normalize_uri(asset: dict[str, Any]) -> str:
    uri = str(asset.get("uri") or asset.get("path") or asset.get("data_uri") or "").strip()
    return uri


def _asset_to_data_uri(asset: dict[str, Any]) -> str | None:
    uri = _normalize_uri(asset)
    if not uri:
        return None
    if uri.startswith("data:"):
        return uri
    if uri.startswith(("http://", "https://")):
        return uri
    path = Path(uri)
    if not path.exists() or not path.is_file():
        return None
    mime_type = str(asset.get("mime_type") or mimetypes.guess_type(path.name)[0] or "image/png")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{data}"


def _asset_to_text_fallback(asset: dict[str, Any], asset_id: str) -> str:
    caption = str(asset.get("caption") or asset.get("alt_text") or "").strip()
    uri = _normalize_uri(asset)
    label = f"[{asset_id}]"
    if caption:
        return f"{label} {caption}"
    if uri:
        return f"{label} {uri}"
    return label


def _openai_image_block(asset: dict[str, Any], asset_id: str) -> dict[str, Any] | None:
    uri = _asset_to_data_uri(asset)
    if not uri:
        return None
    detail = str(asset.get("detail") or "auto")
    return {"type": "image_url", "image_url": {"url": uri, "detail": detail}}


def _anthropic_image_block(asset: dict[str, Any], asset_id: str) -> dict[str, Any] | None:
    uri = _asset_to_data_uri(asset)
    if not uri:
        return None
    if uri.startswith("data:"):
        header, data = uri.split(",", 1)
        mime_type = header[5:].split(";")[0] if ";" in header else "image/png"
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": data,
            },
        }
    return {
        "type": "image",
        "source": {"type": "url", "url": uri},
    }


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def build_multimodal_user_content(
    item: BenchmarkItem,
    prompt_text: str,
    provider: str,
) -> str | list[dict[str, Any]]:
    """Build provider-native user content for multimodal target calls."""
    spec = get_multimodal_spec(item)
    if not spec:
        return prompt_text

    provider_name = provider.lower()
    assets = _asset_map(spec)
    parts = spec.get("content")
    blocks: list[dict[str, Any]] = []

    if not isinstance(parts, list) or not parts:
        blocks.append(_text_block(prompt_text))
        for asset_id, asset in assets.items():
            if str(asset.get("kind") or "").lower() == "image":
                block = (
                    _anthropic_image_block(asset, asset_id)
                    if provider_name == "anthropic"
                    else _openai_image_block(asset, asset_id)
                )
                if block:
                    blocks.append(block)
                else:
                    blocks.append(_text_block(_asset_to_text_fallback(asset, asset_id)))
            else:
                blocks.append(_text_block(_asset_to_text_fallback(asset, asset_id)))
        return blocks if len(blocks) > 1 else prompt_text

    for index, part in enumerate(parts, 1):
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").lower()
        if part_type == "text":
            text = str(part.get("text") or "").strip()
            if text:
                blocks.append(_text_block(text))
        elif part_type == "asset":
            asset_id = str(part.get("asset_id") or part.get("assetId") or "").strip()
            asset = assets.get(asset_id)
            if asset is None:
                blocks.append(_text_block(f"[missing asset {asset_id or index}]"))
                continue
            kind = str(asset.get("kind") or "").lower()
            if kind == "image":
                block = (
                    _anthropic_image_block(asset, asset_id)
                    if provider_name == "anthropic"
                    else _openai_image_block(asset, asset_id)
                )
                if block:
                    blocks.append(block)
                else:
                    blocks.append(_text_block(_asset_to_text_fallback(asset, asset_id)))
            else:
                blocks.append(_text_block(_asset_to_text_fallback(asset, asset_id)))

    return blocks if len(blocks) > 1 else (blocks[0]["text"] if blocks else prompt_text)


def multimodal_metadata_issues(item: BenchmarkItem) -> list[str]:
    spec = get_multimodal_spec(item)
    if not spec:
        return []
    issues: list[str] = []
    if str(spec.get("schema_version") or "") != MULTIMODAL_SCHEMA_VERSION:
        issues.append("metadata.multimodal.schema_version must be evalclaw.multimodal.v1.")
    modalities = spec.get("modalities")
    if not isinstance(modalities, list) or not modalities:
        issues.append("metadata.multimodal.modalities must be a non-empty list.")
    assets = spec.get("assets")
    if not isinstance(assets, list) or not assets:
        issues.append("metadata.multimodal.assets must be a non-empty list.")
    content = spec.get("content")
    if content is not None and not isinstance(content, list):
        issues.append("metadata.multimodal.content must be a list when provided.")
    return issues
