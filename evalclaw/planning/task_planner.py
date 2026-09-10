"""Skill-driven benchmark content and TaskDesign planning."""
from __future__ import annotations

import json
import re
import tempfile
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.llm import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    LLMFinalContentMissingError,
    TargetToolModelResponse,
    call_orchestrator_with_tools,
    extract_json,
)
from ..models.roles import RoleModelSettings, role_model_settings
from ..diagnostics import (
    document_append,
    document_get,
    document_remove,
    document_set,
)
from ..prompts.planner import BENCHMARK_PLANNER_SYSTEM_PROMPT
from ..protocols.tool import ToolCall, ToolResult, ToolSpec
from ..protocols.tool_adapters import (
    evalclaw_tool_result_to_anthropic,
    evalclaw_tool_result_to_openai,
    evalclaw_tool_result_to_openai_response_input,
)
from ..research.backends import fetch_url_text, web_search
from ..types import (
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkPlan,
    BenchmarkPlanAudit,
    ChallengeEffort,
    EvalSpec,
    ResearchBrief,
    ResearchSourceMaterial,
    TaskBlueprint,
    TaskType,
    environment_category,
)
from .planner import _safe_scale_budget, _scale_budget_guidance
from .skill_loader import benchmark_planner_system_prompt


def _unique_strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


_TASK_COUNT_NOUNS = r"(?:tasks?|questions?|items?|problems?|prompts?|dialogues?|scenarios?|test cases?)"
_TOTAL_TASK_COUNT_RE = re.compile(
    rf"\b(?:a\s+)?total\s+(?:of\s+)?(?:exactly\s+)?(?P<count>\d+)"
    rf"(?:\s+[\w-]+){{0,5}}\s+{_TASK_COUNT_NOUNS}\b",
    re.IGNORECASE,
)
_EXACT_TASK_COUNT_RE = re.compile(
    rf"\bexactly\s+(?P<count>\d+)(?:\s+[\w-]+){{0,5}}\s+{_TASK_COUNT_NOUNS}\b",
    re.IGNORECASE,
)
_CJK_TOTAL_TASK_COUNT_RE = re.compile(
    r"(?:总共|总计|共)[^\d]{0,8}(?P<count>\d+)\s*(?:道|个|项|份)?(?:题目?|问题|任务|对话|案例)"
)


def _explicit_total_task_count(instruction: str) -> int | None:
    """Return an unambiguous user-specified total task count, if present."""
    for pattern in (_TOTAL_TASK_COUNT_RE, _CJK_TOTAL_TASK_COUNT_RE):
        match = pattern.search(instruction)
        if match:
            return int(match.group("count"))
    candidates = {
        int(match.group("count"))
        for match in _EXACT_TASK_COUNT_RE.finditer(instruction)
        if not re.match(
            r"\s+(?:per|for\s+each|in\s+each)\b",
            instruction[match.end() : match.end() + 32],
            re.IGNORECASE,
        )
    }
    return next(iter(candidates)) if len(candidates) == 1 else None


def _valid_effort_distribution(
    raw: dict[str, float],
) -> dict[ChallengeEffort, float]:
    """Return a normalized E1/E2/E3 ratio map, or {} when raw is invalid/empty.

    Accepts keys as enum names ('E1'), lowercase names, or enum values. Weights
    must be non-negative and sum to roughly 1.0 to be treated as a constraint.
    """
    if not isinstance(raw, dict) or not raw:
        return {}
    normalized: dict[ChallengeEffort, float] = {}
    for key, value in raw.items():
        token = str(key).strip().upper()
        try:
            level = ChallengeEffort(token)
        except ValueError:
            continue
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if weight < 0:
            return {}
        normalized[level] = weight
    if not normalized:
        return {}
    total = sum(normalized.values())
    if total <= 0:
        return {}
    # Require the weights to sum to a plausible distribution before treating
    # them as a hard constraint; otherwise fall back to Planner freedom.
    if abs(total - 1.0) > 0.01:
        return {}
    return {level: weight / total for level, weight in normalized.items()}


def _effort_distribution_policy(distribution: dict[ChallengeEffort, float]) -> str:
    parts = ", ".join(
        f"{level.value} ≈ {round(weight * 100):.0f}%"
        for level, weight in sorted(distribution.items(), key=lambda item: item[0].value)
    )
    return (
        "The framework requires the total task count to be distributed across "
        f"challenge_effort levels as follows: {parts}. "
        "Set each TaskDesign.challenge_effort so the planned per-level task counts "
        "approximate these ratios."
    )


def _instruction_resource(
    goal: str,
    config: BenchmarkConfig,
    *,
    feedback: str | None = None,
    previous_plan: BenchmarkPlan | None = None,
) -> str:
    explicit_task_count = _explicit_total_task_count(goal)
    constraints: dict[str, object] = {
        "available_task_types": [task_type.value for task_type in TaskType],
        "available_environment_types": [environment.value for environment in AgentEnvironmentType],
    }

    if explicit_task_count is not None:
        print(f"[Planner] User specified explicit task count: {explicit_task_count}. Not passing scale_budget.")
        constraints["explicit_total_task_count"] = explicit_task_count
        constraints["count_policy"] = (
            "The user explicitly requested exactly this many tasks. "
            "All TaskDesign.task_count values must sum to this total."
        )
    else:
        scale_budget = _safe_scale_budget(config.scale_budget)
        constraints["scale_budget"] = scale_budget.value
        constraints["scale_budget_guidance"] = _scale_budget_guidance(scale_budget)
        constraints["count_policy"] = (
            "Use scale_budget as guidance for the total number of tasks."
        )

    if config.source_backed_ratio is not None:
        constraints["source_backed_ratio"] = config.source_backed_ratio
    effort_distribution = _valid_effort_distribution(config.challenge_effort_distribution)
    if effort_distribution:
        constraints["challenge_effort_distribution"] = {
            level.value: round(weight, 4) for level, weight in sorted(effort_distribution.items())
        }
        constraints["effort_policy"] = _effort_distribution_policy(effort_distribution)
    sections = [
        "# User Evaluation Request",
        "",
        goal.strip(),
        "",
        "# Framework-Supplied Task-Design Constraints",
        "",
        json.dumps(constraints, ensure_ascii=False, indent=2),
    ]
    if feedback:
        sections.extend(["", "# User Feedback on the Previous Plan", "", feedback.strip()])
    if previous_plan is not None:
        sections.extend(
            [
                "",
                "# Previous Plan to Revise",
                "",
                json.dumps({"plan": previous_plan.model_dump(mode="json")}, ensure_ascii=False, indent=2),
            ]
        )
    return "\n".join(sections).strip()


_PLANNER_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="search_web",
        description=(
            "Search public web sources for authoritative benchmark design material "
            "(capability dimensions, failure modes, software documentation, task resources). "
            "Returns a summary with citation URLs."
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


def _plan_tool_keys(simplified: bool) -> str:
    return "objective, dimensions" if simplified else "objective, constraints, planner_notes, dimensions"


def _planner_read_tool(simplified: bool) -> ToolSpec:
    return ToolSpec(
        name="read_plan",
        description=(
            f"Read the working plan JSON file (top-level keys {_plan_tool_keys(simplified)}). "
            "With no path returns the full document; with a dot path returns just that "
            "node (e.g. \"dimensions.0\" or \"objective\")."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Optional dot path to read."},
            },
            "additionalProperties": False,
        },
    )


def _planner_write_tool(simplified: bool) -> ToolSpec:
    return ToolSpec(
        name="update_plan",
        description=(
            f"Apply a list of operations to the working plan JSON file (top-level keys "
            f"{_plan_tool_keys(simplified)}). Each operation is {{\"op\": \"set\"|\"remove\"|\"append\", "
            "\"path\": \"dot.path\" (list items indexed from 0), \"value\": ...}. Returns the updated "
            "plan summary (dimension names and task_designs counts)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["set", "remove", "append"]},
                            "path": {"type": "string"},
                            "value": {},
                        },
                        "required": ["op", "path"],
                        "additionalProperties": False,
                    },
                    "description": "Ordered operations to apply to the plan.",
                },
            },
            "required": ["operations"],
            "additionalProperties": False,
        },
    )


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _plan_summary(document: dict[str, Any], *, simplified: bool = False) -> dict[str, Any]:
    dimensions = document.get("dimensions")
    if not isinstance(dimensions, list):
        dimensions = []
    summary: dict[str, Any] = {
        "objective": str(document.get("objective") or ""),
        "dimensions": [
            {
                "name": str(d.get("name") or f"dimension_{index}") if isinstance(d, dict) else f"dimension_{index}",
                "task_designs": len(d.get("task_designs") or []) if isinstance(d, dict) else 0,
            }
            for index, d in enumerate(dimensions)
        ],
    }
    if not simplified:
        summary["constraints"] = len(document.get("constraints") or [])
    return summary


def _record_source_material(
    source_materials: dict[str, ResearchSourceMaterial],
    url: str,
    *,
    content: str,
) -> None:
    existing = source_materials.get(url)
    if existing is None or len(content) > len(existing.content):
        source_materials[url] = ResearchSourceMaterial(url=url, content=content)


def _execute_planner_tool(
    call: ToolCall,
    config: BenchmarkConfig,
    *,
    max_chars: int,
    source_materials: dict[str, ResearchSourceMaterial],
    document_path: str = "",
) -> ToolResult:
    try:
        if call.name in ("read_plan", "update_plan"):
            if not document_path:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content="No working plan document is available.",
                    error="no_document",
                )
            target = Path(document_path)
            try:
                current = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"Could not read the working plan document: {exc}") from exc
            if not isinstance(current, dict):
                raise ValueError("The working plan document is not a JSON object")

            if call.name == "read_plan":
                path = str(call.arguments.get("path") or "").strip()
                if path:
                    try:
                        node = document_get(current, path)
                    except KeyError as exc:
                        return ToolResult(
                            tool_call_id=call.id,
                            name=call.name,
                            content=f"No node at path {path!r}: {exc}",
                            error="missing_path",
                        )
                    return ToolResult(
                        tool_call_id=call.id,
                        name=call.name,
                        content=json.dumps(node, ensure_ascii=False)[:max_chars],
                    )
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content=json.dumps(current, ensure_ascii=False)[:max_chars],
                )

            operations = call.arguments.get("operations")
            if not isinstance(operations, list):
                raise ValueError("operations must be a list")
            for operation in operations:
                if not isinstance(operation, dict):
                    raise ValueError("each operation must be an object")
                op = str(operation.get("op") or "")
                path = str(operation.get("path") or "")
                if op == "set":
                    document_set(current, path, operation.get("value"))
                elif op == "remove":
                    document_remove(current, path)
                elif op == "append":
                    document_append(current, path, operation.get("value"))
                else:
                    raise ValueError(f"unknown operation {op!r}")
            target.write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=json.dumps(
                    _plan_summary(current, simplified=config.ablation_simplified_contract),
                    ensure_ascii=False,
                )[:max_chars],
            )
        if call.name == "search_web":
            query = str(call.arguments.get("query") or "").strip()
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
            max_results = _bounded_int(
                call.arguments.get("max_results"), default=5, minimum=1, maximum=8
            )
            value = {
                "query": query,
                "content": result.content,
                "citations": result.citations[:max_results],
            }
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=json.dumps(value, ensure_ascii=False)[:max_chars],
            )
        if call.name == "fetch_url":
            if not config.use_web_research or str(config.search_backend).lower() == "none":
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content="Web fetch is disabled by benchmark configuration.",
                    error="fetch_disabled",
                )
            url = str(call.arguments.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                raise ValueError("url must be an absolute HTTP(S) URL")
            requested_chars = _bounded_int(
                call.arguments.get("max_chars"), default=max_chars, minimum=500, maximum=max_chars
            )
            content = fetch_url_text(url, max_chars=requested_chars)
            if content is None:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content="The URL could not be fetched as readable text.",
                    error="fetch_failed",
                )
            _record_source_material(source_materials, url, content=content)
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=json.dumps({"url": url, "content": content}, ensure_ascii=False)[:max_chars],
            )
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Unknown tool: {call.name}",
            error="unknown_tool",
        )
    except Exception as exc:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=f"Tool error: {exc}",
            error="tool_error",
        )


def _append_planner_tool_results(
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
    elif response.adapter == "openai_responses":
        messages.pop()
        output = response.assistant_message.get("responses_output")
        if isinstance(output, list):
            messages.extend(item for item in output if isinstance(item, dict))
        messages.extend(
            evalclaw_tool_result_to_openai_response_input(result) for result in results
        )
    else:
        messages.extend(evalclaw_tool_result_to_openai(result) for result in results)


def _run_planner_tool_loop(
    user_content: str,
    system: str,
    config: BenchmarkConfig,
    settings: RoleModelSettings,
    *,
    max_calls: int,
    max_chars: int,
    source_materials: dict[str, ResearchSourceMaterial],
    debug_dir: Path | None,
    trace_name: str,
    document_path: str = "",
) -> str:
    final_instruction = (
        "Commit your finished plan parts with update_plan, then stop with no further tool calls."
    )
    web_enabled = bool(config.use_web_research) and str(config.search_backend).lower() != "none"
    simplified = config.ablation_simplified_contract
    read_tool = _planner_read_tool(simplified)
    write_tool = _planner_write_tool(simplified)
    tools = (
        [*_PLANNER_TOOLS, read_tool, write_tool]
        if web_enabled
        else [read_tool, write_tool]
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
    calls_used = 0

    def _read_document() -> str:
        if not document_path:
            return ""
        try:
            return Path(document_path).read_text(encoding="utf-8")
        except OSError:
            return ""

    def _call(tools: list[ToolSpec], name: str) -> TargetToolModelResponse:
        return call_orchestrator_with_tools(
            messages,
            system_prompt=system,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            tools=tools,
            max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            retry_on_truncation=True,
            trace_dir=debug_dir / "llm" if debug_dir is not None else None,
            trace_name=name,
        )

    def _final_content() -> str:
        document = _read_document().strip()
        if document:
            return document
        raise LLMFinalContentMissingError("Planner produced no planning document.")

    def _force_final() -> str:
        messages.append(
            {"role": "user", "content": f"The bounded tool budget is exhausted. {final_instruction}"}
        )
        _call([], f"{trace_name}-final")
        return _final_content()

    while True:
        response = _call(tools, trace_name)
        if not response.tool_calls:
            document = _read_document().strip()
            if document:
                return document
            if response.content.strip():
                return response.content
            recovery = _call([], f"{trace_name}-recover")
            if recovery.content.strip():
                return recovery.content
            raise LLMFinalContentMissingError("Planner returned no final planning JSON.")
        remaining = max_calls - calls_used
        if remaining <= 0:
            messages.append(response.assistant_message)
            return _force_final()
        selected = response.tool_calls[:remaining]
        results = [
            _execute_planner_tool(
                call,
                config,
                max_chars=max_chars,
                source_materials=source_materials,
                document_path=document_path,
            )
            for call in selected
        ]
        for skipped in response.tool_calls[remaining:]:
            results.append(
                ToolResult(
                    tool_call_id=skipped.id,
                    name=skipped.name,
                    content="This tool call was skipped because the bounded tool budget was exhausted.",
                    error="tool_budget_exhausted",
                )
            )
        calls_used += len(selected)
        _append_planner_tool_results(messages, response, results)
        if calls_used >= max_calls:
            return _force_final()


def _planner_resources(instruction: str) -> str:
    files = [
        '<FILE path="resources/instruction.md">\n'
        + instruction
        + "\n</FILE>"
    ]
    return (
        "The following read-only Planner resources are available by path.\n\n"
        "<PLANNER_RESOURCES>\n"
        + "\n\n".join(files)
        + "\n</PLANNER_RESOURCES>"
    )


def _audit_plan(
    plan: BenchmarkPlan,
    *,
    expected_task_count: int | None = None,
    expected_effort_distribution: dict[ChallengeEffort, float] | None = None,
    simplified: bool = False,
) -> list[str]:
    issues: list[str] = []
    if not plan.dimensions:
        return ["plan.dimensions must contain at least one dimension."]
    dimension_ids = [dimension.id for dimension in plan.dimensions]
    if len(dimension_ids) != len(set(dimension_ids)):
        issues.append("Dimension ids must be unique.")

    all_design_ids: set[str] = set()
    allowed_task_types = (
        {TaskType.choice, TaskType.fill_blank, TaskType.generation}
        if simplified
        else set(TaskType)
    )
    for dimension in plan.dimensions:
        prefix = dimension.id or "unnamed_dimension"
        required_fields = (
            [dimension.id, dimension.name]
            if simplified
            else [dimension.id, dimension.name, dimension.measurement_target, dimension.boundary, dimension.approach]
        )
        if not all(required_fields):
            issues.append(
                f"{prefix}: id and name are required."
                if simplified
                else f"{prefix}: id, name, measurement_target, boundary, and approach are required."
            )
        if not dimension.task_designs:
            issues.append(f"{prefix}: task_designs must not be empty.")
        local_design_ids = [design.id for design in dimension.task_designs]
        if len(local_design_ids) != len(set(local_design_ids)):
            issues.append(f"{prefix}: TaskDesign ids must be unique within the dimension.")
        repeated = all_design_ids.intersection(local_design_ids)
        if repeated:
            issues.append(f"{prefix}: TaskDesign ids must be globally unique: {sorted(repeated)}.")
        all_design_ids.update(local_design_ids)
        for design in dimension.task_designs:
            design_prefix = f"{prefix}/{design.id or 'unnamed_task_design'}"
            if design.task_type not in allowed_task_types:
                issues.append(f"{design_prefix}: unsupported task_type {design.task_type.value}.")
            if not design.description:
                issues.append(
                    f"{design_prefix}: content_design must include a concrete purpose or description."
                )
            if not simplified:
                declared_category = str(
                    design.environment_requirements.get("category") or ""
                ).strip()
                resolved_category = environment_category(design)
                if design.environment_requirements and not declared_category:
                    issues.append(
                        f"{design_prefix}: non-empty environment_requirements must define category."
                    )
                if declared_category and resolved_category is None:
                    issues.append(
                        f"{design_prefix}: environment category {declared_category!r} is not one of "
                        + ", ".join(environment.value for environment in AgentEnvironmentType)
                        + "."
                    )
                if design.task_type == TaskType.agent and not declared_category:
                    issues.append(f"{design_prefix}: agent tasks require environment_requirements.")
                if design.task_type == TaskType.multi_turn:
                    followup_mode = str(
                        design.interaction_requirements.get("followup_mode") or ""
                    ).strip().lower()
                    if followup_mode not in {"adaptive", "scripted"}:
                        issues.append(
                            f"{design_prefix}: multi_turn TaskDesigns must set "
                            "interaction_requirements.followup_mode to 'adaptive' or 'scripted'."
                        )
                if declared_category and design.task_type != TaskType.agent:
                    issues.append(
                        f"{design_prefix}: environment category {declared_category!r} is only valid "
                        "for agent tasks. Remove the environment or change the task type when executable "
                        "interaction is essential."
                    )
                source_strategy = str(design.source_plan.get("strategy") or "").strip()
                source_queries = _unique_strings(design.source_plan.get("search_queries"))
                source_urls = _unique_strings(design.source_plan.get("suggested_urls"))
                external_strategies = {
                    "adapted",
                    "reused",
                    "imported_dataset",
                }
                if source_strategy not in {
                    "generated",
                    *external_strategies,
                }:
                    issues.append(
                        f"{design_prefix}: source_plan.strategy must be generated, adapted, reused, "
                        "or imported_dataset."
                    )
                elif source_strategy == "generated" and (source_urls or source_queries):
                    issues.append(
                        f"{design_prefix}: generated source_plan.strategy requires empty "
                        "suggested_urls and search_queries."
                    )
                elif source_strategy in external_strategies and not source_urls:
                    issues.append(
                        f"{design_prefix}: {source_strategy} source_plan.strategy requires at least "
                        "one suggested URL."
                    )
                for url in source_urls:
                    if not url.lower().startswith(("https://", "http://")):
                        issues.append(f"{design_prefix}: suggested URL is invalid: {url!r}.")


    planned_task_count = sum(
        design.task_count for dim in plan.dimensions for design in dim.task_designs
    )
    if not planned_task_count:
        issues.append("The complete plan must contain at least one task.")
    if expected_task_count is not None and planned_task_count != expected_task_count:
        issues.append(
            f"The user explicitly requested exactly {expected_task_count} tasks, but the plan contains "
            f"{planned_task_count}. Adjust TaskDesign.task_count values so their sum is exactly "
            f"{expected_task_count}."
        )
    if not simplified and expected_effort_distribution and planned_task_count:
        actual: dict[ChallengeEffort, int] = {}
        for dim in plan.dimensions:
            for design in dim.task_designs:
                actual[design.challenge_effort] = (
                    actual.get(design.challenge_effort, 0) + design.task_count
                )
        tolerance_parts: list[str] = []
        for level, ratio in sorted(expected_effort_distribution.items(), key=lambda item: item[0].value):
            expected = round(planned_task_count * ratio)
            actual_count = actual.get(level, 0)
            if abs(actual_count - expected) > 1:
                tolerance_parts.append(
                    f"{level.value}: planned {actual_count} tasks, expected ~{expected}"
                )
        if tolerance_parts:
            issues.append(
                "TaskDesign.challenge_effort must match the required distribution: "
                + "; ".join(tolerance_parts)
                + "."
            )
    return issues


def _parse_plan_response(
    data: object,
    config: BenchmarkConfig,
    *,
    expected_task_count: int | None = None,
    framework_dimension_ids: list[str] | None = None,
) -> tuple[BenchmarkPlan, list[str]]:
    if not isinstance(data, dict) or not isinstance(data.get("plan"), dict):
        raise ValueError("Planner response must be an object with a plan object at its root.")
    raw_plan = dict(data["plan"])
    raw_plan["id"] = "evalclaw_plan"
    simplified = config.ablation_simplified_contract
    raw_dimensions = raw_plan.get("dimensions")
    if not isinstance(raw_dimensions, list):
        raw_dimensions = []
    normalized_dimensions: list[dict[str, object]] = []
    for dimension_index, raw_dimension in enumerate(raw_dimensions, 1):
        if not isinstance(raw_dimension, dict):
            normalized_dimensions.append({})
            continue
        dimension = dict(raw_dimension)
        dimension_id = (
            framework_dimension_ids[dimension_index - 1]
            if framework_dimension_ids and dimension_index <= len(framework_dimension_ids)
            else f"dimension_{dimension_index}"
        )
        dimension["id"] = dimension_id
        if simplified:
            dimension.setdefault("measurement_target", "")
            dimension.setdefault("boundary", "")
            dimension.setdefault("approach", "")
        raw_designs = dimension.get("task_designs")
        if not isinstance(raw_designs, list):
            raw_designs = []
        normalized_designs: list[dict[str, object]] = []
        for design_index, raw_design in enumerate(raw_designs, 1):
            if not isinstance(raw_design, dict):
                normalized_designs.append({})
                continue
            design = dict(raw_design)
            design["id"] = f"{dimension_id}_task_design_{design_index}"
            if simplified and isinstance(design.get("content_design"), str):
                design["content_design"] = {"description": design["content_design"]}
            normalized_designs.append(design)
        dimension["task_designs"] = normalized_designs
        normalized_dimensions.append(dimension)
    raw_plan["dimensions"] = normalized_dimensions
    plan = BenchmarkPlan.model_validate(raw_plan).model_copy(
        update={
            "subjects": [target.id for target in config.targets],
            "scale_budget": _safe_scale_budget(config.scale_budget),
        }
    )
    issues = _audit_plan(
        plan,
        expected_task_count=expected_task_count,
        expected_effort_distribution=_valid_effort_distribution(
            config.challenge_effort_distribution
        ),
        simplified=simplified,
    )
    if framework_dimension_ids is not None and len(plan.dimensions) != len(framework_dimension_ids):
        issues.append(
            "Planner must return exactly one dimension for each dimension in the existing EvalSpec: "
            f"expected {len(framework_dimension_ids)}, got {len(plan.dimensions)}."
        )
    return plan, issues


def _run_planner(
    instruction: str,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] | None,
    expected_task_count: int | None = None,
    framework_dimension_ids: list[str] | None = None,
) -> tuple[BenchmarkPlan, list[ResearchSourceMaterial]]:
    settings = role_model_settings(config, "planner")
    if not settings.configured:
        raise RuntimeError("Planner model is not configured.")
    system = benchmark_planner_system_prompt(
        BENCHMARK_PLANNER_SYSTEM_PROMPT,
        simplified=config.ablation_simplified_contract,
    )
    base_resources = _planner_resources(instruction)
    debug_root = Path(config.planner_debug_dir).expanduser() if config.planner_debug_dir else None
    debug_invocation_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    debug_dir = debug_root / debug_invocation_id if debug_root is not None else None
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        plan_document = debug_dir / "plan.json"
    else:
        plan_document = Path(tempfile.mkdtemp(prefix="evalclaw-plan-")) / "plan.json"
    initial_document = (
        {"objective": "", "dimensions": []}
        if config.ablation_simplified_contract
        else {"objective": "", "constraints": [], "planner_notes": "", "dimensions": []}
    )
    plan_document.write_text(
        json.dumps(initial_document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    document_path = str(plan_document)

    def persist_planner_debug(
        *,
        attempt: int,
        status: str,
        raw_response: str | None = None,
        validation_issues: list[str] | None = None,
        error: Exception | None = None,
        parsed_keys: list[str] | None = None,
    ) -> None:
        if debug_root is None:
            return
        phase = "initial" if attempt == 1 else "repair"
        stem = f"attempt-{attempt:02d}-{phase}"
        try:
            assert debug_dir is not None
            debug_dir.mkdir(parents=True, exist_ok=True)
            response_path = debug_dir / f"{stem}.response.txt"
            if raw_response is not None:
                response_path.write_text(raw_response, encoding="utf-8")
            diagnostics = {
                "invocation_id": debug_invocation_id,
                "model": settings.model,
                "backend": config.llm_backend,
                "attempt": attempt,
                "phase": phase,
                "status": status,
                "response_file": response_path.name if response_path.exists() else None,
                "response_bytes": response_path.stat().st_size if response_path.exists() else 0,
                "parsed_top_level_keys": parsed_keys or [],
                "validation_issues": validation_issues or [],
                "error_type": type(error).__name__ if error is not None else None,
                "error": str(error) if error is not None else None,
            }
            (debug_dir / f"{stem}.diagnostics.json").write_text(
                json.dumps(diagnostics, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            if log:
                log(f"  Planner: could not save debug artifacts ({exc}).")

    errors: list[str] = []
    previous_response: object | None = None
    source_materials: dict[str, ResearchSourceMaterial] = {}
    max_calls = _bounded_int(config.planner_tool_max_calls, default=20, minimum=1, maximum=100)
    max_chars = _bounded_int(config.planner_tool_max_chars, default=50_000, minimum=1000, maximum=100_000)
    max_attempts = max(1, config.max_planner_iterations)
    for attempt in range(1, max_attempts + 1):
        user_content = base_resources
        if errors:
            user_content += (
                "\n\n<FILE path=\"resources/repair.json\">\n"
                + json.dumps(
                    {
                        "attempt": attempt,
                        "issues": errors,
                        "previous_response": previous_response,
                        "instruction": (
                            "Return the complete planning JSON file again. Fix every listed issue "
                            "while changing sound parts as little as possible."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n</FILE>"
            )
        if log:
            log(f"  Planner: designing dimensions and TaskDesigns ({attempt}/{max_attempts}).")
        raw: str | None = None
        parsed_response: object | None = None
        try:
            raw = _run_planner_tool_loop(
                user_content,
                system,
                config,
                settings,
                max_calls=max_calls,
                max_chars=max_chars,
                source_materials=source_materials,
                debug_dir=debug_dir,
                trace_name=f"planner-attempt-{attempt:02d}",
                document_path=document_path,
            )
            parsed_response = extract_json(raw)
            previous_response = parsed_response
            plan, errors = _parse_plan_response(
                {"plan": parsed_response},
                config,
                expected_task_count=expected_task_count,
                framework_dimension_ids=framework_dimension_ids,
            )
        except Exception as exc:
            errors = [f"{type(exc).__name__}: {exc}"]
            persist_planner_debug(
                attempt=attempt,
                status="response_invalid" if raw is not None else "call_failed",
                raw_response=raw,
                validation_issues=errors,
                error=exc,
                parsed_keys=(
                    list(parsed_response)
                    if isinstance(parsed_response, dict)
                    else None
                ),
            )
            if log:
                log(f"  Planner: attempt {attempt} failed: {errors[0][:500]}")
            continue
        persist_planner_debug(
            attempt=attempt,
            status="deterministic_audit_failed" if errors else "accepted",
            raw_response=raw,
            validation_issues=errors,
            parsed_keys=list(parsed_response) if isinstance(parsed_response, dict) else None,
        )
        if errors and log:
            log(
                f"  Planner: attempt {attempt} failed deterministic audit with "
                f"{len(errors)} issue(s)."
            )
            for issue in errors[:8]:
                log(f"    - {issue[:500]}")
        if not errors:
            completed = plan.model_copy(update={"audit": BenchmarkPlanAudit(passed=True)})
            if log:
                log(
                    f"  Planner: completed {len(completed.dimensions)} dimension(s), "
                    f"{len(completed.builder_jobs)} TaskDesign builder job(s), and "
                    f"{sum(job.planned_task_count for job in completed.builder_jobs)} task(s)."
                )
            return completed, list(source_materials.values())
    raise RuntimeError(
        "Planner could not produce a valid benchmark plan: " + "; ".join(errors[:12])
    )


def plan_benchmark(
    goal: str,
    config: BenchmarkConfig,
    *,
    feedback: str | None = None,
    previous_plan: BenchmarkPlan | None = None,
    log: Callable[[str], None] | None = None,
) -> BenchmarkPlan:
    """Turn one natural-language request into a complete set of TaskDesigns."""
    instruction = _instruction_resource(
        goal,
        config,
        feedback=feedback,
        previous_plan=previous_plan,
    )
    if role_model_settings(config, "planner").configured:
        plan, materials = _run_planner(
            instruction,
            config,
            log=log,
            expected_task_count=_explicit_total_task_count(goal),
        )
        if materials:
            config.research_brief = ResearchBrief(source_materials=materials)
        return plan
    raise RuntimeError(
        "Planner model is not configured. Benchmark planning requires a configured Planner role "
        "and does not substitute a local plan."
    )


def plan_from_spec(
    spec: EvalSpec,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] | None = None,
) -> BenchmarkPlan:
    """Re-plan an explicitly supplied benchmark outline through the same Skill path."""
    if not role_model_settings(config, "planner").configured:
        raise RuntimeError(
            "Planner model is not configured. Benchmark re-planning requires a configured Planner role."
        )
    instruction = (
        "Design the complete benchmark plan represented by the following existing outline. "
        "Preserve its objective, dimensions, task counts, task types, scoring contracts, and constraints, "
        "while supplying the complete TaskDesign detail required by the Planner Skill.\n\n"
        + json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    expected_task_count = (
        sum(int(dimension.target_item_count) for dimension in spec.dimensions)
        if spec.dimensions
        and all(dimension.target_item_count is not None for dimension in spec.dimensions)
        else None
    )
    plan, materials = _run_planner(
        _instruction_resource(instruction, config),
        config,
        log=log,
        expected_task_count=expected_task_count,
        framework_dimension_ids=[dimension.id for dimension in spec.dimensions],
    )
    if materials:
        config.research_brief = ResearchBrief(source_materials=materials)
    return plan


def plan_blueprints_for_spec(
    spec: EvalSpec,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] | None = None,
) -> list[TaskBlueprint]:
    return plan_from_spec(spec, config, log=log).builder_jobs


__all__ = ["plan_benchmark", "plan_blueprints_for_spec", "plan_from_spec"]
