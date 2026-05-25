"""Optional lm-eval-harness execution support."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .artifacts import write_lm_eval_artifacts
from .types import BenchmarkDataset, TargetModelConfig


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


def run_lm_eval(
    dataset: BenchmarkDataset,
    target: TargetModelConfig,
    out_dir: Path,
    *,
    executable: str | None = None,
) -> dict:
    """Run lm-eval-harness for a target using generated artifacts.

    This is an interoperability runner. It is best suited to exact-match and
    multiple-choice tasks. Open-generation tasks can still be exported, but
    EvaluationClaw's direct runner remains the source of truth for rubric-based
    LLM judging.
    """
    env_exe = Path(sys.executable).with_name("lm_eval")
    exe = executable or (str(env_exe) if env_exe.exists() else None) or shutil.which("lm_eval") or shutil.which("lm-eval")
    if not exe:
        raise RuntimeError("lm-eval-harness executable not found. Install lm-eval in the active environment.")

    artifacts = write_lm_eval_artifacts(dataset, out_dir)
    results_dir = out_dir / "lm-eval-results" / target.id
    results_dir.mkdir(parents=True, exist_ok=True)
    command = [
        exe,
        "run",
        "--model",
        "openai-chat-completions",
        "--model_args",
        _model_args(target),
        "--tasks",
        str(artifacts["yaml"]),
        "--output_path",
        str(results_dir),
        "--apply_chat_template",
    ]
    env = os.environ.copy()
    key = _target_api_key(target)
    if key:
        env["OPENAI_API_KEY"] = key
    proc = subprocess.run(command, capture_output=True, text=True, timeout=3600, env=env)
    payload = {
        "target_id": target.id,
        "model": target.model,
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-8000:],
        "results_dir": str(results_dir),
        "artifacts": {key: str(value) for key, value in artifacts.items()},
    }
    (results_dir / "evalclaw-lm-eval-run.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"lm-eval failed for {target.id}; see {results_dir / 'evalclaw-lm-eval-run.json'}")
    return payload
