"""EvaluationClaw CLI."""
from __future__ import annotations

import json
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .pipeline import run_pipeline
from .providers import orchestrator_defaults, target_from_model
from .types import BenchmarkConfig, BenchmarkPackage, TargetModelConfig

app = typer.Typer(
    name="evalclaw",
    help="Build, QC, run, and report model evaluation benchmarks from natural language goals.",
    add_completion=False,
)
console = Console()
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


@app.callback()
def _main() -> None:
    """EvaluationClaw command group."""
    return None


def _ask_user(prompt: str) -> str:
    return typer.prompt(prompt, default="", show_default=False)


def _parse_targets(
    model: str,
    compare: list[str],
    target_api_key: Optional[str],
    base_url: Optional[str],
    fallback_key: Optional[str],
) -> list[TargetModelConfig]:
    target_models = [model, *compare]
    targets: list[TargetModelConfig] = []
    seen: set[str] = set()
    for target_model in target_models:
        if target_model in seen:
            continue
        seen.add(target_model)
        targets.append(
            target_from_model(
                target_model,
                api_key=target_api_key if target_model == model else None,
                base_url=base_url if target_model == model else None,
                fallback_key=fallback_key,
            )
        )
    return targets


def _print_summary(pkg: BenchmarkPackage) -> None:
    console.print()
    console.print(Panel("[bold]EvaluationClaw Summary[/bold]", expand=False))
    console.print(f"Goal: {pkg.goal}")
    console.print(f"Spec: {pkg.spec.id}")
    console.print(f"Dimensions: {len(pkg.spec.dimensions)}")
    console.print(f"Items: {len(pkg.dataset.items)}")
    console.print(f"QC quality: {pkg.qc_report.quality_score * 100:.1f}%")
    console.print(f"QC issues: {len(pkg.qc_report.issues)}")

    if pkg.report.summaries:
        table = Table(title="Target Results")
        table.add_column("Target")
        table.add_column("Model")
        table.add_column("Average", justify="right")
        table.add_column("Items", justify="right")
        table.add_column("Errors", justify="right")
        for summary in pkg.report.summaries:
            table.add_row(
                summary.target_id,
                summary.model,
                f"{summary.average_score * 100:.1f}%",
                str(summary.total_items),
                str(summary.errors),
            )
        console.print(table)
    else:
        console.print("[yellow]No target results were run.[/yellow]")

    if pkg.report.recommendations:
        console.print()
        console.print("[bold]Recommendations[/bold]")
        for rec in pkg.report.recommendations:
            console.print(f"- {rec}")


@app.command("generate")
def generate(
    goal: Optional[str] = typer.Option(None, "-g", "--goal", help="Evaluation goal."),
    model: str = typer.Option("claude-sonnet-4-6", "-m", "--model", help="Primary target model."),
    compare: list[str] = typer.Option(
        [],
        "--compare",
        help="Additional target model to compare. May be repeated.",
    ),
    orchestrator_model: str = typer.Option(
        "claude-opus-4-6",
        "--orchestrator-model",
        help="Model used for planner/generator/QC/judge.",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="Orchestrator API key. Defaults to provider env vars such as ANTHROPIC_API_KEY, GEMINI_API_KEY, or DEEPSEEK_API_KEY.",
    ),
    target_api_key: Optional[str] = typer.Option(
        None,
        "--target-api-key",
        help="Primary target API key. Compare targets use provider environment defaults.",
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="OpenAI-compatible base URL for the primary target.",
    ),
    orchestrator_base_url: Optional[str] = typer.Option(
        None,
        "--orchestrator-base-url",
        help="OpenAI-compatible base URL for the orchestrator.",
    ),
    questions_per_dimension: int = typer.Option(5, "--qpd", help="Items per dimension."),
    max_planner_iterations: int = typer.Option(5, "--max-planner-iterations", help="Planner self-critique iterations."),
    max_qc_iterations: int = typer.Option(3, "--max-qc-iterations", help="Reserved for future QC regeneration loops."),
    output_dir: str = typer.Option("./benchmark-output", "-o", "--output-dir", help="Output directory."),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Skip confirmation prompts."),
    no_run: bool = typer.Option(False, "--no-run", help="Build and QC the benchmark without running targets."),
    no_research: bool = typer.Option(False, "--no-research", help="Disable web research during generation."),
    no_hf_discovery: bool = typer.Option(False, "--no-hf-discovery", help="Disable HuggingFace dataset discovery."),
    single_pass_judge: bool = typer.Option(False, "--single-pass-judge", help="Use one judge pass instead of the default double-pass audit."),
    llm_backend: str = typer.Option("auto", "--llm-backend", help="LLM backend: auto, litellm, or legacy."),
    runner: str = typer.Option("direct", "--runner", help="Runner mode: direct, lm-eval, or auto."),
    improve_iterations: int = typer.Option(0, "--improve-iterations", help="Loop 3 self-improvement iterations after the first run."),
    json_output: bool = typer.Option(False, "--json", help="Print full package JSON to stdout."),
) -> None:
    """Generate an EvaluationClaw benchmark package."""
    if not goal:
        goal = typer.prompt("Evaluation goal").strip()
    if not goal:
        console.print("[red]Goal cannot be empty.[/red]")
        raise typer.Exit(1)

    effective_api_key, effective_orch_base = orchestrator_defaults(
        orchestrator_model,
        api_key=api_key,
        base_url=orchestrator_base_url,
    )

    targets = _parse_targets(
        model,
        compare,
        target_api_key,
        base_url,
        fallback_key=effective_api_key,
    )
    config = BenchmarkConfig(
        orchestrator_model=orchestrator_model,
        orchestrator_api_key=effective_api_key,
        orchestrator_base_url=effective_orch_base,
        targets=targets,
        questions_per_dimension=questions_per_dimension,
        max_planner_iterations=max_planner_iterations,
        max_qc_iterations=max_qc_iterations,
        output_dir=output_dir,
        run_targets=not no_run,
        use_web_research=not no_research,
        use_hf_discovery=not no_hf_discovery,
        judge_double_pass=not single_pass_judge,
        llm_backend=llm_backend,
        runner=runner,
        improve_iterations=improve_iterations,
    )

    log_console = Console(stderr=json_output)

    def _log(msg: str) -> None:
        log_console.print(msg)

    def _progress(msg: str) -> None:
        stream = sys.stderr if json_output else sys.stdout
        stream.write(f"\r{msg}")
        stream.flush()

    try:
        pkg = run_pipeline(
            goal,
            config,
            log=_log,
            progress=_progress,
            ask_user=_ask_user if not no_interactive else None,
            interactive=not no_interactive,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]Evalclaw failed: {exc}[/red]")
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(pkg.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        _print_summary(pkg)


def main() -> None:
    app()
