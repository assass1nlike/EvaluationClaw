"""EvaluationClaw CLI."""
from __future__ import annotations

import json
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .execution.swebench import (
    SweBenchHarnessConfig,
    prepare_proxy_base_image,
    run_swebench_harness,
)
from .models.providers import orchestrator_defaults, target_from_model
from .pipeline import run_pipeline
from .types import BenchmarkConfig, BenchmarkMode, BenchmarkPackage, ScaleBudget, TargetModelConfig

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
            provider=reference_provider,
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


def _console_safe(text: object) -> str:
    value = str(text).replace("\x00", "").replace("\ufffd", "?")
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return value.encode(encoding, errors="replace").decode(encoding, errors="replace")


@app.command("generate")
def generate(
    goal: Optional[str] = typer.Option(None, "-g", "--goal", help="Evaluation goal."),
    model: str = typer.Option("claude-sonnet-4-6", "-m", "--model", help="Primary target model."),
    compare: list[str] = typer.Option(
        [],
        "--compare",
        help="Additional target model to compare. May be repeated.",
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
        help="Model used for planner/generator/QC/judge.",
    ),
    task_agent_model: Optional[str] = typer.Option(
        None,
        "--task-agent-model",
        help="Optional model for per-item task agents in complex interactive evaluations. Defaults to the orchestrator model.",
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
    reference_api_key: Optional[str] = typer.Option(
        None,
        "--reference-api-key",
        help="API key for --reference-model. Defaults to provider env vars or the orchestrator key.",
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="OpenAI-compatible base URL for the primary target.",
    ),
    reference_base_url: Optional[str] = typer.Option(
        None,
        "--reference-base-url",
        help="OpenAI-compatible base URL for --reference-model.",
    ),
    orchestrator_base_url: Optional[str] = typer.Option(
        None,
        "--orchestrator-base-url",
        help="OpenAI-compatible base URL for the orchestrator.",
    ),
    task_agent_base_url: Optional[str] = typer.Option(
        None,
        "--task-agent-base-url",
        help="OpenAI-compatible base URL for --task-agent-model.",
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
    benchmark_mode: str = typer.Option(
        "auto",
        "--benchmark-mode",
        help="Benchmark construction mode: auto, static, or agent.",
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
    agent_task_builder: str = typer.Option(
        "llm",
        "--agent-task-builder",
        help="Agent task materialization mode: llm, local, or auto. Use local only for offline smoke tests.",
    ),
    agent_task_builder_max_workers: int = typer.Option(
        4,
        "--agent-task-builder-workers",
        help="Maximum concurrent agent task-builder LLM calls.",
    ),
    agent_task_builder_repair_attempts: int = typer.Option(
        2,
        "--agent-task-builder-repair-attempts",
        help="Maximum per-blueprint task-builder structural repair attempts before QC.",
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
    swebench_use_wsl: bool = typer.Option(False, "--swebench-use-wsl", help="Run SWE-bench harness commands through WSL when selected items require SWE-bench."),
    swebench_wsl_distro: Optional[str] = typer.Option(None, "--swebench-wsl-distro", help="WSL distribution for SWE-bench harness preflight/run."),
    swebench_wsl_python_executable: str = typer.Option(
        ".venv-swebench-wsl/bin/python",
        "--swebench-wsl-python",
        help="Python executable inside WSL with the official SWE-bench harness installed.",
    ),
    swebench_wsl_http_proxy: Optional[str] = typer.Option(
        None,
        "--swebench-wsl-http-proxy",
        help="HTTP/HTTPS proxy URL exported inside WSL for SWE-bench network access.",
    ),
    swebench_python_executable: str = typer.Option(
        "python",
        "--swebench-python",
        help="Python executable with the official SWE-bench harness installed for non-WSL runs.",
    ),
    swebench_docker_executable: str = typer.Option(
        "docker",
        "--swebench-docker",
        help="Docker CLI executable for non-WSL SWE-bench runs.",
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
        120,
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
    try:
        parsed_benchmark_mode = BenchmarkMode(benchmark_mode.lower())
    except ValueError:
        console.print("[red]--benchmark-mode must be one of: auto, static, agent.[/red]")
        raise typer.Exit(1)
    if search_backend.lower() not in {"auto", "gemini", "keyless", "none"}:
        console.print("[red]--search-backend must be one of: auto, gemini, keyless, none.[/red]")
        raise typer.Exit(1)
    if agent_task_builder.lower() not in {"llm", "local", "auto"}:
        console.print("[red]--agent-task-builder must be one of: llm, local, auto.[/red]")
        raise typer.Exit(1)
    if agent_task_builder_max_workers < 1:
        console.print("[red]--agent-task-builder-workers must be at least 1.[/red]")
        raise typer.Exit(1)
    if agent_task_builder_repair_attempts < 0:
        console.print("[red]--agent-task-builder-repair-attempts cannot be negative.[/red]")
        raise typer.Exit(1)
    if max_research_iterations < 1:
        console.print("[red]--max-research-iterations must be at least 1.[/red]")
        raise typer.Exit(1)

    effective_api_key, effective_orch_base = orchestrator_defaults(
        orchestrator_model,
        api_key=api_key,
        base_url=orchestrator_base_url,
    )
    effective_task_agent_key = None
    effective_task_agent_base = None
    if task_agent_model:
        effective_task_agent_key, effective_task_agent_base = orchestrator_defaults(
            task_agent_model,
            api_key=task_agent_api_key or effective_api_key,
            base_url=task_agent_base_url,
        )

    targets = _parse_targets(
        model,
        compare,
        target_api_key,
        base_url,
        fallback_key=effective_api_key,
    )
    reference = _parse_reference_model(
        reference_model,
        reference_provider,
        reference_api_key,
        reference_base_url,
        fallback_key=effective_api_key,
    )
    config = BenchmarkConfig(
        benchmark_mode=parsed_benchmark_mode,
        orchestrator_model=orchestrator_model,
        orchestrator_api_key=effective_api_key,
        orchestrator_base_url=effective_orch_base,
        task_agent_model=task_agent_model,
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
        run_targets=not no_run,
        use_web_research=not no_research,
        search_backend=search_backend.lower(),
        use_deep_research=deep_research,
        max_research_iterations=max_research_iterations,
        use_hf_discovery=not no_hf_discovery,
        agent_task_builder=agent_task_builder.lower(),
        agent_task_builder_max_workers=agent_task_builder_max_workers,
        agent_task_builder_repair_attempts=agent_task_builder_repair_attempts,
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
        swebench_use_wsl=swebench_use_wsl,
        swebench_wsl_distro=swebench_wsl_distro,
        swebench_wsl_python_executable=swebench_wsl_python_executable,
        swebench_wsl_http_proxy=swebench_wsl_http_proxy,
        swebench_python_executable=swebench_python_executable,
        swebench_docker_executable=swebench_docker_executable,
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


@app.command("swebench-run")
def swebench_run(
    predictions_path: str = typer.Option(
        "gold",
        "--predictions-path",
        help="Official SWE-bench predictions JSONL path, or 'gold' for gold patches.",
    ),
    dataset_name: str = typer.Option(
        "princeton-nlp/SWE-bench_Lite",
        "--dataset-name",
        help="SWE-bench dataset name.",
    ),
    split: str = typer.Option("test", "--split", help="Dataset split to run."),
    instance_id: list[str] = typer.Option(
        [],
        "--instance-id",
        help="Limit execution to one instance id. May be repeated.",
    ),
    output_dir: str = typer.Option(
        "benchmark-output/swebench",
        "-o",
        "--output-dir",
        help="Directory where the SWE-bench harness writes outputs.",
    ),
    run_id: str = typer.Option("evalclaw_swebench", "--run-id", help="SWE-bench run id."),
    max_workers: int = typer.Option(1, "--max-workers", help="SWE-bench harness workers."),
    cache_level: Optional[str] = typer.Option(
        "env",
        "--cache-level",
        help="SWE-bench cache level, such as env, instance, or none.",
    ),
    clean: Optional[bool] = typer.Option(
        None,
        "--clean/--no-clean",
        help="Pass clean mode to the SWE-bench harness.",
    ),
    force_rebuild: Optional[bool] = typer.Option(
        None,
        "--force-rebuild/--no-force-rebuild",
        help="Force the SWE-bench harness to rebuild Docker images instead of using cached or pulled images.",
    ),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="Per-instance timeout."),
    namespace: Optional[str] = typer.Option(None, "--namespace", help="Docker image namespace."),
    instance_image_tag: Optional[str] = typer.Option(
        None,
        "--instance-image-tag",
        help="SWE-bench instance image tag.",
    ),
    env_image_tag: Optional[str] = typer.Option(
        None,
        "--env-image-tag",
        help="SWE-bench environment image tag.",
    ),
    python_executable: str = typer.Option(
        sys.executable,
        "--python-executable",
        help="Python executable with the official swebench package installed.",
    ),
    docker_executable: str = typer.Option("docker", "--docker-executable", help="Docker CLI executable."),
    use_wsl: bool = typer.Option(
        False,
        "--use-wsl",
        help="Run the official SWE-bench harness inside WSL. Useful on Windows because the harness depends on Unix APIs.",
    ),
    wsl_distro: Optional[str] = typer.Option(
        None,
        "--wsl-distro",
        help="WSL distribution for --use-wsl, for example Ubuntu-24.04. Defaults to the WSL default distro.",
    ),
    wsl_python_executable: Optional[str] = typer.Option(
        None,
        "--wsl-python-executable",
        help="Python executable inside WSL with the official swebench package installed.",
    ),
    wsl_docker_host: str = typer.Option(
        "unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.proxy.sock",
        "--wsl-docker-host",
        help="Docker socket URI exposed by Docker Desktop inside WSL.",
    ),
    wsl_docker_cli_dir: str = typer.Option(
        "/mnt/wsl/docker-desktop/cli-tools/usr/bin",
        "--wsl-docker-cli-dir",
        help="Directory containing Docker Desktop's Linux docker CLI inside WSL.",
    ),
    wsl_http_proxy: Optional[str] = typer.Option(
        None,
        "--wsl-http-proxy",
        help="Optional HTTP(S) proxy URL exported inside WSL for dataset and image downloads.",
    ),
    skip_docker_check: bool = typer.Option(
        False,
        "--skip-docker-check",
        help="Skip EvaluationClaw's preflight Docker check and let the SWE-bench harness fail directly.",
    ),
    skip_harness_check: bool = typer.Option(
        False,
        "--skip-harness-check",
        help="Skip EvaluationClaw's preflight import check for swebench.harness.run_evaluation.",
    ),
) -> None:
    """Run the official Docker-based SWE-bench harness from EvaluationClaw."""
    if max_workers < 1:
        console.print("[red]--max-workers must be at least 1.[/red]")
        raise typer.Exit(1)
    if timeout is not None and timeout < 1:
        console.print("[red]--timeout must be at least 1 second.[/red]")
        raise typer.Exit(1)
    config = SweBenchHarnessConfig(
        predictions_path=predictions_path,
        output_dir=output_dir,
        dataset_name=dataset_name,
        split=split,
        max_workers=max_workers,
        run_id=run_id,
        instance_ids=instance_id,
        cache_level=cache_level,
        clean=clean,
        force_rebuild=force_rebuild,
        timeout=timeout,
        namespace=namespace,
        instance_image_tag=instance_image_tag,
        env_image_tag=env_image_tag,
        python_executable=(
            wsl_python_executable
            or (".venv-swebench-wsl/bin/python" if use_wsl and python_executable == sys.executable else python_executable)
        ),
        docker_executable=docker_executable,
        use_wsl=use_wsl,
        wsl_distro=wsl_distro,
        wsl_docker_host=wsl_docker_host,
        wsl_docker_cli_dir=wsl_docker_cli_dir,
        wsl_http_proxy=wsl_http_proxy,
    )
    try:
        result = run_swebench_harness(
            config,
            check_docker=not skip_docker_check,
            check_harness=not skip_harness_check,
        )
    except Exception as exc:
        console.print(f"[red]SWE-bench run failed before harness execution: {_console_safe(exc)}[/red]")
        raise typer.Exit(1)

    console.print("[bold]SWE-bench command[/bold]")
    console.print(" ".join(result.command))
    if result.stdout:
        console.print("[bold]stdout[/bold]")
        console.print(_console_safe(result.stdout))
    if result.stderr:
        console.print("[bold]stderr[/bold]")
        console.print(_console_safe(result.stderr))
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


@app.command("swebench-prepare-proxy-base")
def swebench_prepare_proxy_base(
    proxy_url: str = typer.Option(
        ...,
        "--proxy-url",
        help="Proxy URL to inject into the SWE-bench base image, for example http://host.docker.internal:7891.",
    ),
    base_image: str = typer.Option(
        "sweb.base.py.x86_64:latest",
        "--base-image",
        help="Existing SWE-bench base image to retag with proxy environment.",
    ),
    docker_executable: str = typer.Option("docker", "--docker-executable", help="Docker CLI executable."),
) -> None:
    """Inject proxy environment into an existing SWE-bench base image."""
    try:
        result = prepare_proxy_base_image(
            proxy_url=proxy_url,
            base_image=base_image,
            docker_executable=docker_executable,
        )
    except Exception as exc:
        console.print(f"[red]SWE-bench proxy base preparation failed: {_console_safe(exc)}[/red]")
        raise typer.Exit(1)
    console.print("[bold]SWE-bench proxy base command[/bold]")
    console.print(" ".join(result.command))
    if result.stdout:
        console.print("[bold]stdout[/bold]")
        console.print(_console_safe(result.stdout))
    if result.stderr:
        console.print("[bold]stderr[/bold]")
        console.print(_console_safe(result.stderr))
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def main() -> None:
    app()
