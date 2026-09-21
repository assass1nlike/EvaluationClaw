"""Repeat independent Petri audits, with four requirements running concurrently."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

from dotenv import load_dotenv
from petri.scorers.prompts import DIMENSIONS


ROOT = Path(__file__).resolve().parent
REQUIREMENTS = (7, 8, 9, 13)
OPTIONS = [
    "--auditor", "deepseek/deepseek-flash", "--target", "deepseek/deepseek-flash",
    "--judge", "deepseek/deepseek-flash", "--base-url", "https://api.deepseek.com/beta",
    "--max-turns", "200", "--thinking", "enabled", "--reasoning-effort", "high",
    "--max-tokens", "300000", "--request-timeout", "600", "--time-limit", "0",
    "--prefill-mode", "no-prefill", "--scoring", "both",
]
QWEN_OPTIONS = [
    "--auditor", "qwen/qwen3.8-27b", "--target", "qwen/qwen3.8-27b",
    "--judge", "qwen/qwen3.8-27b", "--base-url", "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "--max-turns", "200", "--thinking", "enabled", "--reasoning-effort", "high",
    "--max-tokens", "300000", "--request-timeout", "600", "--time-limit", "0",
    "--prefill-mode", "prefill", "--scoring", "both",
]
QWEN_TARGET_OPTIONS = [
    "--auditor", "deepseek/deepseek-flash", "--target", "qwen/qwen3.8-27b",
    "--judge", "deepseek/deepseek-flash", "--base-url", "https://api.deepseek.com/beta",
    "--target-base-url", "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "--max-turns", "200", "--thinking", "enabled", "--reasoning-effort", "high",
    "--max-tokens", "300000", "--request-timeout", "600", "--time-limit", "0",
    "--prefill-mode", "prefill", "--scoring", "both",
]
SOL_TARGET_OPTIONS = [
    "--auditor", "deepseek/deepseek-flash", "--target", "sol/gpt-5.6-sol",
    "--judge", "deepseek/deepseek-flash", "--base-url", "https://api.deepseek.com/beta",
    "--target-base-url", "https://api.sudorelay.com/v1",
    "--max-turns", "200", "--thinking", "enabled", "--reasoning-effort", "high",
    "--max-tokens", "300000", "--request-timeout", "600", "--time-limit", "0",
    "--prefill-mode", "no-prefill", "--scoring", "both", "--sol-rpm", "50",
    "--sol-rate-limit-file", str(ROOT / ".local/state/sol-rate-limit"),
]


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def metrics(values):
    values = [value for value in values if value is not None]
    return {
        "n": len(values),
        "mean": statistics.mean(values) if values else None,
        "stderr": statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None,
    }


def summarize(records, planned):
    return {
        "planned_epochs": planned,
        "finished_epochs": len(records),
        "nonzero_exits": sum(record["exit_code"] != 0 for record in records),
        "performance": metrics(record["score"] for record in records),
        "native_reference": {
            name: metrics(record["native_scores"].get(name) for record in records)
            for name in DIMENSIONS
        },
        "epochs": records,
    }


def run_epoch(batch, requirement, epoch, seed, options):
    directory = batch / f"requirement-{requirement:02d}"
    output = directory / f"epoch-{epoch:02d}"
    command = [
        sys.executable, str(batch / "source" / "run.py"), *options,
        "--instruction", str(batch / "source" / "inputs" / f"requirement-{requirement:02d}.txt"),
        "--seed", str(seed), "--output-dir", str(output),
    ]
    env = {**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONUNBUFFERED": "1",
           "PYTHONPATH": str(batch / "source" / "upstream" / "src")}
    with (directory / f"epoch-{epoch:02d}.console.log").open("w") as console:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=console, stderr=subprocess.STDOUT)
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    return {
        "epoch": epoch, "seed": seed, "exit_code": result.returncode,
        "status": summary.get("status", "run_failed"),
        "assessment_status": summary.get("assessment_status"),
        "score": summary.get("scores", {}).get("performance"),
        "native_scores": summary.get("native_reference", {}).get("scores") or {},
        "tool_errors": summary.get("tool_errors", []),
        "judge_errors": summary.get("judge_errors", {}),
        "output": str(output.relative_to(batch)),
    }


def run_requirement(batch, requirement, seeds, options, concurrency):
    directory = batch / f"requirement-{requirement:02d}"
    directory.mkdir(exist_ok=True)
    summary_path = directory / "summary.json"
    records = json.loads(summary_path.read_text())["epochs"] if summary_path.exists() else []
    completed = {record["epoch"] for record in records}
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(run_epoch, batch, requirement, epoch, seed, options)
                   for epoch, seed in enumerate(seeds, 1) if epoch not in completed]
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            records.sort(key=lambda item: item["epoch"])
            write_json(summary_path, summarize(records, len(seeds)))
            print(f"Requirement {requirement:02d}, epoch {record['epoch']}/{len(seeds)}, "
                  f"seed {record['seed']}: {record['status']}, score={record['score']}, "
                  f"exit={record['exit_code']}", flush=True)
    return summarize(records, len(seeds))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=20)
    profiles = {"deepseek": OPTIONS, "qwen": QWEN_OPTIONS, "qwen-target": QWEN_TARGET_OPTIONS,
                "sol-target": SOL_TARGET_OPTIONS}
    parser.add_argument("--profile", choices=profiles, default="deepseek")
    parser.add_argument("--seed", type=int, default=42, help="First seed; incremented once per epoch")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--epoch-concurrency", type=int, default=1)
    parser.add_argument("--resume", type=Path, help="Resume a stopped batch using its fixed source and configuration")
    args = parser.parse_args()
    if args.epoch_concurrency < 1:
        parser.error("--epoch-concurrency must be positive")
    if args.resume and args.output_dir:
        parser.error("--resume and --output-dir cannot be combined")
    if args.epochs < 1:
        parser.error("--epochs must be positive")
    load_dotenv(ROOT / ".env", override=True)
    options = profiles[args.profile]
    lines = (ROOT.parent.parent / "user-inputs.txt").read_text().splitlines()
    for requirement in REQUIREMENTS:
        path = ROOT / "inputs" / f"requirement-{requirement:02d}.txt"
        if path.read_text().strip() != lines[requirement - 1].strip():
            raise ValueError(f"Requirement {requirement} differs from user-inputs.txt")
    started = datetime.now(timezone.utc)
    if args.resume:
        batch = args.resume.resolve()
        manifest = json.loads((batch / "config.json").read_text())
        if "finished_at" in manifest:
            parser.error("Batch has already finished")
        if Path(f"/proc/{manifest['pid']}").exists():
            parser.error("Previous batch process still exists; stop it before resuming")
        source = batch / "source"
        hashes = json.loads((source / "sha256.json").read_text())
        for name, digest in hashes.items():
            if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Source snapshot changed: {name}")
        seeds, options = manifest["seeds"], manifest["options"]
        archive = batch / "interrupted" / started.strftime("%Y%m%dT%H%M%SZ")
        archive.mkdir(parents=True)
        shutil.copy2(batch / "config.json", archive / "config.json")
        for requirement in REQUIREMENTS:
            directory = batch / f"requirement-{requirement:02d}"
            summary = directory / "summary.json"
            completed = {record["epoch"] for record in json.loads(summary.read_text())["epochs"]} if summary.exists() else set()
            for epoch in range(1, len(seeds) + 1):
                if epoch in completed:
                    continue
                for path in (directory / f"epoch-{epoch:02d}", directory / f"epoch-{epoch:02d}.console.log"):
                    if path.exists():
                        destination = archive / directory.name / path.name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(path), destination)
        manifest["resumed_at"] = started.isoformat()
        manifest["pid"] = os.getpid()
    else:
        batch = (args.output_dir or ROOT / "results" / started.strftime(f"main-{args.profile}-%Y%m%dT%H%M%SZ")).resolve()
        batch.mkdir(parents=True)
        source = batch / "source"
        source.mkdir()
        files = [*ROOT.glob("*.py"), *ROOT.glob("*.sh"), ROOT / "judge_prompt.txt", ROOT / "README.md"]
        for path in files:
            shutil.copy2(path, source / path.name)
        shutil.copytree(ROOT / "inputs", source / "inputs")
        shutil.copytree(ROOT / "upstream" / "src" / "petri", source / "upstream" / "src" / "petri",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        write_json(source / "sha256.json", {
            str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(source.rglob("*")) if path.is_file()
        })
        seeds = list(range(args.seed, args.seed + args.epochs))
        manifest = {
            "started_at": started.isoformat(), "pid": os.getpid(), "requirements": list(REQUIREMENTS),
            "epochs_per_requirement": args.epochs, "seeds": seeds, "parallel_requirements": 4,
            "epoch_execution": "Sequential independent processes; each runs one native Petri epoch",
            "profile": args.profile, "options": options,
            "failed_epochs": "Record and continue; no automatic rerun",
            "workspace_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        }
    manifest["epoch_concurrency"] = args.epoch_concurrency
    manifest["epoch_execution"] = "Independent processes; refill a slot whenever an epoch finishes"
    scheduler = batch / "schedulers" / started.strftime("%Y%m%dT%H%M%SZ.py")
    scheduler.parent.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), scheduler)
    manifest["scheduler"] = str(scheduler.relative_to(batch))
    manifest["scheduler_sha256"] = hashlib.sha256(scheduler.read_bytes()).hexdigest()
    write_json(batch / "config.json", manifest)
    print(f"Batch: {batch}", flush=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {requirement: executor.submit(run_requirement, batch, requirement, seeds, options, args.epoch_concurrency)
                   for requirement in REQUIREMENTS}
        summaries = {str(requirement): future.result() for requirement, future in futures.items()}
    write_json(batch / "summary.json", summaries)
    report = "需求评分为主结果；均值与标准误仅使用有效分数。原生 23 维统计见 summary.json。\n\n"
    report += "| 需求行 | 完成次数 | 有效需求评分 | 均值 | 标准误 | 非零退出次数 |\n| --- | --- | --- | --- | --- | --- |\n"
    for requirement, summary in summaries.items():
        value = summary["performance"]
        report += (f"| {requirement} | {summary['finished_epochs']} | {value['n']} | "
                   f"{value['mean']} | {value['stderr']} | {summary['nonzero_exits']} |\n")
    (batch / "report.md").write_text(report)
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(batch / "config.json", manifest)
    return int(any(summary["nonzero_exits"] for summary in summaries.values()))


if __name__ == "__main__":
    sys.exit(main())
