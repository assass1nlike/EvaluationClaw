"""Compile declared interfaces without executing programs or interpreting task text."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from ..execution.task_runtime import contract_issues
from ..protocols.task_definition import ComponentSpec, TaskMessage
from ..types import BenchmarkItem, EvalSpec, TaskAsset, TaskSuite
from .schema import Benchmark, Task

FORMAT = "benchmark-package/v1"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(path):
    def invalid(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_pairs, parse_constant=invalid)


def _path(root, name, *, directory=False):
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise ValueError(f"Expected a package-relative path: {name!r}")
    path = root / str(relative)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes package: {name!r}")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f"Missing {'directory' if directory else 'file'}: {name}")
    return path


def _text(root, name):
    # read_text's newline translation would change exact answers and task inputs.
    return _path(root, name).read_bytes().decode("utf-8")


def _hashes(root):
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Archive symlink trees as an asset instead of a package link: {path.relative_to(root)}")
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _message(message, root):
    value = message.model_dump(exclude={"file"})
    if message.file is not None:
        value["content"] = _text(root, message.file)
    return TaskMessage.model_validate(value)


def _program(program, root):
    files = {}
    for name in program.files:
        path = _path(root, name)
        key = path.relative_to(root).as_posix()
        if key in files or key == "benchmark_io.py":
            raise ValueError(f"Duplicate or reserved program file: {key}")
        files[key] = path.read_bytes().decode("utf-8")
    files["benchmark_io.py"] = Path(__file__).with_name("benchmark_io.py").read_text()
    return ComponentSpec(**program.model_dump(exclude={"files"}), files=files)


def _evaluation(task, root):
    references, metrics, scorers = [], [], []
    grades = task.grading if isinstance(task.grading, list) else [task.grading]
    for i, grade in enumerate(grades):
        defined = grade.metrics if grade.metrics is not None else [
            {"id": grade.name, "minimum": 0, "maximum": 1}]
        defined = [m.model_dump() if hasattr(m, "model_dump") else m for m in defined]
        metrics.extend(defined)
        answer = grade.answer
        if grade.answer_file is not None:
            answer = (_json(_path(root, grade.answer_file)) if grade.answer_format == "json"
                      else _text(root, grade.answer_file))
        if grade.method == "exact" and not isinstance(answer, str):
            raise ValueError("Exact text comparison requires a string answer; use json for other JSON values")
        ref_ids = []
        if answer is not None:
            ref_ids = [f"reference-{i}"]
            references.append({"id": ref_ids[0], "kind": grade.reference_kind, "value": answer,
                               "semantics": grade.reference_is or
                               ("exhaustive" if grade.method in {"exact", "json"} else "example")})
        instructions = _text(root, grade.rubric) if grade.rubric is not None else grade.instructions
        scorers.append({"id": f"grader-{i}", "kind": {"judge": "llm", "program": "component"}.get(grade.method, grade.method),
            "metrics": [m["id"] for m in defined], "references": ref_ids, "instructions": instructions,
            "component": _program(grade.program, root) if grade.program else None,
            "strip": grade.strip, "case_sensitive": grade.case_sensitive, "response_view": grade.response_view,
            "weights": grade.weights, "depends_on": grade.depends_on})
    primary = task.primary
    if primary is None and len(metrics) == 1:
        metric = metrics[0]
        if (metric.get("value_type", "number") in {"number", "boolean"}
                and metric.get("minimum") is not None and metric.get("maximum") is not None
                and metric.get("direction", "higher") != "descriptive"):
            primary = {"metric": metric["id"], "minimum": metric["minimum"], "maximum": metric["maximum"],
                       "direction": metric.get("direction", "higher")}
    return {"references": references, "metrics": metrics, "scorers": scorers, "scalar": primary}


def _task(root, relative):
    directory = _path(root, relative, directory=True)
    task = Task.model_validate(_json(directory / "task.json"))
    messages = ([_message(m, directory) for m in task.messages] if task.messages else
                [TaskMessage(role="user", content=_text(directory, task.prompt))])
    assets = []
    declared = set()
    for file in task.files:
        if file.id.startswith("package:"):
            raise ValueError("File IDs beginning package: are reserved for original files")
        path = _path(directory, file.path)
        if file.mount and (PurePosixPath(file.mount).is_absolute() or ".." in PurePosixPath(file.mount).parts):
            raise ValueError(f"Mount must be relative: {file.mount}")
        assets.append(TaskAsset(id=file.id, path=path.relative_to(root).as_posix(),
            visibility=file.audience, mount_path=file.mount,
            media_type=file.media_type or mimetypes.guess_type(file.path)[0] or "application/octet-stream",
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        declared.add(path)
    # Reviewers can always retrieve the original package, including source code.
    for name, digest in _hashes(directory).items():
        path = directory / name
        if path not in declared:
            assets.append(TaskAsset(id=f"package:{name}", path=path.relative_to(root).as_posix(),
                visibility=["judge"], sha256=digest,
                media_type=mimetypes.guess_type(name)[0] or "application/octet-stream"))
    environment = None
    if task.workspace:
        ws = task.workspace
        environment = {"type": "docker_workspace", "image": ws.image, "auto_select_image": False,
            "pull_image": ws.pull_image,
            "setup_commands": ws.setup, "network": ws.network, "workdir": ws.workdir,
            "timeout": ws.command_timeout, "max_steps": ws.max_steps,
            "test_command": ws.score_command, "evaluation": {"result_format": "json_on_stdout"},
            "hidden_files": {name: _text(directory, name) for name in ws.private_files}}
        public_paths = {a.mount_path or Path(a.path).name for a in assets if "target" in a.visibility}
        if len(public_paths) != sum("target" in a.visibility for a in assets):
            raise ValueError("Public workspace file destinations must be unique")
        if public_paths.intersection(ws.private_files):
            raise ValueError("A private scoring file cannot also occupy a public mount path")
        if ws.dockerfile:
            context = _path(directory, ws.context, directory=True)
            dockerfile = _path(directory, ws.dockerfile)
            if not dockerfile.is_relative_to(context):
                raise ValueError("Dockerfile must be inside its context directory")
            environment["image"] = "build://auto"
            environment["image_build"] = {"enabled": True, "context_dir": context.relative_to(root).as_posix(),
                                          "dockerfile_name": dockerfile.relative_to(context).as_posix()}
    elif task.service:
        environment = {"type": "tool_service", "service": _program(task.service, directory),
                       "capabilities": task.service_capabilities, "initial_state": task.initial_state}
    interaction = task.interaction
    protocol = ("program" if interaction.driver else "model" if interaction.instructions else
                "dialogue" if interaction.turns else "tool_loop" if environment is not None else "response")
    item = BenchmarkItem(id=task.id, title=task.title, challenge_effort=None,
        task_type="agent" if environment is not None or protocol in {"program", "model"} else
                  "multi_turn" if protocol == "dialogue" else "generation",
        content={"messages": messages, "output_contract": task.output, "stop": task.stop,
                 "operation": task.operation, "continuations": task.continuations},
        interaction={"protocol": protocol, "turns": [_message(m, directory) for m in interaction.turns],
            "reset_between_turns": interaction.reset_between_turns,
            "controller": _program(interaction.driver, directory) if interaction.driver else None,
            "controller_prompt": interaction.instructions, "controller_model_role": interaction.model_role,
            "controller_actions": interaction.actions, "participants": interaction.participants,
            "budget": interaction.budget, "controller_observations": interaction.observations,
            "actor_contact_tool": interaction.actor_contact_tool},
        environment=environment, assets=assets, evaluation=_evaluation(task, directory), tags=task.tags,
        annotations=task.labels,
        source={"kind": "imported"}, provenance={"format": FORMAT, "record": f"{relative}/task.json"})
    issues = contract_issues(item)
    if issues:
        raise ValueError("; ".join(issues))
    return item


def _compile(root):
    benchmark = Benchmark.model_validate(_json(root / "benchmark.json"))
    from .readiness import components, image_context
    for dependency in benchmark.images:
        if dependency.dockerfile:
            image_context(root, dependency)
    tasks = []
    for relative in benchmark.tasks:
        try:
            tasks.append(_task(root, relative))
        except (ValueError, OSError) as exc:
            raise ValueError(f"{relative}/task.json: {exc}") from exc
    if len({t.id for t in tasks}) != len(tasks):
        raise ValueError("Task IDs must be unique across the benchmark")
    aggregation = []
    for definition in benchmark.aggregation:
        value = definition.model_dump(exclude={"program"})
        if definition.program:
            value.update(aggregation="component", component=_program(definition.program, root))
            for asset_id in definition.program.assets:
                matches = [a for t in tasks for a in t.assets if a.id == asset_id]
                if len(matches) != 1:
                    raise ValueError(f"Suite program asset must identify exactly one task file: {asset_id}")
        aggregation.append(value)
    suite = TaskSuite(objective=benchmark.objective,
        spec=EvalSpec(objective=benchmark.objective, scale=len(tasks), task_types=list(dict.fromkeys(t.task_type for t in tasks))),
        tasks=tasks, evaluation_plan=aggregation, created_at="")
    local_images = {dependency.image for dependency in benchmark.images}
    for _, _, spec in components(suite):
        if spec.image in local_images:
            spec.pull_image = False
    for task in tasks:
        if task.environment is not None and getattr(task.environment, "image", None) in local_images:
            task.environment.pull_image = False
    return suite


def _bind(suite, root):
    for item in suite.tasks:
        for asset in item.assets:
            asset.path = str(_path(root, asset.path).resolve())
            if hashlib.sha256(Path(asset.path).read_bytes()).hexdigest() != asset.sha256:
                raise ValueError(f"Asset checksum mismatch: {asset.id}")
        env = item.environment
        if env is not None and getattr(env, "image_build", {}).get("context_dir"):
            env.image_build["context_dir"] = str(_path(root, env.image_build["context_dir"], directory=True).resolve())
    return suite


def load_package(directory):
    """Validate and bind an author's package without rewriting or executing it."""
    root = Path(directory).resolve()
    _hashes(root)
    return _bind(_compile(root), root)


def pack(directory, output):
    """Publish a portable bundle with original bytes, fixed mappings, and hashes."""
    root, output = Path(directory).resolve(), Path(output).absolute()
    if output.exists() or output.resolve().is_relative_to(root):
        raise ValueError("Output must be a new directory outside the input package")
    hashes = _hashes(root)
    suite = _compile(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".benchmark-package-", dir=output.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        shutil.copytree(root, staging / "original")
        if _hashes(staging / "original") != hashes or _hashes(root) != hashes:
            raise ValueError("Package changed during conversion")
        encoded = suite.model_dump_json(indent=2).encode()
        (staging / "suite.json").write_bytes(encoded)
        (staging / "conversion.json").write_text(json.dumps({"format": FORMAT, "files": hashes,
            "suite_sha256": hashlib.sha256(encoded).hexdigest(),
            "mapping": {t.id: t.provenance["record"] for t in suite.tasks}}, indent=2))
        staging.rename(output)
    return load_bundle(output)


def load_bundle(directory):
    """Load the saved conversion, verifying bytes and rebasing only declared paths."""
    root = Path(directory).resolve()
    record = _json(root / "conversion.json")
    if record["format"] != FORMAT:
        raise ValueError("Unsupported conversion format")
    if _hashes(root / "original") != record["files"]:
        raise ValueError("Original package checksum mismatch")
    data = (root / "suite.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != record["suite_sha256"]:
        raise ValueError("Converted suite checksum mismatch")
    return _bind(TaskSuite.model_validate_json(data), root / "original")
