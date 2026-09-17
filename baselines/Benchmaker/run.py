"""Run the original attribute, generation, and decoding stages locally."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def seed_everything(seed):
    if os.environ.get("PYTHONHASHSEED") != str(seed):
        os.environ["PYTHONHASHSEED"] = str(seed)
        os.environ["PYTHONUNBUFFERED"] = "1"
        os.execv(sys.executable, [sys.executable, *sys.argv])
    random.seed(seed)
    import numpy as np
    np.random.seed(seed)
    os.environ["BENCHMAKER_SEED"] = str(seed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/smoke.json")
    parser.add_argument("--run", default="smoke")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config["NumberPerAbility"] < 10 or config["NumberPerAbility"] % 10:
        parser.error("NumberPerAbility must be a positive multiple of 10 for upstream decoding")
    load_dotenv(ROOT / ".env", override=True)
    seed_everything(config["seed"])
    run = (ROOT / "runs" / args.run).resolve()
    if not run.is_relative_to(ROOT / "runs"):
        parser.error("--run must stay inside Benchmaker/runs")
    if args.resume:
        previous = json.loads((run / "config.json").read_text())
        if any(previous[key] != value for key, value in config.items()):
            parser.error("Resume requires the original task configuration")
        records = [json.loads(line) for line in (run / "requests.jsonl").read_text().splitlines()]
        os.environ["BENCHMAKER_REQUEST_OFFSET"] = str(max(r["request_id"] for r in records) + 1)
        for path in run.glob("API_Com_syn/*/*/*harder/raw_data/*/*.json"):
            if path.stat().st_size == 0:
                path.unlink()
    else:
        run.mkdir(parents=True, exist_ok=False)
    for name in ("NLTK_DATA", "MPLCONFIGDIR", "XDG_CACHE_HOME"):
        location = ROOT / ".cache" / name.lower()
        location.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(location)
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["TMPDIR"] = str(ROOT / ".cache/tmp")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    import nltk
    for nltk_resource in ("punkt", "punkt_tab", "stopwords"):
        nltk.download(nltk_resource, download_dir=os.environ["NLTK_DATA"], raise_on_error=True)
    if not args.resume:
        (run / "prompts").symlink_to(ROOT / "upstream/prompts", target_is_directory=True)
    sys.path.append(str(ROOT / "upstream"))
    os.chdir(run)
    from final_generate_attribute_0 import main_0_single
    from final_LLMasBenchmarkGenerator_1 import main_1_single
    from final_decode_2 import main_2

    model = os.environ["BENCHMAKER_MODEL"]
    metadata = {
        **config,
        "model": model,
        "api": {k: v for k, v in os.environ.items()
                if k.startswith("BENCHMAKER_") and k != "BENCHMAKER_API_KEY"},
        "upstream_commit": "8aaa2b6c644d52580a640c67f3ee024f217eb240",
        "difficulty_implementation": "exact_rank_lookup",
        "address_space_limit_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("upstream/difficulty.py", "upstream/final_LLMasBenchmarkGenerator_1.py")
        },
    }
    if args.resume:
        with (run / "resumes.jsonl").open("a") as stream:
            stream.write(json.dumps(metadata, ensure_ascii=False) + "\n")
    else:
        (run / "config.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    benchmark = config["benchmark_name"]
    for ability, description in config["abilities"].items():
        os.environ["BENCHMAKER_STAGE"] = "attributes"
        print(f"Generating attributes: {ability}", flush=True)
        main_0_single(model, description, benchmark, ability)
        os.environ["BENCHMAKER_STAGE"] = "questions"
        print(f"Generating questions: {ability}", flush=True)
        main_1_single(model, description, benchmark, ability,
                      config["NumberPerAbility"], config["DemoNum"],
                      config["DiverNum"], config["OptionNum"])
    summary = main_2(benchmark, model, config["DemoNum"],
                     config["DiverNum"], config["NumberPerAbility"])
    output = run / "generated_benchmark/API_Com_syn" / benchmark / model / (
        f"attr_deep_diffusion_difattr_diflabel_v2-{config['DemoNum']}_harder/data.json"
    )
    data = json.loads(output.read_text())
    expected = config["NumberPerAbility"] * len(config["abilities"])
    if len(data) != expected:
        raise RuntimeError(f"Expected {expected} questions, got {len(data)}")
    for sample in data:
        if not sample["question"] or not sample["reasoning"] or not sample["candiates"]:
            raise RuntimeError(f"Incomplete question: {sample['idx']}")
        if sample["label"].upper() not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:config["OptionNum"]]:
            raise RuntimeError(f"Invalid label: {sample['idx']}")
        if len(sample["model_predictions"]) != 10:
            raise RuntimeError(f"Missing calibration responses: {sample['idx']}")
    (run / "benchmark.json").symlink_to(output.relative_to(run))
    (run / "summary.txt").write_text(summary + "\n")
    print(summary, flush=True)
    print(f"Validated {len(data)} questions: {run / 'benchmark.json'}", flush=True)


if __name__ == "__main__":
    main()
