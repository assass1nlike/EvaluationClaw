"""Small helpers for durable, redacted pipeline diagnostics."""
from __future__ import annotations

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
