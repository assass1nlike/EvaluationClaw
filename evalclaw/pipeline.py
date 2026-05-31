"""EvaluationClaw orchestration pipeline."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from .artifacts import write_artifact_manifest, write_lm_eval_artifacts
from .improver import run_loop3_improvement
from .lm_eval_runner import run_lm_eval
from .planner import plan_eval_spec, translate_goal_to_english
from .planning_loop import (
    apply_human_review_feedback,
    format_human_review_overview,
    generate_dataset_with_qc_loop,
)
from .report_viewer import build_report_viewer_html
from .reporter import artifact_index_markdown, build_report
from .runner import run_eval
from .types import BenchmarkConfig, BenchmarkPackage, EvalSpec

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]+")


def _redact_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def _persist_package(pkg: BenchmarkPackage, output_dir: str, log: Callable[[str], None]) -> None:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pkg.created_at.replace(":", "").replace("+", "_").replace(".", "_")
    json_path = out_dir / f"evalclaw_{stem}.json"
    md_path = out_dir / f"evalclaw_{stem}.md"
    html_path = out_dir / f"evalclaw_{stem}.html"
    artifacts = write_lm_eval_artifacts(pkg.dataset, out_dir)
    manifest_path = out_dir / "manifest.json"
    artifact_section = artifact_index_markdown(
        package_path=json_path,
        report_path=md_path,
        frontend_report_path=html_path,
        manifest_path=manifest_path,
        lm_eval_paths=artifacts,
    )
    pkg.report.markdown = pkg.report.markdown.rstrip() + "\n\n" + artifact_section
    json_payload = json.dumps(pkg.model_dump(mode="json"), ensure_ascii=False, indent=2)
    json_path.write_text(_redact_secrets(json_payload), encoding="utf-8")
    md_path.write_text(_redact_secrets(pkg.report.markdown), encoding="utf-8")
    html_path.write_text(_redact_secrets(build_report_viewer_html(pkg)), encoding="utf-8")
    manifest_path = write_artifact_manifest(
        out_dir,
        package_path=json_path,
        report_path=md_path,
        frontend_report_path=html_path,
        lm_eval_paths=artifacts,
    )
    log(f"Saved package: {json_path}")
    log(f"Saved report: {md_path}")
    log(f"Saved browser report: {html_path}")
    log(f"Saved lm-eval JSONL: {artifacts['jsonl']}")
    log(f"Saved lm-eval YAML: {artifacts['yaml']}")
    log(f"Saved manifest: {manifest_path}")


def run_pipeline(
    goal: str,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
    progress: Callable[[str], None] = print,
    ask_user: Optional[Callable[[str], str]] = None,
    interactive: bool = True,
) -> BenchmarkPackage:
    """Run Planner -> Generator -> QC Gate -> Runner -> Reporter."""
    original_goal = goal
    goal = translate_goal_to_english(goal, config)
    if goal != original_goal:
        log("\n[Input] Translated non-English evaluation goal to English before planning.")
        log(f"  English goal: {goal}")

    log("\n[Planner] Building eval_spec with self-critique...")
    spec: EvalSpec = plan_eval_spec(goal, config)
    log(f"  Objective: {spec.objective}")
    log(f"  Dimensions: {len(spec.dimensions)}")
    log(f"  Planner critique: {spec.critique.score:.1f}/5")

    if interactive and ask_user is not None:
        feedback = ask_user("\nPress Enter to accept the eval_spec, or enter revision feedback: ").strip()
        if feedback:
            log("\n[Planner] Revising eval_spec from feedback...")
            spec = plan_eval_spec(goal, config, feedback=feedback, previous_spec=spec)
            log(f"  Revised dimensions: {len(spec.dimensions)}")

    log("\n[Planner/Generator/QC] Building benchmark dataset with pre-run self-check...")
    spec, dataset, qc_report = generate_dataset_with_qc_loop(spec, config, log=log)
    log(f"  Final dimensions: {len(spec.dimensions)}")
    log(f"  Final items: {len(dataset.items)}")
    log(f"  Sources used: {len(dataset.sources)}")
    log(f"  {qc_report.summary}")
    log(f"  Quality score: {qc_report.quality_score * 100:.1f}%")

    if config.human_review and ask_user is not None:
        for round_index in range(1, 4):
            overview = format_human_review_overview(dataset, qc_report, config)
            feedback = ask_user(
                f"\n[Human Review] Round {round_index}/3\n{overview}\n"
                "\nPress Enter, 'ok', or 'approve' to continue to runner.\n"
                "Otherwise, enter requested changes:"
            ).strip()
            if not feedback or feedback.lower() in {"ok", "okay", "approve", "approved", "y", "yes"}:
                log("\n[Human Review] Approved by user.")
                break
            log("\n[Human Review] Applying user feedback...")
            spec, dataset, qc_report = apply_human_review_feedback(dataset, qc_report, config, feedback, log=log)
            log(f"  Revised dimensions: {len(spec.dimensions)}")
            log(f"  Revised items: {len(dataset.items)}")
            log(f"  Revised QC quality: {qc_report.quality_score * 100:.1f}%")

    if interactive and ask_user is not None and not qc_report.is_acceptable:
        answer = ask_user("\nQC has blocking issues. Continue to runner anyway? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            config = config.model_copy(update={"run_targets": False})

    run_direct = config.runner in {"direct", "auto"}
    direct_config = config if run_direct else config.model_copy(update={"run_targets": False})

    log("\n[Runner] Executing accepted items against target models...")
    if not run_direct and config.runner == "lm-eval":
        log("  Direct runner skipped because --runner=lm-eval.")

    def _on_progress(done: int, total: int, target_id: str, item_id: str) -> None:
        progress(f"  {done}/{total} {target_id} {item_id}")

    run = run_eval(dataset, qc_report, direct_config, on_progress=_on_progress)
    if config.runner in {"lm-eval", "auto"} and config.targets and config.output_dir:
        log("\nlm-eval: Running interoperability harness...")
        out_dir = Path(config.output_dir)
        lm_eval_artifacts: dict[str, object] = {}
        for target in config.targets:
            try:
                lm_eval_artifacts[target.id] = run_lm_eval(dataset, target, out_dir)
                log(f"  lm-eval completed for {target.id}")
            except Exception as exc:
                lm_eval_artifacts[target.id] = {"error": str(exc)}
                log(f"  lm-eval failed for {target.id}: {exc}")
        run.runner_artifacts["lm_eval"] = lm_eval_artifacts
    log(f"  Results: {len(run.results)} item responses")

    improvements = []
    for iteration in range(1, max(0, config.improve_iterations) + 1):
        log(f"\n[Loop 3] Running self-improvement iteration {iteration}...")
        improved = run_loop3_improvement(dataset, qc_report, run, config, iteration=iteration, log=log)
        improvements.append(improved)
        log(f"  Actions: {len(improved.actions)}")
        if improved.qc_report:
            log(f"  Improved QC quality: {improved.qc_report.quality_score * 100:.1f}%")
        if improved.run:
            log(f"  Improved results: {len(improved.run.results)} item responses")
        if improved.dataset and improved.qc_report and improved.run:
            dataset = improved.dataset
            qc_report = improved.qc_report
            run = improved.run

    log("\n[Reporter] Building Markdown report...")
    report = build_report(run)

    pkg = BenchmarkPackage(
        goal=goal,
        spec=spec,
        dataset=dataset,
        qc_report=qc_report,
        run=run,
        improvements=improvements,
        report=report,
    )
    if config.output_dir:
        _persist_package(pkg, config.output_dir, log)
    return pkg
