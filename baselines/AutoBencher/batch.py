"""Run independent AutoBencher tasks concurrently and record exit status."""

import asyncio
import argparse
from datetime import datetime, timezone
import json
import shutil
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    batch_dir = args.resume.resolve() if args.resume else ROOT / "runs" / ("batch-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    if args.resume:
        previous = json.loads((batch_dir / "config.json").read_text())
        if config["iterations"] != previous["iterations"]:
            archive = batch_dir / "archive" / f"iterations-{previous['iterations']}"
            archive.mkdir(parents=True)
            for name in ["config.json", "status.json", "summary.json"]:
                if (batch_dir / name).exists():
                    shutil.copy2(batch_dir / name, archive / name)
            (batch_dir / "summary.json").unlink(missing_ok=True)
    else:
        batch_dir.mkdir(parents=True)
    (batch_dir / "config.json").write_text(json.dumps(config, indent=2))
    states = {task["name"]: {"status": "pending"} for task in config["tasks"]}

    def save():
        temporary = batch_dir / "status.tmp"
        temporary.write_text(json.dumps(states, indent=2))
        temporary.replace(batch_dir / "status.json")

    async def run(task):
        name = task["name"]
        output = batch_dir / name
        command = [sys.executable, "-u", str(ROOT / "run.py")]
        if args.resume:
            command.extend(["--resume", str(output), "--iterations", str(config["iterations"])])
        else:
            command.extend(["--theme", task["theme"], "--output-dir", str(output)])
            for key in ["model", "base_url", "iterations", "seed", "acc_target", "extra_body"]:
                value = json.dumps(config[key]) if key == "extra_body" else str(config[key])
                command.extend(["--" + key.replace("_", "-"), value])
            if config.get("test_taker"):
                command.extend(["--test-taker", json.dumps(config["test_taker"])])
            if config.get("parallel"):
                command.extend(["--parallel", json.dumps(config["parallel"])])
        with (batch_dir / f"{name}.log").open("a" if args.resume else "w") as log:
            process = await asyncio.create_subprocess_exec(
                *command, cwd=ROOT, stdout=log, stderr=asyncio.subprocess.STDOUT)
            states[name] = {"status": "running", "pid": process.pid,
                            "started": datetime.now(timezone.utc).isoformat(),
                            "output_dir": str(output), "command": command}
            save()
            code = await process.wait()
            states[name].update(status="complete" if code == 0 else "failed",
                                exit_code=code, ended=datetime.now(timezone.utc).isoformat())
            save()
            return code

    save()
    print(f"Batch directory: {batch_dir}", flush=True)
    codes = await asyncio.gather(*(run(task) for task in config["tasks"]))
    return int(any(code != 0 for code in codes))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
