"""Freeze, launch and audit direct-model benchmark authoring experiments."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import shutil
import subprocess
import sys
import threading
import time

from .batch_config import Settings, evaluation_config, seed_everything
from .batch_gateway import AUTHOR_CLIENT, Gateway, save
from .package import _hashes, load_bundle, pack
from .readiness import prepare


def docker(*args, **kwargs):
    from ..execution.docker import docker_subprocess_env, resolve_docker_executable
    return subprocess.run([resolve_docker_executable("docker"), *args],
        env=docker_subprocess_env("docker"), **kwargs)


def freeze(config, output):
    settings = Settings.model_validate_json(config.read_text())
    # Ensure credentials exist before creating a launchable snapshot, never save them.
    for variable in (settings.author_key_env, settings.evaluation_key_env,
                     settings.task_key_env if settings.task_model else settings.evaluation_key_env,
                     settings.laaj_key_env if settings.laaj_model else settings.evaluation_key_env,
                     *(key for pool in settings.key_pools.values() for key in pool)):
        if not os.environ.get(variable):
            raise ValueError(f"Missing credential environment variable: {variable}")
    image = docker("image", "inspect", settings.author_image, "--format", "{{.Id}}",
                   capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    version = docker("run", "--rm", "--pull", "never", "--entrypoint", "codex", image, "--version",
                     capture_output=True, text=True, check=True, timeout=60).stdout.strip()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(Path(__file__).parents[1], output / "source/evalclaw",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    save(output / "settings.json", settings.model_dump(mode="json"))
    save(output / "snapshot.json", {"source": _hashes(output / "source"),
        "settings_sha256": hashlib.sha256((output / "settings.json").read_bytes()).hexdigest(),
        "author_image_id": image, "codex_version": version,
        "python": sys.version, "packages": subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze"], text=True).splitlines(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "environment": {key: os.environ.get(key) for key in ("DOCKER_HOST", "EVALCLAW_DOCKER_MIRRORS",
            "EVALCLAW_IMAGE_ROUTES", "EVALCLAW_DOCKER_HTTP_PROXY", "EVALCLAW_DOCKER_HTTPS_PROXY")}})
    shutil.copy2(Path(__file__).with_name("docs") / "EXPERIMENT.md", output / "README.md")
    return settings


def verify_snapshot(root):
    snapshot = json.loads((root / "snapshot.json").read_text())
    if _hashes(root / "source") != snapshot["source"]:
        raise ValueError("Frozen experiment source changed")
    if hashlib.sha256((root / "settings.json").read_bytes()).hexdigest() != snapshot["settings_sha256"]:
        raise ValueError("Frozen experiment settings changed")
    return snapshot


def subprocess_env(root, settings):
    bypass = ",".join(filter(None, [os.environ.get("NO_PROXY", os.environ.get("no_proxy", "")),
                                  settings.gateway_host, *settings.direct_hosts]))
    return {**os.environ, "PYTHONPATH": str(root / "source"), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": str(settings.seed), "NO_PROXY": bypass, "no_proxy": bypass}


def launch(config, output):
    settings = freeze(config, output)
    with (output / "batch.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "evalclaw.authoring.batch", "run", str(output)],
            cwd=output, env=subprocess_env(output, settings), stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    save(output / "process.json", {"pid": process.pid, "started": time.time(), "detached": True})
    return {"pid": process.pid, "directory": str(output)}


def author(root, settings, job, gateway, token, image):
    directory = root / job.id
    work = directory / "work"
    work.mkdir(parents=True)
    source = Path(__file__).with_name("docs")
    for name in ("DELIVERY.md", "INTERFACES.md"):
        shutil.copy2(source / name, work / name)
    shutil.copy2(Path(__file__).with_name("benchmark_io.py"), work / "benchmark_io.py")
    (work / "benchmark-package").write_text(AUTHOR_CLIENT)
    (work / "benchmark-package").chmod(0o755)
    prompt = (f"{job.goal}\n\nCreate exactly {job.count} tasks. Deliver in /work/package. "
        "Read DELIVERY.md first; consult INTERFACES.md as needed. "
        "benchmark-package is on PATH: check, prepare and exercise use the operator's isolated runtime. "
        "Put program interface call cases in /work/package/cases.json and exercise them before finishing. "
        "For program-controlled interaction, also include episode cases with scripted target tool calls "
        "and follow-up responses to test the connected interaction without a target model. "
        "Static tasks without programs do not need cases. These checks provide interface feedback only. "
        "Use obtainable images or declare their sources/build files in benchmark.json. "
        "The target uses a native model/tool interface with these supported message roles: "
        + json.dumps(settings.evaluation_model.supported_message_roles) + ". "
        "Do not change the evaluation request to fit a runtime limitation; document any unsupported requirement. "
        "Runtime models and credentials are provided separately. Finish with a brief delivery description.")
    (directory / "prompt.txt").write_text(prompt)
    name = "evalclaw-author-" + secrets.token_hex(8)
    url = f"http://{settings.gateway_host}:{gateway.server_address[1]}"
    command = ["run", "--rm", "--name", name, "--pull", "never", "--memory", f"{settings.author_memory_gib}g",
        "--cpus", str(settings.author_cpus), "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", "HOME=/tmp/author", "-e", "PATH=/work:/usr/local/bin:/usr/bin:/bin",
        "-e", "AUTHOR_TOKEN=" + token, "-e", "AUTHOR_GATEWAY=" + url,
        "-e", f"PYTHONHASHSEED={settings.seed}", "-v", f"{work}:/work",
        "-v", f"{work / 'benchmark-package'}:/usr/local/bin/benchmark-package:ro", "-w", "/work",
        "--entrypoint", "codex", image, "exec", "--ignore-user-config", "--skip-git-repo-check",
        "--ephemeral", "--dangerously-bypass-approvals-and-sandbox", "--json", "-m", settings.author_model,
        "-c", "model_provider=experiment", "-c", "model_providers.experiment.name=experiment",
        "-c", f'model_providers.experiment.base_url="{url}/v1"', "-c", "model_providers.experiment.env_key=AUTHOR_TOKEN",
        "-c", "model_providers.experiment.wire_api=responses", "-c", f"model_reasoning_effort={settings.author_effort}",
        "-c", "features.multi_agent=false", prompt]
    started = time.time()
    save(directory / "status.json", {"stage": "authoring", "started": started, "container": name})
    result = {"requested": job.count, "timed_out": False}
    try:
        with (directory / "codex.jsonl").open("w") as out, (directory / "stderr.log").open("w") as err:
            result["exit_code"] = docker(*command, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                         timeout=settings.author_timeout_seconds).returncode
    except subprocess.TimeoutExpired:
        result.update(timed_out=True, exit_code=None)
    finally:
        docker("rm", "-f", name, capture_output=True, timeout=60)
        result["seconds"] = time.time() - started
    try:
        suite = pack(work / "package", directory / "bundle")
        result.update(task_ids=[t.id for t in suite.tasks], generated=len(suite.tasks),
                      count_matches=len(suite.tasks) == job.count)
    except Exception as exc:
        result["conversion_error"] = f"{type(exc).__name__}: {exc}"
    save(directory / "author-result.json", result)
    save(directory / "status.json", {"stage": "authored", **result})
    return result


def evaluate(root, settings, job):
    from ..execution.contract_capabilities import binding_issues
    from ..execution.memory_budget import memory_budget
    from ..execution.runner import run_eval
    from ..quality.laaj import evaluate_with_laaj
    from ..types import QcReport
    directory = root / job.id
    out = directory / "evaluation"
    out.mkdir()
    config = evaluation_config(settings, out, bindings=json.loads(os.environ.get("EVALCLAW_AUTHORING_BINDINGS", "{}")))
    suite = load_bundle(directory / "bundle")
    config.laaj_sample_size = min(settings.laaj_sample_size or len(suite.tasks), len(suite.tasks))
    save(directory / "status.json", {"stage": "preparing"})
    issues = {task.id: binding_issues(task, config, config.targets[0]) for task in suite.tasks}
    save(out / "binding-issues.json", issues)
    try:
        images = prepare(directory / "bundle", suite, bind=True)
        save(out / "images.json", images)
        save(out / "prepared-suite.json", suite.model_dump(mode="json"))
    except Exception as exc:
        save(out / "preparation-error.json", {"error": f"{type(exc).__name__}: {exc}"})
        raise
    cases_file = directory / "bundle/original/cases.json"
    if cases_file.exists():
        from .readiness import exercise
        save(out / "interface-tests.json", exercise(suite, json.loads(cases_file.read_text()), config=config))
    else:
        save(out / "interface-tests.json", {"status": "not_supplied"})
    accepted = [t.id for t in suite.tasks if not issues[t.id]]
    run = None
    with memory_budget(config, out):
        if accepted:
            save(directory / "status.json", {"stage": "running", "accepted": len(accepted)})
            run = run_eval(suite, QcReport(passed_item_ids=accepted, summary="No semantic QC or task repair"),
                           config, trace_dir=out / "run")
            save(out / "run.json", run.model_dump(mode="json"))
        save(directory / "status.json", {"stage": "quality"})
        selected = random.Random(settings.seed).sample(sorted(suite.tasks, key=lambda t: t.id), config.laaj_sample_size)
        selected_ids = {task.id for task in selected}
        quality_suite = suite.model_copy(update={"tasks": [t for t in suite.tasks if t.id in selected_ids]})
        save(out / "laaj-sampling.json", {"strategy": "uniform_without_replacement", "seed": settings.seed,
            "total_items": len(suite.tasks), "sample_size": len(selected),
            "item_ids": [t.id for t in quality_suite.tasks]})
        quality = evaluate_with_laaj(suite.objective, quality_suite, None, config, run=run,
                                    artifact_dir=out, trace_dir=out / "laaj")
        quality.total_item_count = len(suite.tasks)
        save(out / "laaj.json", quality.model_dump(mode="json"))
    results = run.results if run else []
    valid = [r for r in results if not r.error]
    summary = {"stage": "completed", "requested": job.count, "generated": len(suite.tasks),
        "unsupported": sum(bool(errors) for errors in issues.values()), "attempted": len(results),
        "execution_errors": sum(bool(r.error) for r in results), "valid_scored": len(valid),
        "mean_score_valid_only": sum(r.score for r in valid) / len(valid) if valid else None,
        "quality_errors": quality.item_errors, "overall_quality_error": quality.overall_error}
    save(directory / "status.json", summary)
    return summary


def evaluate_process(root, settings, job, bindings):
    with (root / job.id / "evaluation.log").open("w") as log:
        process = subprocess.run([sys.executable, "-m", "evalclaw.authoring.batch", "evaluate", str(root), job.id],
            cwd=root, env={**subprocess_env(root, settings), "EVALCLAW_AUTHORING_BINDINGS": json.dumps(bindings)},
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        status = json.loads((root / job.id / "status.json").read_text())
        if status.get("stage") != "failed":
            save(root / job.id / "status.json", {"stage": "failed", "evaluation_exit_code": process.returncode,
                                                "last_stage": status})
    return json.loads((root / job.id / "status.json").read_text())


def preflight(root, settings, bindings):
    from ..models.llm import call_target_model_with_tools, call_orchestrator_with_tools
    from ..models.roles import role_model_settings
    from ..protocols.tool import ToolSpec, ToolResult
    from ..quality.laaj import _append_tool_results
    config = evaluation_config(settings, root, bindings=bindings)
    tools = [ToolSpec(name="check_connection", description="Check the test connection.")]
    checks = {}
    for role, model in (("target", config.targets[0]), ("task", config.task_models[0]), ("laaj", None)):
        messages = [{"role": "user", "content": "Call check_connection exactly once with no arguments, then report its result."}]
        options = {"trace_dir": root / "preflight", "trace_name": role, "max_tokens": 4096}
        def call():
            if model is None:
                return call_orchestrator_with_tools(messages, tools=tools,
                    **role_model_settings(config, "laaj").call_kwargs(), **options)
            return call_target_model_with_tools(messages, model, tools, timeout_s=180, **options)
        response = call()
        if len(response.tool_calls) != 1 or response.tool_calls[0].name != "check_connection":
            raise RuntimeError(f"{role} preflight did not return the requested native tool call")
        _append_tool_results(messages, response, [ToolResult(tool_call_id=response.tool_calls[0].id,
                            name="check_connection", content="Connection successful.")])
        options["trace_name"] = role + "-result"
        final = call()
        if final.tool_calls or not final.content.strip():
            raise RuntimeError(f"{role} preflight could not finish after receiving a tool result")
        checks[role] = {"status": "passed", "model": model.model if model else config.laaj_model,
                        "adapter": response.adapter, "tool": response.tool_calls[0].name}
    save(root / "preflight/result.json", checks)


def run(root, settings, snapshot):
    tokens = {secrets.token_urlsafe(32): job.id for job in settings.jobs}
    gateway = Gateway(root, settings, tokens)
    threading.Thread(target=gateway.serve_forever, daemon=True).start()
    evaluations, authors = {}, {}
    try:
        preflight(root, settings, gateway.evaluation_bindings("preflight"))
        bindings = {job.id: gateway.evaluation_bindings(job.id) for job in settings.jobs}
        with ThreadPoolExecutor(settings.evaluation_workers) as evaluators, ThreadPoolExecutor(settings.author_workers) as workers:
            pending = {workers.submit(author, root, settings, job, gateway,
                next(token for token, name in tokens.items() if name == job.id), snapshot["author_image_id"]): job for job in settings.jobs}
            for future in as_completed(pending):
                job = pending[future]
                try:
                    result = future.result()
                    authors[job.id] = result
                    if "task_ids" in result:
                        evaluations[job.id] = evaluators.submit(evaluate_process, root, settings, job, bindings[job.id])
                except Exception as exc:
                    authors[job.id] = {"requested": job.count, "error": f"{type(exc).__name__}: {exc}"}
                    save(root / job.id / "status.json", {"stage": "failed", **authors[job.id]})
            save(root / "author-summary.json", authors)
            results = {job: future.result() for job, future in evaluations.items()}
        save(root / "summary.json", {"requested": sum(j.count for j in settings.jobs), "authors": authors,
                                      "evaluations": results, "finished": time.time()})
    finally:
        gateway.shutdown()
        gateway.server_close()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "freeze"):
        start = sub.add_parser(command, help="Freeze settings and source" + ("; launch detached" if command == "start" else " without launching"))
        start.add_argument("config", type=Path)
        start.add_argument("output", type=Path)
    for command in ("run", "evaluate"):
        child = sub.add_parser(command)
        child.add_argument("directory", type=Path)
        if command == "evaluate":
            child.add_argument("job")
    args = parser.parse_args()
    if args.command == "start":
        print(json.dumps(launch(args.config.resolve(), args.output.resolve())))
        return
    if args.command == "freeze":
        freeze(args.config.resolve(), args.output.resolve())
        print(json.dumps({"status": "frozen", "directory": str(args.output.resolve())}))
        return
    root = args.directory.resolve()
    snapshot = verify_snapshot(root)
    settings = Settings.model_validate_json((root / "settings.json").read_text())
    seed_everything(settings.seed)
    if args.command == "run":
        try:
            run(root, settings, snapshot)
        except Exception as exc:
            save(root / "failure.json", {"error": f"{type(exc).__name__}: {exc}"})
            raise
    else:
        try:
            evaluate(root, settings, next(j for j in settings.jobs if j.id == args.job))
        except Exception as exc:
            save(root / args.job / "status.json", {"stage": "failed", "error": f"{type(exc).__name__}: {exc}"})
            raise


if __name__ == "__main__":
    main()
