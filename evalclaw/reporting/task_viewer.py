"""Self-contained browser page for reading generated benchmark tasks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..types import BenchmarkPackage
from ._katex_assets import inject_katex
from .task_viewer_template import HTML_TEMPLATE


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _definition_value(item: Any, name: str, fallback: Any = None) -> Any:
    definition = getattr(item, "source_definition", None)
    value = getattr(definition, name, None) if definition is not None else None
    return _json_value(value) if value is not None else fallback


def _task_payload(pkg: BenchmarkPackage) -> dict[str, Any]:
    dimensions = {
        dimension.id: {
            "name": dimension.name,
            "description": dimension.description,
        }
        for dimension in pkg.suite.dimensions
    }
    tasks: list[dict[str, Any]] = []
    for index, item in enumerate(pkg.suite.tasks, 1):
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        source = item.source.model_dump(mode="json")
        dimension = dimensions.get(item.dimension_id, {})
        title = (
            _definition_value(item, "title")
            or source.get("title")
            or metadata.get("title")
            or f"Task {index}"
        )
        description = (
            _definition_value(item, "description")
            or source.get("notes")
            or ""
        )
        content_summary = (
            _definition_value(item, "content_summary")
            or metadata.get("task_content_summary")
            or ""
        )
        environment = _definition_value(item, "environment")
        if not environment and isinstance(metadata.get("agent_env"), dict):
            environment = metadata["agent_env"]
        task_agent = metadata.get("task_agent") if isinstance(metadata.get("task_agent"), dict) else {}
        scoring = _definition_value(item, "scoring") or task_agent.get("scoring") or {}
        interaction = _definition_value(item, "interaction") or task_agent.get("interaction") or {}
        tasks.append(
            {
                "number": index,
                "id": item.id,
                "dimension_id": item.dimension_id,
                "dimension_name": dimension.get("name") or item.dimension_id,
                "task_type": item.task_type.value,
                "title": str(title),
                "content_summary": str(content_summary),
                "description": str(description),
                "prompt": item.prompt,
                "assets": [asset.model_dump(mode="json") for asset in item.assets],
                "choices": [choice.model_dump(mode="json") for choice in item.choices],
                "correct_choice_ids": list(item.correct_choice_ids),
                "expected_text": item.expected_text,
                "rubric": item.rubric,
                "judge_tools": [tool.model_dump(mode="json") for tool in item.judge_tools],
                "output_contract": item.output_contract,
                "system_prompt": _definition_value(item, "system_prompt") or task_agent.get("system_prompt") or "",
                "interaction": interaction,
                "scoring": scoring,
                "environment": environment or {},
                "source": source,
                "resource_ids": _definition_value(item, "resource_ids") or [],
                "challenge_effort": item.challenge_effort.value,
                "tags": list(item.tags),
            }
        )
    return {
        "title": pkg.spec.id,
        "objective": pkg.goal or pkg.suite.objective or pkg.spec.objective,
        "tasks": tasks,
    }


def build_task_viewer_html(pkg: BenchmarkPackage) -> str:
    """Build the standalone task-browsing HTML document."""
    payload = json.dumps(_task_payload(pkg), ensure_ascii=False)
    payload = payload.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return inject_katex(HTML_TEMPLATE.replace("__PAYLOAD__", payload))


def write_task_viewer(pkg: BenchmarkPackage, html_path: Path) -> Path:
    html_path.write_text(build_task_viewer_html(pkg), encoding="utf-8")
    return html_path


__all__ = ["build_task_viewer_html", "write_task_viewer"]
