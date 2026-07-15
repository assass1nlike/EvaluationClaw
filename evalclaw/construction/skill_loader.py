"""Load only the environment-construction Skill references a Blueprint needs."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..types import TaskBlueprint, TaskDesign, TaskType

_SKILL_DIR = Path(__file__).parent / "skills" / "build-environment-tasks"
_CATEGORY_ROUTES = {
    "dialogue": ("dialogue", "references/dialogue.md"),
    "workspace": ("workspace", "references/workspace.md"),
    "code_sandbox": ("code_sandbox", "references/code-sandbox.md"),
    "code sandbox": ("code_sandbox", "references/code-sandbox.md"),
    "container": ("docker_workspace", "references/docker-workspace.md"),
    "docker_workspace": ("docker_workspace", "references/docker-workspace.md"),
    "browser": ("gui_desktop", "references/gui-desktop.md"),
    "desktop": ("gui_desktop", "references/gui-desktop.md"),
    "gui_desktop": ("gui_desktop", "references/gui-desktop.md"),
}
_REFERENCE_ORDER = [
    "references/dialogue.md",
    "references/workspace.md",
    "references/code-sandbox.md",
    "references/docker-workspace.md",
    "references/gui-desktop.md",
    "references/task-agent.md",
    "references/agent-task-package.md",
]


@lru_cache(maxsize=None)
def _read_skill_file(relative_path: str) -> str:
    path = _SKILL_DIR / relative_path
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Task Builder environment Skill file is empty: {path}")
    return text


def _design_route(design: TaskDesign) -> dict[str, object] | None:
    category = str(design.environment_requirements.get("category") or "").strip().lower()
    routed = _CATEGORY_ROUTES.get(category)
    if routed is None:
        return None
    runtime_type, environment_reference = routed
    references = [environment_reference]
    interaction_mode = str(design.interaction_requirements.get("mode") or "").strip().lower()
    if (
        runtime_type == "dialogue"
        or design.task_type == TaskType.multi_turn
        or interaction_mode in {"multi_turn", "mixed"}
    ):
        references.append("references/task-agent.md")
    if (
        runtime_type in {"docker_workspace", "gui_desktop"}
        or bool(design.environment_requirements.get("requires_vm"))
        or bool(design.environment_requirements.get("vm"))
    ):
        references.append("references/agent-task-package.md")
    return {
        "task_design_id": design.id,
        "runtime_environment_type": runtime_type,
        "references": references,
    }


def environment_skill_payload(blueprint: TaskBlueprint) -> dict[str, object] | None:
    routes: list[dict[str, object]] = []
    unrouted: list[str] = []
    for design in blueprint.task_designs:
        if not design.environment_requirements:
            continue
        route = _design_route(design)
        if route is None:
            unrouted.append(design.id)
        else:
            routes.append(route)
    if unrouted:
        raise ValueError(
            "Environment-backed TaskDesigns have no supported Skill route: "
            + ", ".join(unrouted)
        )
    if not routes:
        return None
    selected = {
        reference
        for route in routes
        for reference in route["references"]
        if isinstance(reference, str)
    }
    loaded_references = [reference for reference in _REFERENCE_ORDER if reference in selected]
    return {
        "applies_to_task_design_ids": [route["task_design_id"] for route in routes],
        "loaded_references": loaded_references,
        "routing": routes,
    }


def environment_skill_system_prompt(blueprint: TaskBlueprint) -> str:
    payload = environment_skill_payload(blueprint)
    if payload is None:
        return ""
    parts = [
        "<ACTIVE_EVALCLAW_TASK_BUILDER_SKILL>\n"
        + _read_skill_file("SKILL.md")
        + "\n</ACTIVE_EVALCLAW_TASK_BUILDER_SKILL>",
        "<ENVIRONMENT_SKILL_ROUTING>\n"
        + json.dumps(payload["routing"], ensure_ascii=False, indent=2)
        + "\n</ENVIRONMENT_SKILL_ROUTING>",
    ]
    for reference in payload["loaded_references"]:
        if isinstance(reference, str):
            parts.append(
                f'<REFERENCE_FILE path="{reference}">\n'
                + _read_skill_file(reference)
                + "\n</REFERENCE_FILE>"
            )
    return "\n\n".join(parts)


__all__ = ["environment_skill_payload", "environment_skill_system_prompt"]
