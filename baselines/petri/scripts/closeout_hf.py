"""Archive supplementary Petri evidence without changing the 240 final records."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distributions
import io
import json
from pathlib import Path
import platform
import re
import subprocess
import tarfile
import zipfile

from dotenv import dotenv_values, load_dotenv
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/hf-closeout"
REPO = "assassinlike/b635"
PREFIX = "petri/closeout/"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    files = set()

    def add(path):
        for p in path.rglob("*") if path.is_dir() else [path]:
            if p.is_file() and not {"__pycache__", ".git", ".env"} & set(p.parts) and p.suffix != ".pyc":
                files.add(p)

    for pattern in ("*.py", "*.sh", "*.md", "*.txt"):
        for path in ROOT.glob(pattern):
            add(path)
    for name in (".gitignore", "backups", "docs", "examples", "inputs", "scripts", "tests", "upstream"):
        add(ROOT / name)
    formal = {"main-deepseek-20260918T202644Z", "main-qwen-target-20260919T050308Z",
              "main-sol-target-20260920T035612Z"}
    for path in (ROOT / "results").iterdir():
        if path.name not in formal | {"hf-export", "hf-closeout"}:
            add(path)
    for name in formal:
        batch = ROOT / "results" / name
        for path in batch.iterdir():
            if path.is_file() or path.name in {"source", "schedulers", "interrupted"}:
                add(path)
    sol = ROOT / "results/main-sol-target-20260920T035612Z"
    rerun = sol / "reruns/20260920T082636Z"
    selected = json.loads((rerun / "config.json").read_text())["selected"]
    for row in selected:
        path = sol / f"requirement-{row['requirement']:02d}" / f"epoch-{row['epoch']:02d}"
        add(path)
        add(path.with_name(path.name + ".console.log"))
    for path in rerun.iterdir():
        if path.is_file() or path.name == "source":
            add(path)
    for name in ("upload-receipt.json", "sol-upload-receipt.json"):
        add(ROOT / "results/hf-export" / name)

    secrets = [value.encode() for key, value in dotenv_values(ROOT / ".env").items()
               if value and any(word in key for word in ("KEY", "TOKEN", "SECRET"))]
    pattern = re.compile(rb"(?<![A-Za-z0-9_-])(?:hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_.-]{20,})")
    examples = set(pattern.findall((ROOT / "upstream/src/petri/solvers/prompts.py").read_bytes()))

    def scan(data, name):
        if any(secret in data for secret in secrets):
            raise ValueError(f"Actual credential in {name}")
        if name.endswith(".eval"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for member in z.namelist():
                    scan(z.read(member), name + ":" + member)
        elif name.endswith(".tar.gz"):
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                for member in t.getmembers():
                    if member.isfile():
                        scan(t.extractfile(member).read(), name + ":" + member.name)
        elif set(pattern.findall(data)) - examples:
            raise ValueError(f"Unreviewed token-like string in {name}")

    environment = {"python": platform.python_version(), "platform": platform.platform(),
                   "workspace_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                   "packages": sorted({f"{d.metadata['Name']}=={d.version}" for d in distributions()})}
    readme = """Petri supplementary closeout archive

The final dataset remains 240 audits: 80 each for DeepSeek Flash, Qwen3.8-27B and GPT-5.6-Sol. This archive contains supplementary evidence, not additional benchmark rows.

Paths inside petri/ retain the local project layout. Included are current external adapters and scripts; full upstream source, LICENSE, pyproject.toml and uv.lock; installed-package versions; original scoring backup and restore instructions; interface probes, test code and results; pilot runs; Qwen interrupted attempts; the stopped initial GPT batch with its backed-up Inspect SQLite logs; and the seven original GPT attempts replaced by complete reruns. Batch source snapshots and metadata preserve historical configurations. Successful final audit packages remain under petri/artifacts/ in the dataset and are not duplicated here.

For the final GPT results use provenance/gpt-5.6-sol/attempts.json and the main data index. The seven superseded attempts remain evidence of missing scores or provider failures; do not count them as additional results or combine their judgments with the new trajectories. Pilots and interrupted attempts are also excluded from the 240 rows. This collection preserves available historical evidence; it does not imply that every failed request has a returned model response or complete token usage.

Use historical source snapshots for reproducing each experiment; the project files in this archive reflect the final workspace. setup.sh uses upstream/uv.lock plus the extra packages listed in that script. environment.json records all installed package versions, including the upload dependency. API keys must be supplied separately. Original scripts expect the EvaluationClaw repository layout, Git metadata and user-inputs.txt; the four exact evaluation requirements are included in inputs/. Paths in old configurations are historical local paths and must be relocated on another machine. The native restore commands are documented in backups/README.md.

Actual credentials, virtual environments, caches and temporary files are excluded. Published synthetic credential examples in Petri prompts remain intact. SHA256SUMS checks the archive and manifest; manifest.json also lists every archive member and its hash. No models were called to create this archive.
"""
    generated = {"petri/environment.json": (json.dumps(environment, indent=2) + "\n").encode(),
                 "petri/CLOSEOUT.md": readme.encode()}
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "final_records": 240,
                "superseded_gpt_epochs": selected, "files": {}}
    with tarfile.open(OUT / "petri-closeout.tar.gz", "w:gz") as archive:
        entries = [("petri/" + str(p.relative_to(ROOT)), p.read_bytes()) for p in sorted(files)]
        for name, data in [*entries, *generated.items()]:
            scan(data, name)
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            archive.addfile(info, io.BytesIO(data))
            manifest["files"][name] = {"bytes": len(data), "sha256": digest(data)}
    (OUT / "README.md").write_text(readme)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with tarfile.open(OUT / "petri-closeout.tar.gz") as archive:
        assert set(archive.getnames()) == set(manifest["files"])
        for member in archive.getmembers():
            assert digest(archive.extractfile(member).read()) == manifest["files"][member.name]["sha256"]
    (OUT / "SHA256SUMS").write_text("".join(f"{digest((OUT / name).read_bytes())}  {name}\n"
                                           for name in ("README.md", "manifest.json", "petri-closeout.tar.gz")))
    print(json.dumps({"files": len(manifest["files"]), "archive_bytes": (OUT / "petri-closeout.tar.gz").stat().st_size,
                      "verification": "All members scanned and hash-verified"}), flush=True)


def upload():
    load_dotenv(ROOT / ".env", override=True)
    api = HfApi()
    head = api.repo_info(REPO, repo_type="dataset").sha
    before = api.list_repo_tree(REPO, repo_type="dataset", revision=head, recursive=True)
    protected = {p.path: p.blob_id for p in before if p.path.startswith(("petri/data/", "petri/artifacts/"))
                 and hasattr(p, "blob_id")}
    def remote(name):
        return Path(hf_hub_download(REPO, name, repo_type="dataset", revision=head)).read_text()
    readme = remote("petri/README.md")
    readme += "\nSupplementary reproducibility and attempt-history evidence: [closeout archive](closeout/README.md). These files do not add benchmark rows.\n"
    hashes = dict((line.split("  ", 1)[1], line.split("  ", 1)[0])
                  for line in remote("petri/SHA256SUMS").splitlines())
    payloads = {PREFIX + name: (OUT / name).read_bytes()
                for name in ("README.md", "manifest.json", "SHA256SUMS", "petri-closeout.tar.gz")}
    payloads["petri/README.md"] = readme.encode()
    for name, data in payloads.items():
        hashes[name.removeprefix("petri/")] = digest(data)
    payloads["petri/SHA256SUMS"] = "".join(f"{value}  {name}\n" for name, value in sorted(hashes.items())).encode()
    commit = api.create_commit(REPO, repo_type="dataset", parent_commit=head,
        commit_message="Archive Petri environment, validation and superseded attempts",
        operations=[CommitOperationAdd(path_in_repo=name, path_or_fileobj=data) for name, data in payloads.items()])
    receipt = {"repo_id": REPO, "commit": commit.oid, "url": commit.commit_url, "parent": head}
    (OUT / "upload-receipt.json").write_text(json.dumps(receipt, indent=2))
    after = api.list_repo_tree(REPO, repo_type="dataset", revision=commit.oid, recursive=True)
    actual = {p.path: p.blob_id for p in after if p.path in protected and hasattr(p, "blob_id")}
    assert actual == protected
    for name, data in payloads.items():
        path = hf_hub_download(REPO, name, repo_type="dataset", revision=commit.oid)
        assert digest(Path(path).read_bytes()) == digest(data)
    receipt["verification"] = "All six uploaded files downloaded and hash-matched; 240 artifact blobs and three indexes unchanged"
    (OUT / "upload-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "upload"))
    args = parser.parse_args()
    prepare() if args.action == "prepare" else upload()
