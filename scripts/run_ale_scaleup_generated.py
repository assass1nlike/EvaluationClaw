from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from evalclaw.execution.environment_claw import format_environment_claw_report, run_environment_claw
from evalclaw.execution.runner import run_eval
from evalclaw.reporting.reporter import build_report
from evalclaw.reporting.viewer import build_report_viewer_html
from evalclaw.types import BenchmarkConfig, BenchmarkPackage, TargetModelConfig

PACKAGE_GLOB = "ale_scaleup_first5_*"


def _latest_package_path(case_dir: Path) -> Path | None:
    manifest = case_dir / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        package = data.get("package")
        if package:
            path = Path(package)
            if path.exists():
                return path
    candidates = sorted(case_dir.glob("evalclaw_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _target_config() -> TargetModelConfig:
    key = os.environ.get("DEEPSEEK_API_KEY")
    return TargetModelConfig(
        id="deepseek-v4-flash",
        provider="openai_compatible",
        model="deepseek-v4-flash",
        api_key=key,
        base_url="https://api.deepseek.com",
    )


def _run_config(pkg: BenchmarkPackage, output_dir: Path) -> BenchmarkConfig:
    return BenchmarkConfig(
        benchmark_mode=pkg.dataset.spec.task_types and "agent" or "auto",
        orchestrator_model="deepseek-v4-pro",
        orchestrator_api_key=os.environ.get("DEEPSEEK_API_KEY"),
        orchestrator_base_url="https://api.deepseek.com",
        targets=[_target_config()],
        scale_budget=pkg.spec.scale_budget,
        output_dir=str(output_dir),
        run_targets=True,
        use_web_research=False,
        use_deep_research=False,
        judge_double_pass=False,
        llm_backend="litellm",
        runner="direct",
        environment_claw=True,
    )


def _write_run_outputs(
    case_dir: Path,
    pkg: BenchmarkPackage,
    env_report: dict[str, Any],
    *,
    blocked: bool,
) -> None:
    suffix = "blocked" if blocked else "run"
    json_path = case_dir / f"rerun_{suffix}.json"
    md_path = case_dir / f"rerun_{suffix}.md"
    html_path = case_dir / f"rerun_{suffix}.html"
    pkg.run.runner_artifacts["environment_claw"] = env_report
    pkg.report = build_report(pkg.run, research_brief=pkg.research_brief)
    json_path.write_text(json.dumps(pkg.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(pkg.report.markdown, encoding="utf-8")
    html_path.write_text(build_report_viewer_html(pkg), encoding="utf-8")


def run_case(case_dir: Path) -> dict[str, Any]:
    package_path = _latest_package_path(case_dir)
    if package_path is None:
        return {"case": case_dir.name, "status": "missing_package"}
    pkg = BenchmarkPackage.model_validate_json(package_path.read_text(encoding="utf-8"))
    config = _run_config(pkg, case_dir)
    accepted = [item for item in pkg.dataset.items if item.id in set(pkg.qc_report.passed_item_ids)]
    log_path = case_dir / "rerun_log.txt"

    def log(message: str) -> None:
        print(message, flush=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")

    log(f"START {case_dir.name} accepted={len(accepted)}")
    started = time.time()
    direct_config, env_report = run_environment_claw(accepted, config)
    for line in format_environment_claw_report(env_report):
        log(line)
    if env_report.blocking_errors:
        pkg.run.runner_artifacts["environment_claw"] = env_report.as_dict()
        _write_run_outputs(case_dir, pkg, env_report.as_dict(), blocked=True)
        log(f"BLOCKED {case_dir.name} errors={len(env_report.blocking_errors)}")
        return {
            "case": case_dir.name,
            "status": "blocked",
            "items": len(accepted),
            "errors": env_report.blocking_errors,
            "elapsed_s": round(time.time() - started, 1),
        }

    def progress(done: int, total: int, target_id: str, item_id: str) -> None:
        log(f"  {done}/{total} {target_id} {item_id}")

    run = run_eval(pkg.dataset, pkg.qc_report, direct_config, on_progress=progress)
    pkg.run = run
    _write_run_outputs(case_dir, pkg, env_report.as_dict(), blocked=False)
    errors = sum(1 for result in run.results if result.error)
    avg = run.summaries[0].average_score if run.summaries else 0.0
    log(f"DONE {case_dir.name} results={len(run.results)} errors={errors} avg={avg:.3f}")
    return {
        "case": case_dir.name,
        "status": "ran",
        "items": len(accepted),
        "results": len(run.results),
        "errors": errors,
        "average_score": avg,
        "elapsed_s": round(time.time() - started, 1),
    }


def main() -> None:
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7890")
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7890")
    root = Path("benchmark-output")
    cases = sorted(root.glob(PACKAGE_GLOB))
    summary = []
    for case_dir in cases:
        summary.append(run_case(case_dir))
    summary_path = root / "ale_scaleup_first5_rerun_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SUMMARY {summary_path}")


if __name__ == "__main__":
    main()
