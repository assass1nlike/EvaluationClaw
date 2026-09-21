"""Package completed Petri main experiments for independent review."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
import zipfile

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "hf-export" / "petri"
BATCHES = {
    "deepseek-flash": "main-deepseek-20260918T202644Z",
    "qwen3.8-27b": "main-qwen-target-20260919T050308Z",
    "gpt-5.6-sol": "main-sol-target-20260920T035612Z/reruns/20260920T082636Z",
}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=BATCHES, default=list(BATCHES))
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    secrets = [value.encode() for key, value in dotenv_values(ROOT / ".env").items()
               if value and any(word in key for word in ("KEY", "TOKEN", "SECRET"))]
    manifest_path = OUTPUT / "provenance/manifest.json"
    manifest = (json.loads(manifest_path.read_text()) if manifest_path.exists()
                else {"repo_id": "assassinlike/b635", "records": 0, "batches": {}})
    token_pattern = re.compile(rb"(?<![A-Za-z0-9_-])(?:hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_.-]{20,})")
    # Petri's published prompt contains a synthetic credential example.
    example_keys = set(token_pattern.findall((ROOT / "upstream/src/petri/solvers/prompts.py").read_bytes()))
    scanned = 0

    def checked_bytes(path):
        nonlocal scanned
        data = path.read_bytes()
        contents = [data]
        if path.suffix == ".eval":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                contents.extend(archive.read(name) for name in archive.namelist())
        for content in contents:
            if any(secret in content for secret in secrets) or set(token_pattern.findall(content)) - example_keys:
                raise ValueError(f"Potential credential in {path}; review before upload")
        scanned += 1
        return data

    def pack(destination, files):
        with tarfile.open(destination, "w:gz") as archive:
            for path, name in files:
                data = checked_bytes(path)
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o644
                archive.addfile(info, io.BytesIO(data))

    (OUTPUT / "data").mkdir(exist_ok=True)
    (OUTPUT / "provenance").mkdir(exist_ok=True)
    for model in args.models:
        batch_name = BATCHES[model]
        batch = ROOT / "results" / batch_name
        summary = json.loads((batch / "summary.json").read_text())
        destination = OUTPUT / "artifacts" / model
        destination.mkdir(parents=True, exist_ok=True)
        rows = []
        for requirement in (7, 8, 9, 13):
            records = summary[str(requirement)]["epochs"]
            assert len(records) == 20
            assert [record["seed"] for record in records] == list(range(42, 62))
            for record in records:
                run = (batch / record["output"]).resolve()
                config = json.loads((run / "config.json").read_text())
                result = json.loads((run / "summary.json").read_text())
                judgment = json.loads((run / "judgment.json").read_text())
                native = json.loads((run / "native_judgment.json").read_text())
                assert config["models"]["target"].split("/", 1)[1] == model
                assert config["seed"] == record["seed"]
                assert result["scores"]["performance"] == record["score"]
                assert native["status"] == "scored" and len(native["scores"]) == 23
                assert len(list((run / "transcripts").glob("*.json"))) == 1
                assert len(list((run / "logs").glob("*.eval"))) == 1
                name = f"requirement-{requirement:02d}-epoch-{record['epoch']:02d}.tar.gz"
                path = destination / name
                files = [(file, str(file.relative_to(run))) for file in sorted(run.rglob("*")) if file.is_file()]
                console = run.parent / f"{run.name}.console.log"
                files.append((console, "console.log"))
                pack(path, files)
                rows.append({
                    "id": f"petri/{model}/requirement-{requirement:02d}/epoch-{record['epoch']:02d}",
                    "target_model": model, "auditor_model": "deepseek-flash", "judge_model": "deepseek-flash",
                    "requirement_line": requirement, "requirement": (run / "instruction.txt").read_text().strip(),
                    "epoch": record["epoch"], "seed": record["seed"], "audit_budget": config["max_turns"],
                    "prefill_mode": config["prefill_mode"], "scoring": config["scoring"],
                    "status": result["status"], "exit_code": record["exit_code"],
                    "performance_score": record["score"], "tool_error_count": len(result["tool_errors"]),
                    "judgment_json": json.dumps(judgment, ensure_ascii=False),
                    "native_judgment_json": json.dumps(native, ensure_ascii=False),
                    "tool_errors_json": json.dumps(result["tool_errors"], ensure_ascii=False),
                    "judge_errors_json": json.dumps(result["judge_errors"], ensure_ascii=False),
                    "config_json": json.dumps(config, ensure_ascii=False),
                    "report": (run / "report.md").read_text(),
                    "artifact_path": "petri/" + str(path.relative_to(OUTPUT)),
                    "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
        (OUTPUT / "data" / f"{model}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        provenance = OUTPUT / "provenance" / model
        provenance.mkdir(exist_ok=True)
        for name in ("config.json", "summary.json", "report.md"):
            (provenance / name).write_bytes(checked_bytes(batch / name))
        source_files = [(p, str(p.relative_to(batch))) for p in sorted((batch / "source").rglob("*")) if p.is_file()]
        source_files.extend((p, str(p.relative_to(batch))) for p in sorted((batch / "schedulers").glob("*.py")))
        if (batch / "scheduler.py").exists():
            source_files.append((batch / "scheduler.py", "scheduler.py"))
        pack(provenance / "source.tar.gz", source_files)
        if model == "gpt-5.6-sol":
            rerun_config = json.loads((batch / "config.json").read_text())
            original = Path(rerun_config["original_batch"])
            for name in ("config.json", "summary.json", "report.md"):
                (provenance / ("original-" + name)).write_bytes(checked_bytes(original / name))
            write_json(provenance / "attempts.json", {
                "selection": "Seven epochs missing at least one score were rerun in full; use both new judgments",
                "rerun_epochs": rerun_config["selected"],
                "selected_artifacts": [{"requirement": req, "epoch": rec["epoch"], "seed": rec["seed"],
                                        "source": str((batch / rec["output"]).resolve().relative_to(ROOT))}
                                       for req in (7, 8, 9, 13) for rec in summary[str(req)]["epochs"]],
            })
        manifest["batches"][model] = {"source_batch": batch_name, "records": len(rows),
                                      "tool_error_epochs": sum(row["tool_error_count"] > 0 for row in rows)}
    (OUTPUT / "provenance" / "exps.md").write_bytes(checked_bytes(ROOT / "exps.md"))
    shutil.copy2(__file__, OUTPUT / "provenance" / "export_hf.py")
    manifest["records"] = sum(batch["records"] for batch in manifest["batches"].values())
    manifest["scanned_source_files"] = manifest.get("scanned_source_files", 0) + scanned
    manifest["interrupted_attempts"] = "Excluded; completed epochs retained once, without duplicate seeds"
    write_json(OUTPUT / "provenance" / "manifest.json", manifest)
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
