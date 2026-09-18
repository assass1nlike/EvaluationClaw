"""Read-only progress and failure evidence for a batch of baseline runs."""

import argparse
import json
from collections import Counter
from pathlib import Path


def read(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def audit(batch):
    manifest = read(batch / "batch.json") or {}
    results = {}
    for topic, run in manifest.get("runs", {}).items():
        root = batch / "user_queries" / topic
        errors, statuses = Counter(), Counter()
        calls, tokens = 0, 0
        for path in root.glob("**/token_usage/*/calls.jsonl"):
            for line in path.read_text().splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # An active writer may not have finished its last line.
                calls += 1
                tokens += (event.get("usage") or {}).get("total_tokens", 0)
                if event.get("error_type"):
                    errors[event["error_type"]] += 1
                if event.get("response_status"):
                    statuses[event["response_status"]] += 1
        exported = read(root / "evaluation.json")
        exported_ids = {(str(x["dataset_id"]), str(x["idx"])) for x in exported or []}
        failures = []
        for path in (root / "transform_log/sample_iterative").glob("*.json"):
            for sample_id, state in (read(path) or {}).get("sample_iterative_states", {}).items():
                for index, step in enumerate(state.get("step_history", [])):
                    if step.get("status") == "fail":
                        failures.append({"file": str(path.relative_to(batch)), "sample_id": sample_id,
                                         "history_index": index, "step": step.get("step_name"),
                                         "error": step.get("error"),
                                         "exported": tuple(sample_id.split("::")) in exported_ids})
        log = batch / (topic + ".generation.log")
        lines = log.read_text(errors="replace").splitlines() if log.exists() else []
        progress = [line for line in lines if line.startswith(("Transform[", "Verifying samples", "[export_results]"))]
        results[topic] = {
            "generation_exit": run.get("generation_exit_code"), "selftest_exit": run.get("selftest_exit_code"),
            "exported": len(exported) if exported is not None else None,
            "selftest": read(root / "selftest/summary.json"),
            "calls": calls, "reported_tokens": tokens, "api_errors": dict(errors),
            "search_response_status": dict(statuses), "framework_step_failures": failures,
            "progress": progress[-1] if progress else "planning/grounding/allocation",
        }
    return {"started_utc": manifest.get("started_utc"), "finished_utc": manifest.get("finished_utc"), "runs": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.batch), ensure_ascii=False, indent=2))
