"""Bounded tools for TaskBuilder construction."""
from __future__ import annotations

import base64
import copy
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import CancelledError
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..diagnostics import write_json
from ..execution.docker_images import (
    build_docker_image_from_context,
    run_docker_image_check,
    safe_context_path,
)
from ..execution.vm_provider import build_vm_image
from ..models.llm import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    LLMFinalContentMissingError,
    LLMOutputTruncatedError,
    TargetToolModelResponse,
    call_llm,
    call_orchestrator_with_tools,
)
from ..models.roles import role_model_settings
from ..prompts.task_builder import TASK_BUILDER_TRUNCATION_SUMMARY_PROMPT
from ..protocols.tool import ToolCall, ToolResult, ToolSpec
from ..protocols.tool_adapters import (
    evalclaw_tool_result_to_anthropic,
    evalclaw_tool_result_to_openai,
    evalclaw_tool_result_to_openai_response_input,
)
from ..research.backends import download_url_file, fetch_url_text, web_search
from ..types import BenchmarkConfig, Message

_MAX_DOWNLOAD_URLS = 32
_MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
_PYTHON_TIMEOUT_SECONDS = 60
TASK_BUILDER_MAX_OUTPUT_TOKENS = 65_536
_MAX_IMAGE_BUILDS = 3
_MAX_IMAGE_CHECKS = 6
_MAX_IMAGE_CONTEXT_FILES = 128
_MAX_IMAGE_CONTEXT_BYTES = 256 * 1024 * 1024
_MAX_IMAGE_CHECK_COMMAND_CHARS = 4000
_IMAGE_GENERATION_TIMEOUT_SECONDS = 600
_MAX_GENERATED_IMAGE_BYTES = 64 * 1024 * 1024
_MAX_IMAGE_REFERENCE_FILES = 10
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_VIEWABLE_IMAGE_MEDIA_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}
_REFERENCE_IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}


class TaskBuilderTruncationSummaryError(RuntimeError):
    """TaskBuilder's interrupted work could not be compressed for retry."""


class TaskBuilderCallError(RuntimeError):
    """A TaskBuilder model call failed after its dedicated retry budget."""


# This prompt must explain when to use construction and source tools, where files
# belong, and that the Builder must return its complete response after tool use.
TASK_BUILDER_TOOL_PROMPT = """\
You may use the supplied tools when they materially improve task construction.
Use run_python for computation, validation, or creating and processing task files.
Save required task files in its fixed working directory. Tool results identify files
with host paths that are available only during construction. Asset paths in the final
response may use those host paths or paths relative to the fixed Builder job directory;
the framework resolves relative asset paths before validation and execution. For task-input files that
must be copied into a runtime workdir, put those host paths in the corresponding task's
top-level assets list. If a file belongs to the environment's declared initial visible
state, read the created file and put its literal contents in environment.visible_files
under the desired guest-relative path instead. Environment file-map values are file
contents, never the returned host path or a filename. For environment-backed tasks, the
framework copies each asset into the runtime workdir under its filename, so prompt or
choices must refer only to that filename; never copy a host path into target-visible text
or environment fields. For non-agent tasks, use only stable labels such as ``Image 1`` and
``Image 2`` in prompt or choices to refer to image assets; the framework attaches them in
assets-list order as multimodal inputs. Never expose host paths. For agent
tasks, refer to each asset by the path visible in the agent environment. When source tools are available, use read_research_source to
inspect text retained by Deep Research, search_web for a new query, fetch_url for
readable public HTTP(S) text, and download_files to persist public files. Do not
perform ceremonial tool calls, search for secrets, or use hidden evaluator content.
Use view_image when visual inspection of an image created or downloaded in the Builder
job directory is needed; the image will be attached to the next model turn. When
generate_image is available, use it to create required PNG task inputs in the Builder
job directory, put returned paths in the corresponding task's assets, and refer to them
according to the asset rules above. It accepts optional reference_paths containing up to
10 existing PNG, JPEG, or WebP files from the Builder job directory; use them when
reference images materially guide the requested generation. If you want images of the same
object from different angles, use reference images to keep details consistent across images.
After generating an image, inspect it with view_image to verify that its visible content
matches the intended task input before
using it. When container image construction
tools are available, use run_python to create or edit a
Dockerfile and its context files in the Builder job directory, then use build_image to
build and inspect that image. Use run_image_check for short dependency or startup
checks after a successful build. The build tool returns a relative image_build.context_dir;
preserve that value in the final task's environment.image_build together with
image_build.enabled=true and the image tag. Do not put host paths in target-visible
fields, and do not claim an image is ready without a successful build or check.
When VM image construction is available, use build_vm_image for GUI tasks that
need software or state unavailable in the base image. Its plan is executed and
checked inside an isolated temporary guest by the provider; preserve the
returned concrete image id in the task's environment.vm.image. Do not claim a
custom VM image is ready without a successful provider result.
During any repair request with revision.path, use run_python to edit the JSON file
at revision.path in place, then return a compact JSON confirmation. Otherwise,
return the complete task-builder JSON object after tool use. The tool budget is
bounded; stop once the task is adequately constructed.
"""


TASK_BUILDER_PYTHON_TOOL = ToolSpec(
    name="run_python",
    description=(
        "Run Python code in an isolated interpreter process whose working directory is the "
        "current Builder job's framework-managed asset directory. Use relative paths to create "
        "or process task files there."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "minLength": 1,
                "description": "Python source code to execute.",
            },
        },
        "required": ["code"],
        "additionalProperties": False,
    },
)


TASK_BUILDER_GENERATE_IMAGE_TOOL = ToolSpec(
    name="generate_image",
    description=(
        "Generate one PNG task-input image with the configured image model and save it "
        "inside the current Builder job directory. You may provide up to 10 existing "
        "PNG, JPEG, or WebP reference images from that directory. If you want images of "
        "the same object from different angles, use reference images to keep details "
        "consistent across images."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "minLength": 1,
                "description": "Complete image-generation prompt.",
            },
            "output_path": {
                "type": "string",
                "minLength": 5,
                "description": (
                    "Relative output path inside the Builder job directory; must end in .png."
                ),
            },
            "size": {
                "type": "string",
                "description": "Requested WIDTHxHEIGHT image size; defaults to 1024x1024.",
            },
            "reference_paths": {
                "type": "array",
                "maxItems": 10,
                "items": {
                    "type": "string",
                    "minLength": 1,
                },
                "description": (
                    "Optional paths to up to 10 existing PNG, JPEG, or WebP reference images "
                    "inside the current Builder job directory."
                ),
            },
        },
        "required": ["prompt", "output_path"],
        "additionalProperties": False,
    },
)


TASK_BUILDER_VIEW_IMAGE_TOOL = ToolSpec(
    name="view_image",
    description=(
        "Attach one image from the current Builder job directory to the next model "
        "turn for visual inspection. Supports PNG, JPEG, GIF, and WebP."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "Existing image path inside the Builder job directory.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)


TASK_BUILDER_IMAGE_TOOLS = [
    ToolSpec(
        name="build_image",
        description=(
            "Build a disposable Docker image from a Dockerfile and files in the current Builder job "
            "directory. The build context is persisted for the final task; use the returned relative "
            "image_build.context_dir in the task environment."
        ),
        parameters={
            "type": "object",
            "properties": {
                "dockerfile_path": {
                    "type": "string",
                    "description": "Relative path, or a path returned by run_python, to the Dockerfile.",
                },
                "context_files": {
                    "type": "array",
                    "maxItems": _MAX_IMAGE_CONTEXT_FILES,
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_path": {
                                "type": "string",
                                "description": "File in the current Builder job directory.",
                            },
                            "target_path": {
                                "type": "string",
                                "description": "Safe relative path for that file in the Docker build context.",
                            },
                        },
                        "required": ["source_path", "target_path"],
                        "additionalProperties": False,
                    },
                },
                "tag": {
                    "type": "string",
                    "description": "Optional local image tag. Omit it to use a content-derived tag.",
                },
                "build_args": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Optional Docker build arguments.",
                },
                "network": {
                    "type": "string",
                    "enum": ["default", "none"],
                    "description": "Network policy for Docker build steps; default is default.",
                },
                "timeout_s": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1200,
                    "description": "Maximum Docker build duration in seconds.",
                },
            },
            "required": ["dockerfile_path"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="run_image_check",
        description=(
            "Run one bounded shell check in the most recently built disposable image, or in the "
            "specified image. The container has no host mounts and uses no network by default."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Short command used to verify the image.",
                },
                "image": {
                    "type": "string",
                    "description": "Optional image tag; defaults to the most recently built image.",
                },
                "timeout_s": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 120,
                    "description": "Maximum check duration in seconds.",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    ),
]


TASK_BUILDER_VM_IMAGE_TOOLS = [
    ToolSpec(
        name="build_vm_image",
        description=(
            "Build and publish a reusable VM image through the configured remote VM provider. "
            "The provider executes the declarative plan inside an isolated temporary guest, "
            "runs the supplied checks, and returns a concrete image id only after success. "
            "Use this for GUI tasks that need software or state unavailable in the base image. "
            "Copy the returned image_id into environment.vm.image."
        ),
        parameters={
            "type": "object",
            "properties": {
                "base_image": {
                    "type": "object",
                    "description": (
                        "Provider-resolvable base image selector and requirements, for example "
                        "{guest_os, architecture, required_capabilities, image}."
                    ),
                    "additionalProperties": True,
                },
                "provisioning": {
                    "type": "object",
                    "description": (
                        "Guest setup plan: package lists, install_steps, commands, and OS-specific "
                        "provisioning fields supported by the VM provider."
                    ),
                    "additionalProperties": True,
                },
                "files": {
                    "type": "object",
                    "description": "Guest-relative paths mapped to literal file contents to install in the image.",
                    "additionalProperties": {"type": "string"},
                },
                "checks": {
                    "type": "array",
                    "minItems": 1,
                    "description": "Commands the provider must execute in the built guest before publishing it.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "minLength": 1},
                            "timeout_s": {"type": "integer", "minimum": 1, "maximum": 600},
                        },
                        "required": ["command"],
                        "additionalProperties": False,
                    },
                },
                "publish_name": {
                    "type": "string",
                    "description": "Optional provider-side name for the published image.",
                },
                "timeout_s": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3600,
                    "description": "Maximum provider build and verification duration in seconds.",
                },
            },
            "required": ["base_image", "provisioning", "checks"],
            "additionalProperties": False,
        },
    ),
]


TASK_BUILDER_SOURCE_TOOLS = [
    ToolSpec(
        name="read_research_source",
        description="Read source text retained by Deep Research without another network request.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL from source_material_index."},
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum retained text characters to return.",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="search_web",
        description=(
            "Search public web/research sources for authoritative benchmark patterns, "
            "realistic failure modes, software documentation, or task resources."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Focused search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of result summaries to retain.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="fetch_url",
        description="Fetch readable text from one public HTTP(S) URL for source-grounded task design.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Public HTTP(S) URL to inspect."},
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum text characters to return.",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="download_files",
        description=(
            "Download public HTTP(S) files into framework-managed benchmark assets. "
            "The response format is unrestricted; use direct file URLs rather than landing pages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": _MAX_DOWNLOAD_URLS,
                    "description": "Direct public HTTP(S) file URLs to download.",
                },
            },
            "required": ["urls"],
            "additionalProperties": False,
        },
    ),
]


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _tool_content(value: Any, *, max_chars: int) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    return encoded[:max_chars]


def _file_state(directory: Path) -> dict[Path, tuple[int, int]]:
    state: dict[Path, tuple[int, int]] = {}
    for path in directory.rglob("*"):
        if path.is_file():
            stat = path.stat()
            state[path] = (stat.st_size, stat.st_mtime_ns)
    return state


def task_builder_work_dir(config: BenchmarkConfig, builder_job_id: str) -> Path | None:
    if not str(config.output_dir).strip():
        return None
    safe_job_id = re.sub(r"[^A-Za-z0-9._-]+", "_", builder_job_id).strip("._")
    return (
        Path(config.output_dir).expanduser().resolve()
        / "assets"
        / "task-builder"
        / (safe_job_id or "task-builder")
    )


def _builder_file(work_dir: Path, raw_path: object) -> Path:
    root = work_dir.expanduser().resolve()
    candidate = Path(str(raw_path or "").strip()).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"Builder file must be an existing file inside the job directory: {raw_path!r}")
    return resolved


def _builder_image_output(work_dir: Path, raw_path: object) -> Path:
    root = work_dir.expanduser().resolve()
    candidate = Path(str(raw_path or "").strip())
    if not str(candidate) or candidate.is_absolute():
        raise ValueError("output_path must be a relative path inside the Builder job directory")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root) or resolved.suffix.lower() != ".png":
        raise ValueError("output_path must stay inside the Builder job directory and end in .png")
    return resolved


def _image_generation_configured(config: BenchmarkConfig) -> bool:
    return all(
        str(value or "").strip()
        for value in (
            config.image_generation_model,
            config.image_generation_api_key,
            config.image_generation_base_url,
        )
    )


def _viewable_image(work_dir: Path, raw_path: object) -> tuple[Path, str]:
    path = _builder_file(work_dir, raw_path)
    media_type = mimetypes.guess_type(path.name)[0] or ""
    if media_type not in _VIEWABLE_IMAGE_MEDIA_TYPES:
        raise ValueError("view_image supports PNG, JPEG, GIF, and WebP files")
    return path, media_type


def _generate_image_asset(
    config: BenchmarkConfig,
    work_dir: Path,
    *,
    prompt: str,
    output_path: object,
    size: str,
    reference_paths: object = None,
) -> dict[str, Any]:
    target = _builder_image_output(work_dir, output_path)
    raw_references = [] if reference_paths is None else reference_paths
    if not isinstance(raw_references, list):
        raise ValueError("reference_paths must be a list when provided")
    if len(raw_references) > _MAX_IMAGE_REFERENCE_FILES:
        raise ValueError(
            f"reference_paths must contain at most {_MAX_IMAGE_REFERENCE_FILES} images"
        )
    references: list[tuple[Path, str]] = []
    for raw_reference in raw_references:
        path = _builder_file(work_dir, raw_reference)
        media_type = mimetypes.guess_type(path.name)[0] or ""
        if media_type not in _REFERENCE_IMAGE_MEDIA_TYPES:
            raise ValueError("reference_paths supports PNG, JPEG, and WebP files")
        references.append((path, media_type))
    endpoint_name = "images/edits" if references else "images/generations"
    endpoint = f"{str(config.image_generation_base_url).rstrip('/')}/{endpoint_name}"
    request_data = {
        "model": config.image_generation_model,
        "prompt": prompt,
        "size": size,
        "n": "1" if references else 1,
    }
    request_kwargs: dict[str, Any] = {
        "headers": {"Authorization": f"Bearer {config.image_generation_api_key}"},
        "timeout": _IMAGE_GENERATION_TIMEOUT_SECONDS,
    }
    if references:
        request_kwargs["data"] = request_data
        request_kwargs["files"] = [
            ("image", (path.name, path.read_bytes(), media_type))
            for path, media_type in references
        ]
    else:
        request_kwargs["json"] = request_data
    response = httpx.post(endpoint, **request_kwargs)
    if response.status_code >= 400:
        try:
            error_body = response.json()
            message = str(error_body.get("error", {}).get("message") or "").strip()
        except (ValueError, AttributeError):
            message = ""
        detail = f": {message}" if message else ""
        raise RuntimeError(f"Image API returned HTTP {response.status_code}{detail}")
    body = response.json()
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise ValueError("Image API response did not contain data[0]")
    item = items[0]
    if not item.get("b64_json"):
        raise ValueError("Image API response did not contain data[0].b64_json")
    image_bytes = base64.b64decode(str(item["b64_json"]), validate=True)
    if len(image_bytes) > _MAX_GENERATED_IMAGE_BYTES:
        raise ValueError(
            f"Generated image exceeds the {_MAX_GENERATED_IMAGE_BYTES}-byte limit"
        )
    if len(image_bytes) < 24 or not image_bytes.startswith(_PNG_SIGNATURE):
        raise ValueError("Image API response was not a valid PNG payload")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.part")
    try:
        partial.write_bytes(image_bytes)
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return {
        "path": str(target),
        "filename": target.name,
        "media_type": "image/png",
        "size_bytes": len(image_bytes),
        "width": int.from_bytes(image_bytes[16:20], "big"),
        "height": int.from_bytes(image_bytes[20:24], "big"),
    }


def _prepare_image_context(
    work_dir: Path,
    *,
    build_number: int,
    dockerfile_path: object,
    context_files: object,
) -> tuple[Path, list[dict[str, str]]]:
    dockerfile = _builder_file(work_dir, dockerfile_path)
    if context_files is None:
        entries = []
    elif isinstance(context_files, list):
        entries = context_files
    else:
        raise ValueError("context_files must be a list when provided")
    if len(entries) > _MAX_IMAGE_CONTEXT_FILES:
        raise ValueError(f"context_files must contain at most {_MAX_IMAGE_CONTEXT_FILES} entries")
    validated: list[tuple[Path, str]] = []
    total_bytes = dockerfile.stat().st_size
    seen_targets = {"Dockerfile"}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each context_files entry must be an object.")
        source = _builder_file(work_dir, entry.get("source_path"))
        target = safe_context_path(str(entry.get("target_path") or ""))
        if target in seen_targets:
            raise ValueError(f"Duplicate or reserved Docker context path: {target}")
        total_bytes += source.stat().st_size
        if total_bytes > _MAX_IMAGE_CONTEXT_BYTES:
            raise ValueError(
                f"Docker build context exceeds {_MAX_IMAGE_CONTEXT_BYTES} bytes."
            )
        seen_targets.add(target)
        validated.append((source, target))
    context_root = work_dir / ".image-build"
    context_root.mkdir(parents=True, exist_ok=True)
    next_number = build_number
    while (context_root / f"build-{next_number:02d}").exists():
        next_number += 1
    context_dir = context_root / f"build-{next_number:02d}"
    context_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(dockerfile, context_dir / "Dockerfile")
    manifest_entries: list[dict[str, str]] = []
    for source, target in validated:
        target_path = context_dir / target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_path)
        manifest_entries.append(
            {
                "source_path": str(source.relative_to(work_dir.resolve())).replace("\\", "/"),
                "target_path": target,
            }
        )
    return context_dir, manifest_entries


def _execute_task_builder_tool(
    call: ToolCall,
    config: BenchmarkConfig,
    *,
    max_chars: int,
    work_dir: Path | None = None,
    tool_state: dict[str, Any] | None = None,
) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    state = tool_state if tool_state is not None else {}
    try:
        if call.name == "run_python":
            code = str(args.get("code") or "")
            if not code.strip():
                raise ValueError("code must be non-empty")
            if work_dir is None:
                raise ValueError("benchmark output_dir is required for Python task construction")
            work_dir.mkdir(parents=True, exist_ok=True)
            before = _file_state(work_dir)
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                try:
                    completed = subprocess.run(
                        [sys.executable, "-I", "-B", "-"],
                        input=code.encode("utf-8"),
                        cwd=work_dir,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        timeout=_PYTHON_TIMEOUT_SECONDS,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    return ToolResult(
                        tool_call_id=call.id,
                        name=call.name,
                        content=f"Python execution timed out after {_PYTHON_TIMEOUT_SECONDS} seconds.",
                        error="python_timeout",
                    )
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read(max_chars + 1).decode("utf-8", errors="replace")
                stderr = stderr_file.read(max_chars + 1).decode("utf-8", errors="replace")
            after = _file_state(work_dir)
            changed_files = [
                str(path.resolve())
                for path, state in sorted(after.items())
                if before.get(path) != state
            ]
            value = {
                "exit_code": completed.returncode,
                "stdout": stdout[:max_chars],
                "stderr": stderr[:max_chars],
                "files": changed_files,
                "working_directory": str(work_dir),
            }
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(value, max_chars=max_chars),
                error="python_execution_failed" if completed.returncode else None,
            )

        if call.name == "generate_image":
            if work_dir is None:
                raise ValueError("benchmark output_dir is required for generated task assets")
            prompt = str(args.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("prompt must be non-empty")
            if not _image_generation_configured(config):
                raise ValueError("image generation is not configured")
            generated = _generate_image_asset(
                config,
                work_dir,
                prompt=prompt,
                output_path=args.get("output_path"),
                size=str(args.get("size") or "1024x1024").strip(),
                reference_paths=args.get("reference_paths"),
            )
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(generated, max_chars=max_chars),
            )

        if call.name == "view_image":
            if work_dir is None:
                raise ValueError("benchmark output_dir is required for viewing task images")
            path, media_type = _viewable_image(work_dir, args.get("path"))
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(
                    {
                        "path": str(path),
                        "media_type": media_type,
                        "size_bytes": path.stat().st_size,
                        "status": "attached to the next model turn",
                    },
                    max_chars=max_chars,
                ),
                raw={"image_path": str(path), "media_type": media_type},
            )

        if call.name == "build_image":
            if work_dir is None:
                raise ValueError("benchmark output_dir is required for image construction")
            builds_used = int(state.get("image_builds_used") or 0)
            if builds_used >= _MAX_IMAGE_BUILDS:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content=f"Image build budget exhausted after {_MAX_IMAGE_BUILDS} build(s).",
                    error="image_build_budget_exhausted",
                )
            work_dir.mkdir(parents=True, exist_ok=True)
            state["last_image"] = ""
            context_dir, manifest_entries = _prepare_image_context(
                work_dir,
                build_number=builds_used + 1,
                dockerfile_path=args.get("dockerfile_path"),
                context_files=args.get("context_files"),
            )
            builds_used += 1
            state["image_builds_used"] = builds_used
            build_args = args.get("build_args")
            if build_args is not None and not isinstance(build_args, dict):
                raise ValueError("build_args must be an object when provided")
            result = build_docker_image_from_context(
                context_dir,
                tag=str(args.get("tag") or "").strip(),
                build_args={str(key): str(value) for key, value in (build_args or {}).items()},
                network=str(args.get("network") or "default").strip().lower(),
                docker_executable=config.docker_executable,
                timeout_s=_bounded_int(
                    args.get("timeout_s"),
                    default=600,
                    minimum=1,
                    maximum=1200,
                ),
            )
            state["last_image"] = result.image
            state["image_contexts"] = {
                **(state.get("image_contexts") if isinstance(state.get("image_contexts"), dict) else {}),
                result.image: {
                    "context_dir": str(context_dir.relative_to(work_dir.resolve())).replace("\\", "/"),
                    "dockerfile_name": "Dockerfile",
                    "context_files": manifest_entries,
                },
            }
            manifest_dir = work_dir / ".image-build" / "manifests"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            write_json(
                manifest_dir / f"{context_dir.name}.json",
                {
                    "image": result.image,
                    "context_dir": state["image_contexts"][result.image]["context_dir"],
                    "dockerfile_name": "Dockerfile",
                    "context_files": manifest_entries,
                    "dockerfile": result.dockerfile,
                },
            )
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(
                    {
                        "image": result.image,
                        "built": result.built,
                        "image_build": {
                            "enabled": True,
                            "context_dir": state["image_contexts"][result.image]["context_dir"],
                            "dockerfile_name": "Dockerfile",
                            "tag": result.image,
                        },
                        "context_files": manifest_entries,
                        "detail": result.detail,
                    },
                    max_chars=max_chars,
                ),
            )

        if call.name == "run_image_check":
            checks_used = int(state.get("image_checks_used") or 0)
            if checks_used >= _MAX_IMAGE_CHECKS:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content=f"Image check budget exhausted after {_MAX_IMAGE_CHECKS} check(s).",
                    error="image_check_budget_exhausted",
                )
            image = str(args.get("image") or state.get("last_image") or "").strip()
            command = str(args.get("command") or "").strip()
            if len(command) > _MAX_IMAGE_CHECK_COMMAND_CHARS:
                raise ValueError(
                    f"Image check command exceeds {_MAX_IMAGE_CHECK_COMMAND_CHARS} characters."
                )
            result = run_docker_image_check(
                image,
                command,
                network="none",
                docker_executable=config.docker_executable,
                timeout_s=_bounded_int(
                    args.get("timeout_s"),
                    default=60,
                    minimum=1,
                    maximum=120,
                ),
            )
            checks_used += 1
            state["image_checks_used"] = checks_used
            value = {
                "image": result.image,
                "command": result.command,
                "exit_code": result.exit_code,
                "stdout": result.stdout[:max_chars],
                "stderr": result.stderr[:max_chars],
                "timed_out": result.timed_out,
            }
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(value, max_chars=max_chars),
                error=(
                    "image_check_timeout"
                    if result.timed_out
                    else "image_check_failed"
                    if result.exit_code != 0
                    else None
                ),
            )

        if call.name == "build_vm_image":
            base_image = args.get("base_image")
            provisioning = args.get("provisioning")
            files = args.get("files", {})
            checks = args.get("checks")
            if not isinstance(base_image, dict) or not isinstance(provisioning, dict):
                raise ValueError("base_image and provisioning must be objects")
            if not isinstance(files, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in files.items()):
                raise ValueError("files must map guest-relative paths to literal string contents")
            if not isinstance(checks, list) or not checks:
                raise ValueError("checks must be a non-empty list")
            provider_url = str(getattr(config, "vm_provider_url", None) or "").strip() or None
            result = build_vm_image(
                provider_url,
                api_key=config.vm_provider_api_key,
                build_plan={
                    "base_image": copy.deepcopy(base_image),
                    "provisioning": copy.deepcopy(provisioning),
                    "files": copy.deepcopy(files),
                    "checks": copy.deepcopy(checks),
                    **({"publish_name": str(args.get("publish_name") or "").strip()} if str(args.get("publish_name") or "").strip() else {}),
                },
                timeout=_bounded_int(args.get("timeout_s"), default=600, minimum=1, maximum=3600),
            )
            state["last_vm_image"] = result.get("image")
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(result, max_chars=max_chars),
            )

        if call.name == "read_research_source":
            url = str(args.get("url") or "").strip()
            brief = config.research_brief
            material = next(
                (
                    candidate
                    for candidate in (brief.source_materials if brief is not None else [])
                    if candidate.url == url
                ),
                None,
            )
            if material is None:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content="No retained Deep Research source matched that URL.",
                    error="source_not_found",
                )
            requested_chars = _bounded_int(
                args.get("max_chars"), default=max_chars, minimum=500, maximum=max_chars
            )
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(
                    {
                        "url": material.url,
                        "title": material.title,
                        "content": material.content[:requested_chars],
                    },
                    max_chars=max_chars,
                ),
            )

        if call.name == "search_web":
            query = str(args.get("query") or "").strip()
            if not query:
                raise ValueError("query must be non-empty")
            if not config.use_web_research or str(config.search_backend).lower() == "none":
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content="Web search is disabled by benchmark configuration.",
                    error="search_disabled",
                )
            result = web_search(query, backend=config.search_backend)
            if result is None:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content="No search result was available.",
                    error="no_search_result",
                )
            max_results = _bounded_int(args.get("max_results"), default=5, minimum=1, maximum=8)
            value = {
                "query": query,
                "content": result.content,
                "citations": result.citations[:max_results],
            }
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(value, max_chars=max_chars),
            )

        if call.name == "fetch_url":
            url = str(args.get("url") or "").strip()
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("url must be an absolute HTTP(S) URL")
            requested_chars = _bounded_int(
                args.get("max_chars"), default=max_chars, minimum=500, maximum=max_chars
            )
            content = fetch_url_text(url, max_chars=requested_chars)
            if content is None:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content="The URL could not be fetched as readable text.",
                    error="fetch_failed",
                )
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content({"url": url, "content": content}, max_chars=max_chars),
            )

        if call.name == "download_files":
            raw_urls = args.get("urls")
            if not isinstance(raw_urls, list) or not raw_urls:
                raise ValueError("urls must be a non-empty list")
            if len(raw_urls) > _MAX_DOWNLOAD_URLS:
                raise ValueError(f"urls must contain at most {_MAX_DOWNLOAD_URLS} entries")
            if work_dir is None:
                raise ValueError("benchmark output_dir is required for downloaded task assets")
            files: list[dict[str, Any]] = []
            errors: list[dict[str, str]] = []
            remaining_bytes = _MAX_DOWNLOAD_BYTES
            for raw_url in raw_urls:
                url = str(raw_url or "").strip()
                try:
                    downloaded = download_url_file(
                        url,
                        work_dir,
                        max_bytes=remaining_bytes,
                    )
                    files.append(downloaded)
                    remaining_bytes -= int(downloaded["size_bytes"])
                except Exception as exc:
                    errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
            value = {"files": files, "errors": errors}
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=_tool_content(value, max_chars=max_chars),
                error="download_failed" if not files else None,
            )

        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Unknown TaskBuilder tool: {call.name}",
            error="unknown_tool",
        )
    except Exception as exc:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"TaskBuilder tool failed: {type(exc).__name__}: {exc}",
            error="tool_error",
        )


def _append_tool_results(
    messages: list[dict[str, Any]],
    response: TargetToolModelResponse,
    results: list[ToolResult],
) -> None:
    viewed_images: list[dict[str, str]] = []
    for result in results:
        raw = result.raw if isinstance(result.raw, dict) else {}
        image_path = str(raw.get("image_path") or "")
        media_type = str(raw.get("media_type") or "")
        if result.name == "view_image" and not result.error and image_path and media_type:
            data = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
            viewed_images.append(
                {
                    "path": image_path,
                    "media_type": media_type,
                    "data": data,
                }
            )

    messages.append(response.assistant_message)
    if response.adapter == "anthropic":
        content = [evalclaw_tool_result_to_anthropic(result) for result in results]
        for image in viewed_images:
            content.extend(
                [
                    {"type": "text", "text": f"Image from view_image: {image['path']}"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image["media_type"],
                            "data": image["data"],
                        },
                    },
                ]
            )
        messages.append(
            {
                "role": "user",
                "content": content,
            }
        )
        return
    if response.adapter == "openai_responses":
        messages.pop()
        output = response.assistant_message.get("responses_output")
        if isinstance(output, list):
            messages.extend(item for item in output if isinstance(item, dict))
        messages.extend(evalclaw_tool_result_to_openai_response_input(result) for result in results)
        if viewed_images:
            content: list[dict[str, Any]] = []
            for image in viewed_images:
                content.extend(
                    [
                        {"type": "input_text", "text": f"Image from view_image: {image['path']}"},
                        {
                            "type": "input_image",
                            "image_url": (
                                f"data:{image['media_type']};base64,{image['data']}"
                            ),
                            "detail": "auto",
                        },
                    ]
                )
            messages.append({"role": "user", "content": content})
        return
    messages.extend(evalclaw_tool_result_to_openai(result) for result in results)
    if viewed_images:
        content = []
        for image in viewed_images:
            content.extend(
                [
                    {"type": "text", "text": f"Image from view_image: {image['path']}"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image['media_type']};base64,{image['data']}",
                            "detail": "auto",
                        },
                    },
                ]
            )
        messages.append({"role": "user", "content": content})


def summarize_task_builder_truncation(
    error: LLMOutputTruncatedError,
    *,
    config: BenchmarkConfig,
    debug_dir: Path | None = None,
) -> str:
    """Compress one interrupted TaskBuilder response for in-place continuation."""
    summary_input = {
        "interrupted_assistant_output": error.partial_output,
    }
    settings = role_model_settings(config, "task_builder")
    try:
        summary = call_llm(
            [
                Message(
                    role="user",
                    content=json.dumps(summary_input, ensure_ascii=False),
                )
            ],
            system=TASK_BUILDER_TRUNCATION_SUMMARY_PROMPT,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            reduce_reasoning_effort=True,
            retry_on_truncation=False,
            trace_dir=debug_dir / "llm" if debug_dir is not None else None,
            trace_name="task-builder-truncation-summary",
        ).strip()
    except Exception as exc:
        raise TaskBuilderTruncationSummaryError(
            f"Could not summarize truncated TaskBuilder work: {type(exc).__name__}: {exc}"
        ) from exc
    if not summary:
        raise TaskBuilderTruncationSummaryError(
            "TaskBuilder returned no truncation summary after exhausting its output budget."
        )
    if debug_dir is not None:
        index = len(list(debug_dir.glob("truncation-summary-*.json"))) + 1
        write_json(
            debug_dir / f"truncation-summary-{index:02d}.json",
            {"summary": summary},
        )
    return summary


def run_task_builder_tools(
    payload: dict[str, Any],
    *,
    system_prompt: str,
    config: BenchmarkConfig,
    include_source_tools: bool,
    include_image_tools: bool = False,
    include_vm_image_tools: bool = False,
    debug_dir: Path | None = None,
    stop_event: Event | None = None,
) -> tuple[str, list[str]]:
    """Run a bounded TaskBuilder tool loop and return final builder JSON text."""

    def raise_if_stopped() -> None:
        if stop_event is not None and stop_event.is_set():
            raise CancelledError("TaskBuilder batch stopped after another job failed.")

    raise_if_stopped()
    max_calls = _bounded_int(
        config.task_builder_tool_max_calls,
        default=50,
        minimum=1,
        maximum=50,
    )
    max_chars = _bounded_int(
        config.task_builder_tool_max_chars,
        default=50_000,
        minimum=1000,
        maximum=100_000,
    )
    tools = [TASK_BUILDER_PYTHON_TOOL, TASK_BUILDER_VIEW_IMAGE_TOOL]
    if _image_generation_configured(config):
        tools.append(TASK_BUILDER_GENERATE_IMAGE_TOOL)
    if include_image_tools:
        tools.extend(TASK_BUILDER_IMAGE_TOOLS)
    if include_vm_image_tools:
        tools.extend(TASK_BUILDER_VM_IMAGE_TOOLS)
    if include_source_tools:
        tools.extend(TASK_BUILDER_SOURCE_TOOLS)
    settings = role_model_settings(config, "task_builder")
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, indent=2),
        }
    ]
    notes: list[str] = []
    calls_used = 0
    truncation_retries = max(
        0,
        int(getattr(config, "task_builder_truncation_retries", 3) or 0),
    )
    truncations_used = 0
    call_retries = max(
        0,
        int(getattr(config, "task_builder_call_retries", 5) or 0),
    )
    trace_index = len(list(debug_dir.glob("tool-round-*.json"))) if debug_dir else 0
    tool_state: dict[str, Any] = {}
    task_plan = payload.get("task_plan") if isinstance(payload.get("task_plan"), dict) else {}
    builder_job_id = str(task_plan.get("builder_job_id") or "task-builder")
    work_dir = task_builder_work_dir(config, builder_job_id)
    revision = payload.get("revision") if isinstance(payload.get("revision"), dict) else {}
    revision_path = str(revision.get("path") or "").strip()
    final_instruction = (
        "The candidate file has been edited. Return a compact JSON confirmation now."
        if revision_path
        else "Return the complete final task-builder JSON now."
    )

    def call_model_once(
        current_messages: list[dict[str, Any]],
        current_tools: list[ToolSpec],
    ) -> TargetToolModelResponse:
        nonlocal trace_index
        raise_if_stopped()
        response = call_orchestrator_with_tools(
            current_messages,
            system_prompt=system_prompt,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            tools=current_tools,
            max_tokens=TASK_BUILDER_MAX_OUTPUT_TOKENS,
            retry_on_truncation=False,
            trace_dir=debug_dir / "llm" if debug_dir is not None else None,
            trace_name=f"task-builder-{trace_index + 1:03d}",
        )
        if debug_dir is not None:
            trace_index += 1
            try:
                debug_dir.mkdir(parents=True, exist_ok=True)
                trace = {
                    "model": settings.model,
                    "backend": config.llm_backend,
                    "system_prompt": system_prompt,
                    "messages": current_messages,
                    "tools": [tool.model_dump(mode="json") for tool in current_tools],
                    "adapter": response.adapter,
                    "assistant_message": response.assistant_message,
                    "parsed_tool_calls": [
                        call.model_dump(mode="json") for call in response.tool_calls
                    ],
                    "raw_response": response.raw_response,
                }
                write_json(
                    debug_dir / f"tool-round-{trace_index:03d}.json",
                    trace,
                    redact=True,
                )
            except OSError as exc:
                notes.append(f"could not save task-builder tool trace ({exc})")
        raise_if_stopped()
        return response

    def call_model(
        current_messages: list[dict[str, Any]],
        current_tools: list[ToolSpec],
    ) -> TargetToolModelResponse:
        nonlocal truncations_used
        call_failures = 0
        while True:
            try:
                return call_model_once(current_messages, current_tools)
            except LLMOutputTruncatedError as exc:
                raise_if_stopped()
                if truncations_used >= truncation_retries:
                    raise
                summary = summarize_task_builder_truncation(
                    exc,
                    config=config,
                    debug_dir=debug_dir,
                )
                truncations_used += 1
                current_messages.append({"role": "assistant", "content": summary})
                current_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue the original TaskBuilder request from the preserved "
                            "conversation. Keep every original requirement unchanged."
                            if current_tools
                            else final_instruction
                        ),
                    }
                )
                notes.append(
                    "task-builder output truncated; replaced the interrupted response "
                    f"with summary {truncations_used}/{truncation_retries}"
                )
            except (CancelledError, TaskBuilderTruncationSummaryError):
                raise
            except Exception as exc:
                if call_failures >= call_retries:
                    raise TaskBuilderCallError(
                        "TaskBuilder model call failed after "
                        f"{call_retries} retry attempt(s): {type(exc).__name__}: {exc}"
                    ) from exc
                call_failures += 1
                notes.append(
                    "task-builder model call failed; retrying "
                    f"({call_failures}/{call_retries}): {type(exc).__name__}: {exc}"
                )

    def recover_missing_final_content(response: TargetToolModelResponse) -> TargetToolModelResponse:
        if response.content.strip():
            return response
        recovery = call_model(
            [
                *messages,
                {
                    "role": "user",
                    "content": final_instruction,
                },
            ],
            [],
        )
        if not recovery.content.strip():
            raise LLMFinalContentMissingError(
                "TaskBuilder returned no final content after one no-thinking recovery attempt."
            )
        return recovery

    while True:
        raise_if_stopped()
        response = call_model(messages, tools)
        if not response.tool_calls:
            response = recover_missing_final_content(response)
            raise_if_stopped()
            return response.content, notes
        remaining = max_calls - calls_used
        if remaining <= 0:
            messages.append(response.assistant_message)
            messages.append(
                {
                    "role": "user",
                    "content": f"The bounded tool budget is exhausted. {final_instruction}",
                }
            )
            response = call_model(messages, [])
            response = recover_missing_final_content(response)
            return response.content, notes + [f"tool budget exhausted at {calls_used} call(s)"]
        selected_calls = response.tool_calls[:remaining]
        results: list[ToolResult] = []
        for call in selected_calls:
            raise_if_stopped()
            results.append(
                _execute_task_builder_tool(
                    call,
                    config,
                    max_chars=max_chars,
                    work_dir=work_dir,
                    tool_state=tool_state,
                )
            )
        for skipped_call in response.tool_calls[remaining:]:
            results.append(
                ToolResult(
                    tool_call_id=skipped_call.id,
                    name=skipped_call.name,
                    content="This tool call was skipped because the bounded tool budget was exhausted.",
                    error="tool_budget_exhausted",
                )
            )
        calls_used += len(selected_calls)
        notes.append(f"task-builder used {len(selected_calls)} tool call(s), total={calls_used}")
        _append_tool_results(messages, response, results)
        if calls_used >= max_calls:
            messages.append(
                {
                    "role": "user",
                    "content": f"The bounded tool budget is exhausted. {final_instruction}",
                }
            )
            response = call_model(messages, [])
            response = recover_missing_final_content(response)
            raise_if_stopped()
            return response.content, notes + [f"tool budget exhausted at {calls_used} call(s)"]


__all__ = [
    "TASK_BUILDER_GENERATE_IMAGE_TOOL",
    "TASK_BUILDER_VIEW_IMAGE_TOOL",
    "TASK_BUILDER_PYTHON_TOOL",
    "TASK_BUILDER_IMAGE_TOOLS",
    "TASK_BUILDER_VM_IMAGE_TOOLS",
    "TASK_BUILDER_SOURCE_TOOLS",
    "TASK_BUILDER_TOOL_PROMPT",
    "TASK_BUILDER_MAX_OUTPUT_TOKENS",
    "TaskBuilderCallError",
    "TaskBuilderTruncationSummaryError",
    "run_task_builder_tools",
    "summarize_task_builder_truncation",
    "task_builder_work_dir",
]
