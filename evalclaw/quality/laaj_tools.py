"""Read-only benchmark-content tools for LLM-as-a-Judge evaluation."""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from ..diagnostics import redact_secrets
from ..protocols.tool import ToolCall, ToolResult, ToolSpec
from ..types import BenchmarkItem, TaskSuite

_DEFAULT_MAX_CHARS = 50_000
_MAX_CHARS = 200_000
_VIEWABLE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

LAAJ_INSPECT_AGENT_TOOL = ToolSpec(
    name="inspect_agent_environment",
    description=(
        "Inspect the complete non-file contract for one or more sampled agent tasks, including "
        "actor roles and permissions, execution limits, evaluator configuration, workflow, and "
        "the originating TaskDesign. File contents are listed separately and can be read with "
        "read_task_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 50,
            },
            "offset": {"type": "integer", "minimum": 0},
            "max_chars": {
                "type": "integer",
                "minimum": 100,
                "maximum": _MAX_CHARS,
            },
        },
        "required": ["item_ids"],
        "additionalProperties": False,
    },
)

LAAJ_READ_TASK_FILE_TOOL = ToolSpec(
    name="read_task_file",
    description=(
        "Read a declared text file from a sampled agent task. Areas visible, runtime, and hidden "
        "refer to agent_env; session refers to session.asset_files; image_build refers to "
        "image_build.context_files; asset refers to a top-level task asset. "
        "definition reads any complete task field via a JSON Pointer (empty path reads the full definition)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "minLength": 1},
            "area": {
                "type": "string",
                "enum": ["visible", "runtime", "hidden", "session", "image_build", "asset", "definition"],
            },
            "path": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0},
            "max_chars": {
                "type": "integer",
                "minimum": 100,
                "maximum": _MAX_CHARS,
            },
        },
        "required": ["item_id", "area", "path"],
        "additionalProperties": False,
    },
)

LAAJ_VIEW_IMAGE_TOOL = ToolSpec(
    name="view_benchmark_image",
    description=(
        "Attach a declared task image or a saved run screenshot to the next LaaJ turn for visual "
        "inspection. Run artifacts must stay inside the current run directory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["task_asset", "run_artifact"]},
            "path": {"type": "string", "minLength": 1},
            "item_id": {
                "type": "string",
                "description": "Required for task_asset; omit for run_artifact.",
            },
        },
        "required": ["source", "path"],
        "additionalProperties": False,
    },
)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _page(text: str, offset: int, max_chars: int) -> dict[str, Any]:
    content = text[offset : offset + max_chars]
    truncated = offset + len(content) < len(text)
    return {
        "content": content,
        "offset": offset,
        "truncated": truncated,
        "next_offset": offset + len(content) if truncated else None,
    }


def _item_map(suite: TaskSuite) -> dict[str, BenchmarkItem]:
    return {item.id: item for item in suite.tasks}


def _agent_env(item: BenchmarkItem) -> dict[str, Any]:
    env = item.metadata.get("agent_env")
    if isinstance(env, dict):
        return env
    if item.source_definition is not None and item.source_definition.environment is not None:
        return item.source_definition.environment.model_dump(mode="json")
    return {}


def _file_manifest(files: Any) -> list[dict[str, Any]]:
    if not isinstance(files, dict):
        return []
    return [
        {"path": str(path), "characters": len(str(content or ""))}
        for path, content in files.items()
    ]


def _session_files(session: Any) -> dict[str, Any]:
    if not isinstance(session, dict):
        return {}
    files: dict[str, Any] = {}
    for key in ("files", "input_files", "asset_files"):
        value = session.get(key)
        if isinstance(value, dict):
            files.update(value)
    assets = session.get("assets")
    if isinstance(assets, dict):
        files.update(assets)
    elif isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            path = asset.get("path") or asset.get("guest_path") or asset.get("filename") or asset.get("name")
            if path and "content" in asset:
                files[str(path)] = asset["content"]
            elif path and "text" in asset:
                files[str(path)] = asset["text"]
    return files


def _task_agent(item: BenchmarkItem) -> dict[str, Any]:
    value = item.metadata.get("task_agent")
    return value if isinstance(value, dict) else {}


def _declared_files(item: BenchmarkItem, area: str) -> dict[str, Any]:
    env = _agent_env(item)
    task_agent = _task_agent(item)
    initial = task_agent.get("initial_content")
    initial = initial if isinstance(initial, dict) else {}
    files: dict[str, Any] = {}
    if area == "visible":
        for value in (env.get("visible_files"), env.get("files"), initial.get("files")):
            if isinstance(value, dict):
                files.update(value)
    elif area in {"runtime", "hidden"}:
        value = env.get(f"{area}_files")
        if isinstance(value, dict):
            files.update(value)
    elif area == "session":
        files.update(_session_files(env.get("session")))
        files.update(_session_files(initial.get("session")))
    elif area == "image_build":
        image_build = env.get("image_build")
        value = image_build.get("context_files") if isinstance(image_build, dict) else None
        if isinstance(value, dict):
            files.update(value)
    return files


def _task_design(suite: TaskSuite, item: BenchmarkItem) -> dict[str, Any] | None:
    for blueprint in suite.blueprints:
        for design in blueprint.task_designs:
            if design.id == item.task_design_id:
                return design.model_dump(mode="json")
    return None


def agent_environment_overview(item: BenchmarkItem) -> dict[str, Any]:
    """Return a compact inventory without embedding task file contents."""
    env = _agent_env(item)
    if not env:
        return {"available": False}
    actors = env.get("actors") if isinstance(env.get("actors"), list) else []
    session = env.get("session") if isinstance(env.get("session"), dict) else {}
    image_build = env.get("image_build") if isinstance(env.get("image_build"), dict) else {}
    evaluation = env.get("evaluation") if isinstance(env.get("evaluation"), dict) else {}
    browser = env.get("browser") if isinstance(env.get("browser"), dict) else {}
    vm = env.get("vm") if isinstance(env.get("vm"), dict) else {}
    setup_commands = env.get("setup_commands")
    return redact_secrets({
        "available": True,
        "type": env.get("type"),
        "image": env.get("image"),
        "network": env.get("network"),
        "workdir": env.get("workdir"),
        "max_steps": env.get("max_steps"),
        "timeout": env.get("timeout"),
        "test_command": env.get("test_command"),
        "judge": {"mode": env["judge"].get("mode", "judge"),
                  "criterion_ids": [c.get("id") for c in env["judge"].get("criteria", [])]}
        if isinstance(env.get("judge"), dict) else None,
        "setup_command_count": len(setup_commands) if isinstance(setup_commands, list) else 0,
        "evaluation_keys": list(evaluation),
        "session_keys": list(session),
        "browser_keys": list(browser),
        "vm_keys": list(vm),
        "image_build_keys": list(image_build),
        "files": {
            area: _file_manifest(_declared_files(item, area))
            for area in ("visible", "runtime", "hidden", "session", "image_build")
        },
        "assets": [
            {
                "path": Path(asset.path).name,
                "media_type": mimetypes.guess_type(asset.path)[0] or "application/octet-stream",
                "size_bytes": Path(asset.path).stat().st_size if Path(asset.path).is_file() else None,
            }
            for asset in item.assets
        ],
        "actors": [
            {
                "id": actor.get("id"),
                "description": actor.get("description"),
                "toolset": actor.get("toolset"),
            }
            for actor in actors
            if isinstance(actor, dict)
        ],
        "actor_toolset_names": sorted(env.get("actor_toolsets", {})),
        "requires_inspection": True,
    })


def _environment_contract(suite: TaskSuite, item: BenchmarkItem) -> dict[str, Any]:
    if item.content is not None:
        from ..protocols.task_view import definition_view
        return redact_secrets(definition_view(item))
    environment = json.loads(json.dumps(_agent_env(item)))
    for key, area in (
        ("visible_files", "visible"),
        ("runtime_files", "runtime"),
        ("hidden_files", "hidden"),
    ):
        if key in environment:
            environment[key] = {"area": area, "files": _file_manifest(environment[key])}
    for parent, key, area in (
        ("session", "asset_files", "session"),
        ("image_build", "context_files", "image_build"),
    ):
        container = environment.get(parent)
        if isinstance(container, dict) and key in container:
            container[key] = {"area": area, "files": _file_manifest(container[key])}

    task_agent = json.loads(json.dumps(_task_agent(item))) or None
    if isinstance(task_agent, dict):
        initial = task_agent.get("initial_content")
        if isinstance(initial, dict) and "files" in initial:
            initial["files"] = {
                "area": "visible",
                "files": _file_manifest(initial["files"]),
            }
        if isinstance(initial, dict) and isinstance(initial.get("session"), dict):
            session = initial["session"]
            for key in ("files", "input_files", "asset_files", "assets"):
                if key in session:
                    session[key] = {
                        "area": "session",
                        "files": _file_manifest(_session_files({key: session[key]})),
                    }

    definition = item.source_definition
    builder_contract = None
    if definition is not None:
        builder_contract = definition.model_dump(
            mode="json",
            include={"title", "description", "system_prompt", "interaction", "scoring", "workflow"},
        )
    return redact_secrets({
        "id": item.id,
        "environment": environment,
        "task_agent": task_agent,
        "agent_task_package": item.metadata.get("agent_task_package"),
        "workflow": item.workflow.model_dump(mode="json") if item.workflow is not None else None,
        "builder_contract": builder_contract,
        "task_design": _task_design(suite, item),
        "asset_files": agent_environment_overview(item).get("assets", []),
    })


def inspect_agent_environment(call: ToolCall, suite: TaskSuite) -> ToolResult:
    if call.name != LAAJ_INSPECT_AGENT_TOOL.name:
        return ToolResult(
            tool_call_id=call.id, name=call.name, content="Unknown LaaJ tool.", error="unknown_tool"
        )
    args = call.arguments if isinstance(call.arguments, dict) else {}
    requested = args.get("item_ids")
    if not isinstance(requested, list) or not requested:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="item_ids must be a non-empty list.",
            error="invalid_arguments",
        )
    items = _item_map(suite)
    missing = [str(item_id) for item_id in requested if str(item_id) not in items]
    if missing:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="Unknown item ids: " + ", ".join(missing),
            error="item_not_found",
        )
    payload = [_environment_contract(suite, items[str(item_id)]) for item_id in requested]
    text = json.dumps(payload, ensure_ascii=False)
    offset = _bounded_int(args.get("offset"), default=0, minimum=0, maximum=len(text))
    max_chars = _bounded_int(
        args.get("max_chars"), default=_DEFAULT_MAX_CHARS, minimum=100, maximum=_MAX_CHARS
    )
    return ToolResult(
        tool_call_id=call.id,
        name=call.name,
        content=json.dumps(_page(text, offset, max_chars), ensure_ascii=False),
    )


def _declared_text(item: BenchmarkItem, area: str, path: str) -> str | None:
    if area == "definition":
        from ..protocols.task_view import definition_text
        return definition_text(item, path)
    if area != "asset":
        value = _declared_files(item, area).get(path)
        if value is None:
            return None
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    asset = next(
        (
            asset
            for asset in item.assets
            if path in {asset.id, asset.path, Path(asset.path).name}
        ),
        None,
    )
    if asset is None:
        return None
    try:
        from ..execution.components import asset_bytes
        return asset_bytes(asset).decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        return None


def read_task_file(call: ToolCall, suite: TaskSuite) -> ToolResult:
    if call.name != LAAJ_READ_TASK_FILE_TOOL.name:
        return ToolResult(
            tool_call_id=call.id, name=call.name, content="Unknown LaaJ tool.", error="unknown_tool"
        )
    args = call.arguments if isinstance(call.arguments, dict) else {}
    item_id = str(args.get("item_id") or "")
    area = str(args.get("area") or "")
    path = str(args.get("path") or "")
    item = _item_map(suite).get(item_id)
    if item is None:
        return ToolResult(
            tool_call_id=call.id, name=call.name, content="Unknown item id.", error="item_not_found"
        )
    try:
        content = _declared_text(item, area, path)
    except (KeyError, IndexError, TypeError, ValueError):
        content = None
    if content is None:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="The requested declared text file does not exist or is not UTF-8 text.",
            error="task_file_not_found",
        )
    content = str(redact_secrets(content))
    offset = _bounded_int(args.get("offset"), default=0, minimum=0, maximum=len(content))
    max_chars = _bounded_int(
        args.get("max_chars"), default=_DEFAULT_MAX_CHARS, minimum=100, maximum=_MAX_CHARS
    )
    payload = {"item_id": item_id, "area": area, "path": path, **_page(content, offset, max_chars)}
    return ToolResult(
        tool_call_id=call.id,
        name=call.name,
        content=json.dumps(payload, ensure_ascii=False),
    )


def _declared_asset(item: BenchmarkItem, raw_path: str) -> Path | None:
    for asset in item.assets:
        if raw_path not in {asset.path, Path(asset.path).name}:
            continue
        candidate = Path(asset.path).expanduser().resolve()
        return candidate if candidate.is_file() else None
    return None


def view_benchmark_image(
    call: ToolCall,
    suite: TaskSuite,
    artifact_dir: Path | None,
) -> ToolResult:
    if call.name != LAAJ_VIEW_IMAGE_TOOL.name:
        return ToolResult(
            tool_call_id=call.id, name=call.name, content="Unknown LaaJ tool.", error="unknown_tool"
        )
    args = call.arguments if isinstance(call.arguments, dict) else {}
    source = str(args.get("source") or "")
    raw_path = str(args.get("path") or "")
    try:
        if source == "task_asset":
            item = _item_map(suite).get(str(args.get("item_id") or ""))
            path = _declared_asset(item, raw_path) if item is not None else None
        elif source == "run_artifact" and artifact_dir is not None:
            root = artifact_dir.resolve()
            candidate = (root / raw_path).resolve()
            path = candidate if candidate.is_relative_to(root) and candidate.is_file() else None
        else:
            path = None
        if path is None:
            raise ValueError("Image must be a declared task asset or a file inside the current run.")
        media_type = mimetypes.guess_type(path.name)[0] or ""
        if media_type not in _VIEWABLE_IMAGE_TYPES:
            raise ValueError("Only PNG, JPEG, GIF, and WebP images can be viewed.")
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=json.dumps({
                "path": raw_path,
                "media_type": media_type,
                "size_bytes": path.stat().st_size,
                "status": "attached to the next model turn",
            }),
            raw={"image_path": str(path), "media_type": media_type},
        )
    except (OSError, ValueError) as exc:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Could not view image: {type(exc).__name__}: {exc}",
            error="image_unavailable",
        )


__all__ = [
    "LAAJ_INSPECT_AGENT_TOOL",
    "LAAJ_READ_TASK_FILE_TOOL",
    "LAAJ_VIEW_IMAGE_TOOL",
    "agent_environment_overview",
    "inspect_agent_environment",
    "read_task_file",
    "view_benchmark_image",
]
