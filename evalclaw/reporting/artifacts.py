"""Artifact exporters for interoperability with external eval runners."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..types import TaskSuite, TaskType


def _safe_task_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", value.lower()).strip("_")
    return name or "evalclaw_task"


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _portable_path(value: Path) -> str:
    return value.as_posix()


def _write_lm_eval_task(
    *,
    items: list,
    task_name: str,
    output_type: str,
    metric: str,
    artifacts_dir: Path,
) -> tuple[Path, Path]:
    jsonl_path = artifacts_dir / f"{task_name}.jsonl"
    yaml_path = artifacts_dir / f"{task_name}.yaml"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for item in items:
            choice_ids = [choice.id for choice in item.choices]
            answer: str | int = item.expected_text or ""
            if item.task_type == TaskType.choice:
                answer = choice_ids.index(item.correct_choice_ids[0])
            record = {
                "id": item.id,
                "dimension_id": item.dimension_id,
                "question": item.prompt,
                "assets": [asset.model_dump(mode="json") for asset in item.assets],
                "choices": [choice.text for choice in item.choices],
                "answer": answer,
                "correct_choice_ids": item.correct_choice_ids,
                "expected_text": item.expected_text or "",
                "judge_tools": [tool.model_dump(mode="json") for tool in item.judge_tools],
                "rubric": item.rubric or "",
                "challenge_effort": item.challenge_effort.value,
                "task_type": item.task_type.value,
                "source": item.source.model_dump(mode="json"),
                "tags": item.tags,
                "metadata": item.metadata,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    yaml_lines = [
        f"task: {task_name}",
        "dataset_path: json",
        "dataset_kwargs:",
        "  data_files:",
        f"    test: {_yaml_scalar(_portable_path(jsonl_path))}",
        "test_split: test",
        f"output_type: {output_type}",
        'doc_to_text: "{{question}}"',
        'doc_to_target: "{{answer}}"',
    ]
    if output_type == "multiple_choice":
        yaml_lines.append('doc_to_choice: "{{choices}}"')
    yaml_lines.extend(
        [
            "metric_list:",
            f"  - metric: {metric}",
            "    aggregation: mean",
            "    higher_is_better: true",
            "metadata:",
            f"  source: {_yaml_scalar('evalclaw')}",
            "",
        ]
    )
    yaml_path.write_text("\n".join(yaml_lines), encoding="utf-8")
    return jsonl_path, yaml_path


def write_lm_eval_artifacts(suite: TaskSuite, out_dir: Path) -> dict[str, Path]:
    """Export only task families that lm-eval can score without changing semantics."""
    artifacts_dir = out_dir / "lm-eval"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    base_name = _safe_task_name(suite.spec.id)
    multiple_choice = [
        item
        for item in suite.tasks
        if item.task_type == TaskType.choice
        and item.choices
        and len(item.correct_choice_ids) == 1
        and not item.assets
    ]
    exact_match = [
        item
        for item in suite.tasks
        if item.task_type == TaskType.fill_blank and item.expected_text and not item.assets
    ]
    supported_ids = {item.id for item in [*multiple_choice, *exact_match]}
    unsupported_ids = [item.id for item in suite.tasks if item.id not in supported_ids]

    artifacts: dict[str, Path] = {}
    if multiple_choice:
        jsonl_path, yaml_path = _write_lm_eval_task(
            items=multiple_choice,
            task_name=f"{base_name}_multiple_choice",
            output_type="multiple_choice",
            metric="acc",
            artifacts_dir=artifacts_dir,
        )
        artifacts["jsonl_multiple_choice"] = jsonl_path
        artifacts["yaml_multiple_choice"] = yaml_path
    if exact_match:
        jsonl_path, yaml_path = _write_lm_eval_task(
            items=exact_match,
            task_name=f"{base_name}_exact_match",
            output_type="generate_until",
            metric="exact_match",
            artifacts_dir=artifacts_dir,
        )
        artifacts["jsonl_exact_match"] = jsonl_path
        artifacts["yaml_exact_match"] = yaml_path

    metadata_path = artifacts_dir / f"{base_name}.metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "spec": suite.spec.model_dump(mode="json"),
                "accepted_item_count": len(suite.tasks),
                "exported_item_count": len(supported_ids),
                "unsupported_item_ids": unsupported_ids,
                "notes": (
                "Only accepted text-only choice and exact fill-blank items "
                    "are exported. Rubric-judged and executable tasks remain direct-runner only."
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    artifacts["metadata"] = metadata_path
    return artifacts


def write_artifact_manifest(
    out_dir: Path,
    *,
    package_path: Path,
    report_path: Path,
    frontend_report_path: Path | None = None,
    task_viewer_path: Path | None = None,
    translated_report_path: Path | None = None,
    lm_eval_paths: dict[str, Path],
    research_brief_paths: dict[str, Path] | None = None,
) -> Path:
    """Write a stable machine-readable index of generated artifacts."""
    payload = {
        "package": str(package_path),
        "report": str(report_path),
        "lm_eval": {key: str(value) for key, value in lm_eval_paths.items()},
        "notes": [
            "package is the canonical EvaluationClaw JSON payload.",
            "report is a human-readable Markdown summary.",
            "frontend_report is a self-contained browser report when present.",
            "task_viewer is a self-contained page for browsing generated task content.",
            "lm_eval artifacts are interoperability exports and may require custom judging for generation tasks.",
        ],
    }
    if frontend_report_path is not None:
        payload["frontend_report"] = str(frontend_report_path)
    if task_viewer_path is not None:
        payload["task_viewer"] = str(task_viewer_path)
    if translated_report_path is not None:
        payload["translated_report"] = str(translated_report_path)
        payload["notes"].append(
            "translated_report is an optional Planner-generated translation of the Markdown report."
        )
    if research_brief_paths:
        payload["research_brief"] = {key: str(value) for key, value in research_brief_paths.items()}
        payload["notes"].append(
            "research_brief artifacts capture the deep-research grounding used for planning and generation."
        )
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path
