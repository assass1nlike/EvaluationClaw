"""Optional lm-eval-harness execution support."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from ..reporting.artifacts import write_lm_eval_artifacts
from ..types import BenchmarkDataset, TargetModelConfig


def _model_args(target: TargetModelConfig) -> str:
    args = [f"model={target.model}"]
    if target.base_url:
        args.append(f"base_url={target.base_url.rstrip('/')}/chat/completions")
    args.append("tokenizer_backend=none")
    return ",".join(args)


def _target_api_key(target: TargetModelConfig) -> str | None:
    if target.api_key:
        return target.api_key
    if target.model.startswith("deepseek-"):
        return os.environ.get("DEEPSEEK_API_KEY")
    if target.model.startswith("gemini"):
        return os.environ.get("GEMINI_API_KEY")
    if target.provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY")
    return os.environ.get("OPENAI_API_KEY")


def _lm_eval_executable_candidates() -> list[Path]:
    scripts_dir = Path(sysconfig.get_path("scripts"))
    executable_dir = Path(sys.executable).parent
    names = ["lm_eval", "lm-eval", "lm_eval.exe", "lm-eval.exe"]
    candidates: list[Path] = []
    for directory in (scripts_dir, executable_dir):
        for name in names:
            candidate = directory / name
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _resolve_lm_eval_executable(executable: str | None = None) -> str | None:
    if executable:
        return executable
    for candidate in _lm_eval_executable_candidates():
        if candidate.exists():
            return str(candidate)
    return shutil.which("lm_eval") or shutil.which("lm-eval")


def run_lm_eval(
    dataset: BenchmarkDataset,
    target: TargetModelConfig,
    out_dir: Path,
    *,
    executable: str | None = None,
) -> dict:
    """Run each semantically supported lm-eval task family independently."""
    exe = _resolve_lm_eval_executable(executable)
    if not exe:
        raise RuntimeError("lm-eval-harness executable not found. Install lm-eval in the active environment.")

    artifacts = write_lm_eval_artifacts(dataset, out_dir)
    yaml_artifacts = {
        name: path for name, path in artifacts.items() if name.startswith("yaml_")
    }
    if not yaml_artifacts:
        raise ValueError(
            "The accepted execution plan contains no task family that lm-eval can score "
            "without changing EvaluationClaw semantics."
        )

    results_dir = out_dir / "lm-eval-results" / target.id
    results_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    key = _target_api_key(target)
    if key:
        env["OPENAI_API_KEY"] = key

    runs: list[dict] = []
    for family, yaml_path in sorted(yaml_artifacts.items()):
        family_name = family.removeprefix("yaml_")
        family_dir = results_dir / family_name
        family_dir.mkdir(parents=True, exist_ok=True)
        command = [
            exe,
            "run",
            "--model",
            "openai-chat-completions",
            "--model_args",
            _model_args(target),
            "--tasks",
            str(yaml_path),
            "--output_path",
            str(family_dir),
            "--apply_chat_template",
        ]
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
            env=env,
        )
        runs.append(
            {
                "family": family_name,
                "command": command,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-8000:],
                "stderr": proc.stderr[-8000:],
                "results_dir": str(family_dir),
            }
        )

    payload = {
        "target_id": target.id,
        "model": target.model,
        "runs": runs,
        "artifacts": {name: str(path) for name, path in artifacts.items()},
    }
    record_path = results_dir / "evalclaw-lm-eval-run.json"
    record_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [run for run in runs if run["returncode"] != 0]
    if failed:
        families = ", ".join(run["family"] for run in failed)
        raise RuntimeError(f"lm-eval failed for {target.id} task families: {families}; see {record_path}")
    return payload
