"""Docker-backed agent environments for realistic tool-use evaluations."""
from __future__ import annotations

import shlex
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ..protocols.tool import ToolSpec, format_tool_specs_for_prompt, object_schema
from .docker import docker_status, docker_subprocess_env, resolve_docker_executable
from .docker_images import (
    apply_docker_image_selection,
    build_docker_image_if_requested,
    inspect_docker_image,
)


@dataclass
class DockerAgentStepOutcome:
    observation: str
    done: bool = False
    error: str | None = None


def _docker_setup_message(executable: str) -> str:
    return (
        "Docker is required for agent_env.type='docker_workspace', but it is not ready.\n\n"
        "Setup/configuration commands:\n"
        "1. Install and start Docker Desktop:\n"
        "   winget install -e --id Docker.DockerDesktop\n"
        "2. Verify Docker from this shell:\n"
        f"   {executable} version\n"
        "   docker run --rm hello-world\n\n"
        "EvaluationClaw does not install Docker automatically. Configure Docker, then rerun the benchmark."
    )


@dataclass
class DockerWorkspaceAgentEnvironment:
    """A containerized workspace for realistic multi-step tool-use tasks."""

    image: str
    visible_files: dict[str, str]
    hidden_files: dict[str, str]
    setup_commands: list[str] = field(default_factory=list)
    test_command: str = "pytest -q"
    max_steps: int = 8
    timeout: int = 20
    docker_executable: str = "docker"
    network: str = "none"
    pull_image: bool = True
    pull_timeout: int = 300
    memory: str | None = None
    cpus: str | None = None
    workdir: str = "/workspace"
    steps: int = 0
    invalid_actions: int = 0
    done: bool = False
    last_test: dict[str, Any] | None = None
    test_runs: int = 0
    last_command: dict[str, Any] | None = None
    _container_name: str = ""
    _tmp: tempfile.TemporaryDirectory[str] | None = None
    _root: Path | None = None
    _visible_paths: set[str] = field(default_factory=set)
    _hidden_paths: set[str] = field(default_factory=set)
    _docker: str = "docker"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "DockerWorkspaceAgentEnvironment":
        task_text = "\n".join(
            str(config.get(key) or "")
            for key in ("prompt", "task_text", "description", "notes")
            if config.get(key)
        )
        config, _ = apply_docker_image_selection(
            {**config, "type": "docker_workspace"},
            task_text=task_text,
        )
        image_build = config.get("image_build") if isinstance(config.get("image_build"), dict) else {}
        config, _ = build_docker_image_if_requested(
            config,
            task_text=task_text,
            docker_executable=str(config.get("docker_executable") or "docker"),
            timeout_s=max(
                1,
                int(config.get("build_timeout") or config.get("image_build_timeout") or image_build.get("build_timeout") or 600),
            ),
        )
        visible = config.get("visible_files")
        if not isinstance(visible, dict):
            visible = config.get("files") if isinstance(config.get("files"), dict) else {}
        hidden = config.get("hidden_files") if isinstance(config.get("hidden_files"), dict) else {}
        setup = config.get("setup_commands")
        if isinstance(setup, str):
            setup_commands = [setup]
        elif isinstance(setup, list):
            setup_commands = [str(command) for command in setup if str(command).strip()]
        else:
            setup_commands = []
        resources = config.get("resource_limits") if isinstance(config.get("resource_limits"), dict) else {}
        env = cls(
            image=str(config.get("image") or "python:3.11-slim"),
            visible_files={str(path): str(content) for path, content in visible.items()},
            hidden_files={str(path): str(content) for path, content in hidden.items()},
            setup_commands=setup_commands,
            test_command=str(config.get("test_command") or "pytest -q"),
            max_steps=max(1, int(config.get("max_steps") or 8)),
            timeout=max(1, int(config.get("timeout") or 20)),
            docker_executable=str(config.get("docker_executable") or "docker"),
            network=str(config.get("network") or "none"),
            pull_image=bool(config.get("pull_image", True)),
            pull_timeout=max(1, int(config.get("pull_timeout") or 300)),
            memory=str(resources.get("memory") or config.get("memory") or "") or None,
            cpus=str(resources.get("cpus") or config.get("cpus") or "") or None,
            workdir=str(config.get("workdir") or "/workspace"),
        )
        env._setup()
        return env

    @property
    def root(self) -> Path:
        if self._root is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="evalclaw-agent-docker-")
            self._root = Path(self._tmp.name)
        return self._root

    def _clean_path(self, value: object) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts:
            return None
        return str(path)

    def _write_local_file(self, path: str, content: str, *, hidden: bool = False) -> None:
        base = self.root / ("__hidden__" if hidden else "__visible__")
        target = base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _run_docker(self, args: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self._docker, *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
            env=docker_subprocess_env(self.docker_executable),
        )

    def _exec_shell(self, command: str, *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return self._run_docker(
            [
                "exec",
                "--workdir",
                self.workdir,
                self._container_name,
                "sh",
                "-lc",
                command,
            ],
            timeout=(timeout or self.timeout) + 5,
        )

    def _require_ok(self, proc: subprocess.CompletedProcess[str], action: str) -> None:
        if proc.returncode == 0:
            return
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Docker {action} failed: {detail}")

    def _copy_to_container(self, source: Path, target: str) -> None:
        proc = self._run_docker(["cp", str(source), f"{self._container_name}:{target}"], timeout=self.timeout + 10)
        self._require_ok(proc, f"cp {source} {target}")

    def _copy_workspace_file(self, local: Path, path: str) -> None:
        parent = str(PurePosixPath(path).parent)
        if parent != ".":
            self._require_ok(
                self._exec_shell(f"mkdir -p -- {shlex.quote(parent)}", timeout=self.timeout),
                f"mkdir {parent}",
            )
        self._copy_to_container(local, f"{self.workdir}/{path}")

    def _setup(self) -> None:
        status = docker_status(executable=self.docker_executable)
        if not status.available:
            raise RuntimeError(_docker_setup_message(self.docker_executable) + f"\n\nDocker error: {status.error}")
        resolved = resolve_docker_executable(self.docker_executable)
        if not resolved:
            raise RuntimeError(_docker_setup_message(self.docker_executable))
        self._docker = resolved
        self._container_name = f"evalclaw-agent-{uuid.uuid4().hex[:12]}"
        self._tmp = tempfile.TemporaryDirectory(prefix="evalclaw-agent-docker-")
        self._root = Path(self._tmp.name)

        for path, content in self.visible_files.items():
            clean = self._clean_path(path)
            if clean is None:
                continue
            self._write_local_file(clean, content)
            self._visible_paths.add(clean)
        for path, content in self.hidden_files.items():
            clean = self._clean_path(path)
            if clean is None:
                continue
            self._write_local_file(clean, content, hidden=True)
            self._hidden_paths.add(clean)

        try:
            if self.pull_image:
                probe = inspect_docker_image(
                    self.image,
                    docker_executable=self.docker_executable,
                    timeout_s=min(30, max(self.timeout, 1)),
                )
                if not probe.local:
                    self._require_ok(
                        self._run_docker(["pull", self.image], timeout=max(self.pull_timeout, self.timeout)),
                        "pull",
                    )
            create = ["create", "--name", self._container_name, "--workdir", self.workdir, "--network", self.network]
            if self.memory:
                create.extend(["--memory", self.memory])
            if self.cpus:
                create.extend(["--cpus", self.cpus])
            create.extend([self.image, "sleep", "infinity"])
            self._require_ok(self._run_docker(create, timeout=self.timeout), "create")
            self._require_ok(self._run_docker(["start", self._container_name], timeout=self.timeout), "start")
            self._require_ok(self._exec_shell(f"mkdir -p {shlex.quote(self.workdir)}"), "mkdir workspace")
            visible_root = self.root / "__visible__"
            for path in sorted(self._visible_paths):
                self._copy_workspace_file(visible_root / path, path)
            for command in self.setup_commands:
                self._require_ok(self._exec_shell(command, timeout=self.timeout), f"setup command {command!r}")
        except Exception:
            self.cleanup()
            raise

    def _list_visible_files(self) -> list[str]:
        if not self._container_name:
            return []
        proc = self._exec_shell("find . -type f | sed 's#^./##' | sort", timeout=self.timeout)
        if proc.returncode != 0:
            return []
        hidden = set(self._hidden_paths)
        files = []
        for line in proc.stdout.splitlines():
            clean = self._clean_path(line)
            if clean is None or clean in hidden or "__pycache__/" in clean or clean.endswith(".pyc"):
                continue
            files.append(clean)
        return sorted(set(files))

    def _read_file(self, path: str, limit: int = 6000) -> tuple[str, str | None]:
        clean = self._clean_path(path)
        if clean is None:
            return "", "Invalid path."
        if clean in self._hidden_paths:
            return "", f"Cannot read hidden test file: {clean}"
        proc = self._exec_shell(f"cat -- {shlex.quote(clean)}", timeout=self.timeout)
        if proc.returncode != 0:
            return "", f"File not found or unreadable: {clean}"
        content = proc.stdout
        if len(content) <= limit:
            return content, None
        half = max(1, limit // 2)
        return content[:half] + "\n...\n" + content[-half:], None

    def _write_file(self, path: str, content: str) -> str | None:
        clean = self._clean_path(path)
        if clean is None:
            return "Invalid path."
        if clean in self._hidden_paths:
            return f"Cannot overwrite hidden test file: {clean}"
        scratch = self.root / "__write__"
        scratch.mkdir(parents=True, exist_ok=True)
        local = scratch / clean
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(content, encoding="utf-8")
        try:
            self._copy_workspace_file(local, clean)
        except RuntimeError as exc:
            return str(exc)
        self._visible_paths.add(clean)
        return None

    def _copy_hidden_files(self) -> None:
        hidden_root = self.root / "__hidden__"
        for path in sorted(self._hidden_paths):
            self._copy_workspace_file(hidden_root / path, path)

    def _remove_hidden_files(self) -> None:
        if not self._hidden_paths:
            return
        quoted = " ".join(shlex.quote(path) for path in sorted(self._hidden_paths))
        self._exec_shell(f"rm -f -- {quoted}", timeout=self.timeout)

    def tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="list_files",
                description="List visible files in the container workspace. Hidden test files are excluded.",
                parameters=object_schema({"path": {"type": "string"}}, additional_properties=True),
            ),
            ToolSpec(
                name="read_file",
                description="Read a visible workspace file by relative path. Hidden files cannot be read.",
                parameters=object_schema({"path": {"type": "string"}}, required=["path"]),
            ),
            ToolSpec(
                name="write_file",
                description="Write complete file content to a visible relative path in the container workspace.",
                parameters=object_schema(
                    {"path": {"type": "string"}, "content": {"type": "string"}},
                    required=["path", "content"],
                ),
            ),
            ToolSpec(
                name="run_command",
                description="Run a shell command inside the container workspace. Use for diagnostics, not final scoring.",
                parameters=object_schema(
                    {"command": {"type": "string"}, "timeout": {"type": "integer"}},
                    required=["command"],
                    additional_properties=True,
                ),
            ),
            ToolSpec(
                name="run_tests",
                description="Run the configured hidden-test command inside the container workspace.",
                parameters=object_schema(),
            ),
            ToolSpec(
                name="final",
                description="Finish the task with a brief completion summary.",
                parameters=object_schema({"answer": {"type": "string"}}),
            ),
        ]

    def action_schema(self) -> str:
        return format_tool_specs_for_prompt(self.tool_specs())

    def observation(self) -> str:
        test_summary = "not run"
        if self.last_test:
            status = "passed" if self.last_test.get("passed") else "failed"
            test_summary = f"{status}; returncode={self.last_test.get('returncode')}"
        command_summary = "not run"
        if self.last_command:
            command_summary = f"returncode={self.last_command.get('returncode')}"
        return (
            f"Environment: docker_workspace\n"
            f"Image: {self.image}\n"
            f"Visible files: {self._list_visible_files() or 'none'}\n"
            f"Hidden files: {len(self._hidden_paths)} file(s), injected only during run_tests.\n"
            f"Test command: {self.test_command}\n"
            f"Last command: {command_summary}\n"
            f"Last test: {test_summary}\n"
            f"Test runs: {self.test_runs}\n"
            f"Steps used: {self.steps}/{self.max_steps}"
        )

    def step(self, action: dict[str, Any]) -> DockerAgentStepOutcome:
        if self.done:
            return DockerAgentStepOutcome(self.observation(), done=True)
        self.steps += 1
        name = str(action.get("action") or action.get("tool") or "").strip().lower()
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        error: str | None = None
        detail = ""

        try:
            if name == "list_files":
                detail = "Visible files:\n" + "\n".join(self._list_visible_files())
            elif name == "read_file":
                content, error = self._read_file(str(args.get("path") or ""))
                if not error:
                    detail = f"File {args.get('path')}:\n{content}"
            elif name == "write_file":
                content = args.get("content")
                if not isinstance(content, str):
                    error = "write_file requires string content."
                else:
                    error = self._write_file(str(args.get("path") or ""), content)
                    if not error:
                        detail = f"Wrote {args.get('path')} ({len(content)} chars)."
            elif name == "run_command":
                command = str(args.get("command") or "").strip()
                command_timeout = int(args.get("timeout") or self.timeout)
                if not command:
                    error = "run_command requires command."
                else:
                    proc = self._exec_shell(command, timeout=max(1, min(command_timeout, self.timeout)))
                    output = (proc.stdout + proc.stderr).strip()
                    if len(output) > 4000:
                        output = output[:2000] + "\n...\n" + output[-2000:]
                    self.last_command = {
                        "command": command,
                        "returncode": proc.returncode,
                        "stdout": proc.stdout[-2000:],
                        "stderr": proc.stderr[-2000:],
                    }
                    detail = f"Command finished with returncode {proc.returncode}.\n{output}"
            elif name in {"run_tests", "run_test"}:
                self.test_runs += 1
                try:
                    self._copy_hidden_files()
                    proc = self._exec_shell(self.test_command, timeout=self.timeout)
                finally:
                    self._remove_hidden_files()
                output = (proc.stdout + proc.stderr).strip()
                if len(output) > 4000:
                    output = output[:2000] + "\n...\n" + output[-2000:]
                self.last_test = {
                    "passed": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-2000:],
                }
                status = "passed" if proc.returncode == 0 else "failed"
                detail = f"Tests {status} with returncode {proc.returncode}.\n{output}"
            elif name == "final":
                self.done = True
                detail = str(args.get("answer") or "Final answer received.")
            else:
                error = f"Unknown action: {name or '<missing>'}"
        except subprocess.TimeoutExpired:
            error = f"Command timed out after {self.timeout} seconds."
        except Exception as exc:
            error = str(exc)

        if error:
            self.invalid_actions += 1
        if self.score() >= 1.0 or self.steps >= self.max_steps:
            self.done = True
        prefix = f"Error: {error}\n\n" if error else ""
        suffix = f"\n\n{detail}" if detail else ""
        return DockerAgentStepOutcome(prefix + self.observation() + suffix, done=self.done, error=error)

    def score(self) -> float:
        if self.last_test and self.last_test.get("passed"):
            return 1.0
        if self.test_runs > 0:
            return 0.25
        return 0.0

    def summary(self) -> str:
        status = "not_run"
        if self.last_test:
            status = "passed" if self.last_test.get("passed") else "failed"
        return (
            f"score={self.score():.2f}; steps={self.steps}/{self.max_steps}; "
            f"test_status={status}; test_runs={self.test_runs}; invalid_actions={self.invalid_actions}"
        )

    def state(self) -> dict[str, Any]:
        return {
            "environment": "docker_workspace",
            "image": self.image,
            "container_name": self._container_name,
            "visible_files": self._list_visible_files(),
            "hidden_files": sorted(self._hidden_paths),
            "steps": self.steps,
            "max_steps": self.max_steps,
            "invalid_actions": self.invalid_actions,
            "test_runs": self.test_runs,
            "last_command": self.last_command,
            "last_test": self.last_test,
            "done": self.done,
            "score": self.score(),
        }

    def cleanup(self) -> None:
        if self._container_name:
            self._run_docker(["rm", "-f", self._container_name], timeout=self.timeout)
            self._container_name = ""
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
            self._root = None
