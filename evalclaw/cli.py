"""EvaluationClaw CLI."""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models.providers import normalize_provider, orchestrator_defaults, target_from_model
from .pipeline import run_pipeline
from .types import BenchmarkConfig, BenchmarkPackage, ScaleBudget, TargetModelConfig

app = typer.Typer(
    name="evalclaw",
    help="Build, QC, run, and report model evaluation benchmarks from natural language goals.",
    add_completion=False,
)
console = Console()
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


@app.callback()
def _main() -> None:
    """EvaluationClaw command group."""
    return None


def _ask_user(prompt: str) -> str:
    return typer.prompt(prompt, default="", show_default=False)


def _parse_targets(
    model: Optional[str],
    compare: list[str],
    target_api_key: Optional[str],
    base_url: Optional[str],
    fallback_key: Optional[str],
    target_provider: Optional[str] = None,
) -> list[TargetModelConfig]:
    target_models = ([model] if model else []) + compare
    targets: list[TargetModelConfig] = []
    seen: set[str] = set()
    for target_model in target_models:
        if target_model in seen:
            continue
        seen.add(target_model)
        targets.append(
            target_from_model(
                target_model,
                provider=target_provider if model and target_model == model else None,
                api_key=target_api_key if model and target_model == model else None,
                base_url=base_url if model and target_model == model else None,
                fallback_key=fallback_key,
            )
        )
    return targets


def _parse_target_configs(
    values: list[str],
    *,
    fallback_key: Optional[str],
) -> list[TargetModelConfig]:
    targets: list[TargetModelConfig] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(values, 1):
        try:
            raw = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--target-config #{index} is not valid JSON: {exc.msg}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"--target-config #{index} must be a JSON object.")
        model = str(raw.get("model") or "").strip()
        if not model:
            raise ValueError(f"--target-config #{index} requires a non-empty model.")
        provider_value = raw.get("provider") or raw.get("protocol")
        provider = normalize_provider(str(provider_value)) if provider_value else None
        api_key = str(raw.get("api_key") or "").strip() or None
        api_key_env = str(raw.get("api_key_env") or "").strip()
        if api_key_env:
            api_key = os.environ.get(api_key_env)
            if not api_key:
                raise ValueError(
                    f"--target-config #{index} references unset or empty environment variable {api_key_env}."
                )
        target = target_from_model(
            model,
            target_id=str(raw.get("id") or "").strip() or None,
            provider=provider,
            api_key=api_key,
            base_url=str(raw.get("base_url") or "").strip() or None,
            fallback_key=fallback_key,
        )
        if target.id in seen_ids:
            raise ValueError(f"--target-config target id must be unique: {target.id}")
        seen_ids.add(target.id)
        targets.append(target)
    return targets


def _parse_reference_model(
    reference_model: Optional[str],
    reference_provider: Optional[str],
    reference_api_key: Optional[str],
    reference_base_url: Optional[str],
    fallback_key: Optional[str],
) -> Optional[TargetModelConfig]:
    if not reference_model:
        return None
    reference_id = f"reference_{reference_model.replace('/', '_').replace(':', '_')}"
    if reference_provider:
        return TargetModelConfig(
            id=reference_id,
            provider=normalize_provider(reference_provider),
            model=reference_model,
            api_key=reference_api_key or fallback_key,
            base_url=reference_base_url,
        )
    return target_from_model(
        reference_model,
        target_id=reference_id,
        api_key=reference_api_key,
        base_url=reference_base_url,
        fallback_key=fallback_key,
    )


def _print_summary(pkg: BenchmarkPackage) -> None:
    console.print()
    console.print(Panel("[bold]EvaluationClaw Summary[/bold]", expand=False))
    console.print(f"Goal: {pkg.goal}")
    console.print(f"Spec: {pkg.spec.id}")
    console.print(f"Dimensions: {len(pkg.spec.dimensions)}")
    console.print(f"Scale budget: {pkg.spec.scale_budget.value}")
    console.print(f"Items: {len(pkg.dataset.items)}")
    average_qc_issues = len(pkg.qc_report.issues) / max(1, len(pkg.dataset.items))
    console.print(f"Average QC issues: {average_qc_issues:.2f}")

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


def _console_safe(text: object) -> str:
    value = str(text).replace("\x00", "").replace("\ufffd", "?")
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return value.encode(encoding, errors="replace").decode(encoding, errors="replace")


@app.command("generate")
def generate(
    goal: Optional[str] = typer.Option(None, "-g", "--goal", help="Evaluation goal."),
    model: Optional[str] = typer.Option(
        None,
        "-m",
        "--model",
        help="Optional primary target model. Omit all target options to build without evaluation.",
    ),
    compare: list[str] = typer.Option(
        [],
        "--compare",
        help="Additional target model to compare. May be repeated.",
    ),
    target_config: list[str] = typer.Option(
        [],
        "--target-config",
        help=(
            "Per-target JSON; may be repeated. Fields: id, model, provider or protocol, base_url, "
            "api_key or api_key_env. Replaces --model/--compare target selection when supplied."
        ),
    ),
    reference_model: Optional[str] = typer.Option(
        None,
        "--reference-model",
        help="Optional reference model for pairwise target-vs-reference evaluation items.",
    ),
    reference_provider: Optional[str] = typer.Option(
        None,
        "--reference-provider",
        help="Optional provider/category for --reference-model, e.g. anthropic, openai, openai_compatible, or mock.",
    ),
    orchestrator_model: str = typer.Option(
        "claude-opus-4-6",
        "--orchestrator-model",
        help="Default model for orchestration roles that have no role-specific override.",
    ),
    orchestrator_provider: Optional[str] = typer.Option(
        None,
        "--orchestrator-provider",
        help=(
            "Explicit orchestrator protocol/provider, such as anthropic, "
            "openai_compatible, or openai_responses."
        ),
    ),
    planner_model: Optional[str] = typer.Option(None, "--planner-model", help="Optional Planner model override."),
    planner_provider: Optional[str] = typer.Option(None, "--planner-provider", help="Protocol/provider for --planner-model."),
    planner_api_key: Optional[str] = typer.Option(None, "--planner-api-key", help="API key for the Planner role."),
    planner_base_url: Optional[str] = typer.Option(None, "--planner-base-url", help="Base URL for the Planner role."),
    task_builder_model: Optional[str] = typer.Option(None, "--task-builder-model", help="Optional TaskBuilder model override."),
    task_builder_provider: Optional[str] = typer.Option(None, "--task-builder-provider", help="Protocol/provider for --task-builder-model."),
    task_builder_api_key: Optional[str] = typer.Option(None, "--task-builder-api-key", help="API key for the TaskBuilder role."),
    task_builder_base_url: Optional[str] = typer.Option(None, "--task-builder-base-url", help="Base URL for the TaskBuilder role."),
    qc_model: Optional[str] = typer.Option(None, "--qc-model", help="Optional LLM QC model override."),
    qc_provider: Optional[str] = typer.Option(None, "--qc-provider", help="Protocol/provider for --qc-model."),
    qc_api_key: Optional[str] = typer.Option(None, "--qc-api-key", help="API key for the LLM QC role."),
    qc_base_url: Optional[str] = typer.Option(None, "--qc-base-url", help="Base URL for the LLM QC role."),
    judge_model: Optional[str] = typer.Option(None, "--judge-model", help="Optional scoring judge model override."),
    judge_provider: Optional[str] = typer.Option(None, "--judge-provider", help="Protocol/provider for --judge-model."),
    judge_api_key: Optional[str] = typer.Option(None, "--judge-api-key", help="API key for the scoring judge role."),
    judge_base_url: Optional[str] = typer.Option(None, "--judge-base-url", help="Base URL for the scoring judge role."),
    research_model: Optional[str] = typer.Option(None, "--research-model", help="Optional Deep Research model override."),
    research_provider: Optional[str] = typer.Option(None, "--research-provider", help="Protocol/provider for --research-model."),
    research_api_key: Optional[str] = typer.Option(None, "--research-api-key", help="API key for the research role."),
    research_base_url: Optional[str] = typer.Option(None, "--research-base-url", help="Base URL for the research role."),
    loop3_model: Optional[str] = typer.Option(None, "--loop3-model", help="Optional Loop 3 diagnosis model override."),
    loop3_provider: Optional[str] = typer.Option(None, "--loop3-provider", help="Protocol/provider for --loop3-model."),
    loop3_api_key: Optional[str] = typer.Option(None, "--loop3-api-key", help="API key for the Loop 3 diagnosis role."),
    loop3_base_url: Optional[str] = typer.Option(None, "--loop3-base-url", help="Base URL for the Loop 3 diagnosis role."),
    task_agent_model: Optional[str] = typer.Option(
        None,
        "--task-agent-model",
        help="Optional model for per-item task agents in complex interactive evaluations. Defaults to the orchestrator model.",
    ),
    task_agent_provider: Optional[str] = typer.Option(
        None,
        "--task-agent-provider",
        help="Explicit protocol/provider for --task-agent-model.",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="Orchestrator API key. Defaults to provider env vars such as ANTHROPIC_API_KEY, GEMINI_API_KEY, or DEEPSEEK_API_KEY.",
    ),
    task_agent_api_key: Optional[str] = typer.Option(
        None,
        "--task-agent-api-key",
        help="Optional API key for --task-agent-model. Defaults to provider env vars or the orchestrator key.",
    ),
    target_api_key: Optional[str] = typer.Option(
        None,
        "--target-api-key",
        help="Primary target API key. Compare targets use provider environment defaults.",
    ),
    target_provider: Optional[str] = typer.Option(
        None,
        "--target-provider",
        help="Explicit protocol/provider for the primary target.",
    ),
    reference_api_key: Optional[str] = typer.Option(
        None,
        "--reference-api-key",
        help="API key for --reference-model. Defaults to provider env vars or the orchestrator key.",
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Base URL for the primary target's inferred protocol.",
    ),
    reference_base_url: Optional[str] = typer.Option(
        None,
        "--reference-base-url",
        help="Base URL for --reference-model using its selected protocol.",
    ),
    orchestrator_base_url: Optional[str] = typer.Option(
        None,
        "--orchestrator-base-url",
        help="Base URL for the orchestrator's selected protocol.",
    ),
    task_agent_base_url: Optional[str] = typer.Option(
        None,
        "--task-agent-base-url",
        help="Base URL for --task-agent-model using its selected protocol.",
    ),
    questions_per_dimension: int = typer.Option(5, "--qpd", help="Items per dimension."),
    max_planner_iterations: int = typer.Option(5, "--max-planner-iterations", help="Planner self-critique iterations."),
    max_qc_iterations: int = typer.Option(3, "--max-qc-iterations", help="Reserved for future QC regeneration loops."),
    max_hf_records: int = typer.Option(1, "--max-hf-records", help="Maximum imported HuggingFace dataset rows per dimension."),
    large_scale_generated_cap: int = typer.Option(
        50,
        "--large-scale-generated-cap",
        help="Maximum model-generated repair/augmentation items per dimension for large/xlarge budgets.",
    ),
    large_scale_source_ratio: float = typer.Option(
        0.8,
        "--large-scale-source-ratio",
        help="Target source-backed ratio for large/xlarge planning and generation.",
    ),
    large_scale_qc_sample: int = typer.Option(
        120,
        "--large-scale-qc-sample",
        help="Stratified item sample size for LLM QC under large/xlarge budgets.",
    ),
    scale_budget: str = typer.Option(
        "mid",
        "--scale-budget",
        help="Relative eval budget: low, mid, high, large, or xlarge.",
    ),
    output_dir: str = typer.Option("./benchmark-output", "-o", "--output-dir", help="Output directory."),
    no_interactive: bool = typer.Option(False, "--no-interactive", help="Skip confirmation prompts."),
    no_run: bool = typer.Option(False, "--no-run", help="Build and QC the benchmark without running targets."),
    no_research: bool = typer.Option(False, "--no-research", help="Disable web research during generation."),
    search_backend: str = typer.Option(
        "auto",
        "--search-backend",
        help="Web search backend: auto (gemini if GEMINI_API_KEY else keyless), gemini, keyless, or none.",
    ),
    deep_research: bool = typer.Option(
        False,
        "--deep-research/--no-deep-research",
        help="Run a bounded deep-research loop before planning to ground the spec in domain research.",
    ),
    max_research_iterations: int = typer.Option(
        3,
        "--max-research-iterations",
        help="Maximum deep-research search/reflection rounds.",
    ),
    no_hf_discovery: bool = typer.Option(False, "--no-hf-discovery", help="Disable HuggingFace dataset discovery."),
    task_builder: str = typer.Option(
        "llm",
        "--task-builder",
        help="Task construction mode: llm, local, or auto. Use local only for offline smoke tests.",
    ),
    task_builder_max_workers: int = typer.Option(
        4,
        "--task-builder-workers",
        help="Maximum concurrent task-builder LLM calls.",
    ),
    task_builder_repair_attempts: int = typer.Option(
        2,
        "--task-builder-repair-attempts",
        help="Maximum per-blueprint task-builder structural repair attempts before QC.",
    ),
    task_builder_research_max_calls: int = typer.Option(
        6,
        "--task-builder-research-max-calls",
        help="Maximum public research tool calls for an E4 task-builder invocation.",
    ),
    task_builder_research_max_chars: int = typer.Option(
        6000,
        "--task-builder-research-max-chars",
        help="Maximum characters retained from each E4 task-builder research result.",
    ),
    single_pass_judge: bool = typer.Option(False, "--single-pass-judge", help="Use one judge pass instead of the default double-pass audit."),
    llm_backend: str = typer.Option("auto", "--llm-backend", help="LLM backend: auto, litellm, or legacy."),
    runner: str = typer.Option("direct", "--runner", help="Runner mode: direct, lm-eval, or auto."),
    no_environment_claw: bool = typer.Option(
        False,
        "--no-environment-claw",
        help="Disable environment probing and runtime configuration decisions before target execution.",
    ),
    no_environment_claw_auto_configure: bool = typer.Option(
        False,
        "--no-environment-claw-auto-configure",
        help="Probe runtime requirements but do not apply safe automatic configuration changes.",
    ),
    human_review: bool = typer.Option(
        False,
        "--human-review",
        help="Pause before running targets so a human can approve or request dimension/item revisions.",
    ),
    improve_iterations: int = typer.Option(0, "--improve-iterations", help="Loop 3 self-improvement iterations after the first run."),
    loop3_diagnosis: str = typer.Option("llm", "--loop3-diagnosis", help="Loop 3 diagnosis mode: llm or local."),
    loop3_timeout: int = typer.Option(90, "--loop3-timeout", help="Loop 3 LLM diagnosis timeout in seconds."),
    loop3_max_actions: int = typer.Option(4, "--loop3-max-actions", help="Maximum Loop 3 actions per iteration."),
    docker_executable: str = typer.Option(
        "docker",
        "--docker-executable",
        help="Docker CLI used by all containerized benchmark environments.",
    ),
    container_sandbox_image: str = typer.Option(
        "python:3.11-slim",
        "--container-sandbox-image",
        help="Default isolated image for code_sandbox agent tasks and Python Judge tests.",
    ),
    no_environment_preflight: bool = typer.Option(
        False,
        "--no-environment-preflight",
        help="Skip executable task setup/evaluator preflight before target execution.",
    ),
    allow_incomplete_benchmark: bool = typer.Option(
        False,
        "--allow-incomplete-benchmark",
        help="Permit a QC-incomplete draft package; target execution still uses accepted items only.",
    ),
    gui_bridge_url: Optional[str] = typer.Option(
        None,
        "--gui-bridge-url",
        help="HTTP URL for a GUI/CUA desktop bridge used by agent_env.type=gui_desktop.",
    ),
    gui_bridge_api_key: Optional[str] = typer.Option(
        None,
        "--gui-bridge-api-key",
        help="Optional bearer token for --gui-bridge-url.",
    ),
    gui_bridge_timeout: int = typer.Option(
        30,
        "--gui-bridge-timeout",
        help="Timeout in seconds for GUI/CUA desktop bridge requests.",
    ),
    vm_provider_url: Optional[str] = typer.Option(
        None,
        "--vm-provider-url",
        help="HTTP URL for a VM provider, or local://auto/local://virtualbox/local://qemu for the built-in local provider.",
    ),
    vm_provider_api_key: Optional[str] = typer.Option(
        None,
        "--vm-provider-api-key",
        help="Optional bearer token for --vm-provider-url.",
    ),
    vm_provider_timeout: int = typer.Option(
        600,
        "--vm-provider-timeout",
        help="Timeout in seconds for VM provider create/delete requests.",
    ),
    keep_vm: bool = typer.Option(
        False,
        "--keep-vm",
        help="Do not destroy VM-provider sessions during runner cleanup.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print full package JSON to stdout."),
) -> None:
    """Generate an EvaluationClaw benchmark package."""
    if not goal:
        goal = typer.prompt("Evaluation goal").strip()
    if not goal:
        console.print("[red]Goal cannot be empty.[/red]")
        raise typer.Exit(1)
    if loop3_diagnosis not in {"llm", "local"}:
        console.print("[red]--loop3-diagnosis must be 'llm' or 'local'.[/red]")
        raise typer.Exit(1)
    if loop3_timeout < 1:
        console.print("[red]--loop3-timeout must be at least 1 second.[/red]")
        raise typer.Exit(1)
    if loop3_max_actions < 0:
        console.print("[red]--loop3-max-actions cannot be negative.[/red]")
        raise typer.Exit(1)
    if max_hf_records < 0:
        console.print("[red]--max-hf-records cannot be negative.[/red]")
        raise typer.Exit(1)
    if large_scale_generated_cap < 0:
        console.print("[red]--large-scale-generated-cap cannot be negative.[/red]")
        raise typer.Exit(1)
    if not 0 <= large_scale_source_ratio <= 1:
        console.print("[red]--large-scale-source-ratio must be between 0 and 1.[/red]")
        raise typer.Exit(1)
    if large_scale_qc_sample < 0:
        console.print("[red]--large-scale-qc-sample cannot be negative.[/red]")
        raise typer.Exit(1)
    if gui_bridge_timeout < 1:
        console.print("[red]--gui-bridge-timeout must be at least 1 second.[/red]")
        raise typer.Exit(1)
    if vm_provider_timeout < 1:
        console.print("[red]--vm-provider-timeout must be at least 1 second.[/red]")
        raise typer.Exit(1)
    try:
        parsed_scale_budget = ScaleBudget(scale_budget.lower())
    except ValueError:
        console.print("[red]--scale-budget must be one of: low, mid, high, large, xlarge.[/red]")
        raise typer.Exit(1)
    if search_backend.lower() not in {"auto", "gemini", "keyless", "none"}:
        console.print("[red]--search-backend must be one of: auto, gemini, keyless, none.[/red]")
        raise typer.Exit(1)
    if task_builder.lower() not in {"llm", "local", "auto"}:
        console.print("[red]--task-builder must be one of: llm, local, auto.[/red]")
        raise typer.Exit(1)
    if task_builder_max_workers < 1:
        console.print("[red]--task-builder-workers must be at least 1.[/red]")
        raise typer.Exit(1)
    if task_builder_repair_attempts < 0:
        console.print("[red]--task-builder-repair-attempts cannot be negative.[/red]")
        raise typer.Exit(1)
    if max_research_iterations < 1:
        console.print("[red]--max-research-iterations must be at least 1.[/red]")
        raise typer.Exit(1)

    effective_api_key, effective_orch_base = orchestrator_defaults(
        orchestrator_model,
        api_key=api_key,
        base_url=orchestrator_base_url,
        provider=orchestrator_provider,
    )
    role_options = {
        "planner": (planner_model, planner_provider, planner_api_key, planner_base_url),
        "task_builder": (
            task_builder_model,
            task_builder_provider,
            task_builder_api_key,
            task_builder_base_url,
        ),
        "qc": (qc_model, qc_provider, qc_api_key, qc_base_url),
        "judge": (judge_model, judge_provider, judge_api_key, judge_base_url),
        "research": (research_model, research_provider, research_api_key, research_base_url),
        "loop3": (loop3_model, loop3_provider, loop3_api_key, loop3_base_url),
    }
    role_config: dict[str, Optional[str]] = {}
    for role, (role_model, role_provider, role_key, role_base) in role_options.items():
        if not any((role_model, role_provider, role_key, role_base)):
            continue
        resolved_key, resolved_base = orchestrator_defaults(
            role_model or orchestrator_model,
            api_key=role_key,
            base_url=role_base,
            provider=role_provider,
        )
        role_config.update(
            {
                f"{role}_model": role_model,
                f"{role}_provider": normalize_provider(role_provider) if role_provider else None,
                f"{role}_api_key": resolved_key,
                f"{role}_base_url": resolved_base,
            }
        )
    effective_task_agent_key = None
    effective_task_agent_base = None
    if task_agent_model:
        effective_task_agent_key, effective_task_agent_base = orchestrator_defaults(
            task_agent_model,
            api_key=task_agent_api_key or effective_api_key,
            base_url=task_agent_base_url,
            provider=task_agent_provider,
        )

    try:
        targets = (
            _parse_target_configs(target_config, fallback_key=effective_api_key)
            if target_config
            else _parse_targets(
                model,
                compare,
                target_api_key,
                base_url,
                fallback_key=effective_api_key,
                target_provider=target_provider,
            )
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    reference = _parse_reference_model(
        reference_model,
        reference_provider,
        reference_api_key,
        reference_base_url,
        fallback_key=effective_api_key,
    )
    config = BenchmarkConfig(
        orchestrator_model=orchestrator_model,
        orchestrator_provider=normalize_provider(orchestrator_provider) if orchestrator_provider else None,
        orchestrator_api_key=effective_api_key,
        orchestrator_base_url=effective_orch_base,
        **role_config,
        task_agent_model=task_agent_model,
        task_agent_provider=normalize_provider(task_agent_provider) if task_agent_provider else None,
        task_agent_api_key=effective_task_agent_key,
        task_agent_base_url=effective_task_agent_base,
        targets=targets,
        reference_model=reference,
        scale_budget=parsed_scale_budget,
        questions_per_dimension=questions_per_dimension,
        max_planner_iterations=max_planner_iterations,
        max_qc_iterations=max_qc_iterations,
        max_hf_records_per_dimension=max_hf_records,
        large_scale_generated_item_cap_per_dimension=large_scale_generated_cap,
        large_scale_min_source_backed_ratio=large_scale_source_ratio,
        large_scale_llm_qc_sample_size=large_scale_qc_sample,
        output_dir=output_dir,
        run_targets=bool(targets) and not no_run,
        use_web_research=not no_research,
        search_backend=search_backend.lower(),
        use_deep_research=deep_research,
        max_research_iterations=max_research_iterations,
        use_hf_discovery=not no_hf_discovery,
        task_builder=task_builder.lower(),
        task_builder_max_workers=task_builder_max_workers,
        task_builder_repair_attempts=task_builder_repair_attempts,
        task_builder_research_max_calls=task_builder_research_max_calls,
        task_builder_research_max_chars=task_builder_research_max_chars,
        judge_double_pass=not single_pass_judge,
        llm_backend=llm_backend,
        runner=runner,
        environment_claw=not no_environment_claw,
        environment_claw_auto_configure=not no_environment_claw_auto_configure,
        human_review=human_review,
        improve_iterations=improve_iterations,
        loop3_diagnosis=loop3_diagnosis,
        loop3_diagnosis_timeout_s=loop3_timeout,
        loop3_max_actions=loop3_max_actions,
        docker_executable=docker_executable,
        container_sandbox_image=container_sandbox_image,
        environment_preflight=not no_environment_preflight,
        allow_incomplete_benchmark=allow_incomplete_benchmark,
        gui_bridge_url=gui_bridge_url,
        gui_bridge_api_key=gui_bridge_api_key,
        gui_bridge_timeout_s=gui_bridge_timeout,
        vm_provider_url=vm_provider_url,
        vm_provider_api_key=vm_provider_api_key,
        vm_provider_timeout_s=vm_provider_timeout,
        vm_provider_destroy_on_cleanup=not keep_vm,
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
    _configure_utf8_streams()
    app()
