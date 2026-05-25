"""Local sandbox helpers for code and lightweight interaction tasks."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def run_python_sandbox(code: str, *, timeout: int = 10) -> tuple[int, str, str]:
    """Run Python code in an isolated temp directory.

    This is a lightweight local sandbox. It does not provide full container
    isolation, but it avoids running in the repository working directory and
    strips access to inherited stdin.
    """
    with tempfile.TemporaryDirectory(prefix="evalclaw-sandbox-") as tmp:
        script = Path(tmp) / "run.py"
        script.write_text(code, encoding="utf-8")
        proc = subprocess.run(
            ["python3", str(script)],
            cwd=tmp,
            input="",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr


def build_code_harness(test_code: str, model_output: str) -> str:
    return test_code.replace("{model_output}", json.dumps(model_output))
