"""Publish the eight completed benchmarks without changing question content."""

import argparse
import getpass
import hashlib
import json
from pathlib import Path

import yaml
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    "knowledge": "batch_20260917_eight_200",
    "reasoning": "batch_20260917_eight_200",
    "math": "batch_20260917_math_long_context_200",
    "computer_science": "batch_20260917_eight_200",
    "data_analysis": "batch_20260917_eight_200",
    "instruction_following": "batch_20260917_eight_200",
    "long_context": "batch_20260918_long_context_200_fallback",
    "multilingual": "batch_20260917_eight_200",
}
COUNTS = [182, 196, 191, 177, 191, 195, 175, 123]
REPO = "assassinlike/b635"


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def build():
    files, rows, manifest = {}, [], {}
    for (topic, batch), expected in zip(RUNS.items(), COUNTS):
        run = ROOT / "cache" / batch / "user_queries" / f"{topic}_200"
        raw = (run / "evaluation.json").read_bytes()
        questions = json.loads(raw)
        assert len(questions) == expected
        query = json.loads((ROOT / "cache" / batch / "configuration" / f"{topic}_200.json").read_text())
        grounding = json.loads((run / "agents/grounding_agent.json").read_text())
        subtasks = {s["id"]: s for s in grounding["context_variables"]["subtasks"]}
        summary = json.loads((run / "selftest/summary.json").read_text())
        config = json.loads((run / "selftest/config.json").read_text())
        assert config["evaluation_sha256"] == hashlib.sha256(raw).hexdigest()
        task = "mathematics" if topic == "math" else topic.replace("_", "-")
        task_rows = []
        for index, item in enumerate(questions):
            result = json.loads((run / "selftest/items" / f"{index:04d}.json").read_text())
            assert result["index"] == index and result["status"] == "scored"
            assert result["subtask_id"] == item["subtask_id"]
            assert result["dataset_id"] == item["dataset_id"]
            assert result["source_idx"] == item["idx"]
            assert result["reference"] == item["sample"]["output"]
            subtask = subtasks[item["subtask_id"]]
            row = {
                "id": f"benchmark-agent/{task}/{index:04d}",
                "task": task, "requirement": query["description"],
                "question_index": index, "subtask_id": item["subtask_id"],
                "subtask_name": subtask["name"], "answer_type": subtask["answer_type"],
                "dataset_id": item["dataset_id"],
                "input_json": encode(item["sample"]["input"]),
                "reference_output_json": encode(item["sample"]["output"]),
                "original_question_json": encode(item),
                "model_answer": result["prediction"], "correct": result["correct"],
                "scoring_method": result["method"],
                "original_selftest_json": encode(result),
            }
            assert json.loads(row["original_question_json"]) == item
            task_rows.append(row)
        assert sum(r["correct"] for r in task_rows) == summary["correct"]
        rows.extend(task_rows)
        files[f"benchmark-agent/data/{task}.jsonl"] = ("\n".join(map(encode, task_rows)) + "\n").encode()
        manifest[task] = {"source_batch": batch, "target_size": query["target_size"],
                          "requirement": query["description"],
                          "evaluation_sha256": hashlib.sha256(raw).hexdigest(),
                          "summary": summary, "selftest_config": config}
        # Retain only the subtask definitions, not internal agent histories or filesystem paths.
        definitions = [{k: s[k] for k in ("id", "name", "description", "answer_type", "modalities", "sample_schema")}
                       for s in subtasks.values()]
        files[f"benchmark-agent/provenance/{task}.json"] = (encode({**manifest[task], "subtasks": definitions}) + "\n").encode()
    assert len(rows) == 1430 and len({r["id"] for r in rows}) == 1430
    assert sum(r["correct"] for r in rows) == 1361
    table = "\n".join(f"| {task} | {m['summary']['exported_items']} | {m['summary']['correct']} | {100*m['summary']['accuracy_on_scored']:.2f}% |"
                      for task, m in manifest.items())
    readme = '''# Benchmark-Agent

All 1,430 exported questions from eight requirements, each with a target budget of 200. Only the final successful run for each requirement is included. No exported questions were removed, edited, or deduplicated. The official conversion and verification stages can reduce the final count; replenishment was disabled.

```python
import json
from datasets import load_dataset

questions = load_dataset("assassinlike/b635", "benchmark-agent", split="test")
task_input = json.loads(questions[0]["input_json"])
reference = json.loads(questions[0]["reference_output_json"])
```

| Requirement | Questions | DeepSeek Flash correct | Accuracy |
| --- | ---: | ---: | ---: |
''' + table + '''
| Total (question-weighted) | 1430 | 1361 | 95.17% |

`input_json` and `reference_output_json` preserve structured inputs and reference outputs as JSON strings because field names and value types vary across tasks. `original_question_json` preserves every original exported field, including source identifiers. All questions have text inputs; there are no referenced image assets. `requirement`, `subtask_name`, and `answer_type` identify evaluation intent and response format.

`model_answer`, `correct`, and `scoring_method` record the completed DeepSeek Flash self-test. `original_selftest_json` retains its full per-question record, including judge output where present. Choice questions use strict letter matching; other answers are judged in a separate DeepSeek Flash call. All 1,430 questions were scored; results were not independently reviewed by humans.

Source pool: HF `General-Level/General-Bench-Openset`, using `nlp` and `image/comprehension`. Generation, transformation, verification, target answering and judging used `deepseek-flash` at `https://api.deepseek.com`, with a 300,000 output-token ceiling and 7,200-second request timeout. Self-test temperature was 0, with 10 workers per requirement. Generation sampling followed the configured baseline; no extra random seed was fixed. Web search was optional and used provider-hosted `gpt-5.6-luna` search via `https://api.fangcunleap.com/azure-gateway/v1`.

The first six successful categories used the eight-requirement batch; mathematics and long-context used separate successful reruns, as identified in `provenance/`. Luna concurrency was 4 for the first batch and mathematics rerun, and 1 for the final long-context run. That long-context run had no API errors or fallback activation. Content filtering was retained as model behavior; three exported long-context questions encountered six search-tool failures due to filtering and continued through the framework's own handling.

Per-requirement provenance includes the verbatim user requirement, subtask schemas, source batch, SHA-256 of the original export, and self-test configuration and scores. `manifest.json` lists checksums of all files in this baseline directory except itself. Existing sibling baselines are separate dataset configurations. Source material remains subject to its original dataset terms; this upload does not assign a new blanket license.
'''
    files["benchmark-agent/README.md"] = readme.encode()
    files["benchmark-agent/provenance/manifest.json"] = (encode({
        "questions": len(rows), "correct": sum(r["correct"] for r in rows),
        "files_sha256": {p: hashlib.sha256(data).hexdigest() for p, data in files.items()},
    }) + "\n").encode()
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    files = build()
    print(f"Validated 1430 questions, 1361 correct, {len(files)} files; original exports match self-test hashes.", flush=True)
    if not args.upload:
        return
    token = getpass.getpass("HF token: ")
    api = HfApi(token=token)
    head = api.repo_info(REPO, repo_type="dataset").sha
    existing = api.list_repo_files(REPO, repo_type="dataset", revision=head)
    if any(p.startswith("benchmark-agent/") for p in existing):
        raise RuntimeError("benchmark-agent already exists; inspect before replacing it")
    root_path = hf_hub_download(REPO, "README.md", repo_type="dataset", revision=head, token=token)
    root = Path(root_path).read_text()
    _, front, body = root.split("---", 2)
    metadata = yaml.safe_load(front)
    assert not any(c["config_name"] == "benchmark-agent" for c in metadata["configs"])
    metadata["configs"].append({"config_name": "benchmark-agent", "data_files": [
        {"split": "test", "path": "benchmark-agent/data/*.jsonl"}]})
    metadata.setdefault("tags", []).append("benchmark-agent")
    lines = body.splitlines()
    table_last = max(i for i, line in enumerate(lines) if line.startswith("|"))
    lines.insert(table_last + 1, "| Benchmark-Agent | 1,430 questions, 8 requirements | `benchmark-agent` | [benchmark-agent/](benchmark-agent/README.md) |")
    body = "\n".join(lines) + '\n\nLoad Benchmark-Agent with `load_dataset("assassinlike/b635", "benchmark-agent", split="test")`.\n'
    files["README.md"] = ("---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---" + body).encode()
    commit = api.create_commit(REPO, repo_type="dataset", parent_commit=head,
        operations=[CommitOperationAdd(path_in_repo=p, path_or_fileobj=data) for p, data in files.items()],
        commit_message="Add 1430 Benchmark-Agent questions from eight completed requirements")
    print("COMMIT", commit.oid, commit.commit_url, flush=True)
    for name, expected in files.items():
        path = hf_hub_download(REPO, name, repo_type="dataset", revision=commit.oid, token=token)
        assert Path(path).read_bytes() == expected, name
    after = set(api.list_repo_files(REPO, repo_type="dataset", revision=commit.oid))
    assert set(existing) <= after
    print(f"Verified all {len(files)} uploaded files byte-for-byte at {commit.oid}; existing files retained.")


if __name__ == "__main__":
    main()
