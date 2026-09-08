"""Docker-backed agent environments for realistic tool-use evaluations."""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ..protocols.tool import ToolSpec, format_tool_specs_for_prompt, object_schema
from .docker import docker_status, docker_subprocess_env, resolve_docker_executable
from .docker_browser import (
    DOCKER_BROWSER_CONFIG_PATH,
    DOCKER_BROWSER_PORT,
    DOCKER_BROWSER_RUNTIME_PATH,
    DOCKER_BROWSER_RUNTIME_SCRIPT,
    docker_browser_tool_specs,
)
from .docker_images import (
    apply_docker_image_selection,
    build_docker_image_if_requested,
    inspect_docker_image,
)
from .evaluation import EvaluatorResult, parse_evaluator_result


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
    runtime_files: dict[str, str] = field(default_factory=dict)
    input_assets: dict[str, Path] = field(default_factory=dict)
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
    browser: dict[str, Any] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    environment_kind: str = "docker_workspace"
    allowed_workspace_tools: set[str] = field(default_factory=set)
    expose_test_tool: bool = True
    auto_evaluate_on_final: bool = False
    steps: int = 0
    invalid_actions: int = 0
    done: bool = False
    last_test: dict[str, Any] | None = None
    evaluator_runs: list[dict[str, Any]] = field(default_factory=list)
    test_runs: int = 0
    last_command: dict[str, Any] | None = None
    final_answer: str = ""
    browser_calls: int = 0
    _container_name: str = ""
    _tmp: tempfile.TemporaryDirectory[str] | None = None
    _root: Path | None = None
    _visible_paths: set[str] = field(default_factory=set)
    _runtime_paths: set[str] = field(default_factory=set)
    _hidden_paths: set[str] = field(default_factory=set)
    _docker: str = "docker"

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        *,
        input_assets: dict[str, Path] | None = None,
    ) -> "DockerWorkspaceAgentEnvironment":
        environment_kind = str(config.get("type") or "docker_workspace")
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
        runtime = config.get("runtime_files") if isinstance(config.get("runtime_files"), dict) else {}
        setup = config.get("setup_commands")
        if isinstance(setup, str):
            setup_commands = [setup]
        elif isinstance(setup, list):
            setup_commands = [str(command) for command in setup if str(command).strip()]
        else:
            setup_commands = []
        resources = config.get("resource_limits") if isinstance(config.get("resource_limits"), dict) else {}
        browser = config.get("browser") if isinstance(config.get("browser"), dict) else {}
        evaluation = config.get("evaluation") if isinstance(config.get("evaluation"), dict) else {}
        configured_tools = config.get("workspace_tools")
        allowed_workspace_tools = (
            {str(name) for name in configured_tools}
            if isinstance(configured_tools, list)
            else set()
        )
        browser_enabled = bool(browser.get("enabled"))
        env = cls(
            image=str(config.get("image") or "python:3.11-slim"),
            visible_files={str(path): str(content) for path, content in visible.items()},
            runtime_files={str(path): str(content) for path, content in runtime.items()},
            hidden_files={str(path): str(content) for path, content in hidden.items()},
            input_assets=dict(input_assets or {}),
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
            browser=browser,
            evaluation=evaluation,
            environment_kind=environment_kind,
            allowed_workspace_tools=allowed_workspace_tools,
            expose_test_tool=bool(config.get("expose_test_tool", not browser_enabled)),
            auto_evaluate_on_final=bool(config.get("auto_evaluate_on_final", browser_enabled)),
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
        if path.is_absolute():
            try:
                path = path.relative_to(PurePosixPath(self.workdir))
            except ValueError:
                return None
        if ".." in path.parts:
            return None
        return str(path)

    def _write_local_file(self, path: str, content: str, *, area: str = "visible") -> None:
        base = self.root / f"__{area}__"
        target = base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _run_docker(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self._docker, *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
            input=input_text,
            env=docker_subprocess_env(self.docker_executable),
        )

    def _exec_shell(
        self,
        command: str,
        *,
        timeout: int | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        exec_args = ["exec"]
        if input_text is not None:
            exec_args.append("-i")
        return self._run_docker(
            [
                *exec_args,
                "--workdir",
                self.workdir,
                self._container_name,
                "sh",
                "-lc",
                command,
            ],
            timeout=(timeout or self.timeout) + 5,
            input_text=input_text,
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
        for path, content in self.runtime_files.items():
            clean = self._clean_path(path)
            if clean is None:
                continue
            self._write_local_file(clean, content, area="runtime")
            self._runtime_paths.add(clean)
        for path, content in self.hidden_files.items():
            clean = self._clean_path(path)
            if clean is None:
                continue
            self._write_local_file(clean, content, area="hidden")
            self._hidden_paths.add(clean)
        input_assets: dict[str, Path] = {}
        for path, source in self.input_assets.items():
            clean = self._clean_path(path)
            if clean is None:
                raise ValueError(f"Invalid environment asset guest path: {path!r}.")
            if clean in self._visible_paths | self._runtime_paths | self._hidden_paths:
                raise ValueError(
                    f"Environment asset would overwrite a declared environment file: {clean!r}."
                )
            if not source.is_file():
                raise ValueError(
                    f"Environment asset source does not exist or is not a file: {source}."
                )
            input_assets[clean] = source
        self.input_assets = input_assets

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
            create.extend(
                [
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "256",
                ]
            )
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
            for path, source in sorted(self.input_assets.items()):
                self._copy_workspace_file(source, path)
                self._visible_paths.add(path)
            runtime_root = self.root / "__runtime__"
            for path in sorted(self._runtime_paths):
                self._copy_workspace_file(runtime_root / path, path)
            for command in self.setup_commands:
                self._require_ok(self._exec_shell(command, timeout=self.timeout), f"setup command {command!r}")
            self._setup_browser_runtime()
        except Exception:
            self.cleanup()
            raise

    def _setup_browser_runtime(self) -> None:
        if not bool(self.browser.get("enabled")):
            return
        start_url = str(self.browser.get("start_url") or "").strip()
        if not start_url:
            raise RuntimeError("Docker browser runtime requires browser.start_url.")
        runtime_root = self.root / "__browser_runtime__"
        runtime_root.mkdir(parents=True, exist_ok=True)
        runtime_script = runtime_root / "browser_runtime.py"
        runtime_config = runtime_root / "browser_config.json"
        runtime_script.write_text(DOCKER_BROWSER_RUNTIME_SCRIPT, encoding="utf-8")
        runtime_config.write_text(
            json.dumps(
                {
                    "start_url": start_url,
                    "allowed_origins": self.browser.get("allowed_origins") or [],
                    "timeout_ms": int(self.browser.get("timeout_ms") or 15000),
                    "startup_timeout": int(self.browser.get("startup_timeout") or 45),
                    "executable_path": str(self.browser.get("executable_path") or ""),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self._require_ok(self._exec_shell("mkdir -p /opt/evalclaw"), "create browser runtime directory")
        self._copy_to_container(runtime_script, DOCKER_BROWSER_RUNTIME_PATH)
        self._copy_to_container(runtime_config, DOCKER_BROWSER_CONFIG_PATH)
        start = (
            f"nohup python3 {shlex.quote(DOCKER_BROWSER_RUNTIME_PATH)} serve "
            f"--port {DOCKER_BROWSER_PORT} >/tmp/evalclaw-browser.log 2>&1 &"
        )
        self._require_ok(self._exec_shell(start, timeout=self.timeout), "start browser runtime")
        startup_timeout = max(5, int(self.browser.get("startup_timeout") or 45))
        probe = (
            f"i=0; while [ $i -lt {startup_timeout} ]; do "
            f"python3 {shlex.quote(DOCKER_BROWSER_RUNTIME_PATH)} ping --port {DOCKER_BROWSER_PORT} "
            ">/dev/null 2>&1 && exit 0; i=$((i+1)); sleep 1; done; "
            "cat /tmp/evalclaw-browser.log >&2; exit 1"
        )
        self._require_ok(
            self._exec_shell(probe, timeout=startup_timeout + 5),
            "wait for browser runtime",
        )

    def _list_visible_files(self) -> list[str]:
        if not self._container_name:
            return []
        proc = self._exec_shell("find . -type f | sed 's#^./##' | sort", timeout=self.timeout)
        if proc.returncode != 0:
            return []
        hidden = set(self._hidden_paths) | set(self._runtime_paths)
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
        if clean in self._hidden_paths or clean in self._runtime_paths:
            return "", f"Cannot read protected runtime/evaluator file: {clean}"
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
        if clean in self._hidden_paths or clean in self._runtime_paths:
            return f"Cannot overwrite protected runtime/evaluator file: {clean}"
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

    def _snapshot_workspace(self) -> None:
        self._require_ok(
            self._exec_shell(
                f"tar -cf /tmp/evalclaw-workspace-before-eval.tar -C {shlex.quote(self.workdir)} .",
                timeout=self.timeout,
            ),
            "snapshot workspace before evaluator",
        )

    def _restore_workspace(self) -> None:
        command = (
            f"find {shlex.quote(self.workdir)} -mindepth 1 -delete && "
            f"tar --no-same-owner -xf /tmp/evalclaw-workspace-before-eval.tar -C {shlex.quote(self.workdir)} && "
            "rm -f /tmp/evalclaw-workspace-before-eval.tar"
        )
        self._require_ok(
            self._exec_shell(command, timeout=self.timeout),
            "restore workspace after evaluator",
        )

    def _browser_call(self, name: str, args: dict[str, Any]) -> tuple[str, str | None]:
        if not bool(self.browser.get("enabled")):
            return "", "Browser runtime is not enabled for this task."
        command = (
            f"python3 {shlex.quote(DOCKER_BROWSER_RUNTIME_PATH)} call {shlex.quote(name)} "
            f"--port {DOCKER_BROWSER_PORT}"
        )
        proc = self._exec_shell(
            command,
            timeout=max(self.timeout, int(self.browser.get("action_timeout") or self.timeout)),
            input_text=json.dumps(args, ensure_ascii=False),
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "Browser tool failed.").strip()
            return "", detail[-4000:]
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return "", f"Browser runtime returned invalid JSON: {proc.stdout[-1000:]}"
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return "", str(payload.get("error") if isinstance(payload, dict) else payload)
        encoded = json.dumps(payload.get("result") or {}, ensure_ascii=False, indent=2)
        if len(encoded) > 18000:
            encoded = encoded[:9000] + "\n... browser snapshot truncated ...\n" + encoded[-9000:]
        self.browser_calls += 1
        return encoded, None

    def _write_final_answer(self, answer: str) -> None:
        payload = json.dumps({"answer": answer}, ensure_ascii=False)
        self._require_ok(
            self._exec_shell(
                "cat > /tmp/evalclaw_final_answer.json",
                timeout=self.timeout,
                input_text=payload,
            ),
            "write final answer",
        )

    def _run_configured_tests(self) -> str:
        self.test_runs += 1
        result_path = str(self.evaluation.get("result_path") or f"{self.workdir}/evalclaw_result.json")
        score_path = str(self.evaluation.get("score_path") or f"{self.workdir}/score.txt")
        snapshotted = False
        try:
            self._snapshot_workspace()
            snapshotted = True
            self._exec_shell(
                f"rm -f -- {shlex.quote(result_path)} {shlex.quote(score_path)}",
                timeout=self.timeout,
            )
            self._copy_hidden_files()
            proc = self._exec_shell(self.test_command, timeout=self.timeout)
            result_proc = self._exec_shell(f"cat -- {shlex.quote(result_path)}", timeout=self.timeout)
            score_proc = self._exec_shell(f"cat -- {shlex.quote(score_path)}", timeout=self.timeout)
        finally:
            self._remove_hidden_files()
            if snapshotted:
                self._restore_workspace()
        evaluator = parse_evaluator_result(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            result_json=result_proc.stdout if result_proc.returncode == 0 else "",
            score_text=score_proc.stdout if score_proc.returncode == 0 else "",
            allow_stdout_score=bool(self.evaluation.get("allow_stdout_score", False)),
        )
        self.evaluator_runs.append(
            {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "result_json": result_proc.stdout if result_proc.returncode == 0 else "",
                "score_text": score_proc.stdout if score_proc.returncode == 0 else "",
                "evaluator": evaluator.as_dict(),
            }
        )
        self.last_test = {
            "passed": evaluator.passed,
            "score": evaluator.score,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
            "evaluator": evaluator.as_dict(),
        }
        status = "passed" if evaluator.passed else "not passed"
        detail = f" Details: {evaluator.details}" if evaluator.details else ""
        return (
            f"Evaluator {status} with score={evaluator.score:.4f}, "
            f"returncode={proc.returncode}.{detail}"
        )

    def preflight(self) -> EvaluatorResult:
        """Verify setup and evaluator materialization in an isolated container."""
        self._run_configured_tests()
        assert self.last_test is not None
        combined_output = "\n".join(
            str(self.last_test.get(key) or "") for key in ("stderr", "stdout")
        ).lower()
        missing_evaluator_markers = (
            "can't open file",
            "cannot open file",
            "file or directory not found:",
        )
        invocation_failed = self.last_test["returncode"] in {126, 127} or (
            not bool(self.last_test.get("evaluator", {}).get("structured"))
            and any(marker in combined_output for marker in missing_evaluator_markers)
        )
        if invocation_failed:
            raise RuntimeError(
                f"Evaluator command could not be invoked: {self.last_test.get('stderr') or self.last_test.get('stdout')}"
            )
        return EvaluatorResult(**self.last_test["evaluator"])

    def tool_specs(self) -> list[ToolSpec]:
        workspace_tools = [
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
        ]
        if self._runtime_paths or self._hidden_paths:
            workspace_tools = [tool for tool in workspace_tools if tool.name != "run_command"]
        if self.allowed_workspace_tools:
            workspace_tools = [
                tool for tool in workspace_tools if tool.name in self.allowed_workspace_tools
            ]
        tools: list[ToolSpec] = []
        if bool(self.browser.get("enabled")):
            tools.extend(docker_browser_tool_specs())
            configured_workspace_tools = self.browser.get("workspace_tools")
            if isinstance(configured_workspace_tools, list):
                allowed = {str(name) for name in configured_workspace_tools}
                tools.extend(tool for tool in workspace_tools if tool.name in allowed)
            elif bool(self.browser.get("allow_workspace_tools")):
                tools.extend(workspace_tools)
        else:
            tools.extend(workspace_tools)
        if self.expose_test_tool:
            tools.append(
                ToolSpec(
                    name="run_tests",
                    description="Run the configured hidden-test command inside the container workspace.",
                    parameters=object_schema(),
                )
            )
        tools.append(
            ToolSpec(
                name="final",
                description="Finish the task with a brief completion summary.",
                parameters=object_schema({"answer": {"type": "string"}}),
            )
        )
        return tools

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
        browser_summary = "disabled"
        if bool(self.browser.get("enabled")):
            browser_summary = (
                f"enabled; start_url={self.browser.get('start_url')}; calls={self.browser_calls}"
            )
        return (
            f"Environment: {self.environment_kind}\n"
            f"Image: {self.image}\n"
            f"Browser: {browser_summary}\n"
            f"Visible files: {self._list_visible_files() or 'none'}\n"
            f"Hidden files: {len(self._hidden_paths)} file(s), injected only during run_tests.\n"
            "Evaluator: configured and runner-private.\n"
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
            available_tools = {tool.name for tool in self.tool_specs()}
            if name not in available_tools:
                error = f"Tool is not available in this environment: {name or '<missing>'}"
            elif name.startswith("browser_"):
                detail, error = self._browser_call(name, args)
            elif name == "list_files":
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
                if not self.expose_test_tool:
                    error = "The hidden evaluator is runner-private and cannot be called by the target agent."
                else:
                    detail = self._run_configured_tests()
            elif name == "final":
                self.done = True
                self.final_answer = str(args.get("answer") or "")
                self._write_final_answer(self.final_answer)
                detail = self.final_answer or "Final answer received."
                if self.auto_evaluate_on_final:
                    detail += "\n\n" + self._run_configured_tests()
        except subprocess.TimeoutExpired:
            error = f"Command timed out after {self.timeout} seconds."
        except Exception as exc:
            error = str(exc)

        if error:
            self.invalid_actions += 1
        if (self.last_test and self.last_test.get("passed")) or self.steps >= self.max_steps:
            self.done = True
        prefix = f"Error: {error}\n\n" if error else ""
        suffix = f"\n\n{detail}" if detail else ""
        return DockerAgentStepOutcome(prefix + self.observation() + suffix, done=self.done, error=error)

    def score(self) -> float:
        if self.last_test:
            return float(self.last_test.get("score") or 0.0)
        return 0.0

    def summary(self) -> str:
        status = "not_run"
        if self.last_test:
            status = "passed" if self.last_test.get("passed") else "failed"
        return (
            f"score={self.score():.2f}; steps={self.steps}/{self.max_steps}; "
            f"test_status={status}; test_runs={self.test_runs}; browser_calls={self.browser_calls}; "
            f"invalid_actions={self.invalid_actions}"
        )

    def state(self) -> dict[str, Any]:
        return {
            "environment": self.environment_kind,
            "image": self.image,
            "container_name": self._container_name,
            "visible_files": self._list_visible_files(),
            "runtime_files": sorted(self._runtime_paths),
            "hidden_files": sorted(self._hidden_paths),
            "steps": self.steps,
            "max_steps": self.max_steps,
            "invalid_actions": self.invalid_actions,
            "test_runs": self.test_runs,
            "last_command": self.last_command,
            "last_test": self.last_test,
            "browser": self.browser,
            "browser_calls": self.browser_calls,
            "final_answer": self.final_answer,
            "done": self.done,
            "score": self.score(),
        }

    def export_artifacts(self, destination: str | Path) -> dict[str, str]:
        """Export the final visible workspace and complete evaluator output."""
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        state_path = root / "environment-state.json"
        evaluator_path = root / "evaluator-runs.json"
        state_path.write_text(
            json.dumps(self.state(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        evaluator_path.write_text(
            json.dumps(self.evaluator_runs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        workspace = root / "workspace"
        if self._container_name:
            workspace.mkdir(parents=True, exist_ok=True)
            self._require_ok(
                self._run_docker(
                    ["cp", f"{self._container_name}:{self.workdir}/.", str(workspace)],
                    timeout=self.timeout + 10,
                ),
                "export workspace",
            )
            for relative in sorted(self._hidden_paths | self._runtime_paths):
                protected = workspace / Path(relative)
                if protected.is_dir():
                    shutil.rmtree(protected)
                elif protected.exists():
                    protected.unlink()
        return {
            "workspace": str(workspace),
            "environment_state": str(state_path),
            "evaluator_runs": str(evaluator_path),
        }

    def cleanup(self) -> None:
        if self._container_name:
            self._run_docker(["rm", "-f", self._container_name], timeout=self.timeout)
            self._container_name = ""
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
            self._root = None
