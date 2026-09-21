"""Rerun complete audits missing either score, preserving their source and seeds."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from run_batch import REQUIREMENTS, run_epoch, summarize, write_json
from petri.scorers.prompts import DIMENSIONS


def missing_score(record):
    return record.get("score") is None or set(record.get("native_scores", {})) != set(DIMENSIONS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    load_dotenv(ROOT / ".env", override=True)
    original, output = args.batch.resolve(), args.output_dir.resolve()
    config = json.loads((original / "config.json").read_text())
    if not config.get("finished_at"):
        raise ValueError("Original batch must have finished")
    records = {req: json.loads((original / f"requirement-{req:02d}/summary.json").read_text())["epochs"]
               for req in REQUIREMENTS}
    selected = [(req, record) for req in REQUIREMENTS for record in records[req] if missing_score(record)]
    if not selected:
        raise ValueError("No missing scores")
    source = original / "source"
    for name, digest in json.loads((source / "sha256.json").read_text()).items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Source snapshot changed: {name}")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, output / "source")
    shutil.copy2(__file__, output / "scheduler.py")
    manifest = {"started_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
                "original_batch": str(original), "options": config["options"],
                "parallel_epochs": len(selected), "selection": "Missing requirement or complete native scores",
                "selected": [{"requirement": req, "epoch": rec["epoch"], "seed": rec["seed"]}
                             for req, rec in selected],
                "replacement": "Use the entire new audit for each selected epoch; retain original artifacts",
                "automatic_reruns": False, "sighup": "ignored"}
    write_json(output / "config.json", manifest)
    completed = []
    # Consolidated records always point to the exact attempt that supplied their scores.
    for req in REQUIREMENTS:
        (output / f"requirement-{req:02d}").mkdir()
        for rec in records[req]:
            rec["output"] = os.path.relpath(original / rec["output"], output)
    with ThreadPoolExecutor(max_workers=len(selected)) as executor:
        futures = {executor.submit(run_epoch, output, req, rec["epoch"], rec["seed"], config["options"]): req
                   for req, rec in selected}
        for future in as_completed(futures):
            req, record = futures[future], future.result()
            completed.append({"requirement": req, **record})
            write_json(output / "progress.json", {"planned": len(selected), "finished": len(completed),
                                                  "epochs": completed})
            records[req] = [record if old["epoch"] == record["epoch"] else old for old in records[req]]
            print(f"Requirement {req}, epoch {record['epoch']}, seed {record['seed']}: "
                  f"{record['status']}, score={record['score']}, native={len(record['native_scores'])}", flush=True)
    summaries = {str(req): summarize(records[req], len(config["seeds"])) for req in REQUIREMENTS}
    write_json(output / "summary.json", summaries)
    report = "全部 80 个 epoch 的汇总；本轮选中的 epoch 使用完整重跑结果，其余沿用原批次。\n\n"
    report += "| 需求行 | 有效需求评分 | 需求分均值 | 标准误 | 完整原生评分 |\n| --- | --- | --- | --- | --- |\n"
    for req, summary in summaries.items():
        m = summary["performance"]
        native = sum(set(rec["native_scores"]) == set(DIMENSIONS) for rec in summary["epochs"])
        report += f"| {req} | {m['n']}/20 | {m['mean']} | {m['stderr']} | {native}/20 |\n"
    (output / "report.md").write_text(report)
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["still_missing"] = [{"requirement": rec["requirement"], "epoch": rec["epoch"]}
                                 for rec in completed if missing_score(rec)]
    write_json(output / "config.json", manifest)
    return int(bool(manifest["still_missing"]))


if __name__ == "__main__":
    sys.exit(main())
