"""Small helpers for durable, redacted pipeline diagnostics."""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()
_SECRET_KEYS = ("api_key", "authorization", "access_token", "secret")
_SECRET_TEXT_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]+"),
    re.compile(r"(?i)\bBearer\s+[^\s,;]+"),
)


def _io_path(path: Path) -> Path:
    path = path.expanduser()
    if os.name != "nt":
        return path
    value = str(path.resolve())
    if value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def invocation_id() -> str:
    return (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )


def safe_name(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return normalized or "unknown"


def new_debug_dir(output_dir: str, section: str) -> Path | None:
    if not str(output_dir).strip():
        return None
    path = Path(output_dir).expanduser().resolve() / "debug" / section / invocation_id()
    _io_path(path).mkdir(parents=True, exist_ok=True)
    return path


def redact_secrets(value: Any) -> Any:
    if isinstance(value, str):
        if value.startswith("data:image/") and ";base64," in value:
            return value.split(",", 1)[0] + ",[OMITTED]"
        for pattern in _SECRET_TEXT_PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        return value
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(marker in str(key).lower() for marker in _SECRET_KEYS) and item
                else redact_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def write_json(path: Path, value: Any, *, redact: bool = False) -> None:
    payload = redact_secrets(value) if redact else value
    io_path = _io_path(path)
    io_path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        io_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


def write_text(path: Path, value: str, *, append: bool = False) -> None:
    io_path = _io_path(path)
    io_path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        with io_path.open("a" if append else "w", encoding="utf-8") as handle:
            handle.write(value)


def deep_merge(base: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``base`` with ``partial`` merged in depth-first.

    dict values recurse; lists merge by index (an existing index recurses or
    overwrites, a beyond-end index appends); anything else overwrites.
    """
    result = copy.deepcopy(base)
    for key, value in partial.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            merged: list[Any] = result[key]
            for index, item in enumerate(value):
                if index < len(merged):
                    if isinstance(merged[index], dict) and isinstance(item, dict):
                        merged[index] = deep_merge(merged[index], item)
                    else:
                        merged[index] = copy.deepcopy(item)
                else:
                    merged.append(copy.deepcopy(item))
            result[key] = merged
        else:
            result[key] = copy.deepcopy(value)
    return result


def _split_document_path(path: str) -> list[str | int]:
    """Split a dot path like ``dimensions.0.name`` into ``["dimensions", 0, "name"]``."""
    parts: list[str | int] = []
    for segment in str(path).split("."):
        segment = segment.strip()
        if segment:
            parts.append(int(segment) if segment.isdigit() else segment)
    return parts


def document_get(document: Any, path: str) -> Any:
    node: Any = document
    for part in _split_document_path(path):
        if isinstance(node, list):
            if not isinstance(part, int) or part < 0 or part >= len(node):
                raise KeyError(f"index {part!r} out of range in path {path!r}")
            node = node[part]
        elif isinstance(node, dict):
            if part not in node:
                raise KeyError(f"key {part!r} missing in path {path!r}")
            node = node[part]
        else:
            raise KeyError(f"cannot descend into {node!r} via {part!r}")
    return node


def document_set(document: dict, path: str, value: Any) -> None:
    """Set a value at a dot path, creating intermediate dicts/lists as needed."""
    parts = _split_document_path(path)
    if not parts:
        raise ValueError("empty document path")
    node: Any = document
    for index, part in enumerate(parts[:-1]):
        nxt = parts[index + 1]
        if isinstance(part, int):
            while len(node) <= part:
                node.append([] if isinstance(nxt, int) else {})
            node = node[part]
        else:
            if part not in node or not isinstance(node[part], (dict, list)):
                node[part] = [] if isinstance(nxt, int) else {}
            node = node[part]
    last = parts[-1]
    if isinstance(last, int):
        while len(node) <= last:
            node.append(None)
        node[last] = value
    else:
        node[last] = value


def document_remove(document: dict, path: str) -> None:
    parts = _split_document_path(path)
    if not parts:
        raise ValueError("empty document path")
    node: Any = document
    for part in parts[:-1]:
        if isinstance(node, list):
            if not isinstance(part, int) or part < 0 or part >= len(node):
                raise KeyError(f"index {part!r} out of range in path {path!r}")
            node = node[part]
        elif isinstance(node, dict):
            node = node[part]
        else:
            raise KeyError(f"cannot descend into {node!r} via {part!r}")
    last = parts[-1]
    if isinstance(node, list) and isinstance(last, int):
        del node[last]
    elif isinstance(node, dict):
        del node[last]
    else:
        raise KeyError(f"cannot remove {last!r} from {node!r}")


def document_append(document: dict, path: str, value: Any) -> None:
    node: Any = document
    for part in _split_document_path(path):
        if isinstance(node, list):
            if not isinstance(part, int) or part < 0 or part >= len(node):
                raise KeyError(f"index {part!r} out of range in path {path!r}")
            node = node[part]
        elif isinstance(node, dict):
            node = node[part]
        else:
            raise KeyError(f"cannot descend into {node!r} via {part!r}")
    if not isinstance(node, list):
        raise ValueError(f"append target {path!r} is not a list")
    node.append(value)


def error_record(exc: BaseException) -> dict[str, str]:
    return {"error_type": type(exc).__name__, "error": str(exc)}


__all__ = [
    "error_record",
    "invocation_id",
    "new_debug_dir",
    "redact_secrets",
    "safe_name",
    "write_json",
    "write_text",
]
