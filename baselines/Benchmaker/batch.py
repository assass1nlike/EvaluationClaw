"""Run the three configured benchmarks concurrently and record their exits."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
NAMES = ("knowledge", "data-analysis", "instruction-following")


def main():
    memory_limit = 16 * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
    directory = ROOT / "runs/batch-50"
    directory.mkdir(exist_ok=True)
    for name in NAMES:
        if (ROOT / "runs" / name).exists():
            raise FileExistsError(f"Run already exists: {name}")
    state = {"supervisor_pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat(),
             "per_process_address_space_limit_bytes": memory_limit,
             "tmux_session": "benchmaker-50", "runs": {}}
    processes = {}
    for name in NAMES:
        command = [sys.executable, "-u", "run.py", "--config", f"configs/{name}.json", "--run", name]
        with (ROOT / "runs" / f"{name}.log").open("x") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT)
        processes[name] = process
        state["runs"][name] = {"pid": process.pid, "command": command, "status": "running"}
    while True:
        for name, process in processes.items():
            code = process.poll()
            record = state["runs"][name]
            if code is not None and record["status"] == "running":
                record.update(status="completed" if code == 0 else "failed", exit_code=code,
                              finished_at=datetime.now(timezone.utc).isoformat())
        temporary = directory / "status.tmp"
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(directory / "status.json")
        if all(r["status"] != "running" for r in state["runs"].values()):
            break
        time.sleep(5)
    sys.exit(int(any(r["exit_code"] != 0 for r in state["runs"].values())))


if __name__ == "__main__":
    main()
