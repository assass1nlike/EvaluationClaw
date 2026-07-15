"""Per-item static quality checks."""
from __future__ import annotations

import re

from ..protocols.agent_task_package import agent_task_package_issues
from ..protocols.multimodal import MULTIMODAL_METADATA_KEY, MULTIMODAL_SCHEMA_VERSION
from ..protocols.science import science_metadata_issues
from ..protocols.task_agent import TASK_AGENT_METADATA_KEY
from ..types import BenchmarkItem, QcCategory, QcIssue, QcSeverity, TaskType
from .common import _issue


def _normalize_mc_text(text: str) -> str:
    normalized = str(text).strip().lower()
    normalized = re.sub(r"^\s*[a-z]\s*[\).:\uff1a]\s*", "", normalized)
    normalized = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"\1/\2", normalized)
    normalized = re.sub(r"\\left|\\right|\\[()[\]{}$]", " ", normalized)
    normalized = re.sub(r"\\+", "", normalized)
    normalized = normalized.replace(",", "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" .,:;\uff0c\u3002\uff1b\uff1a")


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
    match = re.match(r"^\s*([A-Z])\s*[\).:\uff1a]", stripped, flags=re.IGNORECASE)
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

def _task_structure_prevalidated(item: BenchmarkItem) -> bool:
    validation = item.metadata.get("task_structure_validation") if isinstance(item.metadata, dict) else None
    return isinstance(validation, dict) and validation.get("status") == "passed"


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
    task_structure_prevalidated = _task_structure_prevalidated(item)
    if item.task_type in {TaskType.multi_turn, TaskType.agent_interaction} and not task_structure_prevalidated:
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
    for message in science_metadata_issues(item):
        issues.append(
            _issue(
                item.id,
                QcSeverity.warning,
                QcCategory.schema,
                message,
                "Use metadata.science with schema_version evalclaw.science.v1 and populate the required science fields.",
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
        if not isinstance(env, dict):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "Agent interaction item must define canonical metadata.agent_env.",
                )
            )
        else:
            visible = set(env.get("visible_files") or {}) if isinstance(env.get("visible_files"), dict) else set()
            runtime = set(env.get("runtime_files") or {}) if isinstance(env.get("runtime_files"), dict) else set()
            hidden = set(env.get("hidden_files") or {}) if isinstance(env.get("hidden_files"), dict) else set()
            overlap = (visible & runtime) | (visible & hidden) | (runtime & hidden)
            if overlap:
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.schema,
                        "Environment file paths overlap across visible/runtime/evaluation phases: "
                        + ", ".join(sorted(overlap)),
                    )
                )
            setup_text = "\n".join(str(command) for command in env.get("setup_commands", []))
            hidden_in_setup = [
                path for path in hidden if path in setup_text or path.rsplit("/", 1)[-1] in setup_text
            ]
            if "/tmp/hidden_files" in setup_text or hidden_in_setup:
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.schema,
                        "setup_commands reference evaluator-only hidden_files.",
                        "Move setup-only server/application assets to runtime_files.",
                    )
                )
        if task_structure_prevalidated:
            return issues
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
        if isinstance(env, dict) and env.get("type") == "gui_desktop":
            session = env.get("session")
            evaluation = env.get("evaluation")
            vm = env.get("vm")
            if not isinstance(session, dict) or not session:
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.schema,
                        "GUI desktop agent item needs metadata.agent_env.session.",
                        "Add session.application, launch/start state, input assets, expected artifacts, and task restrictions.",
                    )
                )
            if not isinstance(evaluation, dict) or not evaluation:
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.scoring,
                        "GUI desktop agent item needs metadata.agent_env.evaluation.",
                        "Add bridge artifact/state checks with pass, partial, and fail criteria.",
                    )
                )
            if bool(env.get("requires_vm")) and (not isinstance(vm, dict) or not vm):
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.schema,
                        "GUI desktop item with requires_vm=true needs metadata.agent_env.vm.",
                        "Add VM image/template, snapshot/reset behavior, display, required software, network, and locale requirements.",
                    )
                )
        for package_issue in agent_task_package_issues(item):
            severity = QcSeverity.error if "missing metadata.agent_task_package" in package_issue else QcSeverity.warning
            issues.append(
                _issue(
                    item.id,
                    severity,
                    QcCategory.schema,
                    package_issue,
                    "Add or repair metadata.agent_task_package with visible_inputs, hidden_references, output_contract, execution, evaluation, artifact_collection, trajectory_requirements, and provenance.",
                )
            )
    return issues
