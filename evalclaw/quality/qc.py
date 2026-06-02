"""Quality-control gate for generated benchmark datasets."""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter

from ..llm import call_llm, extract_json
from ..prompts.qc import QC_SYSTEM_PROMPT
from ..protocols.multimodal import MULTIMODAL_METADATA_KEY, MULTIMODAL_SCHEMA_VERSION
from ..protocols.task_agent import TASK_AGENT_METADATA_KEY, compact_task_agent_for_qc
from ..types import (
    BenchmarkConfig,
    BenchmarkDataset,
    BenchmarkItem,
    Message,
    QcCategory,
    QcIssue,
    QcReport,
    QcSeverity,
    SourceKind,
    TaskType,
)

DIFFICULTY_RANK = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}


def _normalize_mc_text(text: str) -> str:
    normalized = str(text).strip().lower()
    normalized = re.sub(r"^\s*[a-z]\s*[\).:：]\s*", "", normalized)
    normalized = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"\1/\2", normalized)
    normalized = re.sub(r"\\left|\\right|\\[()[\]{}$]", " ", normalized)
    normalized = re.sub(r"\\+", "", normalized)
    normalized = normalized.replace(",", "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" .,:;，。；：")


def _mc_answer_has_choice(answer: str | None, choices: list[str]) -> bool:
    if not answer:
        return False
    stripped = answer.strip()
    if len(stripped) == 1 and "A" <= stripped.upper() <= chr(ord("A") + len(choices) - 1):
        return True
    answer_text = _normalize_mc_text(stripped)
    return any(answer_text == _normalize_mc_text(choice) for choice in choices)


def _mc_answer_letter(answer: str | None, choices: list[str]) -> str | None:
    if not answer:
        return None
    stripped = answer.strip()
    if len(stripped) == 1 and "A" <= stripped.upper() <= chr(ord("A") + len(choices) - 1):
        return stripped.upper()
    match = re.match(r"^\s*([A-Z])\s*[\).:：]", stripped, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    answer_text = _normalize_mc_text(stripped)
    for index, choice in enumerate(choices):
        if answer_text == _normalize_mc_text(choice):
            return chr(ord("A") + index)
    return None


def _rubric_answer_letter(rubric: str | None) -> str | None:
    if not rubric:
        return None
    for pattern in (
        r"(?:correct\s+answer|answer)\s*(?:is)?\s*[:=]?\s*([A-Z])\b",
        r"\b([A-Z])\s+is\s+the\s+correct\s+answer\b",
    ):
        match = re.search(pattern, rubric, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def _issue(
    item_id: str | None,
    severity: QcSeverity,
    category: QcCategory,
    message: str,
    suggested_action: str = "",
) -> QcIssue:
    return QcIssue(
        item_id=item_id,
        severity=severity,
        category=category,
        message=message,
        suggested_action=suggested_action,
    )


def _static_item_issues(item: BenchmarkItem) -> list[QcIssue]:
    issues: list[QcIssue] = []
    if not item.prompt.strip():
        issues.append(_issue(item.id, QcSeverity.error, QcCategory.schema, "Prompt is empty."))
    if len(item.prompt.strip()) < 20:
        issues.append(
            _issue(
                item.id,
                QcSeverity.warning,
                QcCategory.clarity,
                "Prompt is very short and may be under-specified.",
                "Add concrete context and expected behavior.",
            )
        )
    if item.task_type == TaskType.multiple_choice:
        if len(item.choices) < 2:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "Multiple-choice item has fewer than two choices.",
                )
            )
        if not item.answer:
            issues.append(
                _issue(item.id, QcSeverity.error, QcCategory.scoring, "Multiple-choice item lacks answer.")
            )
        elif not _mc_answer_has_choice(item.answer, item.choices):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.scoring,
                    "Multiple-choice answer does not identify one of the provided choices.",
                    "Use a valid option letter or exact choice text.",
                )
            )
        normalized_choices = [_normalize_mc_text(choice) for choice in item.choices]
        if len(set(normalized_choices)) < len(normalized_choices):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.scoring,
                    "Multiple-choice item has duplicate or indistinguishable choices.",
                    "Rewrite choices so exactly one answer is clearly correct.",
                )
            )
        answer_letter = _mc_answer_letter(item.answer, item.choices)
        rubric_letter = _rubric_answer_letter(item.rubric)
        if answer_letter and rubric_letter and answer_letter != rubric_letter:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.scoring,
                    f"Multiple-choice answer ({answer_letter}) conflicts with rubric reference answer ({rubric_letter}).",
                    "Fix the answer key or rewrite the rubric before running this item.",
                )
            )
    if item.task_type == TaskType.yes_no and (item.answer or "").lower() not in {"yes", "no"}:
        issues.append(
            _issue(item.id, QcSeverity.error, QcCategory.scoring, "Yes/no item answer must be yes or no.")
        )
    if (
        item.task_type
        in {TaskType.open_generation, TaskType.multi_turn, TaskType.agent_interaction, TaskType.pairwise_preference}
        and not item.rubric
    ):
        issues.append(
            _issue(
                item.id,
                QcSeverity.error,
                QcCategory.scoring,
                "Open, multi-turn, agent, or pairwise item lacks a rubric.",
                "Add a concrete scoring rubric or deterministic environment scoring note.",
            )
        )
    if item.task_type in {TaskType.multi_turn, TaskType.agent_interaction}:
        task_agent = item.metadata.get(TASK_AGENT_METADATA_KEY)
        if not isinstance(task_agent, dict):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.warning,
                    QcCategory.schema,
                    "Complex interactive item does not include metadata.task_agent.",
                    "Add metadata.task_agent with schema_version, system_prompt, initial_content, interaction, and scoring.",
                )
            )
        else:
            if task_agent.get("schema_version") != "evalclaw.task_agent.v1":
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.warning,
                        QcCategory.schema,
                        "metadata.task_agent schema_version is missing or not evalclaw.task_agent.v1.",
                        "Set metadata.task_agent.schema_version to evalclaw.task_agent.v1.",
                    )
                )
            if not str(task_agent.get("system_prompt") or "").strip():
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.warning,
                        QcCategory.clarity,
                        "metadata.task_agent lacks a system_prompt.",
                        "Define the task-specific agent role and behavior in metadata.task_agent.system_prompt.",
                    )
                )
            scoring = task_agent.get("scoring")
            if not isinstance(scoring, dict) or not str(scoring.get("instructions") or scoring.get("method") or "").strip():
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.warning,
                        QcCategory.scoring,
                        "metadata.task_agent lacks clear scoring guidance.",
                        "Add scoring.method plus scoring.instructions, levels, or pass_fail standards.",
                )
            )
    multimodal = item.metadata.get(MULTIMODAL_METADATA_KEY)
    if isinstance(multimodal, dict):
        schema_version = str(multimodal.get("schema_version") or "")
        if schema_version != MULTIMODAL_SCHEMA_VERSION:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.warning,
                    QcCategory.schema,
                    "metadata.multimodal schema_version is missing or not evalclaw.multimodal.v1.",
                    "Set metadata.multimodal.schema_version to evalclaw.multimodal.v1.",
                )
            )
        modalities = multimodal.get("modalities")
        if not isinstance(modalities, list) or not modalities:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.warning,
                    QcCategory.schema,
                    "metadata.multimodal.modalities must be a non-empty list.",
                    "List the modalities used by this item, such as image, audio, or video.",
                )
            )
        assets = multimodal.get("assets")
        if not isinstance(assets, list) or not assets:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "metadata.multimodal.assets must be a non-empty list.",
                    "Add at least one media asset with an id and source information.",
                )
            )
        content = multimodal.get("content")
        if content is not None and not isinstance(content, list):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "metadata.multimodal.content must be a list when provided.",
                    "Use ordered multimodal content blocks with text and asset references.",
                )
            )
    if item.rubric:
        rubric_lower = item.rubric.lower()
        contradiction_markers = ("actually", "careful", "extraneous", "undefined", "not in domain", "however")
        if "correct answer" in rubric_lower and any(marker in rubric_lower for marker in contradiction_markers):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.scoring,
                    "Rubric appears to contain a self-correction or contradictory reference answer.",
                    "Rewrite the rubric so the reference answer is unambiguous and domain restrictions are explicit.",
                )
            )
    if item.task_type == TaskType.short_answer and not item.answer and not item.rubric:
        issues.append(
            _issue(
                item.id,
                QcSeverity.error,
                QcCategory.scoring,
                "Short-answer item needs an exact answer or rubric.",
            )
        )
    if item.task_type == TaskType.code_execution and not item.test_code:
        issues.append(
            _issue(item.id, QcSeverity.error, QcCategory.scoring, "Code execution item lacks test_code.")
        )
    if item.task_type == TaskType.agent_interaction:
        env = item.metadata.get("agent_env")
        if env is not None and not isinstance(env, dict):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "Agent interaction item metadata.agent_env must be an object when provided.",
                )
            )
        if isinstance(env, dict) and env.get("type") == "code_sandbox":
            hidden_files = env.get("hidden_files")
            visible_files = env.get("visible_files") or env.get("files")
            if not isinstance(visible_files, dict):
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.schema,
                        "Code sandbox agent item needs metadata.agent_env.visible_files or files.",
                    )
                )
            if not isinstance(hidden_files, dict) and not env.get("test_command"):
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.warning,
                        QcCategory.scoring,
                        "Code sandbox item has no hidden_files and no explicit test_command.",
                        "Add hidden tests or a deterministic test command.",
                    )
                )
    return issues


def _duplicate_issues(items: list[BenchmarkItem]) -> list[QcIssue]:
    issues: list[QcIssue] = []
    for idx, item in enumerate(items):
        for other in items[idx + 1 :]:
            ratio = difflib.SequenceMatcher(None, item.prompt.lower(), other.prompt.lower()).ratio()
            if ratio >= 0.92:
                severity = QcSeverity.error if ratio >= 0.98 else QcSeverity.warning
                issues.append(
                    _issue(
                        other.id,
                        severity,
                        QcCategory.duplicate,
                        f"Prompt is very similar to {item.id} (similarity {ratio:.2f}).",
                        "Rewrite one item to test a distinct behavior.",
                    )
                )
    return issues


def _coverage_issues(dataset: BenchmarkDataset) -> list[QcIssue]:
    issues: list[QcIssue] = []
    counts = Counter(item.dimension_id for item in dataset.items)
    task_counts = Counter(item.task_type for item in dataset.items)
    for dimension in dataset.spec.dimensions:
        dim_items = [item for item in dataset.items if item.dimension_id == dimension.id]
        if not dim_items:
            issues.append(
                _issue(
                    None,
                    QcSeverity.error,
                    QcCategory.coverage,
                    f"Dimension {dimension.id} has no generated items.",
                    "Generate at least one item for every planned dimension.",
                )
            )
            continue
        if dataset.spec.scale_budget.value == "high" and len(dim_items) < 2:
            issues.append(
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.coverage,
                    f"High-budget dimension {dimension.id} has only {len(dim_items)} item(s).",
                    "Add more targeted items or Loop 3 expansion before treating this as a deep evaluation.",
                )
            )
        target_rank = DIFFICULTY_RANK.get(dimension.target_difficulty.value, 4)
        low_items = [
            item.id
            for item in dim_items
            if DIFFICULTY_RANK.get(item.difficulty.value, 3) < target_rank
        ]
        if low_items:
            issues.append(
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.difficulty,
                    f"Dimension {dimension.id} has {len(low_items)} item(s) below target difficulty {dimension.target_difficulty.value}.",
                    "Increase item difficulty without drifting from the user's requested content.",
                )
            )
        if dimension.needs_research:
            backed = [
                item
                for item in dim_items
                if item.source.kind in {SourceKind.web, SourceKind.hf_dataset, SourceKind.lm_eval, SourceKind.imported}
            ]
            if not backed:
                issues.append(
                    _issue(
                        None,
                        QcSeverity.warning,
                        QcCategory.coverage,
                        f"Dimension {dimension.id} requested research but has no source-backed items.",
                        "Use high-quality external sources or explicitly document why generation is preferable.",
                    )
                )
    for task_type in dataset.spec.task_types:
        if task_counts[task_type] == 0:
            issues.append(
                _issue(
                    None,
                    QcSeverity.warning,
                    QcCategory.coverage,
                    f"Planned task type {task_type.value} has no generated items.",
                    "Generate at least one item for each planned task type or remove it from the spec.",
                )
            )
    return issues


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
                env_summary[f"{key}_preview"] = {
                    name: str(content)[:500] for name, content in list(files.items())[:5]
                }
        for key in ("rooms", "goal"):
            value = env.get(key)
            if isinstance(value, dict):
                env_summary[key] = value
        compact["agent_env"] = env_summary
    task_agent = metadata.get(TASK_AGENT_METADATA_KEY)
    if isinstance(task_agent, dict):
        compact[TASK_AGENT_METADATA_KEY] = compact_task_agent_for_qc(task_agent)

    for key, value in metadata.items():
        if key in {"agent_env", TASK_AGENT_METADATA_KEY}:
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
    if not isinstance(env, dict) or env.get("type") != "code_sandbox":
        return issue
    if not isinstance(env.get("hidden_files"), dict) or not env.get("test_command"):
        return issue
    message = issue.message.lower()
    false_positive_markers = ("hidden", "not visible", "unverifiable", "unexecutable")
    if "hidden" in message and any(marker in message for marker in false_positive_markers):
        return issue.model_copy(
            update={
                "severity": QcSeverity.warning,
                "message": (
                    issue.message
                    + " Note: EvaluationClaw code_sandbox hidden files are executable by the "
                    "runner via test_command; this was demoted from an LLM QC blocking error."
                ),
            }
        )
    return issue


def _llm_qc(dataset: BenchmarkDataset, config: BenchmarkConfig) -> list[QcIssue]:
    if not config.orchestrator_api_key:
        return []
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
        for item in dataset.items[:50]
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


def run_qc_gate(dataset: BenchmarkDataset, config: BenchmarkConfig) -> QcReport:
    """Run MVP static QC plus optional LLM review."""
    issues: list[QcIssue] = []
    for item in dataset.items:
        issues.extend(_static_item_issues(item))
        if item.task_type == TaskType.pairwise_preference and config.reference_model is None:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "Pairwise preference item requires BenchmarkConfig.reference_model.",
                    "Pass --reference-model or regenerate without pairwise_preference items.",
                )
            )
    issues.extend(_duplicate_issues(dataset.items))
    issues.extend(_coverage_issues(dataset))
    issues.extend(_llm_qc(dataset, config))

    rejected_ids = {
        issue.item_id
        for issue in issues
        if issue.item_id and issue.severity == QcSeverity.error
    }
    passed_ids = [item.id for item in dataset.items if item.id not in rejected_ids]
    total = max(1, len(dataset.items))
    penalty = sum(0.2 if issue.severity == QcSeverity.error else 0.05 for issue in issues)
    quality_score = max(0.0, min(1.0, 1.0 - penalty / total))
    summary = (
        f"QC completed: {len(passed_ids)}/{len(dataset.items)} items passed, "
        f"{len(rejected_ids)} rejected, {len(issues)} issues."
    )
    return QcReport(
        issues=issues,
        passed_item_ids=passed_ids,
        rejected_item_ids=sorted(rejected_ids),
        quality_score=quality_score,
        summary=summary,
    )
