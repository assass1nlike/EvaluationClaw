#!/usr/bin/env python
"""Experiment 1: A/B comparison of baseline vs deep-research benchmark generation.

For each (vague) goal in the config, runs the EvalClaw pipeline twice with the
same settings — deep research OFF (baseline) vs ON — then computes comparison
metrics into metrics.json and a human-readable report.md per goal under
experiments/results/exp1_<slug>/.

Degrades gracefully without credentials: the pipeline falls back to its local
no-key paths, LLM audits are marked skipped, semantic diversity falls back to
token-Jaccard, and the runner/discriminative metric is skipped.

Usage:
  python experiments/run_ab_deep_research.py --config experiments/config.example.json
  python experiments/run_ab_deep_research.py --smoke   # 1 goal, low budget, minimal samples
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))            # experiments/ for _lib
sys.path.insert(0, str(_HERE.parent))     # repo root for evalclaw when not pip-installed

import _lib

from evalclaw.models.providers import resolve_role_connection, target_from_model
from evalclaw.pipeline import run_pipeline
from evalclaw.types import BenchmarkConfig, ScaleBudget


def _build_bench_config(
    exp: dict,
    variant_dir: Path,
    *,
    deep_research: bool,
    smoke: bool,
) -> tuple[BenchmarkConfig, str, str, bool]:
    """Build the pipeline config for one variant.

    Returns (config, strong_target_id, weak_target_id, offline, orch).
    ``offline`` is True when no role credential could be resolved; in that mode
    network-dependent stages are disabled so the run still completes.
    """
    role_model = exp["role_model"]
    role_key, role_base = resolve_role_connection(role_model)
    offline = not role_key

    strong = target_from_model(exp["strong_target"], fallback_key=role_key)
    weak = target_from_model(exp["weak_target"], fallback_key=role_key)
    targets = [strong] if weak.id == strong.id else [strong, weak]
    run_targets = any(bool(t.api_key) for t in targets)

    role_fields: dict[str, object] = {}
    for role in ("planner", "task_builder", "qc", "research"):
        role_fields[f"{role}_model"] = role_model
        role_fields[f"{role}_api_key"] = role_key
        role_fields[f"{role}_base_url"] = role_base

    config = BenchmarkConfig(
        **role_fields,
        targets=targets,
        scale_budget=ScaleBudget(str(exp["scale_budget"]).lower() if not smoke else "low"),
        use_deep_research=deep_research,
        max_research_iterations=1 if smoke else int(exp["max_research_iterations"]),
        search_backend=str(exp["search_backend"]),
        llm_backend=str(exp["llm_backend"]),
        use_web_research=not offline,
        use_hf_discovery=not offline,
        run_targets=run_targets,
        human_review=False,
        output_dir=str(variant_dir),
    )
    orch = {
        "model": role_model,
        "api_key": role_key,
        "base_url": role_base,
        "backend": config.llm_backend,
    }
    return config, strong.id, weak.id, offline, orch


def _run_variant(
    goal: str,
    exp: dict,
    variant_dir: Path,
    *,
    deep_research: bool,
    smoke: bool,
) -> dict:
    """Run one pipeline variant and compute its metrics dict."""
    config, strong_id, weak_id, offline, orch = _build_bench_config(
        exp, variant_dir, deep_research=deep_research, smoke=smoke
    )
    timer = _lib.StageTimer()

    try:
        with _lib.count_llm_calls() as llm_counter, timer.stage("pipeline"):
            pkg = run_pipeline(
                goal,
                config,
                log=lambda msg: print(f"    {msg}"),
                progress=lambda _msg: None,
                ask_user=None,
                interactive=False,
            )
    except Exception as exc:
        return {
            "error": f"pipeline failed: {exc}",
            "wall_time_s": timer.as_dict().get("pipeline"),
            "offline": offline,
        }

    with timer.stage("coverage_audit"):
        coverage = _lib.audit_dimension_coverage(goal, pkg.spec, orch)

    accepted_ids = set(pkg.qc_report.passed_item_ids)
    accepted_items = [item for item in pkg.dataset.items if item.id in accepted_ids] or list(pkg.dataset.items)
    per_dim = 1 if smoke else int(exp["item_audit_sample_per_dimension"])
    cap = 3 if smoke else int(exp["item_audit_sample_cap"])
    sample = _lib.stratified_sample(accepted_items, per_dimension=per_dim, cap=cap)
    with timer.stage("item_audit"):
        item_validity = _lib.audit_item_validity(goal, sample, orch)

    embed_fn = None
    if exp.get("embedding_model") and orch["api_key"]:
        embed_fn = _lib.make_litellm_embed_fn(str(exp["embedding_model"]))
    with timer.stage("diversity"):
        diversity = _lib.semantic_diversity(
            [item.prompt for item in accepted_items], embed_fn=embed_fn
        )

    if pkg.run.results:
        discriminative = _lib.discriminative_power(pkg.run.summaries, strong_id, weak_id)
    else:
        discriminative = {"skipped": "runner produced no results (no target credentials or run disabled)"}

    metrics = {
        "offline": offline,
        "deep_research": deep_research,
        "research_brief_present": pkg.research_brief is not None,
        "wall_time_s": timer.as_dict().get("pipeline"),
        "stage_times_s": timer.as_dict(),
        "llm_calls": dict(llm_counter),
        "dimensions": len(pkg.spec.dimensions),
        "items": len(pkg.dataset.items),
        "accepted_items": len(accepted_items),
        "qc_quality": round(pkg.qc_report.quality_score, 4),
        "coverage_audit": coverage,
        "item_validity": item_validity,
        "diversity": diversity,
        "discriminative": discriminative,
    }
    if offline:
        metrics["notes"] = (
            "offline mode: no role credential resolved, so web research, HF discovery, "
            "target runs, and LLM audits were skipped; pipeline used local fallbacks."
        )
    return metrics


def run_experiment(exp: dict, *, smoke: bool, output_root: Path) -> list[Path]:
    goals = exp["goals"][:1] if smoke else exp["goals"]
    report_paths: list[Path] = []
    for goal in goals:
        slug = _lib.slugify(goal)
        goal_dir = output_root / f"exp1_{slug}"
        print(f"\n=== Goal: {goal}")
        variants: dict = {}
        for variant, deep in (("baseline", False), ("deep_research", True)):
            print(f"  -- Variant: {variant}")
            variants[variant] = _run_variant(
                goal, exp, goal_dir / variant, deep_research=deep, smoke=smoke
            )
        metrics = {
            "goal": goal,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "smoke": smoke,
            "experiment_config": {
                "role_model": exp["role_model"],
                "strong_target": exp["strong_target"],
                "weak_target": exp["weak_target"],
                "embedding_model": exp.get("embedding_model"),
                "scale_budget": "low" if smoke else exp["scale_budget"],
                "search_backend": exp["search_backend"],
            },
            "variants": variants,
        }
        _lib.write_json(goal_dir / "metrics.json", metrics)
        report_path = goal_dir / "report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_lib.render_exp1_report(goal, metrics), encoding="utf-8")
        report_paths.append(report_path)
        print(f"  Metrics: {goal_dir / 'metrics.json'}")
        print(f"  Report:  {report_path}")
    return report_paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--config",
        default=str(_HERE / "config.example.json"),
        help="Experiment config JSON (default: experiments/config.example.json).",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Smoke mode: first goal only, low scale budget, minimal audit samples.",
    )
    parser.add_argument("--output-root", default=None, help="Override the config output_root.")
    args = parser.parse_args()

    config_path = Path(args.config)
    exp = _lib.load_config(config_path if config_path.exists() else None)
    if not config_path.exists():
        print(f"[warn] config {config_path} not found; using built-in defaults")
    output_root = Path(args.output_root or exp["output_root"])
    if not output_root.is_absolute():
        output_root = _lib.REPO_ROOT / output_root

    with _lib.tee_output(output_root / "exp1_run.log"):
        reports = run_experiment(exp, smoke=args.smoke, output_root=output_root)
        print(f"\nDone. {len(reports)} goal report(s) written under {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
