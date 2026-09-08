"""OpenHands harness runner.

Wraps the target model in the OpenHands coding agent instead of the framework's
own agent loop. Only the launch command is OpenHands-specific; image build,
workspace setup, and scoring are shared via ``harness``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..types import BenchmarkConfig, BenchmarkItem, TargetModelConfig
from . import harness

_OPENHANDS_TIMEOUT_S = 1800


def _openhands_env(
    target: TargetModelConfig,
    image: str,
    workdir: Path,
) -> dict[str, str]:
    env = os.environ.copy()
    env["LLM_MODEL"] = target.model
    if target.api_key:
        env["LLM_API_KEY"] = target.api_key
    if target.base_url:
        env["LLM_BASE_URL"] = target.base_url
    env["SANDBOX_BASE_CONTAINER_IMAGE"] = image
    env["SANDBOX_VOLUMES"] = f"{workdir}:/workspace:rw"
    env["SANDBOX_USER_ID"] = str(os.getuid())
    return env


def _run_openhands_cli(
    item: BenchmarkItem,
    target: TargetModelConfig,
    image: str,
    workdir: Path,
) -> str:
    command = ["openhands", "--headless", "--override-with-envs", "--json", "-t", item.prompt]
    try:
        proc = subprocess.run(
            command,
            env=_openhands_env(target, image, workdir),
            capture_output=True,
            text=True,
            timeout=_OPENHANDS_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "The openhands CLI is not installed. Install it (e.g. `uv tool install openhands`) "
            "to use the openhands harness."
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(f"OpenHands harness failed: {proc.stderr or proc.stdout}")
    return proc.stdout


class OpenHandsRunner:
    name = "openhands"

    def run(
        self,
        item: BenchmarkItem,
        target: TargetModelConfig,
        config: BenchmarkConfig,
        *,
        artifact_dir: Path | None = None,
    ) -> tuple[str, float, str]:
        harness.reject_tool_constraints(item)
        image, workdir = harness.prepare_docker_task(item, config)
        try:
            raw = _run_openhands_cli(item, target, image, workdir)
            score, reasoning = harness.score_docker_task(item, config, image, workdir)
            if artifact_dir is not None:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "openhands-output.jsonl").write_text(raw, encoding="utf-8")
                (artifact_dir / "openhands-reasoning.txt").write_text(reasoning, encoding="utf-8")
            return raw, score, reasoning
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


harness.register_harness(OpenHandsRunner())
