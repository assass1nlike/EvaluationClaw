"""EvaluationClaw orchestration pipeline."""
from __future__ import annotations

import json
import re
import traceback
from pathlib import Path
from typing import Callable, Optional

from .benchmark import build_benchmark_suite_with_qc_loop
from .diagnostics import error_record, new_debug_dir, write_json, write_text
from .execution.environment_claw import format_environment_claw_report, run_environment_claw
from .execution.lm_eval import run_lm_eval
from .execution.plan import build_execution_plan
from .execution.runner import run_eval, validate_asset_target_support
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
    execution_plan = build_execution_plan(pkg.suite, pkg.qc_report)
    artifacts = write_lm_eval_artifacts(execution_plan.suite, out_dir)
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


def _run_pipeline(
    goal: str,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
    progress: Callable[[str], None] = print,
    ask_user: Optional[Callable[[str], str]] = None,
    interactive: bool = True,
    debug_run_dir: Path | None = None,
) -> BenchmarkPackage:
    """Run preparation -> unified construction/QC -> execution -> reporting."""
    reset_network_state()
    debug_dirs: dict[str, str] = {}
    if config.output_dir and not config.planner_debug_dir:
        debug_dirs["planner_debug_dir"] = str(Path(config.output_dir) / "debug" / "planner")
    if config.output_dir and not config.task_builder_debug_dir:
        debug_dirs["task_builder_debug_dir"] = str(
            Path(config.output_dir) / "debug" / "task-builder"
        )
    if debug_dirs:
        config = config.model_copy(update=debug_dirs)
    original_goal = goal
    if debug_run_dir is not None:
        write_json(
            debug_run_dir / "input.json",
            {"original_goal": original_goal, "normalized_goal": None},
        )
    goal = translate_goal_to_english(goal, config)
    if debug_run_dir is not None:
        write_json(
            debug_run_dir / "input.json",
            {"original_goal": original_goal, "normalized_goal": goal},
        )
    if goal != original_goal:
        log("\n[Input] Normalized the evaluation goal to English before planning.")
        log(f"  English goal: {goal}")

    if config.use_deep_research and config.research_brief is None:
        log("\n[Benchmark Design Research] Running bounded research loop before planning...")
        brief = run_deep_research(
            goal,
            config,
            log=log,
            trace_dir=debug_run_dir / "research" if debug_run_dir is not None else None,
        )
        if brief is None:
            raise RuntimeError(
                "Deep research was requested but could not run. Configure the Research role "
                "with a non-none search backend, or disable --deep-research."
            )
        if config.output_dir:
            output_root = Path(config.output_dir)
            write_json(output_root / "research_brief.json", brief.model_dump(mode="json"))
            write_text(output_root / "research_brief.md", render_brief_markdown(brief))
        config = config.model_copy(update={"research_brief": brief})
        log(
            f"  Design brief: {len(brief.dimensions)} candidate dimensions, "
            f"{len(brief.task_patterns)} task patterns, "
            f"{len(brief.source_recommendations)} source recommendations"
        )

    log("\n[Planner/Builder/QC] Building benchmark through the single task-construction pipeline...")
    spec, suite, qc_report = build_benchmark_suite_with_qc_loop(
        goal,
        config,
        log=log,
        trace_dir=debug_run_dir / "construction" if debug_run_dir is not None else None,
    )
    benchmark_plan = suite.plan
    if debug_run_dir is not None:
        write_json(
            debug_run_dir / "construction.json",
            {
                "spec": spec.model_dump(mode="json"),
                "plan": benchmark_plan.model_dump(mode="json") if benchmark_plan else None,
                "suite": suite.model_dump(mode="json"),
                "qc_report": qc_report.model_dump(mode="json"),
            },
        )
    log(f"  Final dimensions: {len(spec.dimensions)}")
    log(f"  Final items: {len(suite.tasks)}")
    log(f"  Sources used: {len(suite.resources)}")
    log(f"  {qc_report.summary}")
    log(f"  Average QC issues: {_average_qc_issues(qc_report, len(suite.tasks)):.2f}")

    if config.human_review and ask_user is not None:
        for round_index in range(1, 4):
            overview = format_human_review_overview(suite, qc_report, config)
            feedback = ask_user(
                f"\n[Human Review] Round {round_index}/3\n{overview}\n"
                "\nPress Enter, 'ok', or 'approve' to continue to runner.\n"
                "Otherwise, enter requested changes:"
            ).strip()
            if not feedback or feedback.lower() in {"ok", "okay", "approve", "approved", "y", "yes"}:
                log("\n[Human Review] Approved by user.")
                break
            log("\n[Human Review] Applying user feedback...")
            spec, suite, qc_report = apply_human_review_feedback(suite, qc_report, config, feedback, log=log)
            benchmark_plan = suite.plan or benchmark_plan
            if debug_run_dir is not None:
                write_json(
                    debug_run_dir / f"human-review-{round_index:02d}.json",
                    {
                        "feedback": feedback,
                        "spec": spec.model_dump(mode="json"),
                        "suite": suite.model_dump(mode="json"),
                        "qc_report": qc_report.model_dump(mode="json"),
                    },
                )
            log(f"  Revised dimensions: {len(spec.dimensions)}")
            log(f"  Revised items: {len(suite.tasks)}")
            log(f"  Revised average QC issues: {_average_qc_issues(qc_report, len(suite.tasks)):.2f}")

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
    execution_plan = build_execution_plan(suite, qc_report)
    accepted_for_run = execution_plan.suite.tasks
    direct_config, environment_claw_report = run_environment_claw(accepted_for_run, direct_config)
    if debug_run_dir is not None:
        write_json(debug_run_dir / "environment.json", environment_claw_report.as_dict())
    for line in format_environment_claw_report(environment_claw_report):
        log(line)
    if direct_config.run_targets and environment_claw_report.blocking_errors:
        raise RuntimeError("\n\n".join(environment_claw_report.blocking_errors))
    validate_asset_target_support(accepted_for_run, config)
    log("\n[Runner] Executing accepted items against target models...")
    if not run_direct and config.runner == "lm-eval":
        log("  Direct runner skipped because --runner=lm-eval.")

    def _on_progress(done: int, total: int, target_id: str, item_id: str) -> None:
        progress(f"  {done}/{total} {target_id} {item_id}")

    run = run_eval(suite, qc_report, direct_config, on_progress=_on_progress)
    run.runner_artifacts["environment_claw"] = environment_claw_report.as_dict()
    if debug_run_dir is not None:
        write_json(debug_run_dir / "run.json", run.model_dump(mode="json"))
    if config.runner in {"lm-eval", "auto"} and config.targets and config.output_dir:
        log("\nlm-eval: Running interoperability harness...")
        out_dir = Path(config.output_dir)
        lm_eval_artifacts: dict[str, object] = {}
        for target in config.targets:
            try:
                lm_eval_artifacts[target.id] = run_lm_eval(execution_plan.suite, target, out_dir)
                log(f"  lm-eval completed for {target.id}")
            except Exception as exc:
                lm_eval_artifacts[target.id] = {"error": str(exc)}
                log(f"  lm-eval failed for {target.id}: {exc}")
        run.runner_artifacts["lm_eval"] = lm_eval_artifacts
    log(f"  Results: {len(run.results)} item responses")

    improvements = []
    for iteration in range(1, max(0, config.improve_iterations) + 1):
        log(f"\n[Loop 3] Running self-improvement iteration {iteration}...")
        improved = run_loop3_improvement(suite, qc_report, run, config, iteration=iteration, log=log)
        improvements.append(improved)
        log(f"  Actions: {len(improved.actions)}")
        if improved.qc_report:
            improved_item_count = len(improved.suite.tasks) if improved.suite else len(suite.tasks)
            log(f"  Improved average QC issues: {_average_qc_issues(improved.qc_report, improved_item_count):.2f}")
        if improved.run:
            log(f"  Improved results: {len(improved.run.results)} item responses")
        if improved.suite and improved.qc_report and improved.run:
            suite = improved.suite
            qc_report = improved.qc_report
            run = improved.run

    log("\n[Reporter] Building Markdown report...")
    report = build_report(run, research_brief=config.research_brief)

    pkg = BenchmarkPackage(
        goal=goal,
        spec=spec,
        plan=benchmark_plan,
        suite=suite,
        qc_report=qc_report,
        run=run,
        improvements=improvements,
        report=report,
        research_brief=config.research_brief,
    )
    if config.output_dir:
        _persist_package(pkg, config, config.output_dir, log)
    return pkg


def run_pipeline(
    goal: str,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
    progress: Callable[[str], None] = print,
    ask_user: Optional[Callable[[str], str]] = None,
    interactive: bool = True,
) -> BenchmarkPackage:
    """Run the pipeline with durable diagnostics even when a later stage fails."""
    debug_run_dir = new_debug_dir(config.output_dir, "runs")
    if debug_run_dir is None:
        return _run_pipeline(
            goal,
            config,
            log=log,
            progress=progress,
            ask_user=ask_user,
            interactive=interactive,
        )

    write_json(
        debug_run_dir / "config.json",
        config.model_dump(mode="json"),
        redact=True,
    )
    log_path = debug_run_dir / "pipeline.log"

    def traced_log(message: str) -> None:
        write_text(log_path, str(message) + "\n", append=True)
        log(message)

    def traced_progress(message: str) -> None:
        write_text(log_path, str(message) + "\n", append=True)
        progress(message)

    try:
        package = _run_pipeline(
            goal,
            config,
            log=traced_log,
            progress=traced_progress,
            ask_user=ask_user,
            interactive=interactive,
            debug_run_dir=debug_run_dir,
        )
    except BaseException as exc:
        write_json(
            debug_run_dir / "failure.json",
            {**error_record(exc), "traceback": traceback.format_exc()},
            redact=True,
        )
        raise
    write_json(debug_run_dir / "status.json", {"status": "completed"})
    return package
