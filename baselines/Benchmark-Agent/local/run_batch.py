"""Run three independent official pipelines, then evaluate the resulting items."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOPICS = ("knowledge_50", "data_analysis_50", "instruction_following_50")


def main():
    batch = ROOT / sys.argv[1]
    batch.mkdir(parents=True, exist_ok=True)
    manifest = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "model": "openai/deepseek-flash",
        "framework_concurrency": 3,
        "api_concurrency": "official defaults; no additional limit",
        "target_size_per_topic": 50,
        "replenishment": "disabled as in official release",
        "runs": {},
    }

    def save():
        path = batch / "batch.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n")
        temporary.replace(path)

    jobs = []
    for topic in TOPICS:
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
    for topic in TOPICS:
        run = batch / "user_queries" / topic
        if not (run / "evaluation.json").exists():
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
