"""Seed and run the unchanged official knowledge benchmark entry point."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import runpy
import subprocess
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def seed_everything(seed):
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("AUTOBENCHER_MODEL"))
    parser.add_argument("--base-url", default=os.getenv("AUTOBENCHER_BASE_URL"))
    parser.add_argument("--theme", default="history")
    parser.add_argument("--iterations", type=int, help="Total iterations; defaults to 2 for a new run")
    parser.add_argument("--acc-target", default="0.1--0.3")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--extra-body", default=os.getenv("AUTOBENCHER_EXTRA_BODY", '{"thinking":{"type":"enabled"}}'))
    parser.add_argument("--test-taker", type=json.loads,
                        help="JSON with model, base_url, api_key_env and extra_body for a separate target")
    parser.add_argument("--resume", type=Path, help="Resume an existing run using its saved configuration")
    parser.add_argument("--output-dir", type=Path, help="Output directory for a new run")
    args = parser.parse_args()
    if args.resume:
        args.resume = args.resume.resolve()
        saved = json.loads((args.resume / "config.json").read_text())
        for key in ["model", "base_url", "theme", "acc_target", "seed"]:
            setattr(args, key, saved[key])
        args.extra_body = json.dumps(saved["extra_body"])
        args.test_taker = saved.get("test_taker")
        if args.iterations is None:
            args.iterations = saved["iterations"]
        if args.iterations < saved["iterations"]:
            parser.error("Cannot reduce the saved iteration count when resuming")
    elif args.iterations is None:
        args.iterations = 2
    if not args.model or not args.base_url or not os.getenv("AUTOBENCHER_API_KEY"):
        parser.error("Set AUTOBENCHER_MODEL, AUTOBENCHER_BASE_URL and AUTOBENCHER_API_KEY in .env")
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    if args.test_taker:
        if set(args.test_taker) != {"model", "base_url", "api_key_env", "extra_body"}:
            parser.error("--test-taker requires model, base_url, api_key_env and extra_body")
        if not os.getenv(args.test_taker["api_key_env"]):
            parser.error(f"Set {args.test_taker['api_key_env']} in .env")
    if os.getenv("PYTHONHASHSEED") != str(args.seed):
        os.environ["PYTHONHASHSEED"] = str(args.seed)
        os.execv(sys.executable, [sys.executable, "-u", *sys.argv])
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    os.environ["HF_HOME"] = str(ROOT / ".cache/huggingface")
    os.environ["HF_HUB_CACHE"] = str(ROOT / ".cache/huggingface/hub")
    os.environ["TRANSFORMERS_CACHE"] = str(ROOT / ".cache/huggingface/hub")
    seed_everything(args.seed)
    run_dir = args.resume or (args.output_dir.resolve() if args.output_dir else
                             ROOT / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    if not args.resume:
        run_dir.mkdir(parents=True)
    upstream = ROOT / "upstream"
    config = {k: v for k, v in vars(args).items() if k not in {"resume", "output_dir"}} | {
        "extra_body": json.loads(args.extra_body),
        "upstream_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip(),
        "upstream_diff": subprocess.check_output(
            ["git", "diff", "HEAD"], cwd=upstream, text=True),
        "python": sys.version,
        "roles": {role: args.model for role in ["agent", "test_taker", "judge"]},
    }
    command = [str(upstream / "wiki_autobencher.py"),
               "--exp_mode", "autobencher", "--use_helm", "no",
               "--agent_modelname", "gpt-autobencher",
               "--test_taker_modelname", "gpt-autobencher-target" if args.test_taker else "gpt-autobencher",
               "--tool_modelname", "gpt-autobencher",
               "--theme", args.theme, "--num_iters", str(args.iterations),
               "--acc_target", args.acc_target,
               "--outfile_prefix1", str(run_dir / "wiki.")]
    config["upstream_argv"] = command
    if args.test_taker:
        config["roles"]["test_taker"] = args.test_taker["model"]
    if args.resume:
        assert config["upstream_commit"] == saved["upstream_commit"]
        if args.iterations != saved["iterations"]:
            (run_dir / "config.json").rename(run_dir / f"config.iterations-{saved['iterations']}.json")
            verification = run_dir / "verification.json"
            if verification.exists():
                verification.rename(run_dir / f"verification.iterations-{saved['iterations']}.json")
            (run_dir / "config.json").write_text(json.dumps(config, indent=2))
        empty_files = [p for p in run_dir.glob("wiki.*__*.KI_questions.json") if p.stat().st_size == 0]
        with (run_dir / "resumes.jsonl").open("a") as f:
            f.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(),
                                "previous_iterations": saved["iterations"],
                                "iterations": args.iterations,
                                "upstream_commit": config["upstream_commit"],
                                "upstream_diff": config["upstream_diff"],
                                "removed_empty_files": [p.name for p in empty_files]}) + "\n")
        for path in empty_files:
            path.unlink()
    else:
        (run_dir / "config.json").write_text(json.dumps(config, indent=2))
    print(f"Run directory: {run_dir}", flush=True)
    from api import start_api

    target = args.test_taker | {"api_key": os.environ[args.test_taker["api_key_env"]]} if args.test_taker else None
    url, close = start_api(args.base_url, os.environ["AUTOBENCHER_API_KEY"],
                           args.model, config["extra_body"], args.seed, run_dir, test_taker=target)
    os.environ["OPENAI_BASE_URL"] = url
    os.environ["OPENAI_API_KEY"] = "local-proxy"
    os.environ.pop("OPENAI_ORG_ID", None)
    sys.path.insert(0, str(upstream))
    sys.argv = command
    os.chdir(run_dir)
    try:
        runpy.run_path(command[0], run_name="__main__")
    finally:
        close()
    from verify import verify

    print(json.dumps(verify(run_dir), indent=2))


if __name__ == "__main__":
    main()
