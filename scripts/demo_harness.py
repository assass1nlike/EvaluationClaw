#!/usr/bin/env python3
"""A minimal demo harness.

A headless CLI harness that solves a coding task inside a workdir: it reads the
initial files, asks the configured LLM for a solution, and writes solution.py
back into the workdir. The framework then scores that workdir with the task's
test command.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx


def _llm_call(prompt: str) -> str:
    model = os.environ.get("LLM_MODEL", "")
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    if not model or not api_key:
        raise RuntimeError("LLM_MODEL and LLM_API_KEY must be set.")
    response = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()

    workdir = Path(args.workdir)
    initial_files: dict[str, str] = {}
    for path in sorted(workdir.rglob("*")):
        if path.is_file():
            initial_files[str(path.relative_to(workdir))] = path.read_text(encoding="utf-8")

    prompt = (
        "You are a coding agent. Solve the task by producing a single Python file "
        "named solution.py.\n\n"
        f"Task:\n{args.task}\n\n"
        f"Initial files in the workspace:\n{json.dumps(initial_files, ensure_ascii=False, indent=2)}\n\n"
        "Return ONLY the raw contents of solution.py (valid Python, no markdown fences, "
        "no explanation). The framework will test it with pytest; import names from the "
        "task description or initial files."
    )
    solution = _llm_call(prompt).strip()
    # Strip accidental markdown fences if the model added them.
    if solution.startswith("```"):
        lines = solution.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        solution = "\n".join(lines).strip()
    (workdir / "solution.py").write_text(solution + "\n", encoding="utf-8")
    print(f"wrote {len(solution)} chars to solution.py")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"demo harness failed: {exc}", file=sys.stderr)
        sys.exit(1)
