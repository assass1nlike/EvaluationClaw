"""LLM-assisted quality-control sampling and issue stabilization."""
from __future__ import annotations

import json

from ..core.scaling import is_large_scale_budget
from ..models.llm import call_llm, extract_json
from ..prompts.qc import QC_SYSTEM_PROMPT
from ..protocols.agent_task_package import (
    AGENT_TASK_PACKAGE_METADATA_KEY,
    compact_agent_task_package,
)
from ..protocols.task_agent import TASK_AGENT_METADATA_KEY, compact_task_agent_for_qc
from ..types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    Message,
    QcCategory,
    QcIssue,
    QcSeverity,
    TaskType,
)
from .common import _issue


def _compact_metadata_for_qc(metadata: dict) -> dict:
    """Keep QC context small while preserving executable environment facts."""
    if not metadata:
        return {}
    compact: dict = {}
    env = metadata.get("agent_env")
    if isinstance(env, dict):
        env_summary: dict = {}
        for key in ("type", "max_steps", "test_command", "start_room"):
            if key in env:
                env_summary[key] = env[key]
        for key in ("visible_files", "files", "hidden_files"):
            files = env.get(key)
            if isinstance(files, dict):
                env_summary[f"{key}_count"] = len(files)
                env_summary[f"{key}_names"] = list(files.keys())[:20]
                env_summary[f"{key}_content_note"] = (
                    "Full file contents are omitted from the LLM QC sample to avoid "
                    "confusing compact excerpts with task truncation."
                )
        for key in ("rooms", "goal"):
            value = env.get(key)
            if isinstance(value, dict):
                env_summary[key] = value
        session = env.get("session")
        if isinstance(session, dict):
            env_summary["session_keys"] = list(session.keys())[:20]
            for key in ("kind", "application", "entrypoint", "start_url"):
                if key in session:
                    env_summary[f"session_{key}"] = session[key]
            assets = session.get("assets")
            if isinstance(assets, list):
                env_summary["session_assets"] = assets[:20]
            expected_artifacts = session.get("expected_artifacts")
            if isinstance(expected_artifacts, list):
                env_summary["session_expected_artifacts"] = expected_artifacts[:20]
        evaluation = env.get("evaluation")
        if isinstance(evaluation, dict):
            env_summary["evaluation_keys"] = list(evaluation.keys())[:20]
            for key in ("method", "pass_criteria", "partial_criteria", "fail_criteria"):
                if key in evaluation:
                    env_summary[f"evaluation_{key}"] = str(evaluation[key])[:800]
        vm = env.get("vm")
        if isinstance(vm, dict):
            env_summary["requires_vm"] = bool(env.get("requires_vm"))
            env_summary["vm_keys"] = list(vm.keys())[:20]
            for key in ("isolation", "image", "snapshot", "network", "locale"):
                if key in vm:
                    env_summary[f"vm_{key}"] = vm[key]
            required_software = vm.get("required_software")
            if isinstance(required_software, list):
                env_summary["vm_required_software"] = required_software[:20]
            display = vm.get("display")
            if isinstance(display, dict):
                env_summary["vm_display"] = display
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
            compact[key] = value
        elif isinstance(value, list):
            compact[key] = value[:10]
        elif isinstance(value, dict):
            compact[key] = {str(k): v for k, v in list(value.items())[:10]}
        else:
            compact[key] = str(value)[:500]
    return compact


def _stabilize_llm_issue(issue: QcIssue, item_by_id: dict[str, BenchmarkItem]) -> QcIssue:
    """Prevent LLM QC from rejecting intentional sandbox hidden-test design."""
    if issue.severity != QcSeverity.error or not issue.item_id:
        return issue
    item = item_by_id.get(issue.item_id)
    if not item or item.task_type != TaskType.agent_interaction:
        return issue
    env = item.metadata.get("agent_env")
    if not isinstance(env, dict):
        return issue
    env_type = str(env.get("type") or "")
    if env_type not in {"code_sandbox", "docker_workspace"}:
        return issue
    message = issue.message.lower()
    if isinstance(env.get("hidden_files"), dict) and env.get("test_command"):
        false_positive_markers = (
            "hidden",
            "not visible",
            "not accessible",
            "unverifiable",
            "unexecutable",
            "may not be able to run",
        )
        if "hidden" in message and any(marker in message for marker in false_positive_markers):
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
    if (
        "deterministic" in message
        and "partial" in message
        and any(level in message for level in ("0.5", "partial credit", "partial condition"))
    ):
        return issue.model_copy(
            update={
                "severity": QcSeverity.warning,
                "message": (
                    issue.message
                    + " Note: EvaluationClaw deterministic evaluators may return fixed "
                    "numeric partial-credit levels such as 0/0.5/1; this was demoted from "
                    "an LLM QC blocking error."
                ),
            }
        )
    task_agent = item.metadata.get("task_agent")
    scoring = task_agent.get("scoring") if isinstance(task_agent, dict) else None
    if isinstance(scoring, dict) and ("partial" in message or "0.5" in message):
        pass_fail = scoring.get("pass_fail") if isinstance(scoring.get("pass_fail"), dict) else {}
        levels = scoring.get("levels") if isinstance(scoring.get("levels"), dict) else {}
        partial_text = str(pass_fail.get("partial") or scoring.get("partial_criteria") or "").strip().lower()
        has_partial = bool(partial_text) and partial_text not in {
            "not applicable",
            "n/a",
            "na",
            "none",
            "no partial credit",
            "not used",
        }
        has_partial_level = "0.5" in {str(key) for key in levels} or "partial" in {
            str(value).lower() for value in levels.values()
        }
        if has_partial and has_partial_level:
            return issue.model_copy(
                update={
                    "severity": QcSeverity.warning,
                    "message": (
                        issue.message
                        + " Note: The structured task_agent.scoring metadata includes both "
                        "partial criteria and a partial score level; this was demoted from "
                        "an LLM QC blocking error."
                    ),
                }
            )
    return issue


def _llm_qc_sample(dataset: BenchmarkDataset, limit: int) -> tuple[list[BenchmarkItem], dict[str, object]]:
    if limit <= 0:
        return [], {"strategy": "disabled", "sample_size": 0}
    groups: dict[tuple[str, str], list[BenchmarkItem]] = {}
    for item in dataset.items:
        batch_id = str(item.metadata.get("batch_id") or "")
        groups.setdefault((batch_id or item.dimension_id, item.task_type.value), []).append(item)
    for group in groups.values():
        group.sort(key=lambda item: item.id)
    ordered_keys = sorted(groups)
    sample: list[BenchmarkItem] = []
    seen: set[str] = set()
    while len(sample) < min(limit, len(dataset.items)):
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
        "strategy": "stratified_by_batch_or_dimension_and_task_type",
        "sample_size": len(sample),
        "total_items": len(dataset.items),
        "groups": len(ordered_keys),
    }


def _llm_qc(dataset: BenchmarkDataset, config: BenchmarkConfig) -> list[QcIssue]:
    if not config.orchestrator_api_key:
        return []
    limit = 50
    if is_large_scale_budget(dataset.spec.scale_budget):
        limit = max(1, int(config.large_scale_llm_qc_sample_size))
    sampled_items, sampling = _llm_qc_sample(dataset, limit)
    sample = [
        {
            "id": item.id,
            "dimension_id": item.dimension_id,
            "task_type": item.task_type.value,
            "difficulty": item.difficulty.value,
            "prompt": item.prompt[:1200],
            "choices": item.choices,
            "answer": item.answer,
            "rubric": item.rubric,
            "source": item.source.model_dump(mode="json"),
            "tags": item.tags,
            "metadata": _compact_metadata_for_qc(item.metadata),
        }
        for item in sampled_items
    ]
    try:
        raw = call_llm(
            [
                Message(
                    role="user",
                    content=json.dumps(
                        {
                            "objective": dataset.spec.objective,
                            "scale_budget": dataset.spec.scale_budget.value,
                            "constraints": dataset.spec.constraints,
                            "planner_notes": dataset.spec.planner_notes,
                            "dimensions": [d.model_dump(mode="json") for d in dataset.spec.dimensions],
                            "batches": [batch.model_dump(mode="json") for batch in dataset.batches],
                            "llm_qc_sampling": sampling,
                            "items": sample,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            ],
            system=QC_SYSTEM_PROMPT,
            model=config.orchestrator_model,
            api_key=config.orchestrator_api_key,
            base_url=config.orchestrator_base_url,
            backend=config.llm_backend,
            max_tokens=4096,
        )
        data = extract_json(raw)
        if not isinstance(data, dict):
            return [
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.clarity,
                    f"LLM QC returned {type(data).__name__}; static QC was used as fallback.",
                    "Retry with a QC model that returns the requested object schema.",
                )
            ]
    except Exception as exc:
        return [
            _issue(
                None,
                QcSeverity.warning,
                QcCategory.clarity,
                f"LLM QC failed; static QC was used as fallback: {str(exc)[:240]}",
                "Retry with a smaller dataset, a different QC model, or local/static-only QC.",
            )
        ]
    issues: list[QcIssue] = []
    item_by_id = {item.id: item for item in dataset.items}
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
