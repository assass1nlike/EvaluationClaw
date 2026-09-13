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
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from ..execution.docker import docker_subprocess_env, resolve_docker_executable
from ..execution.docker_images import (
    apply_docker_image_selection,
    build_docker_image_if_requested,
)
from ..execution.evaluation import parse_evaluator_result
from ..protocols.assets import environment_asset_sources
from ..protocols.task_agent import task_agent_initial_content_text, task_agent_system_prompt
from ..types import SUPPORTED_HARNESSES, BenchmarkConfig, BenchmarkItem, TargetModelConfig

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
    """Run a process while draining stdout and stderr into bounded buffers."""
    process = subprocess.Popen(
        command,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    captured: dict[str, tuple[bytes, bool]] = {}
    encoded_markers = {marker: marker.encode("utf-8") for marker in failure_markers}
    max_marker_length = max((len(marker) for marker in encoded_markers.values()), default=1)
    found_markers: set[str] = set()

    def drain(name: str, stream: Any) -> None:
        head = bytearray()
        tail = bytearray()
        half = _OUTPUT_LIMIT_BYTES // 2
        total = 0
        carry = b""
        while chunk := stream.read(64 * 1024):
            total += len(chunk)
            searchable = carry + chunk
            for marker, encoded in encoded_markers.items():
                if encoded in searchable:
                    found_markers.add(marker)
            carry = searchable[-(max_marker_length - 1):] if max_marker_length > 1 else b""
            remaining = half - len(head)
            if remaining > 0:
                head.extend(chunk[:remaining])
                chunk = chunk[remaining:]
            if chunk:
                tail.extend(chunk)
                if len(tail) > half:
                    del tail[:-half]
        if total > _OUTPUT_LIMIT_BYTES:
            value = bytes(head) + b"\n[output truncated]\n" + bytes(tail)
        else:
            value = bytes(head) + bytes(tail)
        captured[name] = (value, total > _OUTPUT_LIMIT_BYTES)

    threads = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        returncode = process.returncode
        timed_out = True
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        for thread in threads:
            thread.join()
    stdout = captured["stdout"][0].decode("utf-8", errors="replace")
    stderr = captured["stderr"][0].decode("utf-8", errors="replace")
    for marker in found_markers:
        if marker not in stdout and marker not in stderr:
            stderr += f"\n[detected failure marker] {marker}"
    if timed_out:
        raise subprocess.TimeoutExpired(
            command, timeout, output=stdout, stderr=stderr
        ) from None
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout,
        stderr,
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

    def evaluate(self, image: str, workdir: Path) -> tuple[float, str]: ...

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


@dataclass(frozen=True)
class DockerWorkspaceBackend:
    """The Docker environment backend used by manifest-based CLI harnesses."""

    item: BenchmarkItem
    config: BenchmarkConfig
    kind: str = "docker_workspace"

    def prepare(self) -> tuple[str, Path]:
        return prepare_docker_task(self.item, self.config)

    def evaluate(self, image: str, workdir: Path) -> tuple[float, str]:
        return score_docker_task(self.item, self.config, image, workdir)

    def cleanup(self, workdir: Path) -> None:
        shutil.rmtree(workdir, ignore_errors=True)


def environment_backend(item: BenchmarkItem, config: BenchmarkConfig) -> EnvironmentBackend:
    kind = str(agent_env(item).get("type") or "docker_workspace").strip().lower()
    if kind != "docker_workspace":
        raise RuntimeError(
            f"Harness-backed agent tasks require a docker_workspace backend; got {kind!r}. "
            "Use a harness adapter that explicitly supports this environment type."
        )
    return DockerWorkspaceBackend(item, config)


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


def agent_env(item: BenchmarkItem) -> dict[str, Any]:
    env = item.metadata.get("agent_env")
    return env if isinstance(env, dict) else {}


def reject_tool_constraints(item: BenchmarkItem) -> None:
    """Reject tasks that declare tool constraints a third-party harness can't honor."""
    env = agent_env(item)
    browser = env.get("browser") if isinstance(env.get("browser"), dict) else {}
    constrained = bool(
        env.get("workspace_tools")
        or browser.get("workspace_tools")
        or browser.get("allow_workspace_tools")
        or browser.get("enabled")
    )
    if constrained:
        raise RuntimeError(
            "Task declares tool constraints (workspace_tools/browser), which a third-party "
            "harness cannot enforce. Remove the harness or the tool constraints."
        )
    if env.get("runtime_files"):
        raise RuntimeError(
            "Harness-backed tasks cannot expose runner-private runtime_files to a shell agent. "
            "Bake runtime support into the task image or use the native agent runner."
        )
    if str(env.get("workdir") or "/workspace") != "/workspace":
        raise RuntimeError(
            "Harness-backed tasks currently require environment.workdir=/workspace."
        )


def _task_container_options(
    env: dict[str, Any],
    *,
    include_network: bool = True,
) -> list[str]:
    options = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        options += ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp"]
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
    system_prompt = task_agent_system_prompt(item, "")
    initial_content = task_agent_initial_content_text(item)
    if not system_prompt and not initial_content:
        return item.prompt
    parts: list[str] = []
    if system_prompt:
        parts.append(f"Task-specific instructions:\n{system_prompt}")
    parts.append(f"Task:\n{item.prompt}")
    if initial_content:
        parts.append(f"Initial task content:\n{initial_content}")
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
    env = _resolve_image_context(item, dict(agent_env(item)), config)
    task_text = item.prompt
    env, _ = apply_docker_image_selection(env, task_text=task_text)
    env, _ = build_docker_image_if_requested(
        env,
        task_text=task_text,
        docker_executable=config.docker_executable,
        timeout_s=600,
    )
    image = str(env.get("image") or "python:3.11-slim")
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
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    return image, workdir


def score_docker_task(
    item: BenchmarkItem,
    config: BenchmarkConfig,
    image: str,
    workdir: Path,
) -> tuple[float, str]:
    """Score by injecting hidden files and running the task's test command."""
    env = agent_env(item)
    test_command = str(env.get("test_command") or "pytest -q")
    evaluation = env.get("evaluation") if isinstance(env.get("evaluation"), dict) else {}
    result_path = str(evaluation.get("result_path") or "/workspace/evalclaw_result.json")
    score_path = str(evaluation.get("score_path") or "/workspace/score.txt")
    resolved = resolve_docker_executable(config.docker_executable)
    if not resolved:
        raise RuntimeError(f"Docker executable {config.docker_executable!r} not found.")
    container_name = f"evalclaw-score-{uuid.uuid4().hex[:12]}"
    hidden = env.get("hidden_files")
    hidden_dir: Path | None = None
    hidden_paths: list[str] = []
    if isinstance(hidden, dict):
        hidden_dir = Path(tempfile.mkdtemp(prefix="evalclaw-harness-hidden-"))
        try:
            for path, content in hidden.items():
                # Validate the target after the untrusted agent has exited. The
                # bytes themselves are staged separately so host permissions and
                # workspace links cannot redirect runner-private writes.
                _workspace_path(workdir, path)
                _write_workspace_file(hidden_dir, path, content)
                hidden_paths.append(str(PurePosixPath(str(path).replace("\\", "/"))))
        except Exception:
            shutil.rmtree(hidden_dir, ignore_errors=True)
            raise
    try:
        setup = env.get("setup_commands") if isinstance(env.get("setup_commands"), list) else []
        setup_script = " && ".join(
            shlex.join(["sh", "-lc", str(command)])
            for command in setup
            if str(command).strip()
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
                setup_script,
                "rm -f -- " + shlex.join([result_path, score_path]),
                test_command,
            )
            if part
        )
        run_args = [
            resolved,
            "run",
            "--rm",
            "--name",
            container_name,
            "-v",
            f"{workdir}:/workspace",
            "-w",
            "/workspace",
            *_task_container_options(env),
        ]
        if hidden_dir is not None:
            run_args += ["-v", f"{hidden_dir}:/evalclaw-hidden:ro"]
        run_args += [image, "sh", "-lc", " && ".join(evaluator_parts)]
        proc: subprocess.CompletedProcess[str] | None = None
        evaluator_timeout = _evaluation_timeout(item)
        try:
            proc = _run_bounded(
                run_args,
                timeout=evaluator_timeout,
                env=docker_subprocess_env(config.docker_executable),
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Harness evaluator timed out after {evaluator_timeout} seconds."
            ) from None
        finally:
            if proc is None:
                _remove_container(resolved, container_name)
    finally:
        if hidden_dir is not None:
            shutil.rmtree(hidden_dir, ignore_errors=True)
    result_json = ""
    score_text = ""
    def workspace_file(path: str) -> Path:
        prefix = "/workspace/"
        relative = path[len(prefix):] if path.startswith(prefix) else path
        return _workspace_path(workdir, relative)

    result_file = workspace_file(result_path)
    score_file = workspace_file(score_path)
    if result_file.is_file():
        result_json = result_file.read_text(encoding="utf-8", errors="replace")
    if score_file.is_file():
        score_text = score_file.read_text(encoding="utf-8", errors="replace")
    evaluator = parse_evaluator_result(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        result_json=result_json,
        score_text=score_text,
        allow_stdout_score=bool(evaluation.get("allow_stdout_score", False)),
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
    return subprocess.run(
        [docker, *args],
        capture_output=True,
        text=True,
        check=check,
        env=env,
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
) -> tuple[str, str, str]:
    """Start a model API gateway on an internal network.

    Returns ``(network, gateway_name, gateway_url)``. The gateway listens on the
    internal network (where the harness will run) and is also bridged so it can
    reach the model API; the harness container gets only the internal network.
    """
    tag = uuid.uuid4().hex[:8]
    network = f"evalclaw-harness-{tag}"
    gateway = f"evalclaw-gateway-{tag}"
    network_args = ["network", "create"]
    if internal:
        network_args.append("--internal")
    network_args.append(network)
    _docker(docker, network_args)
    try:
        _docker(
            docker,
            [
                "run", "-d", "--name", gateway, "--network", network,
                "-e", "EVALCLAW_UPSTREAM_API_KEY",
                _MODEL_GATEWAY_IMAGE,
                "--upstream", upstream,
                "--provider", provider,
                "--model", model,
                "--port", "18080",
            ],
            extra_env={"EVALCLAW_UPSTREAM_API_KEY": api_key},
        )
        if internal:
            _docker(docker, ["network", "connect", "bridge", gateway])
    except Exception:
        _docker(docker, ["rm", "-f", gateway], check=False)
        _docker(docker, ["network", "rm", network], check=False)
        raise
    time.sleep(1.0)  # let the gateway bind its port before the harness connects
    return network, gateway, f"http://{gateway}:18080"


def _stop_model_gateway(docker: str, network: str, gateway: str) -> None:
    _docker(docker, ["rm", "-f", gateway], check=False)
    _docker(docker, ["network", "rm", network], check=False)


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
    ) -> tuple[str, float, str]:
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        reject_tool_constraints(item)
        self._validate_target(target)
        backend = environment_backend(item, config)
        image, workdir = backend.prepare()
        context = HarnessContext(item, target, config, image, workdir)
        preflight: list[str] = []
        try:
            preflight = self._preflight(context)
            raw = self._launch(
                context.item, context.target, context.config, context.image, context.workdir
            )
            score, reasoning = backend.evaluate(context.image, context.workdir)
            raw = _redact_secret(raw, target.api_key)
            reasoning = _redact_secret(reasoning, target.api_key)
            if artifact_dir is not None:
                finished_at = datetime.now(timezone.utc)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / f"{self.name}-output.txt").write_text(raw, encoding="utf-8")
                (artifact_dir / f"{self.name}-reasoning.txt").write_text(reasoning, encoding="utf-8")
                self._collect_trajectory(workdir, artifact_dir)
                (artifact_dir / "episode.json").write_text(
                    json.dumps(
                        {
                            "item_id": item.id,
                            "task_sha256": _task_digest(item),
                            "target_id": target.id,
                            "harness": self.name,
                            "environment": backend.kind,
                            "model": target.model,
                            "provider": target.provider,
                            "status": "completed",
                            "score": score,
                            "started_at": started_at.isoformat(),
                            "finished_at": finished_at.isoformat(),
                            "duration_ms": round((time.monotonic() - started) * 1000),
                            "timeouts": {
                                "harness_seconds": self._episode_timeout(item),
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
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            return raw, score, reasoning
        except BaseException as exc:
            if artifact_dir is not None:
                finished_at = datetime.now(timezone.utc)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                if isinstance(exc, HarnessExecutionError):
                    (artifact_dir / f"{self.name}-output.txt").write_text(
                        _redact_secret(exc.stdout, target.api_key), encoding="utf-8"
                    )
                    (artifact_dir / f"{self.name}-stderr.txt").write_text(
                        _redact_secret(exc.stderr, target.api_key), encoding="utf-8"
                    )
                self._collect_trajectory(workdir, artifact_dir)
                (artifact_dir / "episode.json").write_text(
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
                            "error": _redact_secret(
                                f"{type(exc).__name__}: {exc}", target.api_key
                            ),
                            "started_at": started_at.isoformat(),
                            "finished_at": finished_at.isoformat(),
                            "duration_ms": round((time.monotonic() - started) * 1000),
                            "timeouts": {
                                "harness_seconds": self._episode_timeout(item),
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
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            raise
        finally:
            backend.cleanup(workdir)

    def _tool_image(self) -> str | None:
        return self._manifest.harness_image or self._manifest.runtime_image

    def _episode_timeout(self, item: BenchmarkItem) -> int:
        env = agent_env(item)
        max_steps = max(1, int(env.get("max_steps") or 8))
        step_timeout = max(1, int(env.get("timeout") or 20))
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

    def _mount_tool_image(self, run_args: list[str]) -> None:
        tool_image = self._tool_image()
        if tool_image:
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

    def _launch(self, item: BenchmarkItem, target: TargetModelConfig, config: BenchmarkConfig, image: str, workdir: Path) -> str:
        env = agent_env(item)
        max_steps = max(1, int(env.get("max_steps") or 8))
        step_timeout = max(1, int(env.get("timeout") or 20))
        episode_timeout = self._episode_timeout(item)
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
        gateway_network: str | None = None
        gateway_name: str | None = None
        container_name = f"evalclaw-harness-{uuid.uuid4().hex[:12]}"
        try:
            if self._manifest.gateway:
                if str(env.get("network") or "none").strip().lower() == "internet":
                    gateway_network, gateway_name, base_url = _start_model_gateway(
                        resolved,
                        base_url,
                        internal=False,
                        api_key=target.api_key or "",
                        provider=provider,
                        model=model,
                    )
                else:
                    gateway_network, gateway_name, base_url = _start_model_gateway(
                        resolved,
                        base_url,
                        api_key=target.api_key or "",
                        provider=provider,
                        model=model,
                    )
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
            run_args: list[str] = [
                resolved, "run", "--rm",
                "--name", container_name,
                "-v", f"{workdir}:/workspace",
                "-w", "/workspace",
                *_task_container_options(env, include_network=not self._manifest.gateway),
            ]
            self._mount_tool_image(run_args)
            if gateway_network is not None:
                run_args += ["--network", gateway_network]
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
                    run_args += ["-e", var_name]
            shell_command = shlex.join(command)
            prefix = self._runtime_prefix()
            for setup in env.get("setup_commands", []):
                if setup:
                    prefix += shlex.join(["sh", "-lc", str(setup)]) + " && "
            for setup in self._manifest.setup:
                prefix += shlex.join(["sh", "-lc", setup]) + " && "
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
            run_args += [image, "sh", "-lc", prefix + shell_command]
            proc: subprocess.CompletedProcess[str] | None = None
            try:
                proc = _run_bounded(
                    run_args,
                    stdin=subprocess.DEVNULL,
                timeout=episode_timeout,
                env=docker_env,
                failure_markers=self._manifest.failure_markers,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(
                    exc.stdout, bytes
                ) else exc.stdout or ""
                stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(
                    exc.stderr, bytes
                ) else exc.stderr or ""
                raise HarnessTimeoutError(
                    self.name, episode_timeout, stdout, stderr
                ) from None
            except FileNotFoundError as exc:
                raise RuntimeError(f"Harness command not found for {self.name!r}.") from exc
            finally:
                if proc is None:
                    _remove_container(resolved, container_name)
            cleanup_only_failure = (
                self.name == "openclaw"
                and "ended with stopReason=stop" in proc.stderr
                and "Agent runtime cleanup did not settle" in proc.stderr
                and bool(proc.stdout.strip())
            )
            if proc.returncode != 0 and not cleanup_only_failure:
                details = _redact_secret(proc.stderr or proc.stdout, target.api_key)
                raise HarnessExecutionError(
                    f"Harness {self.name!r} failed: {details}",
                    proc.stdout,
                    proc.stderr,
                )
            for marker in self._manifest.failure_markers:
                if marker in proc.stdout or marker in proc.stderr:
                    details = _redact_secret(proc.stderr or proc.stdout, target.api_key)
                    raise HarnessExecutionError(
                        f"Harness {self.name!r} reported an execution error: {details}",
                        proc.stdout,
                        proc.stderr,
                    )
            return proc.stdout
        finally:
            if gateway_name is not None:
                _stop_model_gateway(resolved, gateway_network or "", gateway_name)

    def _preflight(self, context: HarnessContext) -> list[str]:
        if not self._manifest.preflight:
            return []
        resolved = resolve_docker_executable(context.config.docker_executable)
        if not resolved:
            raise RuntimeError(
                f"Docker executable {context.config.docker_executable!r} not found."
            )
        outputs: list[str] = []
        for command in self._manifest.preflight:
            container_name = f"evalclaw-preflight-{uuid.uuid4().hex[:12]}"
            rendered = command.format(
                model=shlex.quote(context.target.model),
                provider=shlex.quote(context.target.provider),
                workdir="/workspace",
            )
            run_args = [
                resolved,
                "run",
                "--rm",
                "--name",
                container_name,
                "-v",
                f"{context.workdir}:/workspace",
                "-w",
                "/workspace",
                *_task_container_options(agent_env(context.item)),
            ]
            self._mount_tool_image(run_args)
            run_args += [context.image, "sh", "-lc", self._runtime_prefix() + rendered]
            probe: subprocess.CompletedProcess[str] | None = None
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
            finally:
                if probe is None:
                    _remove_container(resolved, container_name)
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
