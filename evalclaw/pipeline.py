"""EvaluationClaw orchestration pipeline."""
from __future__ import annotations

import json
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .benchmark import build_benchmark_suite_with_qc_loop
from .diagnostics import (
    _io_path,
    error_record,
    invocation_id,
    new_debug_dir,
    write_json,
    write_text,
)
from .execution.environment_claw import (
    EnvironmentAction,
    EnvironmentClawReport,
    EnvironmentProbe,
    format_environment_claw_report,
    run_environment_claw,
)
from .execution.lm_eval import run_lm_eval
from .execution.plan import build_execution_plan
from .execution.runner import run_eval
from .planning.loop import apply_human_review_feedback, format_human_review_overview
from .planning.planner import translate_goal_to_english
from .quality.improver import run_loop3_improvement
from .reporting.artifacts import write_artifact_manifest, write_lm_eval_artifacts
from .reporting.reporter import artifact_index_markdown, build_report
from .reporting.viewer import build_report_viewer_html
from .research.backends import reset_network_state
from .research.deep_research import render_brief_markdown, run_deep_research
from .types import (
    BenchmarkConfig,
    BenchmarkPackage,
    BenchmarkPlan,
    EvalRun,
    EvalSpec,
    ImprovementIteration,
    QcReport,
    ResearchBrief,
    TaskSuite,
)

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]+")


def _read_json(path: Path) -> object | None:
    io_path = _io_path(path)
    try:
        return json.loads(io_path.read_text(encoding="utf-8")) if io_path.is_file() else None
    except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return None


def _load_model(path: Path, model_type: type) -> object | None:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    try:
        return model_type.model_validate(payload)
    except (TypeError, ValueError):
        return None


def _write_run_state(
    run_dir: Path,
    status: str,
    *,
    stage: str | None = None,
    resumed_from: str | None = None,
) -> None:
    previous = _read_json(run_dir / "status.json")
    previous_stages = previous.get("completed_stages", []) if isinstance(previous, dict) else []
    completed_stages = [str(stage) for stage in previous_stages] if isinstance(previous_stages, list) else []
    if status == "done" and stage and stage not in completed_stages:
        completed_stages.append(stage)
    payload: dict[str, object] = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed_stages": completed_stages,
    }
    if stage is not None:
        payload["stage"] = stage
    if resumed_from is not None:
        payload["resumed_from"] = resumed_from
    write_json(run_dir / "status.json", payload)


def _resolve_resume_dir(output_dir: str, resume_run: str | Path) -> Path:
    candidate = Path(resume_run).expanduser()
    if not candidate.is_dir():
        candidate = Path(output_dir).expanduser().resolve() / "debug" / "runs" / str(resume_run)
    if not candidate.is_dir():
        raise FileNotFoundError(f"Resume run directory does not exist: {resume_run}")
    return candidate.resolve()


def _report_from_dict(payload: object) -> EnvironmentClawReport | None:
    if not isinstance(payload, dict):
        return None
    try:
        probes = [EnvironmentProbe(**value) for value in payload.get("probes", [])]
        actions = [EnvironmentAction(**value) for value in payload.get("actions", [])]
        return EnvironmentClawReport(
            enabled=bool(payload.get("enabled")),
            probes=probes,
            actions=actions,
            blocking_errors=[str(value) for value in payload.get("blocking_errors", [])],
        )
    except (TypeError, ValueError):
        return None


def _load_construction_resume(
    construction_dir: Path,
) -> tuple[BenchmarkPlan | None, TaskSuite | None, QcReport | None, int]:
    plan_payload = _read_json(construction_dir / "plan.json")
    plan = None
    if isinstance(plan_payload, dict):
        try:
            plan = BenchmarkPlan.model_validate(plan_payload.get("plan", plan_payload))
        except (TypeError, ValueError):
            plan = None

    final_payload = _read_json(construction_dir / "final.json")
    if isinstance(final_payload, dict):
        try:
            suite = TaskSuite.model_validate(final_payload["suite"])
            qc_report = QcReport.model_validate(final_payload["qc_report"])
            suite.plan = plan
            return plan, suite, qc_report, 0
        except (KeyError, TypeError, ValueError):
            pass

    suite = _load_model(construction_dir / "initial-suite.json", TaskSuite)
    qc_report = _load_model(construction_dir / "initial-qc.json", QcReport)
    last_round = 0
    checkpoint_dir = construction_dir / "qc-checkpoints"
    if checkpoint_dir.is_dir():
        for path in sorted(checkpoint_dir.glob("round-*.json")):
            payload = _read_json(path)
            if not isinstance(payload, dict):
                continue
            try:
                candidate_suite = TaskSuite.model_validate(payload["suite"])
                candidate_qc = QcReport.model_validate(payload["qc_report"])
                candidate_round = int(payload["round"])
            except (KeyError, TypeError, ValueError):
                continue
            if candidate_round >= last_round:
                suite, qc_report, last_round = candidate_suite, candidate_qc, candidate_round
    if isinstance(suite, TaskSuite):
        suite.plan = plan
    return plan, suite if isinstance(suite, TaskSuite) else None, qc_report if isinstance(qc_report, QcReport) else None, last_round


def _load_eval_run(path: Path, suite: TaskSuite, qc_report: QcReport) -> EvalRun | None:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    try:
        return EvalRun.model_validate({**payload, "suite": suite, "qc_report": qc_report})
    except (TypeError, ValueError):
        return None


def _redact_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def _live_run_id(
    debug_run_dir: Path | None,
    live_url: str | None = None,
) -> str | None:
    """Return a run_id when live events have a local or remote destination."""
    if debug_run_dir is None:
        return None
    if live_url:
        return invocation_id()
    try:
        from .live.server import is_running
        if not is_running():
            return None
    except Exception:
        return None
    return invocation_id()


def _live_register(
    run_id: str | None,
    goal: str,
    debug_run_dir: Path | None,
    *,
    live_url: str | None = None,
    log: Callable[[str], None],
) -> None:
    if run_id is None or debug_run_dir is None:
        return
    try:
        from .live.registry import register_run
        from .live.server import server_url
        register_run(
            run_id,
            goal=goal,
            created_at=datetime.now(timezone.utc).isoformat(),
            debug_dir=debug_run_dir,
            remote_url=live_url,
        )
        url = f"{live_url.rstrip('/')}/run/{run_id}" if live_url else server_url(run_id)
        if url:
            log(f"\n[Live] Run visualisation: {url}")
    except Exception:
        pass


def _live_log(run_id: str | None, message: str) -> None:
    if run_id is None:
        return
    try:
        from .live.streamers import notify_log
        notify_log(run_id, message)
    except Exception:
        pass


def _live_stage(run_id: str | None, stage: str, *, status: str = "active") -> None:
    if run_id is None:
        return
    try:
        from .live.streamers import notify_stage
        notify_stage(run_id, stage, status=status)
    except Exception:
        pass


def _live_end(run_id: str | None, *, failed: bool = False) -> None:
    if run_id is None:
        return
    try:
        import time

        from .live.registry import get_run
        bus = get_run(run_id)
        if bus is not None:
            bus.publish({"type": "run_end", "failed": failed, "t": time.time()})
            bus.end()
    except Exception:
        pass


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
    live_run_id: str | None = None,
    resuming: bool = False,
) -> BenchmarkPackage:
    """Run preparation -> unified construction/QC -> execution -> reporting."""
    reset_network_state()
    debug_dirs: dict[str, str] = {}
    if config.output_dir and not config.planner_debug_dir:
        debug_dirs["planner_debug_dir"] = str(
            debug_run_dir / "planner"
            if debug_run_dir is not None
            else Path(config.output_dir) / "debug" / "planner"
        )
    if config.output_dir and not config.task_builder_debug_dir:
        debug_dirs["task_builder_debug_dir"] = str(
            debug_run_dir / "task-builder"
            if debug_run_dir is not None
            else Path(config.output_dir) / "debug" / "task-builder"
        )
    if debug_dirs:
        config = config.model_copy(update=debug_dirs)

    if live_run_id is None:
        live_run_id = _live_run_id(debug_run_dir, config.live_url)
    _live_register(live_run_id, goal, debug_run_dir, live_url=config.live_url, log=log)

    import time as _time

    def _live_emit(msg: str) -> None:
        _live_log(live_run_id, msg)
        log(msg)

    def mark_stage(stage: str, status: str = "active") -> None:
        if debug_run_dir is not None:
            _write_run_state(debug_run_dir, status, stage=stage)

    original_goal = goal
    saved_input = _read_json(debug_run_dir / "input.json") if resuming and debug_run_dir else None
    resumed_goal_loaded = False
    if resuming and isinstance(saved_input, dict):
        saved_goal = str(saved_input.get("normalized_goal") or "").strip()
        if saved_goal:
            goal = saved_goal
            resumed_goal_loaded = True
        original_goal = str(saved_input.get("original_goal") or goal)
    if debug_run_dir is not None and not resuming:
        mark_stage("input")
        write_json(
            debug_run_dir / "input.json",
            {"original_goal": original_goal, "normalized_goal": None},
        )
    if not resumed_goal_loaded:
        goal = translate_goal_to_english(goal, config)
    if debug_run_dir is not None:
        if not resumed_goal_loaded:
            write_json(
                debug_run_dir / "input.json",
                {"original_goal": original_goal, "normalized_goal": goal},
            )
        mark_stage("input", "done")
    if goal != original_goal:
        _live_emit("\n[Input] Normalized the evaluation goal to English before planning.")
        _live_emit(f"  English goal: {goal}")

    mark_stage("research")
    saved_brief = (
        _load_model(debug_run_dir / "research" / "brief.json", ResearchBrief)
        if resuming and debug_run_dir is not None
        else None
    )
    if saved_brief is not None and config.research_brief is None:
        config = config.model_copy(update={"research_brief": saved_brief})
    if config.use_deep_research and config.research_brief is None:
        _live_emit("\n[Benchmark Design Research] Running bounded research loop before planning...")
        _live_stage(live_run_id, "research")
        brief = run_deep_research(
            goal,
            config,
            log=_live_emit,
            trace_dir=debug_run_dir / "research" if debug_run_dir is not None else None,
        )
        if brief is None:
            raise RuntimeError(
                "Deep research was requested but could not run. Configure the Research role "
                "with a non-none search backend, or disable --deep-research."
            )
        if debug_run_dir is not None:
            write_json(debug_run_dir / "research" / "brief.json", brief.model_dump(mode="json"))
        if config.output_dir:
            output_root = Path(config.output_dir)
            write_json(output_root / "research_brief.json", brief.model_dump(mode="json"))
            write_text(output_root / "research_brief.md", render_brief_markdown(brief))
        config = config.model_copy(update={"research_brief": brief})
        _live_emit(
            f"  Design brief: {len(brief.dimensions)} candidate dimensions, "
            f"{len(brief.task_patterns)} task patterns, "
            f"{len(brief.source_recommendations)} source recommendations"
        )
    elif saved_brief is not None:
        _live_emit("\n[Benchmark Design Research] Resumed completed research brief.")
    elif config.use_deep_research and config.research_brief is not None and debug_run_dir is not None:
        write_json(debug_run_dir / "research" / "brief.json", config.research_brief.model_dump(mode="json"))
    mark_stage("research", "done")
    if config.use_deep_research:
        _live_stage(live_run_id, "research", status="done")

    log("\n[Planner/Builder/QC] Building benchmark through the single task-construction pipeline...")
    _live_stage(live_run_id, "planner")
    mark_stage("construction")
    construction_dir = debug_run_dir / "construction" if debug_run_dir is not None else None
    resume_plan = resume_suite = resume_qc_report = None
    resume_repair_round = 0
    if resuming and construction_dir is not None:
        resume_plan, resume_suite, resume_qc_report, resume_repair_round = _load_construction_resume(
            construction_dir
        )
    if (
        resuming
        and resume_suite is not None
        and resume_qc_report is not None
        and (construction_dir is not None and (construction_dir / "final.json").is_file())
    ):
        spec, suite, qc_report = resume_suite.spec, resume_suite, resume_qc_report
        _live_emit("  Planner/Builder/QC: resumed completed construction and QC.")
    else:
        spec, suite, qc_report = build_benchmark_suite_with_qc_loop(
            goal,
            config,
            log=_live_emit,
            ask_user=ask_user if config.human_review else None,
            trace_dir=construction_dir,
            resume_plan=resume_plan,
            resume_suite=resume_suite,
            resume_qc_report=resume_qc_report,
            resume_repair_round=resume_repair_round,
        )
    review_state = _read_json(debug_run_dir / "human-review-state.json") if resuming and debug_run_dir else None
    if review_state is None and resuming and debug_run_dir is not None:
        review_paths = sorted(debug_run_dir.glob("human-review-*.json"))
        if review_paths:
            review_state = _read_json(review_paths[-1])
    if isinstance(review_state, dict):
        try:
            reviewed_suite = TaskSuite.model_validate(review_state["suite"])
            reviewed_qc = QcReport.model_validate(review_state["qc_report"])
            reviewed_spec = EvalSpec.model_validate(review_state["spec"])
            reviewed_plan = (
                BenchmarkPlan.model_validate(review_state["plan"])
                if review_state.get("plan") is not None
                else None
            )
        except (KeyError, TypeError, ValueError):
            reviewed_suite = reviewed_qc = reviewed_spec = reviewed_plan = None
        if isinstance(reviewed_suite, TaskSuite) and isinstance(reviewed_qc, QcReport):
            suite, qc_report = reviewed_suite, reviewed_qc
            spec = reviewed_spec if isinstance(reviewed_spec, EvalSpec) else reviewed_suite.spec
            suite.plan = reviewed_plan if isinstance(reviewed_plan, BenchmarkPlan) else resume_plan
            _live_emit("  Human review: resumed the latest reviewed benchmark state.")
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
    mark_stage("construction", "done")
    mark_stage("qc", "done")
    _live_stage(live_run_id, "planner", status="done")
    _live_stage(live_run_id, "construction", status="done")
    _live_stage(live_run_id, "qc", status="done")

    human_review_approved = False
    if config.human_review and ask_user is not None:
        mark_stage("human_review")
        saved_review = _read_json(debug_run_dir / "human-review-state.json") if resuming and debug_run_dir else None
        if isinstance(saved_review, dict) and saved_review.get("approved"):
            human_review_approved = True
            _live_emit("  Human review: resumed prior approval.")
        else:
            for round_index in range(1, 4):
                overview = format_human_review_overview(suite, qc_report, config)
                feedback = ask_user(
                    f"\n[Human Review] Round {round_index}/3\n{overview}\n"
                    "\nSubmit an empty response to continue to runner.\n"
                    "Otherwise, enter requested changes:"
                ).strip()
                if not feedback:
                    log("\n[Human Review] Approved by user.")
                    human_review_approved = True
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
                            "plan": benchmark_plan.model_dump(mode="json") if benchmark_plan else None,
                            "suite": suite.model_dump(mode="json"),
                            "qc_report": qc_report.model_dump(mode="json"),
                        },
                    )
                log(f"  Revised dimensions: {len(spec.dimensions)}")
                log(f"  Revised items: {len(suite.tasks)}")
                log(f"  Revised average QC issues: {_average_qc_issues(qc_report, len(suite.tasks)):.2f}")
        if debug_run_dir is not None:
            write_json(
                debug_run_dir / "human-review-state.json",
                {
                    "approved": human_review_approved,
                    "spec": spec.model_dump(mode="json"),
                    "plan": benchmark_plan.model_dump(mode="json") if benchmark_plan else None,
                    "suite": suite.model_dump(mode="json"),
                    "qc_report": qc_report.model_dump(mode="json"),
                },
            )
        mark_stage("human_review", "done")
    else:
        mark_stage("human_review", "done")

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
    mark_stage("environment")
    environment_state = _read_json(debug_run_dir / "environment-state.json") if resuming and debug_run_dir else None
    resumed_environment = False
    if isinstance(environment_state, dict):
        saved_suite = environment_state.get("suite")
        saved_report = _report_from_dict(environment_state.get("report"))
        if isinstance(saved_suite, dict) and saved_report is not None:
            try:
                suite = TaskSuite.model_validate(saved_suite)
                suite.plan = benchmark_plan
                execution_plan = build_execution_plan(suite, qc_report)
                accepted_for_run = execution_plan.suite.tasks
                direct_config = direct_config.model_copy(
                    update={"run_targets": bool(environment_state.get("run_targets", direct_config.run_targets))}
                )
                environment_claw_report = saved_report
                resumed_environment = True
                _live_emit("  Environment Claw: resumed completed environment preparation.")
            except (TypeError, ValueError):
                resumed_environment = False
    if not resumed_environment:
        environment_config = direct_config.model_copy(update={"environment_preflight": False})
        direct_config, environment_claw_report = run_environment_claw(
            accepted_for_run,
            environment_config,
        )
        if debug_run_dir is not None:
            write_json(debug_run_dir / "environment.json", environment_claw_report.as_dict())
            write_json(
                debug_run_dir / "environment-state.json",
                {
                    "run_targets": direct_config.run_targets,
                    "suite": suite.model_dump(mode="json"),
                    "report": environment_claw_report.as_dict(),
                },
            )
    for line in format_environment_claw_report(environment_claw_report):
        log(line)
    if direct_config.run_targets and environment_claw_report.blocking_errors:
        raise RuntimeError("\n\n".join(environment_claw_report.blocking_errors))
    log("\n[Runner] Executing accepted items against target models...")
    if not run_direct and config.runner == "lm-eval":
        log("  Direct runner skipped because --runner=lm-eval.")

    def _on_progress(done: int, total: int, target_id: str, item_id: str) -> None:
        progress(f"  {done}/{total} {target_id} {item_id}")

    mark_stage("environment", "done")
    mark_stage("runner")
    run = (
        _load_eval_run(debug_run_dir / "run.json", suite, qc_report)
        if resuming and debug_run_dir is not None
        else None
    )
    if run is None:
        run = run_eval(
            suite,
            qc_report,
            direct_config,
            on_progress=_on_progress,
            trace_dir=debug_run_dir / "runner" if debug_run_dir is not None else None,
        )
    else:
        _live_emit("  Runner: resumed completed target execution.")
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

    mark_stage("runner", "done")
    improvements = []
    mark_stage("improvement")
    for iteration in range(1, max(0, config.improve_iterations) + 1):
        checkpoint = (
            debug_run_dir / "improvements" / f"iteration-{iteration:02d}.json"
            if debug_run_dir is not None
            else None
        )
        cached_improvement = None
        if resuming and checkpoint is not None:
            payload = _read_json(checkpoint)
            if isinstance(payload, dict):
                saved_run = payload.get("run")
                if isinstance(saved_run, dict):
                    payload["run"] = {
                        **saved_run,
                        "suite": payload.get("suite"),
                        "qc_report": payload.get("qc_report"),
                    }
                try:
                    cached_improvement = ImprovementIteration.model_validate(payload)
                except (TypeError, ValueError):
                    cached_improvement = None
        if cached_improvement is not None:
            improvements.append(cached_improvement)
            if cached_improvement.suite and cached_improvement.qc_report and cached_improvement.run:
                suite, qc_report, run = (
                    cached_improvement.suite,
                    cached_improvement.qc_report,
                    cached_improvement.run,
                )
            continue
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
        if checkpoint is not None:
            write_json(checkpoint, improved.model_dump(mode="json"))
    mark_stage("improvement", "done")

    mark_stage("reporting")
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
    mark_stage("reporting", "done")
    return pkg


def run_pipeline(
    goal: str | None,
    config: BenchmarkConfig,
    *,
    log: Callable[[str], None] = print,
    progress: Callable[[str], None] = print,
    ask_user: Optional[Callable[[str], str]] = None,
    interactive: bool = True,
    resume_run: str | Path | None = None,
) -> BenchmarkPackage:
    """Run the pipeline with durable diagnostics even when a later stage fails."""
    resuming = resume_run is not None
    if resuming:
        debug_run_dir = _resolve_resume_dir(config.output_dir, resume_run)
        saved_input = _read_json(debug_run_dir / "input.json")
        if not isinstance(saved_input, dict):
            raise ValueError(f"Resume run has no readable input checkpoint: {debug_run_dir}")
        saved_original_goal = str(saved_input.get("original_goal") or "").strip()
        if goal and saved_original_goal and goal.strip() != saved_original_goal:
            raise ValueError(
                "The supplied goal does not match the goal recorded by the resume run. "
                "Omit the goal to resume the recorded run."
            )
        goal = str(saved_input.get("normalized_goal") or saved_original_goal).strip()
        _write_run_state(debug_run_dir, "running", resumed_from=str(debug_run_dir))
    else:
        if not goal or not goal.strip():
            raise ValueError("A non-empty goal is required when starting a new run.")
        debug_run_dir = new_debug_dir(config.output_dir, "runs")
    if debug_run_dir is None:
        return _run_pipeline(
            goal or "",
            config,
            log=log,
            progress=progress,
            ask_user=ask_user,
            interactive=interactive,
            resuming=False,
        )

    if not resuming:
        write_json(
            debug_run_dir / "config.json",
            config.model_dump(mode="json"),
            redact=True,
        )
    log(
        f"[Checkpoint] {'Resuming' if resuming else 'Run'} directory: {debug_run_dir}"
    )
    log_path = debug_run_dir / "pipeline.log"

    def traced_log(message: str) -> None:
        write_text(log_path, str(message) + "\n", append=True)
        log(message)

    def traced_progress(message: str) -> None:
        write_text(log_path, str(message) + "\n", append=True)
        progress(message)

    live_run_id = _live_run_id(debug_run_dir, config.live_url)
    try:
        package = _run_pipeline(
            goal,
            config,
            log=traced_log,
            progress=traced_progress,
            ask_user=ask_user,
            interactive=interactive,
            debug_run_dir=debug_run_dir,
            live_run_id=live_run_id,
            resuming=resuming,
        )
    except BaseException as exc:
        _live_end(live_run_id, failed=True)
        state = _read_json(debug_run_dir / "status.json")
        _write_run_state(
            debug_run_dir,
            "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
            stage=state.get("stage") if isinstance(state, dict) else None,
        )
        write_json(
            debug_run_dir / "failure.json",
            {**error_record(exc), "traceback": traceback.format_exc()},
            redact=True,
        )
        raise
    _live_end(live_run_id)
    _write_run_state(debug_run_dir, "completed", stage="completed")
    return package
