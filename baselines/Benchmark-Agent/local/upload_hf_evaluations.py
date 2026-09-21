"""Publish completed model evaluations linked to the existing HF questions."""

import argparse
from collections import Counter
import getpass
import hashlib
import json
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = "assassinlike/b635"
PREFIX = "benchmark-agent/evaluations"
RUNS = {
    "qwen3.8-27b": ("qwen3_8_27b_20260918", 1349),
    "gpt-5.6-sol-default": ("gpt_5_6_sol_20260918", 1317),
    "gpt-5.6-sol-high": ("gpt_5_6_sol_high_sudocode_20260919", 1363),
}


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def build(api, head, token):
    def remote(name):
        return Path(hf_hub_download(REPO, name, repo_type="dataset", revision=head, token=token)).read_bytes()

    files, summaries, questions = {}, {}, {}
    for run_id, (directory, expected_correct) in RUNS.items():
        root = ROOT / "cache" / directory
        config = json.loads((root / "config.json").read_text())
        results = json.loads((root / "results.json").read_text())
        state = json.loads((root / "status.json").read_text())
        assert len(results) == 1430 and all(r["status"] == "scored" for r in results)
        assert sum(r["correct"] for r in results) == expected_correct
        for topic, source in config["sources"].items():
            source_path = ROOT / "cache" / source["batch"] / "user_queries" / f"{topic}_200" / "evaluation.json"
            raw = source_path.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == source["evaluation_sha256"]
            local = json.loads(raw)
            assert local == json.loads((root / topic / "evaluation.json").read_text())
            task = "mathematics" if topic == "math" else topic.replace("_", "-")
            if topic not in questions:
                questions[topic] = [json.loads(line) for line in remote(f"benchmark-agent/data/{task}.jsonl").splitlines()]
            published = questions[topic]
            assert len(local) == len(published) == source["count"]
            for index, (item, row) in enumerate(zip(local, published)):
                assert row["question_index"] == index
                assert json.loads(row["original_question_json"]) == item
                assert json.loads(row["reference_output_json"]) == item["sample"]["output"]
        rows, seen, topics = [], set(), {}
        for result in results:
            topic, index = result["topic"], result["index"]
            assert (topic, index) not in seen
            seen.add((topic, index))
            assert result == json.loads((root / topic / "items" / f"{index:04d}.json").read_text())
            question = questions[topic][index]
            assert result["reference"] == json.loads(question["reference_output_json"])
            assert result["subtask_id"] == question["subtask_id"]
            assert result["dataset_id"] == question["dataset_id"]
            assert type(result["correct"]) is bool
            rows.append({
                "id": f"{run_id}/{question['id']}", "run_id": run_id,
                "question_id": question["id"], "task": question["task"],
                "question_index": index, "model": config["answer"]["model"],
                "model_answer": result["prediction"], "correct": result["correct"],
                "score": int(result["correct"]), "scoring_method": result["method"],
                "reference_output_json": question["reference_output_json"],
                "judge_reason": result.get("judge_reason", ""),
                "original_evaluation_json": encode(result),
            })
            entry = topics.setdefault(topic, {"questions": 0, "correct": 0})
            entry["questions"] += 1
            entry["correct"] += int(result["correct"])
        for topic, entry in topics.items():
            assert entry["questions"] == state["by_topic"][topic]["scored"]
            assert entry["correct"] == state["by_topic"][topic]["correct"]
            entry["accuracy"] = entry["correct"] / entry["questions"]
        files[f"{PREFIX}/data/{run_id}.jsonl"] = ("\n".join(map(encode, rows)) + "\n").encode()
        files[f"{PREFIX}/configs/{run_id}.json"] = (encode(config) + "\n").encode()
        summaries[run_id] = {"source_directory": directory, "questions": len(rows),
            "correct": expected_correct, "accuracy": expected_correct / len(rows),
            "scoring_methods": dict(Counter(r["scoring_method"] for r in rows)), "by_topic": topics}
    files[f"{PREFIX}/summary.json"] = (json.dumps(summaries, ensure_ascii=False, indent=2) + "\n").encode()
    readme = '''# Benchmark-Agent model evaluations

Three completed evaluations of the same 1,430 questions, including successful recovery of the previously unscored Sol items. Original questions and DeepSeek self-test records remain in the `benchmark-agent` configuration.

| Run | Correct | Accuracy |
| --- | ---: | ---: |
| qwen3.8-27b | 1349 / 1430 | 94.34% |
| gpt-5.6-sol-default | 1317 / 1430 | 92.10% |
| gpt-5.6-sol-high | 1363 / 1430 | 95.31% |

```python
import json
from datasets import load_dataset
answers = load_dataset("assassinlike/b635", "benchmark-agent-evaluations", split="test")
questions = load_dataset("assassinlike/b635", "benchmark-agent", split="test")
detail = json.loads(answers[0]["original_evaluation_json"])
```

Join `question_id` to the questions' `id`. `run_id` distinguishes the three evaluations; each question has one record per run. `model_answer` is the candidate answer, while `reference_output_json` is the framework's reference answer. `score` is 1 for correct and 0 for incorrect. `scoring_method` identifies exact option-letter matching or a separate DeepSeek Flash judgment. `judge_reason` is empty for deterministic scoring. `original_evaluation_json` preserves the final local record, including full answer and judge API responses, returned reasoning content and token usage where available. Missing reasoning fields do not establish that thinking was disabled.

Qwen explicitly enabled thinking and omitted reasoning_effort and thinking_budget; the official documented defaults are xhigh and 131072. Sol default used RightAPI without an explicit effort parameter; the user reports a medium default, which the saved responses do not confirm. Sol high used https://api.sudorelay.com/v1 with explicit reasoning_effort=high, eight workers and a 45 RPM limit including retries. Both endpoint and effort changed between the Sol runs, so differences cannot be attributed solely to effort. Exact request parameters, judge prompts, source hashes and endpoints are in configs/. Per-requirement scores are in summary.json. Qwen default documentation: https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions .

These files contain final scored records, not a complete transport retry or billing ledger. No questions, references or original scores were revised for publication.
'''
    files[f"{PREFIX}/README.md"] = readme.encode()
    files[f"{PREFIX}/manifest.json"] = (encode({"questions_revision": head, "records": 4290,
        "files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}) + "\n").encode()
    root = remote("README.md").decode()
    _, front, body = root.split("---", 2)
    metadata = yaml.safe_load(front)
    assert not any(c["config_name"] == "benchmark-agent-evaluations" for c in metadata["configs"])
    metadata["configs"].append({"config_name": "benchmark-agent-evaluations",
        "data_files": [{"split": "test", "path": f"{PREFIX}/data/*.jsonl"}]})
    body += "\nBenchmark-Agent Qwen and Sol answers and scores: [evaluations](benchmark-agent/evaluations/README.md), configuration `benchmark-agent-evaluations` (4,290 records).\n"
    files["README.md"] = ("---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---" + body).encode()
    secrets = [v for k, v in dotenv_values(ROOT / ".env").items()
               if v and ("KEY" in k or "TOKEN" in k)] + [token]
    for name, data in files.items():
        if any(secret and secret.encode() in data for secret in secrets):
            raise ValueError(f"Credential found in upload artifact: {name}")
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    token = getpass.getpass("HF token: ")
    api = HfApi(token=token)
    head = api.repo_info(REPO, repo_type="dataset").sha
    before = {p.path: p.blob_id for p in api.list_repo_tree(REPO, repo_type="dataset", revision=head, recursive=True)
              if hasattr(p, "blob_id")}
    if any(name.startswith(PREFIX + "/") for name in before):
        raise RuntimeError("Evaluations already exist; inspect before replacing")
    files = build(api, head, token)
    output = ROOT / "cache/hf_evaluations_20260919"
    for name, data in files.items():
        path = output / "files" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Validated 4290 scored records against published questions; {len(files)} files, {sum(map(len, files.values()))} bytes.", flush=True)
    if not args.upload:
        return
    commit = api.create_commit(REPO, repo_type="dataset", parent_commit=head,
        operations=[CommitOperationAdd(path_in_repo=name, path_or_fileobj=data) for name, data in files.items()],
        commit_message="Add Qwen and both Sol evaluations for all 1430 Benchmark-Agent questions")
    receipt = {"commit": commit.oid, "url": commit.commit_url, "parent": head, "records": 4290,
               "files": list(files), "verified": False}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("COMMIT", commit.oid, commit.commit_url, flush=True)
    for name, expected in files.items():
        path = hf_hub_download(REPO, name, repo_type="dataset", revision=commit.oid, token=token)
        assert Path(path).read_bytes() == expected, name
    after = {p.path: p.blob_id for p in api.list_repo_tree(REPO, repo_type="dataset", revision=commit.oid, recursive=True)
             if hasattr(p, "blob_id")}
    assert all(after.get(name) == blob for name, blob in before.items() if name != "README.md")
    receipt["verified"] = True
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("Verified all uploaded bytes and preserved existing question files.", flush=True)


if __name__ == "__main__":
    main()
