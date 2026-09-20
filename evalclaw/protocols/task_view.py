"""Bounded review views with exact paths to the complete definition."""
from __future__ import annotations

import json
import hashlib


def task_revision(task):
    """Bind a review to the full saved definition, including legacy runtime metadata."""
    from ..types import BenchmarkItem
    item = task if isinstance(task, BenchmarkItem) else BenchmarkItem.model_validate(task)
    value = json.dumps(item.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def definition_data(task):
    return task.model_dump(mode="json", exclude={"source", "provenance", "metadata"}, exclude_defaults=True)


def definition_text(task, pointer=""):
    value = definition_data(task)
    if pointer and not pointer.startswith("/"):
        raise ValueError("Definition path must be a JSON Pointer")
    for part in pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def definition_view(task):
    def compact(value, pointer="", files=False):
        if isinstance(value, dict):
            return {k: compact(v, pointer + "/" + k.replace("~", "~0").replace("/", "~1"),
                               k in {"files", "visible_files", "hidden_files", "runtime_files", "context_files"})
                    for k, v in value.items()} if not files else {
                        k: {"characters": len(str(v)), "definition_path": pointer + "/" + k.replace("~", "~0").replace("/", "~1")}
                        for k, v in value.items()}
        if isinstance(value, list):
            return [compact(v, pointer + f"/{i}") for i, v in enumerate(value)]
        if isinstance(value, str) and len(value) > 12000:
            return {"excerpt": value[:6000] + "\n[excerpt]\n" + value[-2000:],
                    "characters": len(value), "definition_path": pointer}
        return value
    return {**compact(definition_data(task)), "complete_definition": {
        "tool": "read_task_file", "area": "definition", "path": "",
        "note": "Paths are JSON Pointers into the complete definition; read pages as needed. Analyzer can also use read_item_evidence(kind=task)."}}
