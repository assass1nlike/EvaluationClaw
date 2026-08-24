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


def _rubric_has_explicit_self_correction(rubric: str | None) -> bool:
    if not rubric:
        return False
    return bool(
        re.search(
            r"\bcorrect\s+answer\b[\s\S]*?\bactually\b[\s\S]*?\b(?:so|therefore)\b[\s\S]*?\banswer\b",
            rubric,
            flags=re.IGNORECASE,
        )
    )


def _item_environment_has_evaluator(item: BenchmarkItem) -> bool:
    env = item.metadata.get("agent_env") if isinstance(item.metadata, dict) else None
    if not isinstance(env, dict):
        return False
    env_type = str(env.get("type") or "")
    if env_type in {"code_sandbox", "docker_workspace"}:
        return bool(str(env.get("test_command") or "").strip())
    if env_type == "workspace":
        workspace = env.get("workspace") if isinstance(env.get("workspace"), dict) else env
        goal = workspace.get("goal") if isinstance(workspace, dict) else None
        return isinstance(goal, dict) and bool(goal.get("outgoing_bin"))
    if env_type == "gui_desktop":
        evaluation = env.get("evaluation")
        if not isinstance(evaluation, dict):
            return False
        if isinstance(evaluation.get("checks"), list) and evaluation["checks"]:
            return True
        return any(
            str(evaluation.get(key) or "").strip()
            for key in ("method", "evaluator", "command", "pass_criteria", "fail_criteria")
        )
    return False


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
    if item.task_type == TaskType.choice:
        if len(item.choices) < 2:
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.schema,
                    "Choice item has fewer than two choices.",
                )
            )
        choice_ids = [choice.id for choice in item.choices]
        if len(set(choice_ids)) != len(choice_ids) or any(not value.strip() for value in choice_ids):
            issues.append(
                _issue(item.id, QcSeverity.error, QcCategory.schema, "Choice option ids must be unique and non-empty.")
            )
        if not item.correct_choice_ids:
            issues.append(
                _issue(item.id, QcSeverity.error, QcCategory.scoring, "Choice item lacks correct_choice_ids.")
            )
        elif any(value not in set(choice_ids) for value in item.correct_choice_ids):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.scoring,
                    "correct_choice_ids contains an unknown option id.",
                    "Use one or more exact ids from choices.",
                )
            )
        normalized_choices = [_normalize_mc_text(choice.text) for choice in item.choices]
        if len(set(normalized_choices)) < len(normalized_choices):
            issues.append(
                _issue(
                    item.id,
                    QcSeverity.error,
                    QcCategory.scoring,
                    "Choice item has duplicate or indistinguishable choices.",
                    "Rewrite choices so every candidate is distinct.",
                )
            )
    if item.task_type == TaskType.fill_blank and not item.expected_text:
        issues.append(
            _issue(item.id, QcSeverity.error, QcCategory.scoring, "Fill-blank item lacks expected_text.")
        )
    if item.task_type in {TaskType.generation, TaskType.multi_turn} and not item.rubric:
        issues.append(
            _issue(
                item.id,
                QcSeverity.error,
                QcCategory.scoring,
                "Generation or multi-turn item lacks a scoring rubric.",
                "Add a concrete rubric for the judge.",
            )
        )
    for judge_tool in item.judge_tools:
        if judge_tool.tool != "python_tests":
            issues.append(
                _issue(item.id, QcSeverity.error, QcCategory.schema, f"Unsupported judge tool: {judge_tool.tool}.")
            )
            continue
        if item.task_type not in {TaskType.generation, TaskType.multi_turn, TaskType.agent}:
            issues.append(
                _issue(item.id, QcSeverity.error, QcCategory.schema, "This task type does not support judge_tools.")
            )
        if judge_tool.tool == "python_tests":
            test_code = str(judge_tool.config.get("test_code") or "")
            if not test_code.strip() or "{model_output}" not in test_code:
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.scoring,
                        "python_tests requires config.test_code that consumes {model_output}.",
                    )
                )
    if (
        item.task_type == TaskType.agent
        and not item.rubric
        and not _item_environment_has_evaluator(item)
    ):
        issues.append(
            _issue(
                item.id,
                QcSeverity.error,
                QcCategory.scoring,
                "Agent interaction item has neither scoring guidance nor an executable environment evaluator.",
                "Add task scoring criteria or a runtime evaluator that scores the resulting state or artifacts.",
            )
        )
    task_structure_prevalidated = _task_structure_prevalidated(item)
    if item.task_type in {TaskType.multi_turn, TaskType.agent} and not task_structure_prevalidated:
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
        else:
            unsupported_modalities = sorted(
                {
                    str(modality).strip().lower()
                    for modality in modalities
                    if str(modality).strip().lower() not in {"text", "image"}
                }
            )
            if unsupported_modalities:
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.schema,
                        "Native multimodal execution currently supports image assets, not: "
                        + ", ".join(unsupported_modalities),
                        "Use image/text input or add a runner adapter that sends the requested modality natively.",
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
            asset_ids: set[str] = set()
        else:
            asset_ids = set()
            for index, asset in enumerate(assets, 1):
                if not isinstance(asset, dict):
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.schema,
                            f"Multimodal asset #{index} must be an object.",
                        )
                    )
                    continue
                asset_id = str(asset.get("id") or "").strip()
                if not asset_id:
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.schema,
                            f"Multimodal asset #{index} lacks a stable id.",
                        )
                    )
                elif asset_id in asset_ids:
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.schema,
                            f"Multimodal asset id {asset_id!r} is duplicated.",
                        )
                    )
                else:
                    asset_ids.add(asset_id)
                if not str(asset.get("kind") or "").strip():
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.schema,
                            f"Multimodal asset {asset_id or index!r} lacks a kind.",
                        )
                    )
                if not any(
                    str(asset.get(key) or "").strip()
                    for key in ("uri", "path", "data_uri")
                ):
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.schema,
                            f"Multimodal asset {asset_id or index!r} has no resolvable source.",
                            "Set uri, path, or data_uri so the runner can load the asset.",
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
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict) or str(part.get("type") or "").lower() != "asset":
                    continue
                asset_id = str(part.get("asset_id") or part.get("assetId") or "").strip()
                if not asset_id or asset_id not in asset_ids:
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.schema,
                            f"Multimodal content references unknown asset {asset_id or '<missing>'!r}.",
                            "Reference one of metadata.multimodal.assets by its stable id.",
                        )
                    )
    if item.task_type != TaskType.choice and _rubric_has_explicit_self_correction(item.rubric):
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
    if item.task_type == TaskType.agent:
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
        if not task_structure_prevalidated and isinstance(env, dict):
            env_type = str(env.get("type") or "")
            if env.get("tools"):
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.schema,
                        "metadata.agent_env.tools cannot create executable custom tools.",
                        "Use the selected runtime's supported structured configuration and tool surface.",
                    )
                )
            if env_type in {"code_sandbox", "docker_workspace"} and not str(
                env.get("test_command") or ""
            ).strip():
                issues.append(
                    _issue(
                        item.id,
                        QcSeverity.error,
                        QcCategory.scoring,
                        f"{env_type} item lacks an explicit test_command.",
                        "Add the deterministic evaluator command that the runner should invoke.",
                    )
                )
            if env_type == "workspace":
                workspace = env.get("workspace") if isinstance(env.get("workspace"), dict) else env
                rooms = workspace.get("rooms") if isinstance(workspace, dict) else None
                goal = workspace.get("goal") if isinstance(workspace, dict) else None
                if not isinstance(rooms, dict) or not rooms or not (
                    isinstance(goal, dict) and goal.get("outgoing_bin")
                ):
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.schema,
                            "Workspace item needs room state and a non-empty outgoing-bin goal.",
                            "Define the built-in room/inventory state instead of file or custom-tool behavior.",
                        )
                    )
            if env_type == "gui_desktop":
                session = env.get("session")
                vm = env.get("vm")
                if not isinstance(session, dict) or not session:
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.schema,
                            "GUI desktop agent item needs metadata.agent_env.session.",
                            "Add the application/desktop surface and launch state.",
                        )
                    )
                if not _item_environment_has_evaluator(item):
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.scoring,
                            "GUI desktop agent item needs executable evaluation checks or a method.",
                            "Add bridge artifact/state checks or a concrete evaluator method.",
                        )
                    )
                if bool(env.get("requires_vm")) and (
                    not isinstance(vm, dict)
                    or not any(
                        str(vm.get(key) or "").strip()
                        for key in ("template", "template_name", "image", "disk_image", "disk_path")
                    )
                ):
                    issues.append(
                        _issue(
                            item.id,
                            QcSeverity.error,
                            QcCategory.schema,
                            "GUI desktop item with requires_vm=true lacks a resolvable VM source.",
                            "Set a template, image, or disk identifier; keep descriptive prose in notes.",
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
