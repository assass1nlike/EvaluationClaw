"""EvaluationClaw orchestration pipeline."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from .benchmark import build_benchmark_dataset_with_qc_loop
from .execution.environment_claw import format_environment_claw_report, run_environment_claw
from .execution.lm_eval import run_lm_eval
from .execution.plan import build_execution_plan
from .execution.runner import run_eval, validate_multimodal_target_support
from .planning.loop import apply_human_review_feedback, format_human_review_overview
from .planning.planner import translate_goal_to_english
from .quality.improver import run_loop3_improvement
from .reporting.artifacts import write_artifact_manifest, write_lm_eval_artifacts
from .reporting.reporter import artifact_index_markdown, build_report
from .reporting.viewer import build_report_viewer_html
from .research.backends import reset_network_state
from .research.deep_research import render_brief_markdown, run_deep_research
from .types import BenchmarkConfig, BenchmarkPackage

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]+")
def _redact_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def _average_qc_issues(qc_report: object, item_count: int) -> float:
    issues = getattr(qc_report, "issues", [])
    return len(issues) / max(1, item_count)


def _persist_package(
    pkg: BenchmarkPackage,
    config: BenchmarkConfig,
    output_dir: str,
    log: Callable[[str], None],
) -> None:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pkg.created_at.replace(":", "").replace("+", "_").replace(".", "_")
    json_path = out_dir / f"evalclaw_{stem}.json"
    md_path = out_dir / f"evalclaw_{stem}.md"
    html_path = out_dir / f"evalclaw_{stem}.html"
    execution_plan = build_execution_plan(pkg.dataset, pkg.qc_report)
    artifacts = write_lm_eval_artifacts(execution_plan.dataset, out_dir)
    research_brief_paths: dict[str, Path] = {}
    if pkg.research_brief is not None:
        brief_json_path = out_dir / "research_brief.json"
        brief_md_path = out_dir / "research_brief.md"
        brief_json_path.write_text(
            _redact_secrets(
                json.dumps(pkg.research_brief.model_dump(mode="json"), ensure_ascii=False, indent=2)
            ),
            encoding="utf-8",
        )
        brief_md_path.write_text(
            _redact_secrets(render_brief_markdown(pkg.research_brief)),
            encoding="utf-8",
        )
        research_brief_paths = {"json": brief_json_path, "markdown": brief_md_path}
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
    html_path.write_text(
        _redact_secrets(
            build_report_viewer_html(
                pkg,
                item_limit=max(0, config.viewer_item_limit),
                result_limit=max(0, config.viewer_result_limit),
            )
        ),
        encoding="utf-8",
    )
    manifest_path = write_artifact_manifest(
        out_dir,
        package_path=json_path,
        report_path=md_path,
        frontend_report_path=html_path,
        lm_eval_paths=artifacts,
        research_brief_paths=research_brief_paths or None,
    )
    if research_brief_paths:
        log(f"Saved research brief: {research_brief_paths['json']}")
        log(f"Saved research brief markdown: {research_brief_paths['markdown']}")
    log(f"Saved package: {json_path}")
    log(f"Saved report: {md_path}")
    log(f"Saved browser report: {html_path}")
    for name, path in artifacts.items():
        log(f"Saved lm-eval {name}: {path}")
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
    """Run preparation -> unified construction/QC -> execution -> reporting."""
    reset_network_state()
    if config.output_dir and not config.task_builder_debug_dir:
        config = config.model_copy(
            update={
                "task_builder_debug_dir": str(
                    Path(config.output_dir) / "debug" / "task-builder"
                )
            }
        )
    original_goal = goal
    goal = translate_goal_to_english(goal, config)
    if goal != original_goal:
        log("\n[Input] Normalized the evaluation goal to English before planning.")
        log(f"  English goal: {goal}")

    if config.use_deep_research and config.research_brief is None:
        log("\n[Deep Research] Running bounded research loop before planning...")
        brief = run_deep_research(goal, config, log=log)
        if brief is None:
            log("  Deep research unavailable (no research-role key or search disabled); continuing without a brief.")
        else:
            config = config.model_copy(update={"research_brief": brief})
            log(
                f"  Research brief: {len(brief.taxonomy)} taxonomy entries, "
                f"{len(brief.existing_benchmarks)} known benchmarks, "
                f"{len(brief.seed_sources)} seed sources"
            )

    log("\n[Planner/Builder/QC] Building benchmark through the single task-construction pipeline...")
    spec, dataset, qc_report = build_benchmark_dataset_with_qc_loop(
        goal,
        config,
        log=log,
    )
    benchmark_plan = dataset.plan
    log(f"  Final dimensions: {len(spec.dimensions)}")
    log(f"  Final items: {len(dataset.items)}")
    log(f"  Sources used: {len(dataset.sources)}")
    log(f"  {qc_report.summary}")
    log(f"  Average QC issues: {_average_qc_issues(qc_report, len(dataset.items)):.2f}")

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
            benchmark_plan = dataset.plan or benchmark_plan
            log(f"  Revised dimensions: {len(spec.dimensions)}")
            log(f"  Revised items: {len(dataset.items)}")
            log(f"  Revised average QC issues: {_average_qc_issues(qc_report, len(dataset.items)):.2f}")

    if interactive and ask_user is not None and not qc_report.is_acceptable:
        answer = ask_user("\nQC has blocking issues. Continue to runner anyway? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            config = config.model_copy(update={"run_targets": False})

    if (not qc_report.is_acceptable or qc_report.rejected_item_ids) and not config.allow_incomplete_benchmark:
        raise RuntimeError(
            "Benchmark is not runner-ready after QC. Set allow_incomplete_benchmark=true only "
            "when intentionally producing a non-executable draft."
        )

    run_direct = config.runner in {"direct", "auto"}
    direct_config = config if run_direct else config.model_copy(update={"run_targets": False})
    execution_plan = build_execution_plan(dataset, qc_report)
    accepted_for_run = execution_plan.dataset.items
    direct_config, environment_claw_report = run_environment_claw(accepted_for_run, direct_config)
    for line in format_environment_claw_report(environment_claw_report):
        log(line)
    if direct_config.run_targets and environment_claw_report.blocking_errors:
        raise RuntimeError("\n\n".join(environment_claw_report.blocking_errors))
    validate_multimodal_target_support(accepted_for_run, config)
    log("\n[Runner] Executing accepted items against target models...")
    if not run_direct and config.runner == "lm-eval":
        log("  Direct runner skipped because --runner=lm-eval.")

    def _on_progress(done: int, total: int, target_id: str, item_id: str) -> None:
        progress(f"  {done}/{total} {target_id} {item_id}")

    run = run_eval(dataset, qc_report, direct_config, on_progress=_on_progress)
    run.runner_artifacts["environment_claw"] = environment_claw_report.as_dict()
    if config.runner in {"lm-eval", "auto"} and config.targets and config.output_dir:
        log("\nlm-eval: Running interoperability harness...")
        out_dir = Path(config.output_dir)
        lm_eval_artifacts: dict[str, object] = {}
        for target in config.targets:
            try:
                lm_eval_artifacts[target.id] = run_lm_eval(execution_plan.dataset, target, out_dir)
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
            improved_item_count = len(improved.dataset.items) if improved.dataset else len(dataset.items)
            log(f"  Improved average QC issues: {_average_qc_issues(improved.qc_report, improved_item_count):.2f}")
        if improved.run:
            log(f"  Improved results: {len(improved.run.results)} item responses")
        if improved.dataset and improved.qc_report and improved.run:
            dataset = improved.dataset
            qc_report = improved.qc_report
            run = improved.run

    log("\n[Reporter] Building Markdown report...")
    report = build_report(run, research_brief=config.research_brief)

    pkg = BenchmarkPackage(
        goal=goal,
        spec=spec,
        plan=benchmark_plan,
        dataset=dataset,
        qc_report=qc_report,
        run=run,
        improvements=improvements,
        report=report,
        research_brief=config.research_brief,
    )
    if config.output_dir:
        _persist_package(pkg, config, config.output_dir, log)
    return pkg
