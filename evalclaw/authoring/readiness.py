"""Explicit dependency preparation and model-free program conformance checks."""
from contextlib import closing
from pathlib import Path
import subprocess

import jsonschema
from pydantic import Field

from ..execution.components import JsonComponent
from ..execution.component_contract import validate_metrics
from ..execution.docker import docker_subprocess_env, resolve_docker_executable
from ..execution.docker_images import build_docker_image_from_context, build_docker_image_if_requested
from ..execution.image_acquisition import acquire_image, configured_mirrors
from ..protocols.task_definition import Contract, ServiceEnvironment
from .schema import Benchmark


def components(suite):
    for task in suite.tasks:
        if isinstance(task.environment, ServiceEnvironment):
            yield task.id, "environment", task.environment.service
        if task.interaction.controller:
            yield task.id, "controller", task.interaction.controller
        for scorer in task.evaluation.scorers:
            if scorer.component:
                yield task.id, scorer.id, scorer.component
    for aggregate in suite.evaluation_plan:
        if aggregate.component:
            yield "@suite", aggregate.id, aggregate.component


def image_context(root, dependency):
    from .package import _path
    context = _path(root, dependency.context, directory=True)
    dockerfile = _path(root, dependency.dockerfile)
    if not dockerfile.is_relative_to(context):
        raise ValueError("Image dependency Dockerfile must be inside its context")
    return context, dockerfile.relative_to(context).as_posix()


def prepare(directory, suite, *, bind=False):
    # Image aliases are daemon-global. Resolve and pin within one preparation
    # transaction, including across concurrently running evaluation processes.
    import fcntl
    import hashlib
    import os
    import tempfile
    daemon = hashlib.sha256(os.environ.get("DOCKER_HOST", "default").encode()).hexdigest()[:16]
    with (Path(tempfile.gettempdir()) / f"evalclaw-image-prepare-{daemon}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _prepare(directory, suite, bind=bind)


def _prepare(directory, suite, *, bind):
    from .package import _json
    root = Path(directory).resolve()
    if (root / "conversion.json").exists():
        root /= "original"
    manifest = Benchmark.model_validate(_json(root / "benchmark.json"))
    docker = resolve_docker_executable("docker")

    def run(*arguments):
        result = subprocess.run([docker, *arguments], capture_output=True, text=True,
                                timeout=600, env=docker_subprocess_env("docker"))
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout.strip()

    def acquire(image, allow_pull=True):
        resolved = acquire_image(image, allow_pull=allow_pull)
        if not configured_mirrors():
            found = subprocess.run([docker, "image", "inspect", resolved], capture_output=True,
                                  timeout=30, env=docker_subprocess_env("docker"))
            if found.returncode:
                if not allow_pull:
                    raise ValueError(f"Required local image is absent: {image}")
                run("pull", resolved)
        return resolved

    records = []
    for dependency in manifest.images:
        if dependency.source:
            source = acquire(dependency.source)
            run("tag", source, dependency.image)
        else:
            context, filename = image_context(root, dependency)
            build_docker_image_from_context(context, dockerfile_name=filename, tag=dependency.image)
        records.append({"dependency": dependency.model_dump(), "image_id": run("image", "inspect", "--format", "{{.Id}}", dependency.image)})
    required = {(spec.image, spec.pull_image) for _, _, spec in components(suite)}
    workspaces = {}
    for task in suite.tasks:
        env = task.environment
        if env is not None and not isinstance(env, ServiceEnvironment):
            built, _ = build_docker_image_if_requested(env.model_dump(mode="json"))
            required.add((built["image"], built.get("pull_image", True)))
            workspaces[task.id] = built["image"]
    identities = {}
    for image, pull in sorted(required):
        resolved = acquire(image, pull)
        identities[image] = run("image", "inspect", "--format", "{{.Id}}", resolved)
        records.append({"image": image, "resolved_image": resolved, "image_id": identities[image]})
    if bind:
        for _, _, spec in components(suite):
            spec.image, spec.pull_image = identities[spec.image], False
        for task in suite.tasks:
            if task.id in workspaces:
                task.environment.image = identities[workspaces[task.id]]
                task.environment.pull_image = False
                task.environment.image_build = {}
    return {"status": "prepared", "images": records}


class Call(Contract):
    method: str
    params: dict = Field(default_factory=dict)
    result_schema: dict = Field(default_factory=dict)


class Case(Contract):
    task: str
    component: str
    calls: list[Call] = Field(min_length=1)


def exercise(suite, cases):
    """Each case has fresh state; calls within it share a real component process."""
    cases = [Case.model_validate(case) for case in cases]
    specs = {(task, name): spec for task, name, spec in components(suite)}
    tasks = {task.id: task for task in suite.tasks}
    reports = []
    for case in cases:
        report = {"task": case.task, "component": case.component, "calls": [], "status": "passed"}
        try:
            spec = specs[(case.task, case.component)]
            task = tasks.get(case.task)
            assets = task.assets if task else [a for t in suite.tasks for a in t.assets]
            with closing(JsonComponent(spec, assets, on_event=lambda event: None)) as component:
                for call in case.calls:
                    entry = {"method": call.method}
                    report["calls"].append(entry)
                    result = component.call(call.method, call.params)
                    entry["result"] = result
                    if call.method == "score" and task:
                        scorer = next(s for s in task.evaluation.scorers
                                      if s.id == case.component or (case.component == "environment" and s.kind == "environment"))
                        validate_metrics(scorer, result, task.evaluation.metrics)
                    jsonschema.validate(result, call.result_schema)
        except Exception as exc:
            report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        reports.append(report)
    return {"status": "passed" if reports and all(r["status"] == "passed" for r in reports) else "failed",
            "cases": reports, "checked": "Only supplied call paths; not task quality or exhaustive correctness"}
