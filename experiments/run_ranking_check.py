#!/usr/bin/env python
"""Experiment 2: ranking sanity check (low-cost YourBench-style validation).

Given a pair of target models with a publicly known capability ordering
(strong > weak, e.g. azure/gpt-4o vs azure/gpt-4o-mini), checks whether a
generated benchmark preserves that ordering and how large the score gap is.

Two modes:
  - default: generate a fresh benchmark for --goal via the EvalClaw pipeline
    (deep research off) and use its run results;
  - --package path/to/evalclaw_*.json: reuse an existing benchmark package and
    re-run only the two targets against its accepted items.

Writes experiments/results/exp2_<slug>/{metrics.json,report.md}.

Usage:
  python experiments/run_ranking_check.py --config experiments/config.example.json
  python experiments/run_ranking_check.py --package benchmark-output/evalclaw_XXXX.json
  python experiments/run_ranking_check.py --smoke
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))            # experiments/ for _lib
sys.path.insert(0, str(_HERE.parent))     # repo root for evalclaw when not pip-installed

import _lib

from evalclaw.execution.runner import run_eval
from evalclaw.models.providers import resolve_role_connection, target_from_model
from evalclaw.pipeline import run_pipeline
from evalclaw.types import BenchmarkConfig, BenchmarkDataset, QcReport, ScaleBudget


def _targets_and_config(exp: dict, *, smoke: bool, output_dir: Path) -> tuple[BenchmarkConfig, str, str]:
    role_model = exp["role_model"]
    role_key, role_base = resolve_role_connection(role_model)
    offline = not role_key
    strong = target_from_model(exp["strong_target"], fallback_key=role_key)
    weak = target_from_model(exp["weak_target"], fallback_key=role_key)
    role_fields: dict[str, object] = {}
    for role in ("planner", "task_builder", "qc", "research"):
        role_fields[f"{role}_model"] = role_model
        role_fields[f"{role}_api_key"] = role_key
        role_fields[f"{role}_base_url"] = role_base
    config = BenchmarkConfig(
        **role_fields,
        targets=[strong, weak],
        scale_budget=ScaleBudget("low" if smoke else str(exp["scale_budget"]).lower()),
        search_backend=str(exp["search_backend"]),
        llm_backend=str(exp["llm_backend"]),
        use_web_research=not offline,
        run_targets=any(bool(t.api_key) for t in (strong, weak)),
        human_review=False,
        output_dir=str(output_dir),
    )
    return config, strong.id, weak.id


def _run_from_package(package_path: Path, config: BenchmarkConfig):
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    dataset = BenchmarkDataset.model_validate(payload["dataset"])
    qc_report = QcReport.model_validate(payload["qc_report"])
    return run_eval(dataset, qc_report, config), dataset.spec.objective


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--config",
        default=str(_HERE / "config.example.json"),
        help="Experiment config JSON (default: experiments/config.example.json).",
    )
    parser.add_argument(
        "--goal",
        default=None,
        help="Goal to generate a benchmark for (default: first goal in the config).",
    )
    parser.add_argument(
        "--package",
        default=None,
        help="Existing evalclaw_*.json package to reuse instead of generating a new benchmark.",
    )
    parser.add_argument("--smoke", action="store_true", help="Smoke mode: low budget, minimal items.")
    parser.add_argument("--output-root", default=None, help="Override the config output_root.")
    args = parser.parse_args()

    config_path = Path(args.config)
    exp = _lib.load_config(config_path if config_path.exists() else None)
    if not config_path.exists():
        print(f"[warn] config {config_path} not found; using built-in defaults")
    goal = args.goal or exp["goals"][0]
    slug = _lib.slugify(Path(args.package).stem if args.package else goal)
    output_root = Path(args.output_root or exp["output_root"])
    if not output_root.is_absolute():
        output_root = _lib.REPO_ROOT / output_root
    out_dir = output_root / f"exp2_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    with _lib.tee_output(out_dir / "exp2_run.log"):
        return _run_checked(args, exp, goal, slug, out_dir)


def _run_checked(args, exp: dict, goal: str, slug: str, out_dir: Path) -> int:
    config, strong_id, weak_id = _targets_and_config(exp, smoke=args.smoke, output_dir=out_dir / "package")
    timer = _lib.StageTimer()

    with _lib.count_llm_calls() as llm_counter, timer.stage("run"):
        if args.package:
            run, goal = _run_from_package(Path(args.package), config)
        else:
            pkg = run_pipeline(
                goal,
                config,
                log=lambda msg: print(f"  {msg}"),
                progress=lambda _msg: None,
                ask_user=None,
                interactive=False,
            )
            run = pkg.run

    if run.results:
        result = _lib.discriminative_power(run.summaries, strong_id, weak_id)
        dimension_gaps = _lib.per_dimension_gaps(run.summaries, strong_id, weak_id)
    else:
        result = {"skipped": "runner produced no results (no target credentials or run disabled)"}
        dimension_gaps = {}

    metrics = {
        "goal": goal,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "smoke": args.smoke,
        "package": args.package,
        "strong_target": exp["strong_target"],
        "weak_target": exp["weak_target"],
        "wall_time_s": timer.as_dict().get("run"),
        "llm_calls": dict(llm_counter),
        "result": result,
        "per_dimension_gaps": dimension_gaps,
    }
    _lib.write_json(out_dir / "metrics.json", metrics)
    report = _lib.render_exp2_report(
        goal, exp["strong_target"], exp["weak_target"], result, dimension_gaps
    )
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"Metrics: {out_dir / 'metrics.json'}")
    print(f"Report:  {out_dir / 'report.md'}")
    if "skipped" in result:
        print(f"Result: skipped — {result['skipped']}")
    else:
        print(f"Result: order_correct={result['order_correct']} gap={result['gap']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
