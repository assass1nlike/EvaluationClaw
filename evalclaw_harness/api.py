"""Standalone construction and validation API for EvalClaw Harness."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from evalclaw.benchmark import build_suite_from_spec_with_qc_loop
from evalclaw.diagnostics import error_record, safe_name, write_json
from evalclaw.execution.agent_envs import build_agent_environment
from evalclaw.quality.qc import run_qc_gate
from evalclaw.types import (
    BenchmarkConfig,
    QcCategory,
    QcIssue,
    QcReport,
    QcSeverity,
    TaskSuite,
)

from .models import HarnessConfig, HarnessRequest, HarnessResult

_ARTIFACT_FILES = ("request.json", "config.json", "suite.json", "qc-report.json", "result.json")


def _prepare_output_dir(output_dir: str | Path) -> Path:
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    existing = [name for name in (*_ARTIFACT_FILES, "failure.json") if (root / name).exists()]
    if existing:
        raise FileExistsError(
            f"Harness output directory already contains run artifacts: {', '.join(existing)}"
        )
    return root


def _artifacts(root: Path, *, include_request: bool) -> dict[str, str]:
    names = ["suite.json", "qc-report.json", "result.json", "config.json"]
    if include_request:
        names.insert(0, "request.json")
    if (root / "traces").exists():
        names.append("traces")
    return {Path(name).stem.replace("-", "_"): name for name in names}


def _save_result(root: Path, result: HarnessResult) -> None:
    write_json(root / "suite.json", result.suite.model_dump(mode="json"), redact=True)
    write_json(root / "qc-report.json", result.qc_report.model_dump(mode="json"), redact=True)
    write_json(root / "result.json", result.model_dump(mode="json"), redact=True)


def build(
    request: HarnessRequest,
    config: HarnessConfig,
    output_dir: str | Path,
    *,
    log: Callable[[str], None] = print,
) -> HarnessResult:
    """Build and quality-check a benchmark without invoking EvalClaw's Planner or Runner."""
    root = _prepare_output_dir(output_dir)
    write_json(root / "request.json", request.model_dump(mode="json"), redact=True)
    write_json(root / "config.json", config.model_dump(mode="json"), redact=True)
    try:
        runtime_config = config.to_benchmark_config(
            output_dir=str(root),
            research_brief=request.research_brief,
        )
        plan = request.to_plan()
        suite, qc_report = build_suite_from_spec_with_qc_loop(
            plan.to_eval_spec(),
            plan.builder_jobs,
            runtime_config,
            log=log,
            trace_dir=root / "traces",
        )
        suite.plan = plan
        status = (
            "ready"
            if qc_report.is_acceptable and len(suite.tasks) == request.planned_task_count
            else "incomplete"
        )
        result = HarnessResult(
            operation="build",
            request_id=request.id,
            status=status,
            suite=suite,
            qc_report=qc_report,
            artifacts=_artifacts(root, include_request=True),
        )
        _save_result(root, result)
        return result
    except Exception as exc:
        write_json(root / "failure.json", error_record(exc), redact=True)
        raise


def _environment_preflight_issues(
    suite: TaskSuite,
    config: BenchmarkConfig,
    trace_dir: Path,
) -> list[QcIssue]:
    if not config.environment_preflight:
        return []
    issues: list[QcIssue] = []
    for item in suite.tasks:
        environment = item.metadata.get("agent_env")
        if not isinstance(environment, dict) or environment.get("type") != "docker_workspace":
            continue
        instance = None
        item_dir = trace_dir / safe_name(item.id)
        try:
            instance = build_agent_environment(item, config)
            outcome = instance.preflight()
            write_json(item_dir / "result.json", outcome.as_dict())
        except Exception as exc:
            write_json(item_dir / "failure.json", error_record(exc), redact=True)
            issues.append(
                QcIssue(
                    item_id=item.id,
                    severity=QcSeverity.error,
                    category=QcCategory.schema,
                    message=f"Executable environment preflight failed: {type(exc).__name__}: {exc}",
                    suggested_action="Repair the task environment before publishing the package.",
                )
            )
        finally:
            cleanup = getattr(instance, "cleanup", None)
            if callable(cleanup):
                cleanup()
    return issues


def _merge_qc_issues(report: QcReport, issues: list[QcIssue], suite: TaskSuite) -> QcReport:
    if not issues:
        return report
    merged = [*report.issues, *issues]
    rejected = {
        issue.item_id
        for issue in merged
        if issue.item_id and issue.severity == QcSeverity.error
    }
    passed = [item.id for item in suite.tasks if item.id not in rejected]
    penalty = sum(0.2 if issue.severity == QcSeverity.error else 0.05 for issue in merged)
    return QcReport(
        issues=merged,
        passed_item_ids=passed,
        rejected_item_ids=sorted(rejected),
        quality_score=max(0.0, min(1.0, 1.0 - penalty / max(1, len(suite.tasks)))),
        summary=(
            f"QC completed: {len(passed)}/{len(suite.tasks)} items passed, "
            f"{len(rejected)} rejected, {len(merged)} issues."
        ),
    )


def validate(
    suite: TaskSuite,
    config: HarnessConfig,
    output_dir: str | Path,
) -> HarnessResult:
    """Run Harness QC and executable-environment preflight on an existing task package."""
    root = _prepare_output_dir(output_dir)
    write_json(root / "config.json", config.model_dump(mode="json"), redact=True)
    try:
        runtime_config = config.to_benchmark_config(output_dir=str(root))
        qc_report = run_qc_gate(suite, runtime_config, trace_dir=root / "traces" / "qc")
        environment_issues = _environment_preflight_issues(
            suite,
            runtime_config,
            root / "traces" / "environment-preflight",
        )
        qc_report = _merge_qc_issues(qc_report, environment_issues, suite)
        result = HarnessResult(
            operation="validate",
            request_id=suite.id,
            status="ready" if qc_report.is_acceptable else "incomplete",
            suite=suite,
            qc_report=qc_report,
            artifacts=_artifacts(root, include_request=False),
        )
        _save_result(root, result)
        return result
    except Exception as exc:
        write_json(root / "failure.json", error_record(exc), redact=True)
        raise


__all__ = ["build", "validate"]
