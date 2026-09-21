"""Pluggable agent-harness abstraction for docker-backed tasks.

A harness wraps the target model into an agent that solves a task inside the
task's docker environment. The framework calls the harness through a uniform
interface and reuses the shared image/build + scoring flow; each harness only
supplies its own launch command.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

from ..execution.docker import docker_subprocess_env, resolve_docker_executable
from ..execution.docker_images import (
    apply_docker_image_selection,
    build_docker_image_if_requested,
)
from ..execution.environment_checks import run_environment_checks
from ..execution.evaluation import parse_evaluator_result
from ..execution.evidence import EVALUATOR_EVIDENCE_SCHEMA, execution_failure, redact_evidence
from ..execution.harness_compatibility import external_harness_issues
from ..execution.harness_evidence import cli_result, normalize_events
from ..execution.image_acquisition import acquire_image, image_pull_options
from ..execution.interventions import InterventionController
from ..execution.process import run_bounded
from ..execution.resource_guard import DockerResourceGuard
from ..protocols.assets import environment_asset_sources
from ..protocols.task_agent import task_agent_initial_content_text, task_agent_system_prompt
from ..types import SUPPORTED_HARNESSES, BenchmarkConfig, BenchmarkItem, TargetModelConfig

if TYPE_CHECKING:
    from .environment_actors import ActorSession

_MODEL_GATEWAY_IMAGE = "evalclaw-model-gateway:latest"
_OUTPUT_LIMIT_BYTES = 8 * 1024 * 1024


class HarnessExecutionError(RuntimeError):
    """A harness failure with its captured process output."""

    def __init__(self, message: str, stdout: str, stderr: str):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


class HarnessTimeoutError(HarnessExecutionError):
    """A harness timeout with the output captured before termination."""

    def __init__(self, name: str, timeout: int, stdout: str, stderr: str):
        super().__init__(
            f"Harness {name!r} timed out after {timeout} seconds.", stdout, stderr
        )
        self.timeout = timeout


def _redact_secret(text: str, secret: str | None) -> str:
    """Remove the exact configured credential without matching ordinary text."""
    return text.replace(secret, "[REDACTED]") if secret else text


def _task_digest(item: BenchmarkItem) -> str:
    payload = json.dumps(
        item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _evaluation_timeout(item: BenchmarkItem) -> int:
    env = agent_env(item)
    evaluation = env.get("evaluation") if isinstance(env.get("evaluation"), dict) else {}
    return max(1, int(evaluation.get("timeout") or env.get("timeout") or 600))


def _run_bounded(
    command: list[str],
    *,
    timeout: int,
    env: dict[str, str],
    stdin: int | None = subprocess.DEVNULL,
    failure_markers: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return run_bounded(
        command, timeout=timeout, env=env, stdin=stdin,
        failure_markers=failure_markers, output_limit=_OUTPUT_LIMIT_BYTES,
    )


class HarnessRunner(Protocol):
    name: str

    def run(
        self,
        item: BenchmarkItem,
        target: TargetModelConfig,
        config: BenchmarkConfig,
        *,
        artifact_dir: Path | None = None,
    ) -> tuple[str, float, str]: ...


class EnvironmentBackend(Protocol):
    """Lifecycle boundary between an agent runtime and its task environment."""

    kind: str

    def prepare(self) -> tuple[str, Path]: ...

    def evaluate(
        self,
        image: str,
        workdir: Path,
        evidence: dict[str, Any] | None = None,
        *,
        container_name: str | None = None,
    ) -> tuple[float, str]: ...

    def cleanup(self, workdir: Path) -> None: ...


@dataclass(frozen=True)
class ModelConnection:
    """Connection details passed to a harness without exposing framework config."""

    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    extra_body: dict[str, Any] | None = None


@dataclass(frozen=True)
class HarnessContext:
    item: BenchmarkItem
    target: TargetModelConfig
    config: BenchmarkConfig
    image: str
    workdir: Path

    @property
    def connection(self) -> ModelConnection:
        return ModelConnection(
            provider=self.target.provider,
            model=self.target.model,
            api_key=self.target.api_key or "",
            base_url=self.target.base_url or "",
            extra_body=self.target.extra_body,
        )


@dataclass
class DockerWorkspaceBackend:
    """The Docker environment backend used by manifest-based CLI harnesses."""

    item: BenchmarkItem
    config: BenchmarkConfig
    kind: str = "docker_workspace"
    prepared_image: str = ""

    def prepare(self) -> tuple[str, Path]:
        image, workdir = prepare_docker_task(self.item, self.config)
        self.prepared_image = image
        return image, workdir

    def evaluate(
        self,
        image: str,
        workdir: Path,
        evidence: dict[str, Any] | None = None,
        *,
        container_name: str | None = None,
        artifact_dir: Path | None = None,
    ) -> tuple[float, str]:
        if agent_env(self.item).get("judge"):
            from ..execution.agent_judge import score_with_agent

            if not container_name:
                raise ValueError("Judge scoring requires the completed task container.")
            return score_with_agent(
                self.item, self.config, container_name, evidence or {},
                lambda: score_docker_task(self.item, self.config, image, workdir,
                                          evidence=evidence, container_name=container_name),
                artifact_dir=artifact_dir,
            )
        return score_docker_task(
            self.item,
            self.config,
            image,
            workdir,
            evidence=evidence,
            container_name=container_name,
        )

    def cleanup(self, workdir: Path) -> None:
        _cleanup_seeded_workspace(workdir, self.prepared_image, self.config)


def environment_backend(item: BenchmarkItem, config: BenchmarkConfig) -> EnvironmentBackend:
    kind = str(agent_env(item).get("type") or "docker_workspace").strip().lower()
    if kind != "docker_workspace":
        raise RuntimeError(
            f"Harness-backed agent tasks require a docker_workspace backend; got {kind!r}. "
            "Use a harness adapter that explicitly supports this environment type."
        )
    return DockerWorkspaceBackend(item, config)


def cleanup_harness_session(lifecycle: dict[str, Any]) -> None:
    """Release a prepared task session, including its gateway and resource guard."""
    docker = lifecycle.get("docker")
    try:
        if lifecycle.get("container_name") and docker:
            _remove_container(str(docker), str(lifecycle["container_name"]))
    finally:
        try:
            if lifecycle.get("gateway_name") and docker:
                _stop_model_gateway(
                    str(docker), str(lifecycle.get("gateway_network") or ""),
                    str(lifecycle["gateway_name"]),
                )
        finally:
            guard = lifecycle.get("resource_guard")
            if guard is not None:
                guard.close()


@dataclass(frozen=True)
class HarnessRunRecord:
    """The runner-facing record for one external agent episode.

    ``raw_output`` is diagnostic output from the harness.  The score is always
    produced by EvaluationClaw's evaluator after the agent exits; a harness
    cannot declare its own success.
    """

    raw_output: str
    score: float
    reasoning: str
    trajectory_paths: tuple[str, ...] = ()


_HARNESS_RUNNERS: dict[str, HarnessRunner] = {}
_builtins_loaded = False


def register_harness(runner: HarnessRunner) -> None:
    if runner.name not in SUPPORTED_HARNESSES:
        raise ValueError(
            f"Harness {runner.name!r} is not in SUPPORTED_HARNESSES; "
            f"add it to types.SUPPORTED_HARNESSES first."
        )
    _HARNESS_RUNNERS[runner.name] = runner


def ensure_builtins_registered() -> None:
    """Register the built-in manifest harnesses."""
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True
    _register_builtin_manifests()


def get_harness(name: str) -> HarnessRunner:
    ensure_builtins_registered()
    if name not in _HARNESS_RUNNERS:
        raise ValueError(f"Unsupported harness {name!r}; supported: {sorted(_HARNESS_RUNNERS)}.")
    return _HARNESS_RUNNERS[name]


def preflight_harness_environments(
    item: BenchmarkItem, config: BenchmarkConfig, *, artifact_dir: Path | None = None,
) -> list[dict[str, Any]]:
    outcomes = []
    for index, target in enumerate(config.targets):
        if not target.harness:
            if agent_env(item).get("actors"):
                raise ValueError("Actor tasks require an external shell harness for every target.")
            continue
        runner = get_harness(target.harness)
        preflight = getattr(runner, "preflight", None)
        if not callable(preflight):
            raise ValueError(f"Harness {target.harness!r} does not implement task environment preflight.")
        outcomes.append(preflight(
            item, target, config,
            artifact_dir=artifact_dir / f"{index:02d}-{target.harness}" if artifact_dir else None,
        ))
    return outcomes


def agent_env(item: BenchmarkItem) -> dict[str, Any]:
    env = item.metadata.get("agent_env")
    return env if isinstance(env, dict) else {}


def reject_tool_constraints(item: BenchmarkItem, harness: str = "external") -> None:
    """Reject tasks that declare tool constraints a third-party harness can't honor."""
    env = agent_env(item)
    issues = external_harness_issues(
        env,
        [harness],
        has_workflow=item.workflow is not None,
        workflow=item.workflow,
    )
    interaction = item.metadata.get("task_agent", {}).get("interaction")
    if interaction:
        issues.append("Agent interaction metadata is not executable. Use workflow.stages for follow-up messages or context resets, and environment.interventions for environment events.")
    if issues:
        raise RuntimeError(" ".join(issues))


def _task_container_options(
    env: dict[str, Any],
    *,
    include_network: bool = True,
    include_user: bool = True,
) -> list[str]:
    options = ["--security-opt", "no-new-privileges"]
    if include_user:
        options += ["--user", _target_container_user(), "-e", "HOME=/tmp"]
    network = str(env.get("network") or "none").strip().lower()
    network_modes = {"none": "none", "internet": "bridge", "restricted": "none"}
    if network not in network_modes:
        raise ValueError("Harness network must be one of: none, restricted, internet.")
    if include_network:
        options += ["--network", network_modes[network]]
    limits = env.get("resource_limits") if isinstance(env.get("resource_limits"), dict) else {}
    for key, flag in (("memory", "--memory"), ("cpus", "--cpus")):
        value = limits.get(key)
        if value is not None and str(value).strip():
            options += [flag, str(value)]
    options += ["--pids-limit", str(limits.get("pids") or 256)]
    return options


def _target_container_user() -> str:
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        uid, gid = os.getuid(), os.getgid()
        if uid != 0:
            return f"{uid}:{gid}"
    return "65534:65534"


def _container_exec_command(
    docker: str,
    container_name: str,
    command: str,
    *,
    user: str,
    env_names: tuple[str, ...] = (),
) -> list[str]:
    args = [
        docker,
        "exec",
        "--user",
        user,
        "--workdir",
        "/workspace",
    ]
    # Both provisioning and target commands operate on this framework-owned worktree.
    # Trust only this directory, regardless of which identity initialized its Git metadata.
    args += [
        "--env", "GIT_CONFIG_COUNT=1",
        "--env", "GIT_CONFIG_KEY_0=safe.directory",
        "--env", "GIT_CONFIG_VALUE_0=/workspace",
    ]
    if user == "0:0":
        args += ["--env", "HOME=/root"]
        uid, gid = _target_container_user().split(":")
        args += ["--env", f"EVALCLAW_TARGET_UID={uid}", "--env", f"EVALCLAW_TARGET_GID={gid}"]
    for name in env_names:
        args += ["--env", name]
    args += [container_name, "sh", "-lc", command]
    return args


def _workspace_path(workdir: Path, raw_path: object) -> Path:
    """Resolve a declared workspace path without following links outside it."""
    text = str(raw_path).replace("\\", "/").strip()
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Workspace paths must be relative and stay inside /workspace: {raw_path!r}.")
    root = workdir.resolve()
    candidate = root
    for part in path.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError(f"Workspace path contains a symbolic link: {raw_path!r}.")
    candidate = candidate.resolve(strict=False)
    if not candidate.is_relative_to(root):
        raise ValueError(f"Workspace path escapes its root: {raw_path!r}.")
    return candidate


def _write_workspace_file(workdir: Path, path: object, content: object) -> None:
    target = _workspace_path(workdir, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Re-resolve after creating parents so a pre-existing directory symlink
    # cannot redirect a runner-private write outside the workspace.
    target = _workspace_path(workdir, path)
    target.write_text(str(content), encoding="utf-8")


def _stage_container_files(
    docker: str,
    container_name: str,
    files: dict[str, Any],
    destination: str,
    *,
    timeout: int,
) -> None:
    """Copy runner-private files into a root-only container directory."""
    if not files:
        return
    staging = Path(tempfile.mkdtemp(prefix="evalclaw-container-files-"))
    try:
        for path, content in files.items():
            _write_workspace_file(staging, path, content)
        for path in staging.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        prepare = _run_bounded(
            _container_exec_command(
                docker,
                container_name,
                f"rm -rf -- {shlex.quote(destination)} && "
                f"mkdir -m 700 -p -- {shlex.quote(destination)}",
                user="0:0",
            ),
            timeout=timeout,
            env=docker_subprocess_env(docker),
        )
        if prepare.returncode != 0:
            raise RuntimeError(prepare.stderr or prepare.stdout)
        copied = _run_bounded(
            [docker, "cp", f"{staging}/.", f"{container_name}:{destination}"],
            timeout=timeout,
            env=docker_subprocess_env(docker),
        )
        if copied.returncode != 0:
            raise RuntimeError(copied.stderr or copied.stdout)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _read_container_file(
    docker: str,
    container_name: str,
    path: str,
    *,
    timeout: int,
) -> str:
    proc = _run_bounded(
        _container_exec_command(
            docker,
            container_name,
            "cat -- " + shlex.quote(path),
            user="0:0",
        ),
        timeout=timeout,
        env=docker_subprocess_env(docker),
    )
    return proc.stdout if proc.returncode == 0 else ""


def _copy_regular_tree(source: Path, destination: Path) -> None:
    """Copy only regular files and directories from an untrusted workspace."""
    if source.is_symlink():
        return
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination, follow_symlinks=False)
        return
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            _copy_regular_tree(child, destination / child.name)


def _harness_prompt(item: BenchmarkItem) -> str:
    from ..protocols.submission import submission_instructions
    prompt = item.prompt + submission_instructions(item)
    system_prompt = task_agent_system_prompt(item, "")
    initial_content = task_agent_initial_content_text(item)
    has_actors = bool(agent_env(item).get("actors"))
    if not system_prompt and not initial_content and not has_actors:
        return prompt
    parts: list[str] = []
    if system_prompt:
        parts.append(f"Task-specific instructions:\n{system_prompt}")
    parts.append(f"Task:\n{prompt}")
    if initial_content:
        parts.append(f"Initial task content:\n{initial_content}")
    if has_actors:
        from .environment_actors import CONTACT_INSTRUCTIONS

        parts.append(CONTACT_INSTRUCTIONS)
    return "\n\n".join(parts)


def _resolve_image_context(
    item: BenchmarkItem,
    env: dict[str, Any],
    config: BenchmarkConfig,
) -> dict[str, Any]:
    """Resolve a relative image_build.context_dir against the Builder job directory."""
    image_build = env.get("image_build")
    if not isinstance(image_build, dict):
        return env
    context_dir = str(image_build.get("context_dir") or "").strip()
    if not context_dir or Path(context_dir).is_absolute() or config is None:
        return env
    builder_job_id = str(item.metadata.get("builder_job_id") or "").strip()
    if not builder_job_id or not str(config.output_dir).strip():
        raise ValueError(
            "A relative image_build.context_dir requires the task's builder_job_id and output_dir."
        )
    safe_job_id = re.sub(r"[^A-Za-z0-9._-]+", "_", builder_job_id).strip("._")
    root = (
        Path(config.output_dir).expanduser().resolve()
        / "assets"
        / "task-builder"
        / (safe_job_id or "task-builder")
    )
    resolved = (root / context_dir).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("image_build.context_dir must stay inside the Builder job directory.")
    updated = dict(env)
    updated["image_build"] = {**image_build, "context_dir": str(resolved)}
    return updated


def prepare_docker_task(item: BenchmarkItem, config: BenchmarkConfig) -> tuple[str, Path]:
    """Select/build the task image and write visible files into a host workdir."""
    from ..execution.evidence import validate_environment_files

    validate_environment_files(item)
    env = _resolve_image_context(item, dict(agent_env(item)), config)
    task_text = item.prompt
    env, _ = apply_docker_image_selection(env, task_text=task_text)
    env, _ = build_docker_image_if_requested(
        env,
        task_text=task_text,
        docker_executable=config.docker_executable,
        timeout_s=config.docker_build_timeout_s,
    )
    image = acquire_image(
        str(env.get("image") or "python:3.11-slim"),
        docker_executable=config.docker_executable, timeout_s=config.docker_pull_timeout_s,
        allow_pull=bool(env.get("pull_image", True)),
    )
    workdir = Path(tempfile.mkdtemp(prefix="evalclaw-harness-"))
    try:
        visible = env.get("visible_files")
        if isinstance(visible, dict):
            for path, content in visible.items():
                _write_workspace_file(workdir, path, content)
        for guest_path, source in environment_asset_sources(item.assets).items():
            target = _workspace_path(workdir, guest_path)
            if target.exists():
                raise ValueError(f"Task asset conflicts with a visible workspace file: {guest_path!r}.")
            if not source.is_file():
                raise ValueError(f"Task asset does not exist or is not a file: {source}.")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        seeded = _seed_image_workspace(image, workdir, config)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return image, seeded


def _seed_image_workspace(image: str, overlay: Path, config: BenchmarkConfig) -> Path:
    """Preserve image file ownership and modes; overlay explicit public files."""
    docker = resolve_docker_executable(config.docker_executable)
    if not docker:
        raise RuntimeError("Docker is unavailable for workspace preparation.")
    env = docker_subprocess_env(config.docker_executable)
    name = "evalclaw-workspace-" + uuid.uuid4().hex[:12]
    workdir = Path(tempfile.mkdtemp(prefix="evalclaw-harness-"))
    guard = DockerResourceGuard(docker, env)
    try:
        guard.register("container", name)
        script = ["set -eu", "if [ -e /workspace ]; then cp -a /workspace/. /evalclaw-seed/; fi"]
        for source in sorted(overlay.rglob("*")):
            relative = source.relative_to(overlay).as_posix()
            destination = PurePosixPath("/evalclaw-seed") / relative
            # Never follow an image symlink while applying declared overrides.
            for path in [*reversed(destination.parents), destination]:
                script.append(f"test ! -L {shlex.quote(str(path))} || {{ echo 'Overlay path contains an image symlink' >&2; exit 1; }}")
            if source.is_dir():
                path = shlex.quote(str(destination))
                script.append(f"if [ ! -e {path} ]; then mkdir {path}; chown {_target_container_user()} {path}; fi")
                continue
            script.extend([
                f"mkdir -p {shlex.quote(str(destination.parent))}",
                f"rm -f {shlex.quote(str(destination))}",
                f"cp -p {shlex.quote('/evalclaw-overlay/' + relative)} {shlex.quote(str(destination))}",
                f"chown {_target_container_user()} {shlex.quote(str(destination))}",
            ])
        # The mount root remains the framework-owned writable worktree. Children
        # retain image permissions; explicit files retain overlay permissions.
        script.extend([f"chown {_target_container_user()} /evalclaw-seed", "chmod 0700 /evalclaw-seed"])
        result = _run_bounded([
            docker, "run", *image_pull_options(), "--name", name, "--network", "none", "--user", "0:0",
            "-v", f"{overlay}:/evalclaw-overlay:ro", "-v", f"{workdir}:/evalclaw-seed",
            "--entrypoint", "sh", image, "-c", "\n".join(script),
        ], timeout=600, env=env)
        if result.returncode:
            raise RuntimeError(f"Image workspace preparation failed: {result.stderr or result.stdout}")
        return workdir
    except BaseException:
        _cleanup_seeded_workspace(workdir, image, config)
        raise
    finally:
        guard.close()


def _cleanup_seeded_workspace(workdir: Path, image: str, config: BenchmarkConfig) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
    if not workdir.exists():
        return
    # Seeded root-owned directories may not be removable by the host user.
    # Only the concrete framework-created workdir is mounted for cleanup.
    if workdir.is_symlink() or workdir.parent != Path(tempfile.gettempdir()) or not workdir.name.startswith("evalclaw-harness-"):
        raise ValueError("Refusing privileged cleanup of a non-framework workspace")
    docker = resolve_docker_executable(config.docker_executable)
    env = docker_subprocess_env(config.docker_executable)
    name = "evalclaw-workspace-cleanup-" + uuid.uuid4().hex[:12]
    guard = DockerResourceGuard(docker, env)
    try:
        guard.register("container", name)
        result = _run_bounded([
            docker, "run", *image_pull_options(), "--name", name, "--network", "none", "--user", "0:0",
            "-v", f"{workdir}:/evalclaw-cleanup", "--entrypoint", "sh", image,
            "-c", f"find /evalclaw-cleanup -mindepth 1 -delete && chown {os.getuid()}:{os.getgid()} /evalclaw-cleanup && chmod 0700 /evalclaw-cleanup",
        ], timeout=120, env=env)
        if result.returncode:
            raise RuntimeError(f"Workspace cleanup failed: {result.stderr or result.stdout}")
        workdir.rmdir()
    finally:
        guard.close()


def score_docker_task(
    item: BenchmarkItem,
    config: BenchmarkConfig,
    image: str,
    workdir: Path,
    *,
    evidence: dict[str, Any] | None = None,
    container_name: str | None = None,
) -> tuple[float, str]:
    """Score the state left in the task container after the target exits."""
    env = agent_env(item)
    test_command = str(env.get("test_command") or "pytest -q")
    evaluation = env.get("evaluation") if isinstance(env.get("evaluation"), dict) else {}
    result_path = str(evaluation.get("result_path") or "/workspace/evalclaw_result.json")
    score_path = str(evaluation.get("score_path") or "/workspace/score.txt")
    resolved = resolve_docker_executable(config.docker_executable)
    if not resolved:
        raise RuntimeError(f"Docker executable {config.docker_executable!r} not found.")
    owned_container = container_name is None
    container_name = container_name or f"evalclaw-score-{uuid.uuid4().hex[:12]}"
    hidden = env.get("hidden_files")
    hidden = hidden if isinstance(hidden, dict) else {}
    hidden_paths: list[str] = []
    for path in hidden:
        _workspace_path(workdir, path)
        hidden_paths.append(str(PurePosixPath(str(path).replace("\\", "/"))))
    evaluator_timeout = _evaluation_timeout(item)
    try:
        if owned_container:
            image = acquire_image(image, docker_executable=config.docker_executable,
                                  timeout_s=config.docker_pull_timeout_s)
            create_args = [
                resolved,
                "create",
                *image_pull_options(),
                "--name",
                container_name,
                "-v",
                f"{workdir}:/workspace",
                "-w",
                "/workspace",
                *_task_container_options(env, include_user=False),
                image,
                "sh",
                "-lc",
                "while :; do sleep 3600; done",
            ]
            created = _run_bounded(
                create_args,
                timeout=evaluator_timeout,
                env=docker_subprocess_env(config.docker_executable),
            )
            if created.returncode != 0:
                raise RuntimeError(created.stderr or created.stdout)
            started = _run_bounded(
                [resolved, "start", container_name],
                timeout=evaluator_timeout,
                env=docker_subprocess_env(config.docker_executable),
            )
            if started.returncode != 0:
                raise RuntimeError(started.stderr or started.stdout)
            setup = env.get("setup_commands") if isinstance(env.get("setup_commands"), list) else []
            setup_script = " && ".join(
                shlex.join(["sh", "-lc", str(command)])
                for command in setup
                if str(command).strip()
            )
            if setup_script:
                setup_proc = _run_bounded(
                    _container_exec_command(
                        resolved, container_name, setup_script, user="0:0"
                    ),
                    timeout=evaluator_timeout,
                    env=docker_subprocess_env(config.docker_executable),
                )
                if setup_proc.returncode != 0:
                    raise RuntimeError(setup_proc.stderr or setup_proc.stdout)

        _stage_container_files(
            resolved,
            container_name,
            hidden,
            "/evalclaw-hidden",
            timeout=evaluator_timeout,
        )
        if evidence is not None:
            _stage_container_files(
                resolved,
                container_name,
                {"episode.json": json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"},
                "/evalclaw-evidence",
                timeout=evaluator_timeout,
            )
        inject_commands = []
        for path in hidden_paths:
            destination = PurePosixPath("/workspace") / PurePosixPath(path)
            inject_commands.append(
                "mkdir -p -- " + shlex.quote(str(destination.parent))
                + " && cp -- "
                + shlex.quote(str(PurePosixPath("/evalclaw-hidden") / path))
                + " "
                + shlex.quote(str(destination))
            )
        cleanup = "rm -f -- " + " ".join(
            shlex.quote(str(PurePosixPath("/workspace") / path)) for path in hidden_paths
        )
        evaluator_parts = [*inject_commands]
        if hidden_paths:
            evaluator_parts.append(f"trap {shlex.quote(cleanup)} EXIT")
        evaluator_parts.extend(
            part
            for part in (
                "rm -f -- " + shlex.join([result_path, score_path]),
                test_command,
            )
            if part
        )
        proc: subprocess.CompletedProcess[str]
        try:
            proc = _run_bounded(
                _container_exec_command(
                    resolved,
                    container_name,
                    " && ".join(evaluator_parts),
                    user="0:0",
                ),
                timeout=evaluator_timeout,
                env=docker_subprocess_env(config.docker_executable),
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Harness evaluator timed out after {evaluator_timeout} seconds."
            ) from None
        result_json = _read_container_file(
            resolved, container_name, result_path, timeout=evaluator_timeout
        )
        score_text = _read_container_file(
            resolved, container_name, score_path, timeout=evaluator_timeout
        )
    finally:
        try:
            cleanup = _run_bounded(
                _container_exec_command(
                    resolved,
                    container_name,
                    "rm -rf -- /evalclaw-hidden /evalclaw-evidence",
                    user="0:0",
                ),
                timeout=min(evaluator_timeout, 30),
                env=docker_subprocess_env(config.docker_executable),
            )
            del cleanup
        except (OSError, subprocess.SubprocessError):
            pass
        if owned_container:
            _remove_container(resolved, container_name)
    evaluator = parse_evaluator_result(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        result_json=result_json,
        score_text=score_text,
        allow_stdout_score=(
            bool(evaluation.get("allow_stdout_score", False))
            or evaluation.get("result_format") == "json_on_stdout"
        ),
        score_field=str(evaluation.get("score_field") or "score"),
    )
    structured_required = bool(
        evaluation.get("result_path") or evaluation.get("score_path")
        or evaluation.get("result_format") == "json_on_stdout"
        or evaluation.get("allow_stdout_score")
    )
    if proc.returncode not in {0, 1} or (structured_required and not evaluator.structured):
        raise RuntimeError(
            "Evaluator did not return a valid result "
            f"(exit {proc.returncode}): {(proc.stderr or proc.stdout)[-2000:]}"
        )
    score = evaluator.score
    reasoning = evaluator.details or "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
    return score, reasoning


def _docker(
    docker: str,
    args: list[str],
    *,
    check: bool = True,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a docker subcommand with Docker's credential env discoverable."""
    env = docker_subprocess_env(docker)
    if extra_env:
        env.update(extra_env)
    if (args[:2] == ["network", "create"] and env.get("EVALCLAW_DOCKER_NETWORK_POOL")
            and not any(a.split("=", 1)[0] == "--subnet" for a in args[2:])):
        from ..execution.docker_networks import create_network

        return create_network(
            [docker], args, env["EVALCLAW_DOCKER_NETWORK_POOL"],
            capture_output=True, text=True, check=check, env=env, timeout=120,
        )
    return subprocess.run(
        [docker, *args],
        capture_output=True,
        text=True,
        check=check,
        env=env,
        timeout=120,
    )


def _remove_container(docker: str, name: str) -> None:
    try:
        _docker(docker, ["rm", "-f", name], check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def _infer_model_base_url(model: str, provider: str = "") -> str:
    name = model.split("/", 1)[-1].lower()
    if name.startswith("deepseek"):
        return "https://api.deepseek.com"
    if provider == "anthropic" or name.startswith("claude"):
        return "https://api.anthropic.com"
    if provider == "openai" or name.startswith(("gpt-", "o1", "o3", "o4")):
        return "https://api.openai.com/v1"
    raise ValueError(
        f"Harness target {model!r} requires an explicit base_url for provider {provider!r}."
    )


def _harness_provider(target: TargetModelConfig) -> str:
    if target.provider == "openai_compatible":
        name = target.model.split("/", 1)[-1].lower()
        if name.startswith("deepseek"):
            return "deepseek"
        if name.startswith("gemini"):
            return "google"
    return target.provider


def _harness_model(target: TargetModelConfig, provider: str) -> str:
    prefix = provider + "/"
    return target.model[len(prefix):] if target.model.startswith(prefix) else target.model


def _start_model_gateway(
    docker: str,
    upstream: str,
    *,
    internal: bool = True,
    api_key: str,
    provider: str,
    model: str,
    extra_body: dict[str, Any] | None = None,
    resource_guard: DockerResourceGuard | None = None,
) -> tuple[str, str, str]:
    """Start a model API gateway on an internal network.

    Returns ``(network, gateway_name, gateway_url)``. The gateway listens on the
    internal network (where the harness will run) and is also bridged so it can
    reach the model API; the harness container gets only the internal network.
    """
    gateway_image = acquire_image(_MODEL_GATEWAY_IMAGE, docker_executable=docker, allow_pull=False)
    tag = uuid.uuid4().hex[:8]
    network = f"evalclaw-harness-{tag}"
    gateway = f"evalclaw-gateway-{tag}"
    if resource_guard is not None:
        resource_guard.register("network", network)
        resource_guard.register("container", gateway)
        if internal:
            resource_guard.register("network", network + "-egress")
    network_args = ["network", "create"]
    if internal:
        network_args.append("--internal")
    network_args.append(network)
    _docker(docker, network_args)
    try:
        _docker(
            docker,
            [
                "run", *image_pull_options(), "-d", "--name", gateway, "--network", network,
                "-e", "EVALCLAW_UPSTREAM_API_KEY",
                "-e", "EVALCLAW_UPSTREAM_EXTRA_BODY",
                "--mount", f"type=bind,src={Path(__file__).resolve().parents[1] / 'execution/model_gateway.py'},dst=/usr/local/bin/model_gateway.py,readonly",
                gateway_image,
                "--upstream", upstream,
                "--provider", provider,
                "--model", model,
                "--port", "18080",
            ],
            extra_env={"EVALCLAW_UPSTREAM_API_KEY": api_key,
                       "EVALCLAW_UPSTREAM_EXTRA_BODY": json.dumps(extra_body or {})},
        )
        if internal:
            _docker(docker, ["network", "create", network + "-egress"])
            _docker(docker, ["network", "connect", network + "-egress", gateway])
    except Exception:
        _docker(docker, ["rm", "-f", gateway], check=False)
        if internal:
            _docker(docker, ["network", "rm", network + "-egress"], check=False)
        _docker(docker, ["network", "rm", network], check=False)
        raise
    time.sleep(1.0)  # let the gateway bind its port before the harness connects
    return network, gateway, f"http://{gateway}:18080"


def _stop_model_gateway(docker: str, network: str, gateway: str) -> None:
    _docker(docker, ["rm", "-f", gateway], check=False)
    _docker(docker, ["network", "rm", network + "-egress"], check=False)
    _docker(docker, ["network", "rm", network], check=False)


def preflight_model_gateways(config: BenchmarkConfig) -> None:
    """Check Docker, gateway reachability and upstream TLS before construction.

    This sends no inference request; model/credential validity is checked by execution.
    """
    if not config.run_targets or not config.environment_preflight:
        return
    checked = set()
    for target in config.targets:
        if not target.harness:
            continue
        runner = get_harness(target.harness)
        if not isinstance(runner, ManifestHarnessRunner) or not runner._manifest.gateway:
            continue
        runner._validate_target(target)
        upstream = target.base_url or _infer_model_base_url(target.model, target.provider)
        if (target.harness, upstream) in checked:
            continue
        docker = resolve_docker_executable(config.docker_executable)
        if not docker:
            raise RuntimeError("Docker is required for the configured target harness.")
        tool_image = runner._tool_image()
        if tool_image:
            _docker(docker, ["image", "inspect", tool_image])
        provider = _harness_provider(target)
        network, gateway, url = _start_model_gateway(
            docker, upstream, api_key=target.api_key or "",
            provider=provider, model=_harness_model(target, provider),
            extra_body=target.extra_body,
        )
        probe = "evalclaw-network-probe-" + uuid.uuid4().hex[:12]
        try:
            # Probe from a second container on the same isolated network as targets.
            _docker(docker, [
                "run", *image_pull_options(), "--rm", "--name", probe, "--network", network,
                "--entrypoint", "python", _MODEL_GATEWAY_IMAGE, "-c",
                "import urllib.request,urllib.error,sys\n"
                "try: urllib.request.urlopen(sys.argv[1], timeout=10)\n"
                "except urllib.error.HTTPError as e:\n"
                " assert e.code == 405, e.code\n", url,
            ])
            _docker(docker, [
                "exec", gateway, "python", "-c",
                "import socket,ssl,sys; from urllib.parse import urlsplit; "
                "u=urlsplit(sys.argv[1]); "
                "s=socket.create_connection((u.hostname,u.port or (443 if u.scheme=='https' else 80)),10); "
                "s=ssl.create_default_context().wrap_socket(s,server_hostname=u.hostname) if u.scheme=='https' else s; "
                "s.close()", upstream,
            ])
        finally:
            _remove_container(docker, probe)
            _stop_model_gateway(docker, network, gateway)
        checked.add((target.harness, upstream))


@dataclass
class ManifestHarness:
    name: str
    run: str  # command template with {task} {image} {workdir} placeholders
    model_env: dict[str, str]  # env var name -> target field (model/api_key/base_url)
    model_template: str = "{model}"  # harness-specific model identifier
    config_args: tuple[str, ...] = ()  # argv fragments rendered at {config_args}
    timeout: int = 3600
    harness_image: str | None = None  # image whose filesystem is mounted to provide the CLI
    runtime_image: str | None = None  # legacy alias for harness_image
    setup: tuple[str, ...] = ()  # runtime setup commands, executed in the task environment
    path: str = "/opt/harness/usr/local/bin"  # runtime executable path inside the mounted image
    home: str = ""  # optional harness home copied from the mounted tool image
    trajectory_paths: tuple[str, ...] = ()  # workspace-relative trace/artifact paths
    gateway: bool = False  # route the model API through an egress gateway (internal network)
    gateway_provider: str | None = None  # provider whose baseUrl is repointed at the gateway
    gateway_setup: str = ""  # optional command template used to configure the provider
    preflight: tuple[str, ...] = ()  # commands that verify the runtime before the episode
    allowed_providers: tuple[str, ...] = ()
    failure_markers: tuple[str, ...] = ()  # output that means failure despite exit code 0
    session_run: str = ""  # command accepting {session_id} and {task}, preserving history


class ManifestHarnessRunner:
    """A harness defined by a declarative manifest that launches an external CLI."""

    def __init__(self, manifest: ManifestHarness):
        self.name = manifest.name
        self._manifest = manifest

    def run(
        self,
        item: BenchmarkItem,
        target: TargetModelConfig,
        config: BenchmarkConfig,
        *,
        artifact_dir: Path | None = None,
        preflight_only: bool = False,
        evaluation_callback=None,
    ) -> tuple[str, float, str]:
        item = item.model_copy(deep=True)
        episode_filename = "native-episode.json" if evaluation_callback else "episode.json"
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        reject_tool_constraints(item, self.name)
        raw_actors = agent_env(item).get("actors")
        actors = []
        toolsets: dict[str, dict[str, Any]] = {}
        if raw_actors:
            from .environment_actors import ActorSession, actor_configuration

            actors, toolsets = actor_configuration(agent_env(item))
        self._validate_target(target)
        backend = environment_backend(item, config)
        image, workdir = backend.prepare()
        context = HarnessContext(item, target, config, image, workdir)
        preflight: list[str] = []
        actor_session: ActorSession | None = None
        launch_capture: dict[str, Any] = {}
        try:
            launch_capture["stage"] = "harness_preflight"
            if actors:
                actor_session = ActorSession(
                    actors=actors,
                    toolsets=toolsets,
                    workdir=workdir,
                    image=image,
                    environment=agent_env(item),
                    config=config,
                    artifact_dir=artifact_dir,
                )
            try:
                raw = self._launch(
                    context.item,
                    context.target,
                    context.config,
                    context.image,
                    context.workdir,
                    capture=launch_capture,
                    **({"actor_session": actor_session} if actor_session else {}),
                    **({"preflight_only": True} if preflight_only else {}),
                )
                preflight = launch_capture.get("preflight", [])
            finally:
                if actor_session is not None:
                    actor_session.close()
            if actor_session is not None:
                actor_session.raise_if_failed()
            if item.workflow is not None:
                final_stage = item.workflow.stages[-1]
                env = agent_env(item)
                if final_stage.test_command:
                    env["test_command"] = final_stage.test_command
                if final_stage.evaluation:
                    env["evaluation"] = final_stage.evaluation
            actor_evidence = actor_session.runtime.evidence() if actor_session else {
                "summary": {}, "interactions": []
            }
            from ..protocols.submission import submission_contract
            evidence = redact_evidence(
                {
                    "schema_version": EVALUATOR_EVIDENCE_SCHEMA,
                    "item_id": item.id,
                    "submission_contract": submission_contract(item),
                    "target": {
                        "id": target.id,
                        "model": target.model,
                        "provider": target.provider,
                        "harness": self.name,
                    },
                    "target_execution": normalize_events(
                        launch_capture.get("model_events", []), self.name, raw,
                        launch_capture.get("stderr", ""), stages=launch_capture.get("stages", []),
                    ),
                    "evidence_error": launch_capture.get("evidence_error"),
                    "actors": actor_evidence,
                    "environment_checks": {
                        "readiness": launch_capture.get("readiness_checks", []),
                        "preflight": launch_capture.get("environment_checks", []),
                    },
                    "interventions": launch_capture.get("interventions", []),
                    "stages": launch_capture.get("stages", []),
                    "timing": {
                        "started_at": started_at.isoformat(),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "duration_ms": round((time.monotonic() - started) * 1000),
                    },
                    "termination": {"status": "preflight" if preflight_only else launch_capture.get("termination", "completed")},
                },
                [target.api_key, config.actor_api_key],
            )
            if artifact_dir is not None:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / f"{self.name}-output.txt").write_text(
                    _redact_secret(raw, target.api_key), encoding="utf-8"
                )
                if launch_capture.get("stderr"):
                    (artifact_dir / f"{self.name}-stderr.txt").write_text(
                        _redact_secret(str(launch_capture["stderr"]), target.api_key),
                        encoding="utf-8",
                    )
                (artifact_dir / "evaluator-evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            launch_capture["stage"] = "evaluation"
            if artifact_dir is not None:
                self._collect_trajectory(workdir, artifact_dir)
            if evaluation_callback is not None:
                score, reasoning = evaluation_callback(backend, context.image, context.workdir,
                                                       evidence, launch_capture.get("container_name"))
            else:
                score, reasoning = backend.evaluate(
                    context.image,
                    context.workdir,
                    evidence=evidence,
                    container_name=launch_capture.get("container_name"),
                    **({"artifact_dir": artifact_dir / "judge" if artifact_dir else None}
                       if agent_env(item).get("judge") else {}),
                )
            raw = _redact_secret(raw, target.api_key)
            reasoning = _redact_secret(reasoning, target.api_key)
            if artifact_dir is not None:
                finished_at = datetime.now(timezone.utc)
                (artifact_dir / f"{self.name}-reasoning.txt").write_text(reasoning, encoding="utf-8")
                self._collect_trajectory(workdir, artifact_dir)
                (artifact_dir / episode_filename).write_text(
                    json.dumps(
                        {
                            "item_id": item.id,
                            "task_sha256": _task_digest(item),
                            "target_id": target.id,
                            "harness": self.name,
                            "environment": backend.kind,
                            "model": target.model,
                            "provider": target.provider,
                            "status": "preflight" if preflight_only else launch_capture.get("termination", "completed"),
                            "score": score,
                            "started_at": started_at.isoformat(),
                            "finished_at": finished_at.isoformat(),
                            "duration_ms": round((time.monotonic() - started) * 1000),
                            "timeouts": {
                                "harness_seconds": self._episode_timeout(item, config),
                                "evaluator_seconds": _evaluation_timeout(item),
                            },
                            "task_image": self._image_identity(config, context.image),
                            "harness_image": self._image_identity(
                                config, self._tool_image()
                            ),
                            "gateway_image": self._image_identity(
                                config, _MODEL_GATEWAY_IMAGE
                            ) if self._manifest.gateway else None,
                            "manifest": asdict(self._manifest),
                            "preflight": preflight,
                            "actors": actor_session.runtime.summary() if actor_session else None,
                            "interventions": launch_capture.get("interventions", []),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            return raw, score, reasoning
        except BaseException as exc:
            failure = execution_failure(exc)
            target_output = str(launch_capture.get("stdout") or "")
            if isinstance(exc, HarnessExecutionError):
                target_output = target_output or exc.stdout
            failure_evidence = redact_evidence({
                "schema_version": EVALUATOR_EVIDENCE_SCHEMA,
                "item_id": item.id,
                "target": {"id": target.id, "model": target.model, "harness": self.name},
                "stage": launch_capture.get("stage", "harness_preflight"),
                "target_started": launch_capture.get("target_started", False),
                "target_execution": {
                    **normalize_events(launch_capture.get("model_events", []), self.name, target_output,
                                       launch_capture.get("stderr", ""), stages=launch_capture.get("stages", [])),
                    "raw_output": target_output,
                    "stderr": launch_capture.get("stderr", ""),
                    "command": launch_capture.get("target_command"),
                    "returncode": launch_capture.get("returncode"),
                },
                "actors": actor_session.runtime.evidence() if actor_session else None,
                "interventions": launch_capture.get("interventions", []),
                "stages": launch_capture.get("stages", []),
                "termination": {"status": "failed", "error_type": type(exc).__name__},
                "failure": failure,
                "evidence_error": launch_capture.get("evidence_error"),
                "artifacts": {"episode": episode_filename, "evidence": "execution-failure.json"},
            }, [target.api_key, config.actor_api_key])
            exc.execution_evidence = failure_evidence
            if artifact_dir is not None:
                finished_at = datetime.now(timezone.utc)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "execution-failure.json").write_text(
                    json.dumps(failure_evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                (artifact_dir / "failure-stderr.txt").write_text(
                    failure_evidence["failure"]["stderr"], encoding="utf-8",
                )
                if launch_capture.get("stdout") or launch_capture.get("stderr"):
                    (artifact_dir / f"{self.name}-output.txt").write_text(
                        _redact_secret(str(launch_capture.get("stdout") or ""), target.api_key),
                        encoding="utf-8",
                    )
                    (artifact_dir / f"{self.name}-stderr.txt").write_text(
                        _redact_secret(str(launch_capture.get("stderr") or ""), target.api_key),
                        encoding="utf-8",
                    )
                elif isinstance(exc, HarnessExecutionError):
                    (artifact_dir / f"{self.name}-output.txt").write_text(
                        _redact_secret(exc.stdout, target.api_key), encoding="utf-8"
                    )
                    (artifact_dir / f"{self.name}-stderr.txt").write_text(
                        _redact_secret(exc.stderr, target.api_key), encoding="utf-8"
                    )
                self._collect_trajectory(workdir, artifact_dir)
                (artifact_dir / episode_filename).write_text(
                    json.dumps(
                        {
                            "item_id": item.id,
                            "task_sha256": _task_digest(item),
                            "target_id": target.id,
                            "harness": self.name,
                            "environment": backend.kind,
                            "model": target.model,
                            "provider": target.provider,
                            "status": "failed",
                            "stage": failure_evidence["stage"],
                            "target_started": failure_evidence["target_started"],
                            "target_execution": failure_evidence["target_execution"],
                            "failure": failure_evidence["failure"],
                            "error": _redact_secret(
                                _redact_secret(
                                    f"{type(exc).__name__}: {exc}", target.api_key
                                ),
                                config.actor_api_key,
                            ),
                            "started_at": started_at.isoformat(),
                            "finished_at": finished_at.isoformat(),
                            "duration_ms": round((time.monotonic() - started) * 1000),
                            "timeouts": {
                                "harness_seconds": self._episode_timeout(item, config),
                                "evaluator_seconds": _evaluation_timeout(item),
                            },
                            "task_image": self._image_identity(config, context.image),
                            "harness_image": self._image_identity(
                                config, self._tool_image()
                            ),
                            "gateway_image": self._image_identity(
                                config, _MODEL_GATEWAY_IMAGE
                            ) if self._manifest.gateway else None,
                            "manifest": asdict(self._manifest),
                            "preflight": preflight,
                            "actors": actor_session.runtime.summary() if actor_session else None,
                            "interventions": launch_capture.get("interventions", []),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            raise
        finally:
            try:
                cleanup_harness_session(launch_capture)
            finally:
                backend.cleanup(workdir)

    def preflight(
        self, item: BenchmarkItem, target: TargetModelConfig, config: BenchmarkConfig,
        *, artifact_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Exercise the real setup, runtime checks and scorer without invoking a target model."""
        _, score, details = self.run(
            item, target, config, artifact_dir=artifact_dir, preflight_only=True,
        )
        return {"harness": self.name, "status": "passed", "baseline_score": score, "details": details}

    def _tool_image(self) -> str | None:
        return self._manifest.harness_image or self._manifest.runtime_image

    def _episode_timeout(
        self, item: BenchmarkItem, config: BenchmarkConfig | None = None
    ) -> int:
        env = agent_env(item)
        max_steps = max(1, int(env.get("max_steps") or 8))
        step_timeout = max(1, int(env.get("timeout") or 20))
        if env.get("actors"):
            step_timeout = max(step_timeout, config.actor_timeout_s if config else 300)
        return min(self._manifest.timeout, max_steps * step_timeout)

    def _validate_target(self, target: TargetModelConfig) -> None:
        if (
            self._manifest.allowed_providers
            and target.provider not in self._manifest.allowed_providers
        ):
            raise RuntimeError(
                f"Harness {self.name!r} supports providers "
                f"{list(self._manifest.allowed_providers)}, not {target.provider!r}."
            )
        if target.api_key and "api_key" in self._manifest.model_env and not self._manifest.gateway:
            raise RuntimeError(
                f"Harness {self.name!r} must use an API gateway so the task container "
                "cannot access the upstream credential."
            )

    def _image_identity(self, config: BenchmarkConfig, image: str | None) -> dict[str, str] | None:
        if not image:
            return None
        resolved = resolve_docker_executable(config.docker_executable)
        if not resolved:
            return {"name": image}
        identity = {"name": image}
        try:
            proc = subprocess.run(
                [resolved, "image", "inspect", image, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
                timeout=30,
                env=docker_subprocess_env(config.docker_executable),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                identity["id"] = proc.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return identity

    def _mount_tool_image(self, run_args: list[str], *, docker_executable: str = "docker") -> None:
        tool_image = self._tool_image()
        if tool_image:
            tool_image = acquire_image(tool_image, docker_executable=docker_executable, allow_pull=False)
            run_args += [
                "--mount",
                f"type=image,src={tool_image},dst=/opt/harness,readonly",
            ]

    def _runtime_prefix(self) -> str:
        if not self._tool_image():
            return ""
        prefix = ""
        if self._manifest.home:
            prefix += (
                f"cp -a /opt/harness/{self._manifest.home} \"$HOME/\" "
                "2>/dev/null || true; "
            )
        if self._manifest.path:
            prefix += f"export PATH={shlex.quote(self._manifest.path)}:$PATH; "
        return prefix + "export EVALCLAW_HARNESS=1; "

    def _launch(
        self,
        item: BenchmarkItem,
        target: TargetModelConfig,
        config: BenchmarkConfig,
        image: str,
        workdir: Path,
        *,
        actor_session: "ActorSession | None" = None,
        capture: dict[str, Any] | None = None,
        preflight_only: bool = False,
        prepare_only: bool = False,
    ) -> str:
        env = agent_env(item)
        max_steps = max(1, int(env.get("max_steps") or 8))
        step_timeout = max(1, int(env.get("timeout") or 20))
        episode_timeout = self._episode_timeout(item, config)
        provider = _harness_provider(target)
        model = _harness_model(target, provider)
        needs_base_url = self._manifest.gateway or "base_url" in self._manifest.model_env or any(
            "{base_url}" in template
            for template in (self._manifest.run, *self._manifest.config_args)
        )
        base_url = target.base_url or (
            _infer_model_base_url(target.model, target.provider) if needs_base_url else ""
        )
        resolved = resolve_docker_executable(config.docker_executable)
        if not resolved:
            raise RuntimeError(f"Docker executable {config.docker_executable!r} not found.")
        lifecycle = capture if capture is not None else {}
        owns_lifecycle = capture is None
        gateway_network: str | None = None
        gateway_name: str | None = None
        container_name = f"evalclaw-harness-{uuid.uuid4().hex[:12]}"
        controller: InterventionController | None = None
        guard = lifecycle["resource_guard"] = DockerResourceGuard(
            resolved, docker_subprocess_env(config.docker_executable)
        )
        guard.register("container", container_name)
        try:
            if self._manifest.gateway:
                lifecycle["stage"] = "model_gateway"
                if str(env.get("network") or "none").strip().lower() == "internet":
                    gateway_network, gateway_name, base_url = _start_model_gateway(
                        resolved,
                        base_url,
                        internal=False,
                        resource_guard=guard,
                        api_key=target.api_key or "",
                        provider=provider,
                        model=model,
                        extra_body=target.extra_body,
                    )
                else:
                    gateway_network, gateway_name, base_url = _start_model_gateway(
                        resolved,
                        base_url,
                        resource_guard=guard,
                        api_key=target.api_key or "",
                        provider=provider,
                        model=model,
                        extra_body=target.extra_body,
                    )
                lifecycle["gateway_network"] = gateway_network
                lifecycle["gateway_name"] = gateway_name
                lifecycle["docker"] = resolved
            lifecycle["stage"] = "environment_setup"
            values = {
                "task": _harness_prompt(item),
                "image": image,
                "workdir": "/workspace",
                "provider": provider,
                "model": model,
                "api_key": "evalclaw-gateway" if self._manifest.gateway else target.api_key or "",
                "base_url": base_url,
                "extra_body": json.dumps(target.extra_body, ensure_ascii=False),
                "max_steps": str(max_steps),
                "step_timeout": str(step_timeout),
                "timeout": str(episode_timeout),
            }
            quoted = {key: shlex.quote(value) for key, value in values.items()}
            config_tokens: list[str] = []
            for template in self._manifest.config_args:
                config_tokens.extend(shlex.split(template.format(**quoted)))
            command = shlex.split(
                self._manifest.run.format(**quoted, config_args=shlex.join(config_tokens))
            )
            create_args: list[str] = [
                resolved, "create", *image_pull_options(),
                "--name", container_name,
                "-v", f"{workdir}:/workspace",
                "-w", "/workspace",
                *_task_container_options(
                    env,
                    include_network=not self._manifest.gateway,
                    include_user=False,
                ),
                "-e", "HOME=/tmp",
            ]
            self._mount_tool_image(create_args, docker_executable=config.docker_executable)
            if actor_session is not None:
                create_args += ["-v", actor_session.mount]
            if gateway_network is not None:
                create_args += ["--network", gateway_network]
            connection = {
                "provider": provider,
                "model": self._manifest.model_template.format(**values),
                "api_key": values["api_key"],
                "base_url": base_url,
            }
            docker_env = docker_subprocess_env(config.docker_executable)
            for field, var_name in self._manifest.model_env.items():
                value = connection.get(field, getattr(target, field, None))
                if value:
                    docker_env[var_name] = str(value)
                    create_args += ["-e", var_name]
            # A lingering shell retains the prompt in argv and can be mistaken
            # for a task service by process-management tools such as pkill -f.
            shell_command = "exec " + shlex.join(command)
            create_args += [
                image,
                "sh",
                "-lc",
                "while :; do sleep 3600; done",
            ]
            lifecycle["container_name"] = container_name
            lifecycle["docker"] = resolved
            created = _run_bounded(
                create_args,
                timeout=min(episode_timeout, 120),
                env=docker_env,
            )
            if created.returncode != 0:
                raise RuntimeError(
                    "Could not create harness task container: "
                    + _redact_secret(created.stderr or created.stdout, target.api_key)
                )
            started = _run_bounded(
                [resolved, "start", container_name],
                timeout=min(episode_timeout, 120),
                env=docker_env,
            )
            if started.returncode != 0:
                raise RuntimeError(
                    "Could not start harness task container: "
                    + _redact_secret(started.stderr or started.stdout, target.api_key)
                )

            if hasattr(os, "getuid") and os.getuid() == 0:
                ownership = _run_bounded(
                    _container_exec_command(
                        resolved,
                        container_name,
                        f"chown {_target_container_user()} /workspace",
                        user="0:0",
                    ),
                    timeout=min(episode_timeout, 120),
                    env=docker_env,
                )
                if ownership.returncode != 0:
                    raise RuntimeError(
                        "Could not make the initial workspace writable by the target: "
                        + _redact_secret(
                            ownership.stderr or ownership.stdout,
                            target.api_key,
                        )
                    )

            trusted_setup: list[str] = []
            for setup in env.get("setup_commands", []):
                if setup:
                    trusted_setup.append(str(setup))
            for setup in self._manifest.setup:
                if setup:
                    trusted_setup.append(setup)
            if trusted_setup:
                setup_proc = _run_bounded(
                    _container_exec_command(
                        resolved,
                        container_name,
                        " && ".join(
                            shlex.join(["sh", "-lc", setup])
                            for setup in trusted_setup
                        ),
                        user="0:0",
                    ),
                    timeout=episode_timeout,
                    env=docker_env,
                )
                if setup_proc.returncode != 0:
                    raise RuntimeError(
                        "Harness task setup failed: "
                        + _redact_secret(
                            setup_proc.stderr or setup_proc.stdout,
                            target.api_key,
                        )
                    )

            prefix = self._runtime_prefix()
            if item.workflow is not None and self.name == "openclaw":
                prefix += "openclaw config set agents.defaults.workspace /workspace && "
            if gateway_name is not None and self._manifest.gateway_setup:
                prefix += self._manifest.gateway_setup.format(
                    gateway_url=base_url,
                    provider=shlex.quote(provider),
                    model=shlex.quote(_harness_model(target, provider)),
                ) + " && "
            elif gateway_name is not None and self._manifest.name == "openclaw" and self._manifest.gateway_provider:
                # Compatibility for callers constructing the old OpenClaw manifest
                # directly. File manifests should use gateway_setup instead.
                prefix += (
                    f"openclaw config set models.providers.{self._manifest.gateway_provider}.baseUrl "
                    f"{base_url} 2>/dev/null; "
                )
            if prefix:
                bootstrap = _run_bounded(
                    _container_exec_command(resolved, container_name, prefix + "true", user=_target_container_user()),
                    timeout=episode_timeout, env=docker_env,
                )
                if bootstrap.returncode:
                    raise RuntimeError("Harness configuration failed: " + bootstrap.stderr)
            # Configuration/home copying is preparation, never part of a target action.
            prefix = (f"export PATH={shlex.quote(self._manifest.path)}:$PATH; export EVALCLAW_HARNESS=1; "
                      if self._tool_image() else "")
            lifecycle["stage"] = "harness_preflight"
            lifecycle["runtime_prefix"] = prefix
            lifecycle["preflight"] = self._preflight(
                HarnessContext(item, target, config, image, workdir), container_name, prefix,
            )
            def check_environment(command):
                return _run_bounded(
                    _container_exec_command(resolved, container_name, command, user=_target_container_user()),
                    timeout=min(episode_timeout, 120), env=docker_env,
                )

            lifecycle["readiness_checks"] = run_environment_checks(
                env.get("readiness_checks", []), check_environment,
            )
            if prepare_only:
                return ""
            if preflight_only:
                lifecycle["environment_checks"] = run_environment_checks(
                    env.get("preflight_commands", []), check_environment,
                )
                return ""
            interventions = [
                dict(intervention)
                for intervention in env.get("interventions", [])
                if isinstance(intervention, dict)
            ]
            if interventions:
                marker = "/tmp/evalclaw-target-started"
                prefix += f"touch {shlex.quote(marker)} && "

                def external_command(
                    command: str, timeout: int
                ) -> subprocess.CompletedProcess[str]:
                    return _run_bounded(
                        _container_exec_command(
                            resolved,
                            container_name,
                            command,
                            user="0:0",
                        ),
                        timeout=timeout,
                        env=docker_subprocess_env(config.docker_executable),
                    )

                def target_started() -> bool:
                    return external_command(f"test -f {shlex.quote(marker)}", 1).returncode == 0

                controller = InterventionController(
                    interventions, external_command, ready=target_started
                )
            target_command = _container_exec_command(
                resolved,
                container_name,
                prefix + f"export EVALCLAW_EPISODE_ID={shlex.quote(container_name)}; " + shell_command,
                user=_target_container_user(),
                env_names=tuple(self._manifest.model_env.values()),
            )
            proc: subprocess.CompletedProcess[str] | None = None
            budget = env.get("budget") or {}
            allowed_time = min(episode_timeout, float(budget.get("wall_time_seconds", episode_timeout)))
            budget_expired = False
            try:
                if controller is not None:
                    controller.start()
                lifecycle["stage"] = "target_execution"
                lifecycle["target_started"] = None  # Dispatch attempted; startup not yet confirmed.
                lifecycle["target_command"] = target_command
                if item.workflow is not None:
                    proc = self._workflow_turns(item, values, quoted, prefix, lifecycle, resolved,
                                                container_name, docker_env, allowed_time)
                else:
                    proc = _run_bounded(
                        target_command, stdin=subprocess.DEVNULL, timeout=allowed_time,
                        env=docker_env, failure_markers=self._manifest.failure_markers,
                    )
            except subprocess.TimeoutExpired as exc:
                # Killing docker exec alone does not stop its process inside Docker.
                budget_expired = bool(budget) and allowed_time == float(budget["wall_time_seconds"])
                if budget_expired:
                    self._stop_episode(resolved, container_name)
                    lifecycle["termination"] = "budget_exhausted"
                else:
                    _docker(resolved, ["kill", container_name], check=False)
                stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(
                    exc.stdout, bytes
                ) else exc.stdout or ""
                stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(
                    exc.stderr, bytes
                ) else exc.stderr or ""
                lifecycle["stdout"] = stdout
                lifecycle["stderr"] = stderr
                if not budget_expired:
                    raise HarnessTimeoutError(self.name, episode_timeout, stdout, stderr) from None
                proc = subprocess.CompletedProcess(target_command, 124, stdout, stderr)
            except FileNotFoundError as exc:
                raise RuntimeError(f"Harness command not found for {self.name!r}.") from exc
            finally:
                if controller is not None:
                    controller.stop()
                    if capture is not None:
                        capture["interventions"] = list(controller.records)
                if gateway_name:
                    try:
                        lifecycle["model_events"] = self._gateway_evidence(resolved, gateway_name)
                    except (OSError, subprocess.SubprocessError) as exc:
                        lifecycle["evidence_error"] = f"{type(exc).__name__}: {exc}"
            lifecycle["stdout"] = proc.stdout
            lifecycle["stderr"] = proc.stderr
            lifecycle["returncode"] = proc.returncode
            if proc.returncode == 0:
                lifecycle["target_started"] = True
            if controller is not None:
                controller.raise_if_failed()
            structured = cli_result(self.name, proc.stdout)
            if not budget_expired and not preflight_only:
                from ..execution.harness_evidence import terminal_model_error
                model_error = terminal_model_error(lifecycle.get("model_events", []))
                if model_error:
                    raise HarnessExecutionError(model_error, proc.stdout, proc.stderr)
            if not budget_expired and (proc.returncode != 0 or structured["status"] == "failed"):
                details = _redact_secret(proc.stderr or proc.stdout, target.api_key)
                raise HarnessExecutionError(
                    f"Harness {self.name!r} failed: {details}",
                    proc.stdout,
                    proc.stderr,
                )
            for marker in (() if budget_expired else self._manifest.failure_markers):
                if marker in proc.stdout or marker in proc.stderr:
                    details = _redact_secret(proc.stderr or proc.stdout, target.api_key)
                    raise HarnessExecutionError(
                        f"Harness {self.name!r} reported an execution error: {details}",
                        proc.stdout,
                        proc.stderr,
                    )
            if controller is not None:
                # Normal completion and task-budget exhaustion are submissions;
                # infrastructure failures above must not execute business settlement.
                if any(s["trigger"]["type"] == "episode_end" for s in interventions):
                    self._stop_episode(resolved, container_name)
                try:
                    controller.finish()
                finally:
                    lifecycle["interventions"] = list(controller.records)
            return proc.stdout
        finally:
            if owns_lifecycle:
                try:
                    _remove_container(resolved, container_name)
                    if gateway_name is not None:
                        _stop_model_gateway(resolved, gateway_network or "", gateway_name)
                finally:
                    guard.close()

    @staticmethod
    def _stop_episode(docker: str, container: str) -> None:
        script = """import os, signal, sys
from pathlib import Path
uid = int(sys.argv[1])
stopped = []
for entry in Path('/proc').iterdir():
    if not entry.name.isdecimal():
        continue
    try:
        if entry.stat().st_uid == uid:
            pid = int(entry.name)
            os.kill(pid, signal.SIGSTOP)
            stopped.append(pid)
    except (OSError, ProcessLookupError):
        continue
for pid in stopped:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
"""
        _docker(docker, ["exec", "--user", "0:0", container, "python3", "-c", script, _target_container_user().split(":")[0]])

    def _workflow_turns(self, item, values, quoted, prefix, lifecycle, docker, container, docker_env, timeout):
        from .workflow import _stage_prompt, stage_item

        deadline = time.monotonic() + timeout
        session_id = str(uuid.uuid4())
        results = {}
        lifecycle["stages"] = []
        proc = None
        for stage in item.workflow.stages:
            if stage.kind == "evaluate":
                break
            if stage.context == "fresh":
                session_id = str(uuid.uuid4())
            prompt = _harness_prompt(stage_item(item, stage).model_copy(update={"prompt": _stage_prompt(stage, results)}))
            args = {**quoted, "task": shlex.quote(prompt), "session_id": shlex.quote(session_id),
                    "max_steps": str(stage.max_steps), "max_tokens": str(stage.max_tokens)}
            template = self._manifest.session_run or self._manifest.run
            configs = [token for part in self._manifest.config_args for token in shlex.split(part.format(**args))]
            command = template.format(**args, config_args=shlex.join(configs))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            record = {"id": stage.id, "session_id": session_id, "context": stage.context,
                      "prompt": prompt, "started_at": time.time(), "status": "running"}
            lifecycle["stages"].append(record)
            proc = _run_bounded(_container_exec_command(
                docker, container, prefix + f"export EVALCLAW_EPISODE_ID={shlex.quote(container)}; exec " + command,
                user=_target_container_user(), env_names=tuple(self._manifest.model_env.values())),
                timeout=remaining, env=docker_env, failure_markers=self._manifest.failure_markers)
            envelope = cli_result(self.name, proc.stdout)
            lifecycle["stdout"], lifecycle["stderr"] = proc.stdout, proc.stderr
            record.update(output=envelope["final_response"], returncode=proc.returncode,
                          status=envelope["status"], tool_call_count=envelope.get("tool_call_count"),
                          finished_at=time.time())
            if lifecycle.get("gateway_name"):
                from ..execution.harness_evidence import terminal_model_error
                events = self._gateway_evidence(docker, lifecycle["gateway_name"])
                lifecycle["model_events"] = events
                error = terminal_model_error([e for e in events if e.get("time", 0) >= record["started_at"]])
                if error:
                    record.update(status="failed", error=error)
                    raise HarnessExecutionError(f"Workflow stage {stage.id}: {error}", proc.stdout, proc.stderr)
            if proc.returncode or envelope["status"] == "failed" or any(
                marker in proc.stdout or marker in proc.stderr for marker in self._manifest.failure_markers
            ):
                raise HarnessExecutionError(f"Workflow stage {stage.id} failed", proc.stdout, proc.stderr)
            results[stage.id] = {"output": envelope["final_response"], "transcript": []}
        return proc

    @staticmethod
    def _gateway_evidence(docker: str, gateway: str) -> list[dict]:
        # Copy outside the target container and read without stdout truncation.
        with tempfile.TemporaryDirectory(prefix="evalclaw-evidence-") as directory:
            path = Path(directory) / "events.jsonl"
            result = _docker(docker, ["cp", f"{gateway}:/tmp/model-events.jsonl", str(path)], check=False)
            if result.returncode or not path.exists():
                return []
            events = []
            with path.open(encoding="utf-8") as source:
                for line in source:
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        # A terminated stream can leave an incomplete final record.
                        continue
            return events

    def _preflight(
        self, context: HarnessContext, container_name: str, prefix: str,
    ) -> list[str]:
        resolved = resolve_docker_executable(context.config.docker_executable)
        if not resolved:
            raise RuntimeError(
                f"Docker executable {context.config.docker_executable!r} not found."
            )
        outputs: list[str] = []
        commands = [
            'test "$(id -u)" -ne 0 && test -r /workspace && test -x /workspace && test -w "$HOME"',
            *self._manifest.preflight,
        ]
        environment = agent_env(context.item)
        if environment.get("budget") or any(
            event.get("trigger", {}).get("type") == "episode_end" for event in environment.get("interventions", [])
        ):
            commands.append("python3 --version")
        if agent_env(context.item).get("actors"):
            from .environment_actors import CONTACT_COMMAND

            commands.append(f"{CONTACT_COMMAND} list")
        for command in commands:
            rendered = command.format(
                model=shlex.quote(context.target.model),
                provider=shlex.quote(context.target.provider),
                workdir="/workspace",
            )
            run_args = _container_exec_command(
                resolved, container_name, prefix + rendered, user=_target_container_user(),
            )
            try:
                probe = _run_bounded(
                    run_args,
                    timeout=min(self._manifest.timeout, 120),
                    env=docker_subprocess_env(context.config.docker_executable),
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"Harness {self.name!r} preflight timed out."
                ) from None
            if probe.returncode != 0:
                raise RuntimeError(
                    f"Harness {self.name!r} preflight failed: {probe.stderr or probe.stdout}"
                )
            outputs.append((probe.stdout or probe.stderr).strip())
        return outputs

    def _collect_trajectory(self, workdir: Path, artifact_dir: Path) -> None:
        """Copy declared harness traces before the task workspace is removed."""
        for relative in self._manifest.trajectory_paths:
            try:
                source = _workspace_path(workdir, relative)
                destination = _workspace_path(artifact_dir / "trajectory", relative)
            except ValueError:
                continue
            if not source.exists():
                continue
            _copy_regular_tree(source, destination)


def load_manifest_harness(path: str | Path) -> str:
    """Load a manifest file, register it as a harness, and return its name."""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Harness manifest must be a mapping: {path}")
    manifest = ManifestHarness(
        name=str(raw.get("name") or "").strip(),
        run=str(raw.get("run") or "").strip(),
        model_env={str(key): str(value) for key, value in (raw.get("model_env") or {}).items()},
        model_template=str(raw.get("model_template") or "{model}"),
        config_args=tuple(str(arg) for arg in (raw.get("config_args") or [])),
        timeout=max(1, int(raw.get("timeout") or 3600)),
        harness_image=str(raw.get("harness_image") or "") or None,
        runtime_image=str(raw.get("runtime_image") or "") or None,
        setup=tuple(str(command) for command in (raw.get("setup") or [])),
        path=str(raw.get("path") or "/opt/harness/usr/local/bin"),
        home=str(raw.get("home") or ""),
        trajectory_paths=tuple(str(path) for path in (raw.get("trajectory_paths") or [])),
        gateway=bool(raw.get("gateway")),
        gateway_provider=str(raw.get("gateway_provider") or "") or None,
        gateway_setup=str(raw.get("gateway_setup") or ""),
        preflight=tuple(str(command) for command in (raw.get("preflight") or [])),
        allowed_providers=tuple(
            str(provider) for provider in (raw.get("allowed_providers") or [])
        ),
        failure_markers=tuple(str(marker) for marker in (raw.get("failure_markers") or [])),
        session_run=str(raw.get("session_run") or ""),
    )
    if not manifest.name or not manifest.run:
        raise ValueError("Harness manifest requires name and run.")
    SUPPORTED_HARNESSES.add(manifest.name)
    register_harness(ManifestHarnessRunner(manifest))
    return manifest.name


_BUILTIN_MANIFESTS: tuple[ManifestHarness, ...] = (
    # Sandboxed, model-agnostic (self-hosted Docker/podman).
    ManifestHarness(
        name="miniswe",
        run="mini -m {model} -t {task} -y",
        model_env={"api_key": "DEEPSEEK_API_KEY"},
        preflight=("mini --version",),
    ),
    # Family-bound (official harnesses). codex has no OPENAI_BASE_URL env var: its
    # base_url / wire_api / env_key live in config.toml, so it's driven by -c flags.
    ManifestHarness(
        name="codex",
        run=(
            "codex exec {config_args} --json --ephemeral "
            "--dangerously-bypass-approvals-and-sandbox "
            "--skip-git-repo-check -m {model} {task}"
        ),
        model_env={"api_key": "OPENAI_API_KEY"},
        config_args=(
            "-c model_provider=evalclaw",
            "-c model_providers.evalclaw.name=evalclaw",
            "-c model_providers.evalclaw.base_url={base_url}",
            "-c model_providers.evalclaw.wire_api=responses",
            "-c model_providers.evalclaw.env_key=OPENAI_API_KEY",
        ),
        harness_image="evalclaw-harness-runtime:latest",
        preflight=("codex --version",),
        gateway=True,
        allowed_providers=("openai", "openai_responses"),
        failure_markers=("bwrap: No permissions to create a new namespace",),
    ),
    ManifestHarness(
        name="claude-code",
        run=(
            "claude -p --model {model} --permission-mode bypassPermissions "
            "--max-turns {max_steps} --name evalclaw --no-session-persistence "
            "--prompt-suggestions false --output-format stream-json --verbose {task}"
        ),
        model_env={"api_key": "ANTHROPIC_API_KEY", "base_url": "ANTHROPIC_BASE_URL"},
        harness_image="evalclaw-harness-runtime:latest",
        preflight=("claude --version",),
        gateway=True,
        allowed_providers=("anthropic",),
    ),
    ManifestHarness(
        name="cursor",
        run="cursor-agent -p --trust --force --model {model} {task}",
        model_env={"api_key": "CURSOR_API_KEY", "base_url": "CURSOR_API_ENDPOINT"},
        preflight=("cursor-agent --version",),
    ),
    ManifestHarness(
        name="grok",
        run="grok -p {task} -m {model} --permission-mode bypassPermissions --always-approve",
        model_env={"api_key": "XAI_API_KEY"},
        preflight=("grok --version",),
    ),
    # Model-agnostic terminal agents.
    ManifestHarness(
        name="opencode",
        run="opencode run --dir {workdir} -m {model} --format json {task}",
        model_env={"api_key": "DEEPSEEK_API_KEY"},
        preflight=("opencode --version",),
    ),
    ManifestHarness(
        name="aider",
        run="aider --model {model} --message {task} --yes --no-git",
        model_env={"api_key": "DEEPSEEK_API_KEY"},
        preflight=("aider --version",),
    ),
    ManifestHarness(
        name="goose",
        run="goose run -t {task}",
        model_env={"model": "GOOSE_MODEL", "api_key": "OPENAI_API_KEY", "base_url": "OPENAI_BASE_URL"},
        preflight=("goose --version",),
    ),
    ManifestHarness(
        name="openclaw",
        session_run="openclaw agent --local --json --session-id {session_id} --model {provider}/{model} --timeout {timeout} --message {task}",
        run=(
            "openclaw agent exec --json --timeout {timeout} "
            "--model {provider}/{model} --cwd {workdir} {task}"
        ),
        model_env={"api_key": "OPENCLAW_API_KEY"},
        harness_image="evalclaw-openclaw:latest",
        home="root/.openclaw",
        gateway=True,
        gateway_setup=(
            "openclaw config set models.providers.{provider}.baseUrl {gateway_url} "
            "&& openclaw config set models.providers.{provider}.apiKey $OPENCLAW_API_KEY"
        ),
        preflight=("openclaw --version",),
        allowed_providers=("openai", "anthropic", "openai_compatible"),
    ),
    ManifestHarness(
        name="openhands",
        run=(
            "env OPENHANDS_SUPPRESS_BANNER=1 openhands-mounted --headless "
            "--override-with-envs --json --exit-without-confirmation -t {task}"
        ),
        model_env={
            "model": "LLM_MODEL",
            "api_key": "LLM_API_KEY",
            "base_url": "LLM_BASE_URL",
        },
        model_template="{provider}/{model}",
        harness_image="evalclaw-openhands:latest",
        preflight=("openhands-mounted --version",),
        gateway=True,
        allowed_providers=("openai", "anthropic", "openai_compatible"),
        failure_markers=('"kind": "ConversationErrorEvent"',),
    ),
)


def _register_builtin_manifests() -> None:
    for manifest in _BUILTIN_MANIFESTS:
        SUPPORTED_HARNESSES.add(manifest.name)
        register_harness(ManifestHarnessRunner(manifest))
