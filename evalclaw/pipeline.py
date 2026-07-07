"""EvaluationClaw orchestration pipeline."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from .agent_benchmark import build_agent_dataset
from .artifacts import write_artifact_manifest, write_lm_eval_artifacts
from .execution.environment_claw import format_environment_claw_report, run_environment_claw
from .execution.swebench import validate_swebench_environment_for_items
from .improver import run_loop3_improvement
from .lm_eval_runner import run_lm_eval
from .planner import plan_eval_spec, translate_goal_to_english
from .planning_loop import (
    apply_human_review_feedback,
    format_human_review_overview,
    generate_dataset_with_qc_loop,
)
from .quality.qc import run_qc_gate
from .report_viewer import build_report_viewer_html
from .reporter import artifact_index_markdown, build_report
from .research.deep_research import render_brief_markdown, run_deep_research
from .runner import run_eval, validate_multimodal_target_support
from .types import BenchmarkConfig, BenchmarkItem, BenchmarkMode, BenchmarkPackage, EvalSpec

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]+")
_AGENT_GOAL_PATTERN = re.compile(
    r"\b(agent|tool\s*use|tool[- ]calling|tools?|environment|sandbox|docker|workspace|"
    r"terminal|shell|browser|gui|desktop|computer\s*use|cua|mouse|keyboard|screenshot|"
    r"screen|click|desktop\s*software|multi[- ]?industrial[- ]?software|"
    r"industrial[- ]?software|engineering[- ]?software|"
    r"cad|eda|cae|cam|pcb|kicad|freecad|blender|api|multi[- ]?step|"
    r"long[- ]?horizon|code\s*agent|repo|repository|issue|debug|repair|run\s+tests?)\b",
    re.IGNORECASE,
)
_AGENT_GOAL_CJK_TERMS = (
    "智能体",
    "代理",
    "工具调用",
    "调用工具",
    "环境交互",
    "沙盒",
    "浏览器",
    "终端",
    "命令行",
    "代码修复",
    "仓库",
    "多步",
    "长程",
)


_AGENT_GOAL_CJK_TERMS += (
    "\u667a\u80fd\u4f53",
    "\u5de5\u5177\u8c03\u7528",
    "\u73af\u5883\u4ea4\u4e92",
    "\u684c\u9762",
    "\u5de5\u4e1a\u8f6f\u4ef6",
    "\u591a\u8f6f\u4ef6",
    "\u534f\u540c",
    "\u5de5\u4f5c\u6d41",
    "\u5de5\u7a0b\u8f6f\u4ef6",
    "\u673a\u68b0\u8bbe\u8ba1",
    "\u7535\u8def\u677f",
)


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
    html_path.write_text(_redact_secrets(build_report_viewer_html(pkg)), encoding="utf-8")
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
    log(f"Saved lm-eval JSONL: {artifacts['jsonl']}")
    log(f"Saved lm-eval YAML: {artifacts['yaml']}")
    log(f"Saved manifest: {manifest_path}")


def _validate_swebench_preflight_with_retry(
    accepted_items: list[BenchmarkItem],
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None],
    ask_user: Optional[Callable[[str], str]],
    interactive: bool,
) -> BenchmarkConfig:
    try:
        validate_swebench_environment_for_items(accepted_items, config)
        return config
    except RuntimeError as exc:
        if not interactive or ask_user is None:
            raise
        log(f"\n[SWE-bench Preflight]\n{exc}")

    while True:
        answer = ask_user(
            "\nSWE-bench runtime is not ready. Configure it using the commands above, then press Enter to retry.\n"
            "Type 'skip' to skip target execution for this run, or 'abort' to stop: "
        ).strip().lower()
        if answer in {"skip", "s", "no-run", "norun"}:
            log("\n[SWE-bench Preflight] Target execution skipped by user.")
            return config.model_copy(update={"run_targets": False})
        if answer in {"abort", "stop", "exit", "q", "quit"}:
            raise RuntimeError("SWE-bench preflight failed and the run was aborted by user.")
        try:
            validate_swebench_environment_for_items(accepted_items, config)
            log("\n[SWE-bench Preflight] Runtime is ready.")
            return config
        except RuntimeError as exc:
            log(f"\n[SWE-bench Preflight] Still not ready.\n{exc}")


def _resolve_benchmark_mode(goal: str, config: BenchmarkConfig) -> BenchmarkMode:
    if config.benchmark_mode != BenchmarkMode.auto:
        return config.benchmark_mode
    if _AGENT_GOAL_PATTERN.search(goal) or any(term in goal for term in _AGENT_GOAL_CJK_TERMS):
        return BenchmarkMode.agent
    return BenchmarkMode.static


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

    if config.use_deep_research and config.research_brief is None:
        log("\n[Deep Research] Running bounded research loop before planning...")
        brief = run_deep_research(goal, config, log=log)
        if brief is None:
            log("  Deep research unavailable (no orchestrator key or search disabled); continuing without a brief.")
        else:
            config = config.model_copy(update={"research_brief": brief})
            log(
                f"  Research brief: {len(brief.taxonomy)} taxonomy entries, "
                f"{len(brief.existing_benchmarks)} known benchmarks, "
                f"{len(brief.seed_sources)} seed sources"
            )

    benchmark_mode = _resolve_benchmark_mode(goal, config)
    log(f"\n[Mode] Benchmark mode: {benchmark_mode.value}")

    if benchmark_mode == BenchmarkMode.agent:
        log("\n[Agent Planner/Builder] Building executable agent task suite...")
        dataset = build_agent_dataset(goal, config)
        spec = dataset.spec
        qc_report = run_qc_gate(dataset, config)
    else:
        log("\n[Planner] Building eval_spec with self-critique...")
        spec = plan_eval_spec(goal, config)
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
    accepted_for_run = [item for item in dataset.items if item.id in set(qc_report.passed_item_ids)]
    direct_config, environment_claw_report = run_environment_claw(accepted_for_run, direct_config)
    for line in format_environment_claw_report(environment_claw_report):
        log(line)
    if direct_config.run_targets and environment_claw_report.blocking_errors:
        raise RuntimeError("\n\n".join(environment_claw_report.blocking_errors))
    validate_multimodal_target_support(accepted_for_run, config)
    if run_direct:
        direct_config = _validate_swebench_preflight_with_retry(
            accepted_for_run,
            direct_config,
            log=log,
            ask_user=ask_user,
            interactive=interactive,
        )

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
    report = build_report(run, research_brief=config.research_brief)

    pkg = BenchmarkPackage(
        goal=goal,
        spec=spec,
        dataset=dataset,
        qc_report=qc_report,
        run=run,
        improvements=improvements,
        report=report,
        research_brief=config.research_brief,
    )
    if config.output_dir:
        _persist_package(pkg, config.output_dir, log)
    return pkg
