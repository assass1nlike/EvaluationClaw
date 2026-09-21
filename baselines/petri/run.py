import argparse
import json
import os
import random
import subprocess
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import deepseek_api  # Registers the DeepSeek reasoning/prefill provider.
import qwen_api  # Registers the DashScope reasoning/partial provider.
import sol_api  # Registers the streaming Responses provider and shared RPM limit.
from dotenv import load_dotenv
from inspect_ai import eval
from inspect_ai.model import GenerateConfig, get_model
from petri.scorers.judge import _format_dimensions, _format_scores_section
from petri.scorers.prompts import DIMENSIONS, SYSTEM_PROMPT as NATIVE_SYSTEM_PROMPT
from petri.solvers.auditor_agent import auditor_agent
from petri.tasks.petri import AUDITOR_INSTRUCTIONS, audit
from petri.solvers.prompts import AUDITOR_SYSTEM_PROMPT
from petri.tools import ALIGNMENT_AUDITOR_TOOLS, send_message, send_tool_call_result
from petri.transcript.transcript import Transcript

from auditor_prompt import NO_PREFILL_SYSTEM_PROMPT
from dual_judge import dual_judges
from requirement_judge import DEFAULT_RUBRIC, SYSTEM_PROMPT, requirement_judge


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
        parser.add_argument(f"--{role}-base-url", help="Override the shared API URL for this role")
    parser.add_argument("--base-url", default=os.getenv("PETRI_API_BASE"),
                        help="Default API base URL for roles without an override")
    parser.add_argument("--instruction", type=Path, help="UTF-8 file containing one audit instruction")
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--thinking", choices=("enabled", "disabled"), default="disabled")
    parser.add_argument("--reasoning-effort", choices=("low", "high", "max"))
    parser.add_argument("--max-tokens", type=int, help="Per-call output limit for all roles, including reasoning")
    parser.add_argument("--sol-rpm", type=float, default=50)
    parser.add_argument("--sol-rate-limit-file", type=Path,
                        default=Path(os.getenv("XDG_STATE_HOME", str(root / ".local/state"))) / "sol-rate-limit")
    parser.add_argument("--request-timeout", type=int, default=120)
    parser.add_argument("--time-limit", type=int, default=900, help="Sample time limit in seconds; 0 disables it")
    parser.add_argument("--prefill-mode", choices=("no-prefill", "prefill"), default="no-prefill",
                        help="Whether auditor tools expose response prefixing")
    parser.add_argument("--allow-prefill", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scoring", choices=("both", "requirement", "native"), default="both")
    parser.add_argument("--rubric", type=Path, help="Predefined scoring criteria for requirement mode")
    parser.add_argument("--output-dir", type=Path, help="New directory for this run's artifacts")
    args = parser.parse_args()
    base_urls = {role: getattr(args, f"{role}_base_url") or args.base_url
                 for role in ("auditor", "target", "judge")}
    if not all(base_urls.values()):
        parser.error("Provide --base-url or an explicit --ROLE-base-url for every role")
    if args.allow_prefill:
        if args.prefill_mode != "no-prefill":
            parser.error("--allow-prefill and --prefill-mode cannot be combined")
        args.prefill_mode = "prefill"
    if args.rubric and args.scoring == "native":
        parser.error("--rubric requires --scoring both or requirement")
    sol_roles = [role for role in ("auditor", "target", "judge")
                 if getattr(args, role).startswith("sol/")]
    if sol_roles and (args.thinking != "enabled" or not args.reasoning_effort):
        parser.error("Sol requires enabled thinking and an explicit reasoning effort")
    if sol_roles and args.prefill_mode != "no-prefill":
        parser.error("Sol Responses requires --prefill-mode no-prefill")
    if not 0 < args.sol_rpm <= 50:
        parser.error("--sol-rpm must be in (0, 50]")
    seed_everything(args.seed)
    instruction = args.instruction.read_text().strip() if args.instruction else AUDITOR_INSTRUCTIONS[14]
    rubric = args.rubric.read_text().strip() if args.rubric else DEFAULT_RUBRIC
    if not instruction or not rubric:
        parser.error("Instruction and rubric must not be empty")
    output = args.output_dir or root / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = output.resolve()
    output.mkdir(parents=True)
    (output / "instruction.txt").write_text(instruction + "\n")
    if args.scoring != "native":
        (output / "rubric.txt").write_text(rubric + "\n")
        (output / "judge_prompt.txt").write_text(SYSTEM_PROMPT)
    if args.scoring != "requirement":
        (output / "native_judge_prompt.txt").write_text(NATIVE_SYSTEM_PROMPT.format(
            dimensions=_format_dimensions(DIMENSIONS), scores_format=_format_scores_section(DIMENSIONS)))
    configs = {
        role: GenerateConfig(
            seed=None if role in sol_roles else args.seed,
            max_tokens=args.max_tokens or (8192 if role == "judge" else 4096),
            max_connections=2 if role == "judge" and args.scoring == "both" else 1,
            max_retries=2, timeout=args.request_timeout,
            reasoning_effort=args.reasoning_effort,
            extra_body=(None if role in sol_roles else {"enable_thinking": args.thinking == "enabled"}
                        if getattr(args, role).partition("/")[0] == "qwen"
                        else {"thinking": {"type": args.thinking}}),
        )
        for role in ("auditor", "target", "judge")
    }
    models = {
        role: get_model(getattr(args, role), base_url=base_urls[role], config=config, memoize=False,
                        **({"rpm": args.sol_rpm, "rate_limit_file": str(args.sol_rate_limit_file.resolve()),
                            "call_log": str(output / "sol-calls.jsonl")} if role in sol_roles else {}))
        for role, config in configs.items()
    }
    manifest = {
        "commit": "4ba39bbcd494e7ef8ea949f2853fa00305e083e3",
        "workspace_commit": subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip(),
        "versions": {name: version(name) for name in ("petri", "inspect-ai", "openai", "anthropic")},
        "base_url": args.base_url,
        "base_urls": base_urls,
        "models": {role: getattr(args, role) for role in models},
        "generation": {role: config.model_dump(exclude_none=True) for role, config in configs.items()},
        "seed": args.seed,
        "max_turns": args.max_turns,
        "allow_prefill": args.prefill_mode == "prefill",
        "prefill_mode": args.prefill_mode,
        "auditor_prompt_variant": "native" if args.prefill_mode == "prefill" else "no-prefill",
        "scoring": args.scoring,
        "primary_scorer": "alignment_judge" if args.scoring == "native" else "requirement_judge",
        "judge_parse_attempts": 3,
        "rubric_source": str(args.rubric) if args.rubric else None,
        "instruction_source": str(args.instruction) if args.instruction else "upstream AUDITOR_INSTRUCTIONS[14] (15th seed)",
        "samples": 1,
        "epochs": 1,
        "time_limit": args.time_limit or None,
    }
    if sol_roles:
        manifest["sol_transport"] = {
            "protocol": "streaming Responses", "rpm": args.sol_rpm,
            "rate_limit_file": str(args.sol_rate_limit_file.resolve()),
            "rate_limit_scope": "All local Petri Sol processes and HTTP attempts sharing the lock file",
            "sdk_retries": 0, "api_seed_supported": False,
            "model_mismatch_retries": configs[sol_roles[0]].max_retries,
            "model_mismatch_exhaustion": "Fail epoch without scoring",
            "max_output_tokens": "Requested limit; relay does not confirm its effective value",
        }
    (output / "config.json").write_text(json.dumps(manifest, indent=2) + "\n")
    auditor_prompt = (AUDITOR_SYSTEM_PROMPT if args.prefill_mode == "prefill"
                      else NO_PREFILL_SYSTEM_PROMPT)
    (output / "auditor_prompt.txt").write_text(auditor_prompt)
    task = audit(max_turns=args.max_turns, special_instructions=json.dumps([instruction]),
                 transcript_save_dir=str(output / "transcripts"))
    if args.scoring == "requirement":
        task.scorer = [requirement_judge(instruction, rubric)]
    elif args.scoring == "both":
        task.scorer = dual_judges(instruction, rubric)
    auditor_tools = []
    for factory in ALIGNMENT_AUDITOR_TOOLS:
        calls_target = factory in (send_message, send_tool_call_result)
        tool = factory(prefill=args.prefill_mode == "prefill") if calls_target else factory()
        if calls_target and "target" in sol_roles:
            tool = models["target"].api.guard_tool(tool)
        auditor_tools.append(tool)
    logs = eval(
        task,
        model=None, model_roles=models, log_dir=str(output / "logs"),
        solver=auditor_agent(max_turns=args.max_turns, auditor_system_message=auditor_prompt,
                             auditor_tools=auditor_tools),
        epochs=1, max_samples=1, fail_on_error=True, time_limit=args.time_limit or None, display="plain",
    )
    log = logs[0]
    if log.status != "success" or not log.samples or log.samples[0].error:
        raise RuntimeError(f"Audit failed; inspect {output}")
    save_results(log, output, args.scoring, instruction)
    print(f"Saved {args.scoring} judgments and transcript: {output}")


def save_results(log, output, scoring, instruction):
    sample = log.samples[0]
    tool_errors = [{"function": e.function, "type": e.error.type, "message": e.error.message}
                   for e in sample.events if e.event == "tool" and e.error]
    judge_errors = dict(sample.metadata.get("judge_errors", {}))
    native = sample.scores.get("alignment_judge")
    if native and (set(native.value) != set(DIMENSIONS)
                   or "score_descriptions" in (native.metadata or {})):
        judge_errors["alignment_judge"] = {"error": "Incomplete native judgment",
                                          "response": (native.metadata or {}).get("response", "")}
        native = None
    if scoring != "requirement":
        native_result = {
            "status": "scored" if native else "failed",
            "scores": native.value if native else None,
            "summary": native.answer if native else None,
            "reason": native.explanation if native else None,
            "response": (native.metadata or {}).get("response") if native else None,
            "error": judge_errors.get("alignment_judge"),
        }
        (output / "native_judgment.json").write_text(json.dumps(
            native_result, indent=2, ensure_ascii=False) + "\n")

    primary_name = "alignment_judge" if scoring == "native" else "requirement_judge"
    primary = native if scoring == "native" else sample.scores.get(primary_name)
    summary = {
        "status": "scoring_error" if judge_errors else "completed_with_tool_errors" if tool_errors else log.status,
        "scoring": scoring, "primary_scorer": primary_name,
        "scores": native.value if scoring == "native" and native else {"performance": None},
        "summary": primary.answer if primary else None,
        "reason": primary.explanation if primary else None,
        "tool_errors": tool_errors, "judge_errors": judge_errors,
        "usage": {name: usage.model_dump() for name, usage in log.stats.model_usage.items()},
    }
    if scoring == "both":
        summary["native_reference"] = native_result
    if scoring != "native" and primary:
        judgment = primary.metadata["judgment"]
        summary.update(scores={"performance": judgment["score"]},
                       assessment_status=judgment["status"], evidence=judgment["evidence"],
                       limitations=judgment["limitations"])
        (output / "judgment.json").write_text(json.dumps(
            primary.metadata, indent=2, ensure_ascii=False) + "\n")
        score_text = f"{judgment['score']}/10" if judgment["score"] is not None else "证据不足（不计分）"
        report = (f"需求：{instruction}\n\n表现评分（主结果）：{score_text}\n\n{judgment['summary']}\n\n"
                  f"{judgment['reason']}\n\n证据：\n\n"
                  + "\n".join(f"- {item}" for item in judgment["evidence"])
                  + f"\n\n评价范围与限制：{judgment['limitations']}\n")
    else:
        report = f"需求：{instruction}\n\n"
        if scoring != "native":
            report += "需求评分失败，未产生主评分。详情见 summary.json。\n"
    if scoring != "requirement":
        report += "\nPetri 原生 23 维评分（参考，各维度含义遵循原生准则）：\n\n"
        if native:
            report += "| 维度 | 分数 |\n| --- | --- |\n"
            report += "".join(f"| {name} | {native.value[name]}/10 |\n" for name in DIMENSIONS)
            report += f"\n{native.answer}\n\n{native.explanation}\n"
        else:
            report += "原生评分失败，未产生有效参考分。详情见 native_judgment.json。\n"
    if tool_errors:
        report += f"\n审计器工具错误 {len(tool_errors)} 次，评分已保留，详情见 summary.json。\n"
    (output / "report.md").write_text(report)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    transcripts = list((output / "transcripts").glob("*.json"))
    if len(transcripts) != 1:
        raise RuntimeError(f"Expected one saved transcript; inspect {output}")
    target_messages = Transcript.load(str(transcripts[0])).collect_messages("target")
    if not any(message.role == "assistant" and message.text.strip() for message in target_messages):
        raise RuntimeError(f"No target response in saved transcript; inspect {output}")
    if judge_errors or primary is None or tool_errors:
        raise RuntimeError(f"Run contained errors; available judgments saved to {output}")


if __name__ == "__main__":
    main()
