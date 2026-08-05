"""Bounded external research tools for high-effort task construction."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from ..models.llm import TargetToolModelResponse, call_orchestrator_with_tools
from ..models.roles import role_model_settings
from ..protocols.tool import ToolCall, ToolResult, ToolSpec
from ..protocols.tool_adapters import (
    evalclaw_tool_result_to_anthropic,
    evalclaw_tool_result_to_openai,
    evalclaw_tool_result_to_openai_response_input,
)
from ..research.backends import fetch_url_text, web_search
from ..types import BenchmarkConfig

TASK_BUILDER_E4_RESEARCH_PROMPT = """\
This task uses E4 construction effort. You may use the supplied research tools
when external evidence would materially improve the benchmark task. Search for
authoritative task shapes, real failure modes, software behavior, evaluation
protocols, or source resources only when useful. Do not perform ceremonial
searches, do not search for secrets, and do not use hidden evaluator content.
Use search_web for a query and fetch_url for a specific public HTTP(S) source.
After research, return the complete task-builder JSON object. The tool budget is
bounded; do not keep researching after you have enough evidence.
"""


TASK_BUILDER_RESEARCH_TOOLS = [
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


def _execute_research_tool(
    call: ToolCall,
    config: BenchmarkConfig,
    *,
    max_chars: int,
) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    try:
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

        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Unknown research tool: {call.name}",
            error="unknown_tool",
        )
    except Exception as exc:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Research tool failed: {type(exc).__name__}: {exc}",
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


def run_task_builder_research(
    payload: dict[str, Any],
    *,
    system_prompt: str,
    config: BenchmarkConfig,
) -> tuple[str, list[str]]:
    """Run a bounded E4 research/tool loop and return final builder JSON text."""
    max_calls = _bounded_int(
        config.task_builder_research_max_calls,
        default=6,
        minimum=1,
        maximum=12,
    )
    max_chars = _bounded_int(
        config.task_builder_research_max_chars,
        default=6000,
        minimum=1000,
        maximum=16000,
    )
    settings = role_model_settings(config, "task_builder")
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    **payload,
                    "resources": {
                        **(
                            payload.get("resources")
                            if isinstance(payload.get("resources"), dict)
                            else {}
                        ),
                        "interactive_research": {
                            "enabled": True,
                            "max_tool_calls": max_calls,
                            "available_tools": [tool.name for tool in TASK_BUILDER_RESEARCH_TOOLS],
                            "instruction": "Use tools only when they materially improve the task; return complete JSON when done.",
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
        }
    ]
    notes: list[str] = []
    calls_used = 0
    while True:
        response = call_orchestrator_with_tools(
            messages,
            system_prompt=system_prompt,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            tools=TASK_BUILDER_RESEARCH_TOOLS,
            max_tokens=16384,
            retry_on_truncation=False,
        )
        if not response.tool_calls:
            return response.content, notes
        remaining = max_calls - calls_used
        if remaining <= 0:
            messages.append(response.assistant_message)
            messages.append(
                {
                    "role": "user",
                    "content": "The bounded research budget is exhausted. Return the complete final task-builder JSON now without further tool calls.",
                }
            )
            response = call_orchestrator_with_tools(
                messages,
                system_prompt=system_prompt,
                **settings.call_kwargs(),
                backend=config.llm_backend,
                tools=[],
                max_tokens=16384,
                retry_on_truncation=False,
            )
            return response.content, notes + [f"research tool budget exhausted at {calls_used} call(s)"]
        selected_calls = response.tool_calls[:remaining]
        results = [_execute_research_tool(call, config, max_chars=max_chars) for call in selected_calls]
        for skipped_call in response.tool_calls[remaining:]:
            results.append(
                ToolResult(
                    tool_call_id=skipped_call.id,
                    name=skipped_call.name,
                    content="This tool call was skipped because the bounded research budget was exhausted.",
                    error="research_budget_exhausted",
                )
            )
        calls_used += len(selected_calls)
        notes.append(f"task-builder research used {len(selected_calls)} tool call(s), total={calls_used}")
        _append_tool_results(messages, response, results)
        if calls_used >= max_calls:
            messages.append(
                {
                    "role": "user",
                    "content": "The bounded research budget is exhausted. Return the complete final task-builder JSON now without further tool calls.",
                }
            )
            response = call_orchestrator_with_tools(
                messages,
                system_prompt=system_prompt,
                **settings.call_kwargs(),
                backend=config.llm_backend,
                tools=[],
                max_tokens=16384,
                retry_on_truncation=False,
            )
            return response.content, notes + [f"research tool budget exhausted at {calls_used} call(s)"]


__all__ = [
    "TASK_BUILDER_E4_RESEARCH_PROMPT",
    "TASK_BUILDER_RESEARCH_TOOLS",
    "run_task_builder_research",
]
