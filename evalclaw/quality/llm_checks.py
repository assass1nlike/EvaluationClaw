"""LLM-assisted quality-control sampling and issue stabilization."""
from __future__ import annotations

import json

from ..core.scaling import is_large_scale_budget
from ..models.llm import call_llm, extract_json
from ..models.roles import role_model_settings
from ..prompts.qc import QC_SYSTEM_PROMPT
from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_METADATA_KEY,
    compact_agent_task_package,
)
from ..protocols.task_agent import TASK_AGENT_METADATA_KEY, compact_task_agent_for_qc
from ..types import (
    BenchmarkConfig,
    BenchmarkItem,
    Message,
    QcCategory,
    QcIssue,
    QcSeverity,
    TaskSuite,
    TaskType,
)
from .common import _issue


def _file_review_excerpt(content: object, limit: int = 3000) -> str:
    text = str(content or "")
    if len(text) <= limit:
        return text
    half = max(1, limit // 2)
    return text[:half] + "\n... QC REVIEW EXCERPT ...\n" + text[-half:]


def _prompt_for_qc(prompt: str, *, limit: int) -> dict[str, object]:
    complete = len(prompt) <= limit
    return {
        "prompt": prompt if complete else _file_review_excerpt(prompt, limit),
        "prompt_is_complete": complete,
        "prompt_character_count": len(prompt),
    }


def _compact_qc_value(
    value: object,
    *,
    depth: int = 0,
    string_limit: int = 1200,
) -> object:
    if isinstance(value, str):
        return (
            value
            if len(value) <= string_limit
            else _file_review_excerpt(value, string_limit)
            + "\n[QC review excerpt clipped; canonical value is complete and longer]"
        )
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= 3:
        return _compact_qc_value(str(value), string_limit=string_limit)
    if isinstance(value, list):
        return [
            _compact_qc_value(item, depth=depth + 1, string_limit=string_limit)
            for item in value[:16]
        ]
    if isinstance(value, dict):
        return {
            str(key): _compact_qc_value(
                child,
                depth=depth + 1,
                string_limit=string_limit,
            )
            for key, child in list(value.items())[:24]
        }
    return _compact_qc_value(str(value), string_limit=string_limit)


def _compact_metadata_for_qc(metadata: dict, *, string_limit: int = 1200) -> dict:
    """Keep QC context small while preserving executable environment facts."""
    if not metadata:
        return {}
    compact: dict = {}
    env = metadata.get("agent_env")
    if isinstance(env, dict):
        env_summary: dict = {}
        for key in (
            "type",
            "image",
            "network",
            "workdir",
            "max_steps",
            "timeout",
            "test_command",
            "start_room",
            "notes",
        ):
            if key in env:
                env_summary[key] = str(env[key])[:1600] if key == "notes" else env[key]
        setup_commands = env.get("setup_commands")
        if isinstance(setup_commands, list):
            env_summary["setup_commands"] = [str(command)[:1200] for command in setup_commands[:12]]
        tools = env.get("tools")
        if isinstance(tools, list):
            env_summary["declared_tools"] = [
                {
                    "name": str(tool.get("name") or ""),
                    "description": str(tool.get("description") or "")[:400],
                }
                for tool in tools[:20]
                if isinstance(tool, dict)
            ]
        browser = env.get("browser")
        if isinstance(browser, dict):
            env_summary["browser"] = {
                key: browser[key]
                for key in (
                    "enabled",
                    "runtime",
                    "start_url",
                    "allowed_origins",
                    "executable_path",
                    "workspace_tools",
                    "allow_workspace_tools",
                )
                if key in browser
            }
        image_build = env.get("image_build")
        if isinstance(image_build, dict) and image_build.get("enabled"):
            env_summary["image_build"] = {
                key: image_build[key]
                for key in (
                    "enabled",
                    "base_image",
                    "system_packages",
                    "python_packages",
                    "node_packages",
                    "commands",
                    "dockerfile",
                )
                if key in image_build
            }
        for key in ("visible_files", "files", "hidden_files"):
            files = env.get(key)
            if isinstance(files, dict):
                env_summary[f"{key}_count"] = len(files)
                env_summary[f"{key}_names"] = list(files.keys())[:20]
                env_summary[f"{key}_content_note"] = (
                    "Full file contents are omitted from the LLM QC sample to avoid "
                    "confusing compact excerpts with task truncation."
                )
                env_summary[f"{key}_review_excerpts"] = {
                    str(path): _file_review_excerpt(content)
                    for path, content in list(files.items())[:4]
                }
        for key in ("rooms", "goal"):
            value = env.get(key)
            if isinstance(value, dict):
                env_summary[key] = value
        session = env.get("session")
        if isinstance(session, dict):
            session_keys = (
                "kind",
                "application",
                "applications",
                "entrypoint",
                "start_url",
                "launch_state",
                "start_state",
                "initial_state",
                "workflow",
                "workflow_stages",
                "input_assets",
                "assets",
                "handoff_artifacts",
                "expected_artifacts",
                "baseline_checks",
            )
            env_summary["session"] = {
                key: _compact_qc_value(session[key], string_limit=string_limit)
                for key in session_keys
                if key in session
            }
        evaluation = env.get("evaluation")
        if isinstance(evaluation, dict):
            env_summary["evaluation"] = _compact_qc_value(
                evaluation,
                string_limit=string_limit,
            )
        vm = env.get("vm")
        if isinstance(vm, dict):
            env_summary["requires_vm"] = bool(env.get("requires_vm"))
            vm_keys = (
                "isolation",
                "image",
                "template",
                "template_name",
                "snapshot",
                "reset_behavior",
                "disk_image",
                "disk_path",
                "network",
                "network_policy",
                "locale",
                "display",
                "required_software",
                "required_capabilities",
                "requirements",
                "resolved_image",
                "config_drive",
                "guest_user",
                "guest_os",
                "os",
            )
            env_summary["vm"] = {
                key: _compact_qc_value(vm[key], string_limit=string_limit)
                for key in vm_keys
                if key in vm
            }
        vm_provisioning = env.get("vm_provisioning")
        if isinstance(vm_provisioning, dict) and vm_provisioning:
            env_summary["vm_provisioning"] = _compact_qc_value(
                vm_provisioning,
                string_limit=string_limit,
            )
        compact["agent_env"] = env_summary
    task_agent = metadata.get(TASK_AGENT_METADATA_KEY)
    if isinstance(task_agent, dict):
        compact[TASK_AGENT_METADATA_KEY] = compact_task_agent_for_qc(task_agent)
    agent_task_package = metadata.get(AGENT_TASK_PACKAGE_METADATA_KEY)
    if isinstance(agent_task_package, dict):
        compact[AGENT_TASK_PACKAGE_METADATA_KEY] = compact_agent_task_package(agent_task_package)

    for key, value in metadata.items():
        if key in {"agent_env", TASK_AGENT_METADATA_KEY, AGENT_TASK_PACKAGE_METADATA_KEY}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = _compact_qc_value(value, string_limit=string_limit)
        elif isinstance(value, (list, dict)):
            compact[key] = _compact_qc_value(value, string_limit=string_limit)
        else:
            compact[key] = _compact_qc_value(str(value), string_limit=string_limit)
    return compact


def _stabilize_llm_issue(issue: QcIssue, item_by_id: dict[str, BenchmarkItem]) -> QcIssue:
    """Prevent LLM QC from rejecting intentional sandbox hidden-test design."""
    if issue.severity != QcSeverity.error or not issue.item_id:
        return issue
    item = item_by_id.get(issue.item_id)
    if not item or item.task_type != TaskType.agent:
        return issue
    env = item.metadata.get("agent_env")
    if not isinstance(env, dict):
        return issue
    env_type = str(env.get("type") or "")
    message = issue.message.lower()
    if env_type == "gui_desktop":
        vm = env.get("vm")
        has_provider_request = (
            bool(env.get("requires_vm"))
            and isinstance(vm, dict)
            and bool(vm.get("guest_os") or vm.get("os"))
            and bool(vm.get("required_capabilities"))
        )
        missing_boot_source_claim = any(
            phrase in message
            for phrase in (
                "no concrete boot source",
                "no resolvable windows desktop",
                "no resolvable desktop",
                "externally managed desktop bridge endpoint",
            )
        )
        if has_provider_request and missing_boot_source_claim:
            return issue.model_copy(
                update={
                    "severity": QcSeverity.warning,
                    "message": (
                        issue.message
                        + " Note: a guest OS plus non-empty required_capabilities is a valid "
                        "VM Provider resolution request; this was demoted from an LLM QC "
                        "blocking error."
                    ),
                }
            )
    if env_type not in {"code_sandbox", "docker_workspace"}:
        return issue
    if isinstance(env.get("hidden_files"), dict) and env.get("test_command"):
        false_positive_phrases = (
            "hidden tests are not visible",
            "hidden files are not visible",
            "target cannot access the hidden",
            "agent cannot access the hidden",
            "hidden tests are not accessible to the target",
            "hidden files are not accessible to the target",
        )
        if any(phrase in message for phrase in false_positive_phrases):
            return issue.model_copy(
                update={
                    "severity": QcSeverity.warning,
                    "message": (
                        issue.message
                        + " Note: EvaluationClaw runner-private hidden files are executable "
                        "through test_command after the target agent finishes; this was "
                        "demoted from an LLM QC blocking error."
                    ),
                }
            )
    return issue


def _llm_qc_sample(suite: TaskSuite, limit: int) -> tuple[list[BenchmarkItem], dict[str, object]]:
    if limit <= 0:
        return [], {"strategy": "disabled", "sample_size": 0}
    groups: dict[str, list[BenchmarkItem]] = {}
    for item in suite.tasks:
        groups.setdefault(item.dimension_id, []).append(item)
    for group in groups.values():
        group.sort(key=lambda item: item.id)
    ordered_keys = sorted(groups)
    sample: list[BenchmarkItem] = []
    seen: set[str] = set()
    while len(sample) < min(limit, len(suite.tasks)):
        progressed = False
        for key in ordered_keys:
            group = groups[key]
            while group and group[0].id in seen:
                group.pop(0)
            if not group:
                continue
            item = group.pop(0)
            sample.append(item)
            seen.add(item.id)
            progressed = True
            if len(sample) >= limit:
                break
        if not progressed:
            break
    return sample, {
        "strategy": "stratified_by_dimension_and_task_type",
        "sample_size": len(sample),
        "total_items": len(suite.tasks),
        "groups": len(ordered_keys),
    }


def _llm_qc(
    suite: TaskSuite,
    config: BenchmarkConfig,
    *,
    trace: dict[str, object] | None = None,
) -> list[QcIssue]:
    settings = role_model_settings(config, "qc")
    if not settings.configured:
        if trace is not None:
            trace["status"] = "disabled"
        return []
    limit = 50
    if is_large_scale_budget(suite.spec.scale_budget):
        limit = max(1, int(config.large_scale_llm_qc_sample_size))
    sampled_items, sampling = _llm_qc_sample(suite, limit)
    task_design_by_id = {
        design.id: design
        for blueprint in suite.blueprints
        for design in blueprint.task_designs
    }
    sampled_design_ids = {
        str(item.metadata.get("task_design_id") or "")
        for item in sampled_items
        if str(item.metadata.get("task_design_id") or "")
    }
    prompt_limit = max(1200, min(6000, 60000 // max(1, len(sampled_items))))
    metadata_string_limit = max(
        1200,
        min(12000, 120000 // max(1, len(sampled_items))),
    )
    sample = [
        {
            "id": item.id,
            "dimension_id": item.dimension_id,
            "task_type": item.task_type.value,
            "challenge_effort": item.challenge_effort.value,
            **_prompt_for_qc(item.prompt, limit=prompt_limit),
            "choices": [choice.model_dump(mode="json") for choice in item.choices],
            "correct_choice_ids": item.correct_choice_ids,
            "expected_text": item.expected_text,
            "rubric": item.rubric,
            "judge_tools": [tool.model_dump(mode="json") for tool in item.judge_tools],
            "output_contract": item.output_contract,
            "source": item.source.model_dump(mode="json"),
            "tags": item.tags,
            "metadata": _compact_metadata_for_qc(
                item.metadata,
                string_limit=metadata_string_limit,
            ),
        }
        for item in sampled_items
    ]
    request = {
        "objective": suite.spec.objective,
        "scale_budget": suite.spec.scale_budget.value,
        "constraints": suite.spec.constraints,
        "planner_notes": suite.spec.planner_notes,
        "dimensions": [d.model_dump(mode="json") for d in suite.spec.dimensions],
        "task_designs": [
            task_design_by_id[design_id].model_dump(mode="json")
            for design_id in sorted(sampled_design_ids)
            if design_id in task_design_by_id
        ],
        "llm_qc_sampling": sampling,
        "items": sample,
    }
    if trace is not None:
        trace.update(
            {
                "status": "requested",
                "system_prompt": QC_SYSTEM_PROMPT,
                "request": request,
                "model": settings.model,
                "provider": settings.provider,
                "base_url": settings.base_url,
                "max_tokens": 4096,
            }
        )
    try:
        raw = call_llm(
            [
                Message(
                    role="user",
                    content=json.dumps(request, ensure_ascii=False, indent=2),
                )
            ],
            system=QC_SYSTEM_PROMPT,
            **settings.call_kwargs(),
            backend=config.llm_backend,
            max_tokens=4096,
        )
        if trace is not None:
            trace["raw_response"] = raw
        data = extract_json(raw)
        if trace is not None:
            trace["parsed_response"] = data
        if not isinstance(data, dict):
            if trace is not None:
                trace["status"] = "invalid_response"
            return [
                _issue(
                    None,
                    QcSeverity.error,
                    QcCategory.clarity,
                    f"LLM QC returned {type(data).__name__}; configured LLM QC did not complete.",
                    "Retry with a QC model that returns the requested object schema.",
                )
            ]
    except Exception as exc:
        if trace is not None:
            trace.update(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
        return [
            _issue(
                None,
                QcSeverity.error,
                QcCategory.clarity,
                f"LLM QC failed; refusing to accept static QC as an equivalent fallback: {str(exc)[:240]}",
                "Retry with a smaller suite, a different QC model, or local/static-only QC.",
            )
            ]
    if trace is not None:
        trace["status"] = "completed"
    issues: list[QcIssue] = []
    item_by_id = {item.id: item for item in suite.tasks}
    for raw_issue in data.get("issues", []):
        try:
            issue = QcIssue(
                item_id=raw_issue.get("item_id"),
                severity=QcSeverity(raw_issue.get("severity", "warning")),
                category=QcCategory(raw_issue.get("category", "clarity")),
                message=str(raw_issue.get("message", "")),
                suggested_action=str(raw_issue.get("suggested_action", "")),
            )
            issues.append(_stabilize_llm_issue(issue, item_by_id))
        except ValueError:
            continue
    return issues
