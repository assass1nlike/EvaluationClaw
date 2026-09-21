"""Run independent official pipelines, then evaluate the resulting items."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOPICS = ("knowledge_50", "data_analysis_50", "instruction_following_50")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("--topics", nargs="+", default=TOPICS)
    args = parser.parse_args()
    batch = ROOT / args.batch
    batch.mkdir(parents=True, exist_ok=True)
    if (batch / "batch.json").exists():
        raise ValueError("Use a fresh batch directory")
    topics = args.topics
    queries = {topic: json.loads((ROOT / "user_queries" / f"{topic}.json").read_text()) for topic in topics}
    configuration = batch / "configuration"
    configuration.mkdir()
    for name in ("models.yaml", "dataset_cards.yaml"):
        shutil.copy2(ROOT / "utils/resources" / name, configuration / name)
    for topic in topics:
        shutil.copy2(ROOT / "user_queries" / f"{topic}.json", configuration / f"{topic}.json")
    config = yaml.safe_load((ROOT / "utils/resources/models.yaml").read_text())
    manifest = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "model": config["tools"]["default"],
        "search_model": config["tools"]["web_search"],
        "search_base_url": config.get("web_search_api", {}).get("base_url"),
        "framework_concurrency": len(topics),
        "seed": 42,
        "hash_seed": os.environ.get("PYTHONHASHSEED"),
        "request_parameters": config.get("request_parameters", {}),
        "api_concurrency": {"deepseek": "no additional limit; official worker pools",
                            "luna_global": config.get("web_search_api", {}).get("global_concurrency")},
        "target_sizes": {topic: query["target_size"] for topic, query in queries.items()},
        "replenishment": "disabled as in official release",
        "runs": {},
    }

    def save():
        path = batch / "batch.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n")
        temporary.replace(path)

    jobs = []
    for topic in topics:
        command = [sys.executable, "local/run_with_usage.py", "--topic_id", f"user_queries/{topic}",
                   "--dataset_card_config", "utils/resources/dataset_cards.yaml",
                   "--cache_path", str(batch) + "/",
                   "--model_config_path", "utils/resources/models.yaml"]
        with (batch / f"{topic}.generation.log").open("w") as log:
            proc = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        manifest["runs"][topic] = {"generation_pid": proc.pid, "generation_command": command}
        jobs.append((topic, proc))
    save()
    for topic, proc in jobs:
        result = batch / "user_queries" / topic / "evaluation.json"
        manifest["runs"][topic]["generation_exit_code"] = proc.wait()
        manifest["runs"][topic]["exported_count"] = len(json.loads(result.read_text())) if result.exists() else 0
        save()

    jobs = []
    for topic in topics:
        run = batch / "user_queries" / topic
        if manifest["runs"][topic]["generation_exit_code"] != 0 or not (run / "evaluation.json").exists():
            continue
        command = [sys.executable, "local/self_evaluate.py", "--run-dir", str(run)]
        with (batch / f"{topic}.selftest.log").open("w") as log:
            proc = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        manifest["runs"][topic]["selftest_pid"] = proc.pid
        jobs.append((topic, proc))
    save()
    for topic, proc in jobs:
        manifest["runs"][topic]["selftest_exit_code"] = proc.wait()
        save()
    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save()


if __name__ == "__main__":
    main()
