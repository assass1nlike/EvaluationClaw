import argparse
import hashlib
import json
import os
import random
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)


def main():
    parser = argparse.ArgumentParser(description="Run the official YourBench pipeline locally.")
    parser.add_argument(
        "--source", type=Path, default=ROOT / "upstream/example/default_example/data"
    )
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.is_dir():
        parser.error(f"Source directory does not exist: {source}")
    load_dotenv(ROOT / ".env", override=True)
    seed_everything(42)
    run_dir = ROOT / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir()
    os.environ["YOURBENCH_SOURCE"] = str(source)
    os.environ["YOURBENCH_RUN_DIR"] = str(run_dir)
    os.chdir(run_dir)

    from datasets import load_from_disk
    from yourbench.conf.loader import load_config
    from yourbench.main import configure_logging
    from yourbench.pipeline.handler import run_pipeline_with_config
    from yourbench.utils.inference import inference_core

    configure_logging(log_dir=run_dir / "logs")
    config = load_config(ROOT / "config.yaml")
    saved_config = config.model_dump()
    for model in saved_config["model_list"]:
        model["api_key"] = "$YOURBENCH_API_KEY"
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(saved_config, allow_unicode=True), encoding="utf-8"
    )
    metadata = {
        "revision": subprocess.check_output(
            ["git", "-C", str(ROOT / "upstream"), "rev-parse", "HEAD"], text=True
        ).strip(),
        "seed": 42,
        "source": str(source),
        "source_sha256": {
            str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(source.rglob("*"))
            if p.is_file() and p.suffix in config.pipeline.ingestion.supported_file_extensions
        },
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    original_get_response = inference_core._get_response

    async def record_response(model, call, *call_args, **call_kwargs):
        response, metrics = await original_get_response(model, call, *call_args, **call_kwargs)
        with (run_dir / "responses.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"messages": call.messages, "response": response, "metrics": asdict(metrics)},
                    ensure_ascii=False,
                )
                + "\n"
            )
        return response, metrics

    inference_core._get_response = record_response
    print(f"Run directory: {run_dir}", flush=True)
    run_pipeline_with_config(config)

    dataset = load_from_disk(str(run_dir / "dataset"))
    expected = [
        "ingested",
        "summarized",
        "chunked",
        "single_hop_questions",
        "multi_hop_questions",
        "prepared_lighteval",
    ]
    for name in expected:
        if name not in dataset or not len(dataset[name]):
            raise RuntimeError(f"Missing or empty output: {name}")
    if not all(row["document_summary"].strip() for row in dataset["summarized"]):
        raise RuntimeError("Empty document summary")
    questions = dataset["prepared_lighteval"]
    for row in questions:
        if not all(
            row[key]
            for key in [
                "question",
                "ground_truth_answer",
                "citations",
                "chunks",
                "document_summary",
            ]
        ):
            raise RuntimeError("Exported question is missing required content")
        if not 0 <= row["citation_score"] <= 100:
            raise RuntimeError("Invalid citation score")
        if row["kind"] == "multi_hop" and len(row["chunk_ids"]) < 2:
            raise RuntimeError("Multi-hop question uses fewer than two chunks")
    exported = [
        json.loads(line)
        for line in (run_dir / "jsonl/prepared_lighteval.jsonl").read_text().splitlines()
    ]
    if exported != questions.to_list():
        raise RuntimeError("JSONL export differs from saved dataset")
    scores = questions["chunk_citation_score"]
    responses = [
        json.loads(line) for line in (run_dir / "responses.jsonl").read_text().splitlines()
    ]
    verification = {
        "passed": True,
        "subset_rows": {name: len(rows) for name, rows in dataset.items()},
        "question_kinds": dict(Counter(questions["kind"])),
        "chunk_citation_score_mean": float(np.mean(scores)),
        "chunk_citation_score_min": min(scores),
        "jsonl_matches_dataset": True,
        "recorded_model_calls": len(responses),
        "estimated_input_tokens": sum(row["metrics"]["input_tokens"] for row in responses),
        "estimated_output_tokens": sum(row["metrics"]["output_tokens"] for row in responses),
    }
    (run_dir / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
