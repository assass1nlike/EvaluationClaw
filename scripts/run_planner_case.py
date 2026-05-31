"""Run one EvaluationClaw planner-loop case up to the pre-run human review state."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from evalclaw.planner import plan_eval_spec
from evalclaw.planning_loop import format_human_review_overview, generate_dataset_with_qc_loop
from evalclaw.providers import orchestrator_defaults, target_from_model
from evalclaw.types import BenchmarkConfig, ScaleBudget

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]+")


def _redact_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--orchestrator-model", default="deepseek-reasoner")
    parser.add_argument("--task-agent-model", default="deepseek-reasoner")
    parser.add_argument("--target-model", default="deepseek-chat")
    parser.add_argument("--scale-budget", default="mid", choices=["low", "mid", "high"])
    parser.add_argument("--questions-per-dimension", type=int, default=3)
    parser.add_argument("--max-planner-iterations", type=int, default=5)
    parser.add_argument("--max-qc-iterations", type=int, default=4)
    parser.add_argument("--max-research-sources", type=int, default=3)
    parser.add_argument("--max-hf-records-per-dimension", type=int, default=0)
    parser.add_argument("--use-web-research", action="store_true")
    parser.add_argument("--use-hf-discovery", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_dir = Path(args.output_root) / args.case_id
    out_dir.mkdir(parents=True, exist_ok=True)
    error_path = out_dir / "error.txt"

    orchestrator_api_key, orchestrator_base_url = orchestrator_defaults(args.orchestrator_model)
    if not orchestrator_api_key:
        raise RuntimeError(
            f"No API key found for orchestrator model {args.orchestrator_model!r}. "
            "Set the matching provider environment variable before running."
        )

    target = target_from_model(args.target_model)

    config = BenchmarkConfig(
        orchestrator_model=args.orchestrator_model,
        orchestrator_api_key=orchestrator_api_key,
        orchestrator_base_url=orchestrator_base_url,
        task_agent_model=args.task_agent_model,
        task_agent_api_key=orchestrator_api_key,
        task_agent_base_url=orchestrator_base_url,
        targets=[target],
        scale_budget=ScaleBudget(args.scale_budget),
        questions_per_dimension=args.questions_per_dimension,
        max_planner_iterations=args.max_planner_iterations,
        max_qc_iterations=args.max_qc_iterations,
        max_research_sources=args.max_research_sources,
        max_hf_records_per_dimension=args.max_hf_records_per_dimension,
        output_dir=str(out_dir),
        run_targets=False,
        use_web_research=args.use_web_research,
        use_hf_discovery=args.use_hf_discovery,
        judge_double_pass=True,
        llm_backend="legacy",
        runner="direct",
        human_review=False,
        improve_iterations=0,
        loop3_diagnosis="llm",
        loop3_diagnosis_timeout_s=90,
        loop3_max_actions=4,
    )

    spec = plan_eval_spec(args.goal, config)
    spec, dataset, qc_report = generate_dataset_with_qc_loop(spec, config)
    overview = format_human_review_overview(dataset, qc_report, config)
    if error_path.exists():
        error_path.unlink()

    state = {
        "case_id": args.case_id,
        "goal": args.goal,
        "config": config.model_dump(mode="json"),
        "spec": spec.model_dump(mode="json"),
        "dataset": dataset.model_dump(mode="json"),
        "qc_report": qc_report.model_dump(mode="json"),
        "overview_path": str(out_dir / "human_review_overview.md"),
        "state_path": str(out_dir / "pre_run_state.json"),
    }
    (out_dir / "human_review_overview.md").write_text(overview, encoding="utf-8")
    state_json = json.dumps(state, ensure_ascii=False, indent=2)
    (out_dir / "pre_run_state.json").write_text(_redact_secrets(state_json), encoding="utf-8")
    print(
        json.dumps(
            {
                "case_id": args.case_id,
                "status": "ready",
                "dimensions": len(spec.dimensions),
                "items": len(dataset.items),
                "qc_quality": qc_report.quality_score,
                "output_dir": str(out_dir),
            },
            ensure_ascii=False,
        )
    )
    if error_path.exists():
        error_path.unlink()


if __name__ == "__main__":
    main()
