"""Upload the prepared Petri export and add its dataset configuration."""

import hashlib
import json
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
import yaml


ROOT = Path(__file__).resolve().parents[1]
REPO = "assassinlike/b635"


def main():
    load_dotenv(ROOT / ".env", override=True)
    api = HfApi()
    export = ROOT / "results" / "hf-export" / "petri"
    files = sorted(path for path in export.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    manifest = json.loads((export / "provenance/manifest.json").read_text())
    assert manifest["records"] == 240
    assert len(list((export / "artifacts").glob("*/*.tar.gz"))) == 240
    hashes = {str(path.relative_to(export)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    (export / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in hashes.items()))
    files.append(export / "SHA256SUMS")
    info = api.repo_info(REPO, repo_type="dataset")
    existing = api.list_repo_files(REPO, repo_type="dataset", revision=info.sha)
    remote_hash_file = Path(hf_hub_download(REPO, "petri/SHA256SUMS", repo_type="dataset", revision=info.sha))
    remote_hashes = {line.split("  ", 1)[1]: line.split("  ", 1)[0]
                     for line in remote_hash_file.read_text().splitlines()}
    for name, digest in remote_hashes.items():
        if name.startswith(("artifacts/deepseek-flash/", "artifacts/qwen3.8-27b/", "data/")):
            assert hashes[name] == digest, f"Existing results changed: {name}"
    files = [path for path in files if path.name == "SHA256SUMS"
             or remote_hashes.get(str(path.relative_to(export))) != hashes[str(path.relative_to(export))]]
    readme = Path(hf_hub_download(REPO, "README.md", repo_type="dataset", revision=info.sha)).read_text()
    _, header, body = readme.split("---", 2)
    metadata = yaml.safe_load(header)
    configs = [config for config in metadata["configs"] if config["config_name"] == "petri"]
    assert len(configs) == 1 and configs[0]["data_files"] == [{"split": "test", "path": "petri/data/*.jsonl"}]
    previous = "Petri: 160 complete audits (80 DeepSeek Flash targets and 80 Qwen3.8-27B targets)"
    updated = "Petri: 240 complete audits (80 each for DeepSeek Flash, Qwen3.8-27B, and GPT-5.6-Sol targets)"
    assert previous in body or updated in body
    body = body.replace(previous, updated)
    new_readme = "---\n" + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True) + "---" + body
    operations = [CommitOperationAdd(path_in_repo="petri/" + str(path.relative_to(export)), path_or_fileobj=str(path))
                  for path in files]
    operations.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=new_readme.encode()))
    print(f"Uploading {len(files)} Petri files ({sum(path.stat().st_size for path in files)} bytes)", flush=True)
    commit = api.create_commit(REPO, repo_type="dataset", operations=operations,
                               commit_message="Add 80 GPT-5.6-Sol Petri audits with dual judgments and rerun provenance",
                               parent_commit=info.sha)
    receipt = {"repo_id": REPO, "commit": commit.oid, "url": commit.commit_url,
               "files": len(files), "records": 240, "added_records": 80, "parent_commit": info.sha}
    (ROOT / "results" / "hf-export" / "sol-upload-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    remote = set(api.list_repo_files(REPO, repo_type="dataset", revision=commit.oid))
    assert set(existing).issubset(remote)
    assert all("petri/" + str(path.relative_to(export)) in remote for path in files)
    for name in ("SHA256SUMS", "data/gpt-5.6-sol.jsonl",
                 "artifacts/gpt-5.6-sol/requirement-07-epoch-01.tar.gz",
                 "artifacts/gpt-5.6-sol/requirement-13-epoch-07.tar.gz"):
        path = Path(hf_hub_download(REPO, "petri/" + name, repo_type="dataset", revision=commit.oid))
        assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256((export / name).read_bytes()).digest()
    receipt["verification"] = "All paths present; original model data unchanged; GPT index, checksums, original and rerun packages downloaded and hash-matched"
    (ROOT / "results" / "hf-export" / "sol-upload-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
