"""Pluggable agent-harness abstraction for docker-backed tasks.

A harness wraps the target model into an agent that solves a task inside the
task's docker environment. The framework calls the harness through a uniform
interface and reuses the shared image/build + scoring flow; each harness only
supplies its own launch command.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..execution.docker import docker_subprocess_env, resolve_docker_executable
from ..execution.docker_images import (
    apply_docker_image_selection,
    build_docker_image_if_requested,
)
from ..types import SUPPORTED_HARNESSES, BenchmarkConfig, BenchmarkItem, TargetModelConfig


class HarnessRunner(Protocol):
    name: str

    def run(
        self,
        item: BenchmarkItem,
        target: TargetModelConfig,
        config: BenchmarkConfig,
        *,
        artifact_dir: Path | None = None,
    ) -> tuple[str, float, str]: ...


_HARNESS_RUNNERS: dict[str, HarnessRunner] = {}
_builtins_loaded = False


def register_harness(runner: HarnessRunner) -> None:
    if runner.name not in SUPPORTED_HARNESSES:
        raise ValueError(
            f"Harness {runner.name!r} is not in SUPPORTED_HARNESSES; "
            f"add it to types.SUPPORTED_HARNESSES first."
        )
    _HARNESS_RUNNERS[runner.name] = runner


def get_harness(name: str) -> HarnessRunner:
    global _builtins_loaded
    if not _builtins_loaded:
        _builtins_loaded = True
        from . import openhands  # noqa: F401  (registers the built-in harness)

    if name not in _HARNESS_RUNNERS:
        raise ValueError(f"Unsupported harness {name!r}; supported: {sorted(_HARNESS_RUNNERS)}.")
    return _HARNESS_RUNNERS[name]


def agent_env(item: BenchmarkItem) -> dict[str, Any]:
    env = item.metadata.get("agent_env")
    return env if isinstance(env, dict) else {}


def reject_tool_constraints(item: BenchmarkItem) -> None:
    """Reject tasks that declare tool constraints a third-party harness can't honor."""
    env = agent_env(item)
    browser = env.get("browser") if isinstance(env.get("browser"), dict) else {}
    constrained = bool(
        env.get("workspace_tools")
        or browser.get("workspace_tools")
        or browser.get("allow_workspace_tools")
        or browser.get("enabled")
    )
    if constrained:
        raise RuntimeError(
            "Task declares tool constraints (workspace_tools/browser), which a third-party "
            "harness cannot enforce. Remove the harness or the tool constraints."
        )


def _resolve_image_context(
    item: BenchmarkItem,
    env: dict[str, Any],
    config: BenchmarkConfig,
) -> dict[str, Any]:
    """Resolve a relative image_build.context_dir against the Builder job directory."""
    image_build = env.get("image_build")
    if not isinstance(image_build, dict):
        return env
    context_dir = str(image_build.get("context_dir") or "").strip()
    if not context_dir or Path(context_dir).is_absolute() or config is None:
        return env
    builder_job_id = str(item.metadata.get("builder_job_id") or "").strip()
    if not builder_job_id or not str(config.output_dir).strip():
        raise ValueError(
            "A relative image_build.context_dir requires the task's builder_job_id and output_dir."
        )
    safe_job_id = re.sub(r"[^A-Za-z0-9._-]+", "_", builder_job_id).strip("._")
    root = (
        Path(config.output_dir).expanduser().resolve()
        / "assets"
        / "task-builder"
        / (safe_job_id or "task-builder")
    )
    resolved = (root / context_dir).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("image_build.context_dir must stay inside the Builder job directory.")
    updated = dict(env)
    updated["image_build"] = {**image_build, "context_dir": str(resolved)}
    return updated


def prepare_docker_task(item: BenchmarkItem, config: BenchmarkConfig) -> tuple[str, Path]:
    """Select/build the task image and write visible files into a host workdir."""
    env = _resolve_image_context(item, dict(agent_env(item)), config)
    task_text = item.prompt
    env, _ = apply_docker_image_selection(env, task_text=task_text)
    env, _ = build_docker_image_if_requested(
        env,
        task_text=task_text,
        docker_executable=config.docker_executable,
        timeout_s=600,
    )
    image = str(env.get("image") or "python:3.11-slim")
    workdir = Path(tempfile.mkdtemp(prefix="evalclaw-harness-"))
    visible = env.get("visible_files")
    if isinstance(visible, dict):
        for path, content in visible.items():
            target = workdir / str(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
    return image, workdir


def score_docker_task(
    item: BenchmarkItem,
    config: BenchmarkConfig,
    image: str,
    workdir: Path,
) -> tuple[float, str]:
    """Score by injecting hidden files and running the task's test command."""
    env = agent_env(item)
    test_command = str(env.get("test_command") or "pytest -q")
    hidden = env.get("hidden_files")
    if isinstance(hidden, dict):
        for path, content in hidden.items():
            target = workdir / str(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
    resolved = resolve_docker_executable(config.docker_executable)
    if not resolved:
        raise RuntimeError(f"Docker executable {config.docker_executable!r} not found.")
    proc = subprocess.run(
        [
            resolved,
            "run",
            "--rm",
            "-v",
            f"{workdir}:/workspace",
            "-w",
            "/workspace",
            image,
            "sh",
            "-lc",
            test_command,
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env=docker_subprocess_env(config.docker_executable),
    )
    score = 1.0 if proc.returncode == 0 else 0.0
    reasoning = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
    return score, reasoning


@dataclass
class ManifestHarness:
    name: str
    run: str  # command template with {task} {image} {workdir} placeholders
    model_env: dict[str, str]  # env var name -> target field (model/api_key/base_url)
    timeout: int = 1800


class ManifestHarnessRunner:
    """A harness defined by a declarative manifest that launches an external CLI."""

    def __init__(self, manifest: ManifestHarness):
        self.name = manifest.name
        self._manifest = manifest

    def run(
        self,
        item: BenchmarkItem,
        target: TargetModelConfig,
        config: BenchmarkConfig,
        *,
        artifact_dir: Path | None = None,
    ) -> tuple[str, float, str]:
        reject_tool_constraints(item)
        image, workdir = prepare_docker_task(item, config)
        try:
            raw = self._launch(item, target, image, workdir)
            score, reasoning = score_docker_task(item, config, image, workdir)
            if artifact_dir is not None:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / f"{self.name}-output.txt").write_text(raw, encoding="utf-8")
                (artifact_dir / f"{self.name}-reasoning.txt").write_text(reasoning, encoding="utf-8")
            return raw, score, reasoning
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _launch(self, item: BenchmarkItem, target: TargetModelConfig, image: str, workdir: Path) -> str:
        command = shlex.split(
            self._manifest.run.format(
                task=shlex.quote(item.prompt),
                image=shlex.quote(image),
                workdir=shlex.quote(str(workdir)),
            )
        )
        env = os.environ.copy()
        for field, var_name in self._manifest.model_env.items():
            value = getattr(target, field, None)
            if value:
                env[var_name] = str(value)
        try:
            proc = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=self._manifest.timeout,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Harness command not found for {self.name!r}.") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"Harness {self.name!r} failed: {proc.stderr or proc.stdout}")
        return proc.stdout


def load_manifest_harness(path: str | Path) -> str:
    """Load a manifest file, register it as a harness, and return its name."""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Harness manifest must be a mapping: {path}")
    manifest = ManifestHarness(
        name=str(raw.get("name") or "").strip(),
        run=str(raw.get("run") or "").strip(),
        model_env={str(key): str(value) for key, value in (raw.get("model_env") or {}).items()},
        timeout=max(1, int(raw.get("timeout") or 1800)),
    )
    if not manifest.name or not manifest.run:
        raise ValueError("Harness manifest requires name and run.")
    SUPPORTED_HARNESSES.add(manifest.name)
    register_harness(ManifestHarnessRunner(manifest))
    return manifest.name
