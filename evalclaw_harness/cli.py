"""Command-line interface for the standalone EvalClaw Harness."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from evalclaw.types import TaskSuite

from .api import build as build_benchmark
from .api import validate as validate_benchmark
from .models import HarnessConfig, HarnessRequest

app = typer.Typer(
    name="evalclaw-harness",
    help="Build and validate benchmark task packages without planning or running target models.",
    add_completion=False,
)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _finish(result_path: Path, status: str) -> None:
    typer.echo(json.dumps({"status": status, "result": str(result_path)}, ensure_ascii=False))


@app.command("build")
def build_command(
    request: Path = typer.Option(..., "--request", exists=True, dir_okay=False, readable=True),
    config: Path = typer.Option(..., "--config", exists=True, dir_okay=False, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir", file_okay=False),
) -> None:
    """Build a task package from a versioned Harness request."""
    try:
        result = build_benchmark(
            HarnessRequest.model_validate(_load(request)),
            HarnessConfig.model_validate(_load(config)),
            output_dir,
            log=lambda message: typer.echo(message, err=True),
        )
    except Exception as exc:
        typer.echo(f"Harness build failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _finish(output_dir.resolve() / "result.json", result.status)


@app.command("validate")
def validate_command(
    suite: Path = typer.Option(..., "--suite", exists=True, dir_okay=False, readable=True),
    config: Path = typer.Option(..., "--config", exists=True, dir_okay=False, readable=True),
    output_dir: Path = typer.Option(..., "--output-dir", file_okay=False),
) -> None:
    """Validate an existing task package through Harness QC."""
    try:
        result = validate_benchmark(
            TaskSuite.model_validate(_load(suite)),
            HarnessConfig.model_validate(_load(config)),
            output_dir,
        )
    except Exception as exc:
        typer.echo(f"Harness validation failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _finish(output_dir.resolve() / "result.json", result.status)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
