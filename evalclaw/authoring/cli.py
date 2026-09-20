"""Structural author feedback and deterministic packaging; no model calls."""
import argparse
import json
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .package import load_bundle, load_package, pack


def main():
    parser = argparse.ArgumentParser(prog="benchmark-package")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Validate interfaces and files, without executing them")
    check.add_argument("directory", type=Path)
    check.add_argument("--config", type=Path, help="Also check declared target bindings")
    prepare = sub.add_parser("prepare", help="Prepare declared Docker dependencies and record image identities")
    prepare.add_argument("directory", type=Path)
    exercise = sub.add_parser("exercise", help="Run author-supplied protocol cases in Docker without target model calls")
    exercise.add_argument("directory", type=Path)
    exercise.add_argument("cases", type=Path, help="JSON list of task/component/calls cases")
    export = sub.add_parser("pack", help="Create a portable, checksummed task bundle")
    export.add_argument("directory", type=Path)
    export.add_argument("output", type=Path)
    kit = sub.add_parser("kit", help="Copy only the author instructions, interface manual and transport helper")
    kit.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "kit":
            args.output.mkdir(parents=True, exist_ok=False)
            source = Path(__file__).parent
            for name in ("DELIVERY.md", "INTERFACES.md"):
                shutil.copy2(source / "docs" / name, args.output / name)
            shutil.copy2(source / "benchmark_io.py", args.output / "benchmark_io.py")
            result = {"status": "copied", "directory": str(args.output)}
        else:
            if args.command == "pack":
                suite = pack(args.directory, args.output)
            else:
                suite = (load_bundle(args.directory) if (args.directory / "conversion.json").exists()
                         else load_package(args.directory))
                if args.command == "prepare":
                    from .readiness import prepare
                    with redirect_stdout(sys.stderr):
                        result = prepare(args.directory, suite)
                    print(json.dumps(result, ensure_ascii=False))
                    return
                if args.command == "exercise":
                    from .readiness import exercise
                    from .package import _json
                    with redirect_stdout(sys.stderr):
                        result = exercise(suite, _json(args.cases))
                    print(json.dumps(result, ensure_ascii=False))
                    if result["status"] != "passed":
                        raise SystemExit(1)
                    return
                if args.config:
                    from ..execution.contract_capabilities import binding_issues
                    from ..types import BenchmarkConfig
                    config = BenchmarkConfig.model_validate_json(args.config.read_text())
                    issues = [{"task": task.id, "target": target.id, "issues": problems}
                              for task in suite.tasks for target in config.targets
                              if (problems := binding_issues(task, config, target))]
                    if issues:
                        print(json.dumps({"status": "unsupported_binding", "issues": issues}, ensure_ascii=False))
                        raise SystemExit(1)
                    unverified = [t.id for t in config.targets if t.supported_message_roles is None]
                    if unverified:
                        print(json.dumps({"status": "unverified_binding", "targets": unverified,
                            "error": "Set supported_message_roles from the target endpoint's capabilities; role support has not been verified."}))
                        raise SystemExit(1)
            result = {"status": "valid", "task_ids": [task.id for task in suite.tasks],
                      "checked": "structure and declared files; not task correctness or executable readiness"}
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
