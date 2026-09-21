"""Export and publish the 120 frozen AutoControl Arena environments."""

import argparse
import ast
from collections import Counter
import getpass
import hashlib
import json
from pathlib import Path

import yaml
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/rerun-200-20260918-145824"
GENERATION = ROOT / "results/baseline-user-inputs-20260918-104821"
EXPORT = ROOT / "results/hf-export"
REPO = "assassinlike/b635"
PREFIX = "autocontrol-arena"
FIELDS = {"design.json": "design_json", "snapshot.json": "snapshot_json",
          "environment.py": "environment_code", "metadata.json": "metadata_json"}


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build():
    manifest = json.loads((SOURCE / "manifest.json").read_bytes())
    generation = json.loads((GENERATION / "manifest.json").read_bytes())
    groups, provenance = {}, []
    for item in sorted(manifest["items"], key=lambda item: item["id"]):
        line = int(item["id"].split("_")[2])
        row = {"id": f"{PREFIX}/{item['id']}", "source_id": item["id"],
               "requirement_line": line, "requirement": item["user_intent"]}
        for filename, field in FIELDS.items():
            raw = (SOURCE / item["environment"] / filename).read_bytes()
            assert sha(raw) == item["sha256"][filename], (item["id"], filename)
            row[field] = raw.decode("utf-8")
            assert row[field].encode("utf-8") == raw
        design = json.loads(row["design_json"])
        assert design["user_intent"] == row["requirement"]
        row["system_prompt"] = design["target_model_config"]["system_prompt"]
        row["task_description"] = design["target_model_config"]["task_description"]
        row["files_sha256_json"] = json.dumps(item["sha256"], sort_keys=True)
        groups.setdefault(line, []).append(row)
        provenance.append({"id": row["id"], "files_sha256": item["sha256"]})
    assert Counter({line: len(rows) for line, rows in groups.items()}) == Counter(
        {line: 20 for line in [5, 10, 11, 12, 14, 15]})
    assert len({item["id"] for item in provenance}) == 120
    files = {}
    for line, rows in groups.items():
        files[f"{PREFIX}/data/user_input_{line:02d}.jsonl"] = (
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode()
    for name in ["hyperparameters.yaml", "model.yaml", "requirements.lock", "revision.txt"]:
        files[f"{PREFIX}/config/{name}"] = (SOURCE / "config" / name).read_bytes()
    prompt_source = (SOURCE / "config/judge-prompts.py").read_text(encoding="utf-8-sig")
    prompt = next(ast.literal_eval(node.value) for node in ast.parse(prompt_source).body
                  if isinstance(node, ast.Assign) and any(
                      isinstance(t, ast.Name) and t.id == "UNIFIED_MONITOR_PROMPT" for t in node.targets))
    files[f"{PREFIX}/config/requirement-judge.txt"] = prompt.encode()
    files[f"{PREFIX}/config/native-judge.txt"] = (
        ROOT / "results/native-scores-20260918-185656/config/native-unified.txt").read_bytes()
    files[f"{PREFIX}/config/environment_model.py"] = (ROOT / "local/environment_model.py").read_bytes()
    files[f"{PREFIX}/provenance/experiment.json"] = encode({
        "upstream": "https://github.com/CosmosYi/AutoControl-Arena",
        "upstream_revision": "4a3b91d68d6401673898f6d0580a922f6e49056f",
        "generation_run": GENERATION.name, "environment_source_run": SOURCE.name,
        "generation": generation["configuration"],
        "evaluation": {k: manifest[k] for k in ["max_steps", "timeout_seconds",
            "hard_timeout_seconds", "max_workers", "profile", "seed"]},
        "requirements": [{"line": line, "count": 20, "requirement": rows[0]["requirement"]}
                         for line, rows in groups.items()],
        "environments": provenance,
    })
    files[f"{PREFIX}/README.md"] = README.encode()
    # Compare real local credentials without printing them or including .env in the export.
    from dotenv import dotenv_values
    secrets = [v.encode() for k, v in dotenv_values(ROOT / ".env").items()
               if v and len(v) >= 16 and ("KEY" in k.upper() or "TOKEN" in k.upper())]
    for name, data in files.items():
        assert not any(secret in data for secret in secrets), f"Credential found in {name}"
    files[f"{PREFIX}/provenance/manifest.json"] = encode({
        "questions": 120, "requirements": 6,
        "files_sha256": {name: sha(data) for name, data in files.items()},
    })
    for name, data in files.items():
        path = EXPORT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Validated 120 questions, 480 original file hashes, {len(files)} export files.", flush=True)
    return files


README = '''# AutoControl Arena

120 frozen agent evaluation environments: 20 for each of requirements 5, 10, 11, 12, 14 and 15 from EvaluationClaw. These are the exact environments used for the 200-step DeepSeek Flash and Qwen3.8-27b evaluations. All 120 are included regardless of a target model's completion or scoring status. Target answers, trajectories and scores are not part of this question export.

The six requirements assess adaptation to lost resources, honest progress reporting, least privilege, handling conflicting instructions in task materials, honest retrospective reporting, and separating harmful sub-goals from legitimate work. Each record includes its verbatim evaluation requirement.

```python
import hashlib
import json
from pathlib import Path
from datasets import load_dataset

questions = load_dataset("assassinlike/b635", "autocontrol-arena", split="test")
for question in questions:
    directory = Path("environments") / question["source_id"]
    directory.mkdir(parents=True, exist_ok=True)
    hashes = json.loads(question["files_sha256_json"])
    for filename, field in {
        "design.json": "design_json", "snapshot.json": "snapshot_json",
        "environment.py": "environment_code", "metadata.json": "metadata_json",
    }.items():
        raw = question[field].encode("utf-8")
        assert hashlib.sha256(raw).hexdigest() == hashes[filename]
        (directory / filename).write_bytes(raw)
```

The four string fields preserve the original files byte-for-byte. `design_json` contains task instructions, scenario design, initial state and evaluation criteria. `snapshot_json` contains tool schemas and the prepared state; `environment_code` implements the environment, including dynamic responses; `metadata_json` records generation metadata. `system_prompt` and `task_description` are convenient projections of the original design, not replacements for the full environment. The requirement and hidden criteria are evaluator information, not additional target instructions.

Restore the files and supply the directory to AutoControl Arena's `--env-path`, with `--intent` set to the record's `requirement`. Set stress, temptation and complexity to 1. Run one fresh interaction per environment with a 200-step ceiling, 21,600-second scenario timeout and 25,200-second process limit. Context management is off and the framework/tool error limit is 3. The saved environments are reused without calling the architect, coder or reviewer. Running them requires the AutoControl Arena framework and model API credentials; downloading this dataset does not execute the environments.

Generation used `deepseek-flash` for all roles, temperature 0.7, max_tokens 300000, stress/temptation/complexity 1, empty optional design/technical/risk specifications, code review enabled, and review/repair budgets 1/2/5. Environment reuse was disabled during construction. The initial run had a 60-step interaction limit; the subsequent 200-step evaluations reused unchanged environment files. No random seed was configured. Thinking and reasoning effort were not explicitly sent; DeepSeek's documented defaults were enabled/high. Live environment responses and model outputs remain stochastic.

`config/` contains the full runtime hyperparameters, DeepSeek profile (credential placeholder only), dependency lock and judge prompt templates. The primary unified judge evaluates the original user requirement, producing action/reasoning shortcoming scores from 0 to 4, higher being worse. The optional native judge separately scores action/reasoning safety risk and intent; it does not score helpfulness or task success. Templates are formatted by AutoControl Arena using the saved design and the newly collected trajectory.

Environment auxiliary model calls and judging use DeepSeek Flash even when the target is another model. `config/environment_model.py` is the local adapter used to select this auxiliary model independently. The Qwen target used max_tokens 131072; DeepSeek roles used 300000. These are evaluation settings, not changes to question content.

Framework: https://github.com/CosmosYi/AutoControl-Arena at upstream revision `4a3b91d68d6401673898f6d0580a922f6e49056f`, with the requirement-oriented judge adaptation described above. `provenance/experiment.json` records source run identifiers, requirements, settings and all 480 original file hashes. `provenance/manifest.json` checksums this export except itself. No new blanket license is assigned to upstream code or generated material.
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    files = build()
    if not args.upload:
        return
    token = getpass.getpass("HF token: ")
    api = HfApi(token=token)
    head = api.repo_info(REPO, repo_type="dataset").sha
    before = {f.path: f.blob_id for f in api.list_repo_tree(REPO, repo_type="dataset",
              revision=head, recursive=True) if hasattr(f, "blob_id")}
    assert not any(p.startswith(PREFIX + "/") for p in before), "Inspect existing export before replacing it"
    root = Path(hf_hub_download(REPO, "README.md", repo_type="dataset", revision=head,
                               token=token, cache_dir=ROOT / ".cache/huggingface")).read_text()
    _, front, body = root.split("---", 2)
    metadata = yaml.safe_load(front)
    assert not any(c["config_name"] == PREFIX for c in metadata["configs"])
    metadata["configs"].append({"config_name": PREFIX,
                              "data_files": [{"split": "test", "path": f"{PREFIX}/data/*.jsonl"}]})
    metadata.setdefault("tags", []).append(PREFIX)
    lines = body.splitlines()
    index = max(i for i, line in enumerate(lines) if line.startswith("|"))
    lines.insert(index + 1, "| AutoControl Arena | 120 environments, 6 requirements × 20 | `autocontrol-arena` | [autocontrol-arena/](autocontrol-arena/README.md) |")
    files["README.md"] = ("---\n" + yaml.safe_dump(metadata, sort_keys=False)
                          + "---" + "\n".join(lines) + "\n").encode()
    commit = api.create_commit(REPO, repo_type="dataset", parent_commit=head,
        operations=[CommitOperationAdd(path_in_repo=p, path_or_fileobj=data) for p, data in files.items()],
        commit_message="Add 120 frozen AutoControl Arena environments across six requirements")
    receipt = {"repo": REPO, "parent_commit": head, "commit": commit.oid,
               "url": commit.commit_url, "questions": 120, "verified": False}
    (EXPORT / "upload.json").write_bytes(encode(receipt))
    print("COMMIT", commit.oid, commit.commit_url, flush=True)
    for name, expected in files.items():
        path = hf_hub_download(REPO, name, repo_type="dataset", revision=commit.oid,
                               token=token, cache_dir=ROOT / ".cache/huggingface")
        assert Path(path).read_bytes() == expected, name
    after = {f.path: f.blob_id for f in api.list_repo_tree(REPO, repo_type="dataset",
             revision=commit.oid, recursive=True) if hasattr(f, "blob_id")}
    assert all(after.get(p) == blob for p, blob in before.items() if p != "README.md")
    receipt["verified"] = True
    (EXPORT / "upload.json").write_bytes(encode(receipt))
    print(f"Verified {len(files)} remote files byte-for-byte; all existing baseline files unchanged.", flush=True)


if __name__ == "__main__":
    main()
