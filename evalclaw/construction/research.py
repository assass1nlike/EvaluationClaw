"""Bounded tools for TaskBuilder construction."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..models.llm import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    LLMFinalContentMissingError,
    TargetToolModelResponse,
    call_orchestrator_with_tools,
)
from ..models.roles import role_model_settings
from ..protocols.tool import ToolCall, ToolResult, ToolSpec
from ..protocols.tool_adapters import (
    evalclaw_tool_result_to_anthropic,
    evalclaw_tool_result_to_openai,
    evalclaw_tool_result_to_openai_response_input,
)
from ..research.backends import download_url_file, fetch_url_text, web_search
from ..types import BenchmarkConfig

_MAX_DOWNLOAD_URLS = 32
_MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
_PYTHON_TIMEOUT_SECONDS = 60

# This prompt must explain when to use construction and source tools, where files
# belong, and that the Builder must return its complete response after tool use.
TASK_BUILDER_TOOL_PROMPT = """\
You may use the supplied tools when they materially improve task construction.
Use run_python for computation, validation, or creating and processing task files.
Save required task files in its fixed working directory, put the returned absolute
paths in the corresponding task's top-level assets list, and refer to those paths
verbatim in prompt. When source tools are available, use read_research_source to
inspect text retained by Deep Research, search_web for a new query, fetch_url for
readable public HTTP(S) text, and download_files to persist public files. Do not
perform ceremonial tool calls, search for secrets, or use hidden evaluator content.
Return the complete task-builder JSON object after tool use. The tool budget is
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


def _execute_task_builder_tool(
    call: ToolCall,
    config: BenchmarkConfig,
    *,
    max_chars: int,
    work_dir: Path | None = None,
) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
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
    messages.append(response.assistant_message)
    if response.adapter == "anthropic":
        messages.append(
            {
                "role": "user",
                "content": [evalclaw_tool_result_to_anthropic(result) for result in results],
            }
        )
        return
    if response.adapter == "openai_responses":
        messages.pop()
        output = response.assistant_message.get("responses_output")
        if isinstance(output, list):
            messages.extend(item for item in output if isinstance(item, dict))
        messages.extend(evalclaw_tool_result_to_openai_response_input(result) for result in results)
        return
    messages.extend(evalclaw_tool_result_to_openai(result) for result in results)


def run_task_builder_tools(
    payload: dict[str, Any],
    *,
    system_prompt: str,
    config: BenchmarkConfig,
    include_source_tools: bool,
    debug_dir: Path | None = None,
) -> tuple[str, list[str]]:
    """Run a bounded TaskBuilder tool loop and return final builder JSON text."""
    max_calls = _bounded_int(
        config.task_builder_tool_max_calls,
        default=6,
        minimum=1,
        maximum=12,
    )
    max_chars = _bounded_int(
        config.task_builder_tool_max_chars,
        default=50_000,
        minimum=1000,
        maximum=100_000,
    )
    tools = [TASK_BUILDER_PYTHON_TOOL]
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
    trace_index = len(list(debug_dir.glob("tool-round-*.json"))) if debug_dir else 0
    task_plan = payload.get("task_plan") if isinstance(payload.get("task_plan"), dict) else {}
    builder_job_id = str(task_plan.get("builder_job_id") or "task-builder")
    safe_job_id = re.sub(r"[^A-Za-z0-9._-]+", "_", builder_job_id).strip("._")
    work_dir = (
        Path(config.output_dir).expanduser().resolve()
        / "assets"
        / "task-builder"
        / (safe_job_id or "task-builder")
        if str(config.output_dir).strip()
        else None
    )

    def call_model(
        current_messages: list[dict[str, Any]],
        current_tools: list[ToolSpec],
    ) -> TargetToolModelResponse:
        nonlocal trace_index
        response = call_orchestrator_with_tools(
            current_messages,
            system_prompt=system_prompt,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            tools=current_tools,
            max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            retry_on_truncation=False,
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
                (debug_dir / f"tool-round-{trace_index:03d}.json").write_text(
                    json.dumps(trace, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as exc:
                notes.append(f"could not save task-builder tool trace ({exc})")
        return response

    def recover_missing_final_content(response: TargetToolModelResponse) -> TargetToolModelResponse:
        if response.content.strip():
            return response
        recovery = call_model(
            [
                *messages,
                {
                    "role": "user",
                    "content": "Return the complete final task-builder JSON now.",
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
        response = call_model(messages, tools)
        if not response.tool_calls:
            response = recover_missing_final_content(response)
            return response.content, notes
        remaining = max_calls - calls_used
        if remaining <= 0:
            messages.append(response.assistant_message)
            messages.append(
                {
                    "role": "user",
                    "content": "The bounded tool budget is exhausted. Return the complete final task-builder JSON now without further tool calls.",
                }
            )
            response = call_model(messages, [])
            response = recover_missing_final_content(response)
            return response.content, notes + [f"tool budget exhausted at {calls_used} call(s)"]
        selected_calls = response.tool_calls[:remaining]
        results = [
            _execute_task_builder_tool(
                call,
                config,
                max_chars=max_chars,
                work_dir=work_dir,
            )
            for call in selected_calls
        ]
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
                    "content": "The bounded tool budget is exhausted. Return the complete final task-builder JSON now without further tool calls.",
                }
            )
            response = call_model(messages, [])
            response = recover_missing_final_content(response)
            return response.content, notes + [f"tool budget exhausted at {calls_used} call(s)"]


__all__ = [
    "TASK_BUILDER_PYTHON_TOOL",
    "TASK_BUILDER_SOURCE_TOOLS",
    "TASK_BUILDER_TOOL_PROMPT",
    "run_task_builder_tools",
]
