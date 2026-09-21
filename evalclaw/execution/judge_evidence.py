"""Bounded judge inputs with addressable, complete scoring evidence."""
from __future__ import annotations

import json


def evidence_view(value, path="", *, budget=24000):
    def compact(node, pointer, allowance):
        text = json.dumps(node, ensure_ascii=False)
        if len(text) <= min(4000, allowance):
            return node
        location = {"evidence_path": pointer, "characters": len(text)}
        if isinstance(node, dict):
            location["keys_preview"] = list(node)[:20]
            location["key_count"] = len(node)
        elif isinstance(node, list):
            location["items"] = len(node)
        if allowance < 1000:
            return location
        if isinstance(node, str):
            location["excerpt"] = node[:min(2000, allowance // 2)]
        elif isinstance(node, dict):
            keys = list(node)[:20]
            location["preview"] = {key: compact(node[key], pointer + "/" + key.replace("~", "~0").replace("/", "~1"),
                                               allowance // (len(keys) + 1)) for key in keys}
        elif isinstance(node, list):
            indices = list(range(min(8, len(node))))
            if len(node) > 8:
                indices.append(len(node) - 1)
            location["preview"] = {str(i): compact(node[i], pointer + f"/{i}", allowance // (len(indices) + 1)) for i in indices}
        if len(json.dumps(location, ensure_ascii=False)) > allowance:
            return {"evidence_path": pointer, "characters": len(text)}
        return location

    return compact(value, path, budget)


def evidence_page(payload, path, offset=0, limit=30000):
    if path and not path.startswith("/"):
        raise ValueError("path must be a JSON Pointer into task, episode, references or submission_contract")
    node = payload
    for part in path.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        node = node[int(key)] if isinstance(node, list) else node[key]
    text = node if isinstance(node, str) else json.dumps(node, ensure_ascii=False)
    return {"content": text[offset:offset + limit], "total_chars": len(text),
            "next_offset": offset + limit if offset + limit < len(text) else None}
