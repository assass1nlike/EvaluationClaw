import argparse
import json
import os
import random
import subprocess
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from inspect_ai import eval
from inspect_ai.model import GenerateConfig, get_model
from petri.scorers.prompts import DIMENSIONS
from petri.solvers.auditor_agent import auditor_agent
from petri.tasks.petri import AUDITOR_INSTRUCTIONS, audit
from petri.tools import ALIGNMENT_AUDITOR_TOOLS, send_message, send_tool_call_result
from petri.transcript.transcript import Transcript


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)


def main():
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env", override=True)
    parser = argparse.ArgumentParser(description="Run one Petri audit with real models.")
    for role in ("auditor", "target", "judge"):
        parser.add_argument(f"--{role}", default=os.getenv("PETRI_MODEL"),
                            required=not os.getenv("PETRI_MODEL"), help="Inspect model ID, e.g. openai/gpt-4o")
    parser.add_argument("--base-url", default=os.getenv("PETRI_API_BASE"),
                        required=not os.getenv("PETRI_API_BASE"), help="API base URL shared by the three roles")
    parser.add_argument("--instruction", type=Path, help="UTF-8 file containing one audit instruction")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--thinking", choices=("enabled", "disabled"), default="disabled")
    parser.add_argument("--allow-prefill", action="store_true")
    args = parser.parse_args()
    seed_everything(42)
    output = root / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True)
    instruction = args.instruction.read_text() if args.instruction else AUDITOR_INSTRUCTIONS[14]
    (output / "instruction.txt").write_text(instruction + "\n")
    configs = {
        role: GenerateConfig(
            seed=42, max_tokens=8192 if role == "judge" else 4096,
            max_connections=1, max_retries=2, timeout=120,
            extra_body={"thinking": {"type": args.thinking}},
        )
        for role in ("auditor", "target", "judge")
    }
    models = {
        role: get_model(getattr(args, role), base_url=args.base_url, config=config, memoize=False)
        for role, config in configs.items()
    }
    manifest = {
        "commit": subprocess.check_output(
            ["git", "-C", str(root / "upstream"), "rev-parse", "HEAD"], text=True
        ).strip(),
        "versions": {name: version(name) for name in ("petri", "inspect-ai", "openai", "anthropic")},
        "base_url": args.base_url,
        "models": {role: getattr(args, role) for role in models},
        "generation": {role: config.model_dump(exclude_none=True) for role, config in configs.items()},
        "seed": 42,
        "max_turns": args.max_turns,
        "allow_prefill": args.allow_prefill,
        "instruction_source": str(args.instruction) if args.instruction else "upstream AUDITOR_INSTRUCTIONS[14] (15th seed)",
        "samples": 1,
        "epochs": 1,
        "time_limit": 900,
    }
    (output / "config.json").write_text(json.dumps(manifest, indent=2) + "\n")
    logs = eval(
        audit(max_turns=args.max_turns, special_instructions=json.dumps([instruction]),
              transcript_save_dir=str(output / "transcripts")),
        model=None, model_roles=models, log_dir=str(output / "logs"),
        solver=auditor_agent(max_turns=args.max_turns, auditor_tools=[
            factory(prefill=args.allow_prefill)
            if factory in (send_message, send_tool_call_result) else factory()
            for factory in ALIGNMENT_AUDITOR_TOOLS
        ]),
        epochs=1, max_samples=1, fail_on_error=True, time_limit=900, display="plain",
    )
    log = logs[0]
    if log.status != "success" or not log.samples or log.samples[0].error:
        raise RuntimeError(f"Audit failed; inspect {output}")
    if any(event.error for event in log.samples[0].events if event.event == "tool"):
        raise RuntimeError(f"Audit contained tool errors; inspect {output}")
    score = log.samples[0].scores["alignment_judge"]
    if (set(score.value) != set(DIMENSIONS)
            or "score_descriptions" in (score.metadata or {})):
        raise RuntimeError(f"Judge did not produce complete scores; inspect {output}")
    transcripts = list((output / "transcripts").glob("*.json"))
    if len(transcripts) != 1:
        raise RuntimeError(f"Expected one saved transcript; inspect {output}")
    target_messages = Transcript.load(str(transcripts[0])).collect_messages("target")
    if not any(message.role == "assistant" and message.text.strip() for message in target_messages):
        raise RuntimeError(f"No target response in saved transcript; inspect {output}")
    (output / "summary.json").write_text(json.dumps({
        "status": log.status, "scores": score.value, "summary": score.answer,
        "usage": {name: usage.model_dump() for name, usage in log.stats.model_usage.items()},
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"Verified audit, target responses, 23 judge scores and transcript: {output}")


if __name__ == "__main__":
    main()
