from __future__ import annotations

import json
import os
import time
from pathlib import Path

from evalclaw.agent_benchmark import (
    build_agent_task_suite,
    plan_agent_benchmark,
    task_suite_to_dataset,
)
from evalclaw.quality.qc import run_qc_gate
from evalclaw.reporting.artifacts import write_artifact_manifest
from evalclaw.reporting.reporter import artifact_index_markdown, build_report
from evalclaw.reporting.viewer import build_report_viewer_html
from evalclaw.research.deep_research import render_brief_markdown, run_deep_research
from evalclaw.runner import run_eval
from evalclaw.types import (
    BenchmarkConfig,
    BenchmarkMode,
    BenchmarkPackage,
    ScaleBudget,
    TargetModelConfig,
)

GOALS = [
    (
        "01_engineering",
        "Design a set of high-difficulty agent benchmarks to evaluate whether models can complete professional engineering workflows in real engineering software and file environments. The tasks should cover starting from input specifications, drawings, configurations, or assets; using CAD, EDA, simulation, or modeling tools; producing checkable engineering artifacts; and being scored by hidden checkers for correctness, completeness, and process documentation.",
    ),
    (
        "02_life_sciences",
        "Design a set of agent benchmarks to evaluate whether models can execute life-science data analysis workflows. Tasks should require the model to read experimental data, metadata, and analysis specifications; select or repair an appropriate analysis pipeline; produce structured results, figures, or reports; and be scored by hidden reference outputs and provenance checks.",
    ),
    (
        "03_health_medicine",
        "Design a set of agent benchmarks to evaluate whether models can handle medical and clinical data tasks. Tasks should cover scenarios such as clinical records, medical images, genetic variants, epidemiological forecasting, or trial data; require the model to generate verifiable outputs in a controlled environment; and avoid purely generic written answers.",
    ),
    (
        "04_systems_security_ops",
        "Design a set of agent benchmarks to evaluate whether models can perform system diagnosis, data-pipeline repair, security analysis, and operations troubleshooting in real computing environments. Tasks should require the model to inspect files, logs, configurations, code, or network data; run commands; and produce results that hidden tests can verify.",
    ),
    (
        "05_math_algorithms_optimization",
        "Design a set of agent benchmarks to evaluate whether models can solve complex algorithmic, optimization, simulation, or formal-computation tasks. Tasks should provide executable code or data environments and require the model to implement, repair, or verify algorithm outputs rather than only provide paper reasoning.",
    ),
]


def _config(*, orchestrator: bool, deep: bool, brief=None, output_dir: str) -> BenchmarkConfig:
    key = os.environ.get("DEEPSEEK_API_KEY")
    return BenchmarkConfig(
        benchmark_mode=BenchmarkMode.agent,
        orchestrator_model="deepseek-v4-pro",
        orchestrator_api_key=key if orchestrator else None,
        orchestrator_base_url="https://api.deepseek.com" if orchestrator else None,
        targets=[
            TargetModelConfig(
                id="deepseek-v4-flash",
                provider="openai_compatible",
                model="deepseek-v4-flash",
                api_key=key,
                base_url="https://api.deepseek.com",
            )
        ],
        scale_budget=ScaleBudget.low,
        questions_per_dimension=1,
        max_planner_iterations=1,
        max_qc_iterations=1,
        max_hf_records_per_dimension=1,
        run_targets=False,
        use_web_research=True,
        search_backend="keyless",
        use_deep_research=deep,
        max_research_iterations=1,
        use_hf_discovery=True,
        judge_double_pass=False,
        llm_backend="litellm",
        output_dir=output_dir,
        research_brief=brief,
    )


def _write_package(pkg: BenchmarkPackage, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pkg.created_at.replace(":", "").replace("+", "_").replace(".", "_")
    json_path = out_dir / f"evalclaw_{stem}.json"
    md_path = out_dir / f"evalclaw_{stem}.md"
    html_path = out_dir / f"evalclaw_{stem}.html"
    research_paths = None
    if pkg.research_brief is not None:
        brief_json = out_dir / "research_brief.json"
        brief_md = out_dir / "research_brief.md"
        brief_json.write_text(json.dumps(pkg.research_brief.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        brief_md.write_text(render_brief_markdown(pkg.research_brief), encoding="utf-8")
        research_paths = {"json": brief_json, "markdown": brief_md}
    manifest_path = out_dir / "manifest.json"
    pkg.report.markdown = pkg.report.markdown.rstrip() + "\n\n" + artifact_index_markdown(
        package_path=json_path,
        report_path=md_path,
        frontend_report_path=html_path,
        manifest_path=manifest_path,
        lm_eval_paths={},
    )
    json_path.write_text(json.dumps(pkg.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(pkg.report.markdown, encoding="utf-8")
    html_path.write_text(build_report_viewer_html(pkg), encoding="utf-8")
    write_artifact_manifest(
        out_dir,
        package_path=json_path,
        report_path=md_path,
        frontend_report_path=html_path,
        lm_eval_paths={},
        research_brief_paths=research_paths,
    )


def run_one(slug: str, goal: str, variant: str, *, deep: bool) -> None:
    out_dir = Path("benchmark-output") / f"ale_scaleup_first5_{slug}_{variant}"
    log_path = out_dir / "generation_log.txt"
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.time()

    def log(message: str) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
        print(message, flush=True)

    log(f"START {slug} {variant}")
    brief = None
    if deep:
        research_config = _config(orchestrator=True, deep=True, output_dir=str(out_dir))
        brief = run_deep_research(goal, research_config, log=log)
        if brief is None:
            log("Deep research returned no brief; continuing with baseline planner context.")

    planning_config = _config(orchestrator=True, deep=deep, brief=brief, output_dir=str(out_dir))
    spec, blueprints = plan_agent_benchmark(goal, planning_config)
    log(f"planned dims={len(spec.dimensions)} blueprints={len(blueprints)}")

    build_config = _config(orchestrator=True, deep=deep, brief=brief, output_dir=str(out_dir))
    suite = build_agent_task_suite(spec, blueprints, build_config)
    dataset = task_suite_to_dataset(suite, spec, build_config)
    qc_report = run_qc_gate(dataset, build_config)
    run = run_eval(dataset, qc_report, build_config)
    report = build_report(run, research_brief=brief)
    pkg = BenchmarkPackage(
        goal=goal,
        spec=spec,
        dataset=dataset,
        qc_report=qc_report,
        run=run,
        report=report,
        research_brief=brief,
    )
    _write_package(pkg, out_dir)
    elapsed = time.time() - start
    log(f"DONE {slug} {variant} elapsed={elapsed:.1f}s items={len(dataset.items)} qc={qc_report.quality_score:.3f}")


def main() -> None:
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7890")
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7890")
    for slug, goal in GOALS:
        run_one(slug, goal, "baseline", deep=False)
        run_one(slug, goal, "deep_research", deep=True)


if __name__ == "__main__":
    main()
