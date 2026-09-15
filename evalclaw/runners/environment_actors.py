"""Runtime for Builder-defined actors used by OpenClaw agent tasks."""
from __future__ import annotations

import json
import os
import secrets
import shlex
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from ..diagnostics import write_json
from ..execution.docker import docker_subprocess_env, resolve_docker_executable
from ..models.llm import TargetToolModelResponse, call_target_model_with_tools
from ..models.providers import infer_provider
from ..protocols.tool import ToolCall, ToolResult, ToolSpec, object_schema, validate_tool_call
from ..protocols.tool_adapters import (
    evalclaw_tool_result_to_anthropic,
    evalclaw_tool_result_to_openai,
)
from ..types import (
    AgentEnvironmentSpec,
    BenchmarkConfig,
    EnvironmentActorSpec,
    TargetModelConfig,
)

_MCP_SERVER_NAME = "evalclaw-contacts"
_CONTAINER_RUNTIME_DIR = "/run/evalclaw-contacts"
ACTOR_RUNTIME_PROMPT = (
    "Runtime protocol: You may use only the tools provided to you. The shared task workspace "
    "is /workspace. Continue using tools as needed. When you return a natural-language message "
    "without a tool call, this interaction ends and that message is delivered to the person who "
    "contacted you."
)


class ActorInfrastructureError(RuntimeError):
    pass

_MCP_PROXY = r"""
const net = require("net");
const readline = require("readline");

const socketPath = process.env.EVALCLAW_ACTOR_SOCKET;
const token = process.env.EVALCLAW_ACTOR_TOKEN;
const actors = JSON.parse(process.env.EVALCLAW_ACTORS || "[]");
const contacts = actors.map((actor) => actor.description ? `${actor.id}: ${actor.description}` : actor.id);
const tool = {
  name: "send_message",
  description: `Send a message to one available contact and wait for their reply. Contacts: ${contacts.join("; ")}`,
  inputSchema: {
    type: "object",
    properties: {
      actor_id: {type: "string", enum: actors.map((actor) => actor.id)},
      message: {type: "string"}
    },
    required: ["actor_id", "message"],
    additionalProperties: false
  },
  annotations: {readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: true}
};

function reply(value) {
  process.stdout.write(JSON.stringify(value) + "\n");
}

function callBroker(actorId, message) {
  return new Promise((resolve, reject) => {
    const client = net.createConnection(socketPath);
    let data = "";
    client.setEncoding("utf8");
    client.on("connect", () => client.write(JSON.stringify({token, actor_id: actorId, message}) + "\n"));
    client.on("data", (chunk) => {
      data += chunk;
      const newline = data.indexOf("\n");
      if (newline < 0) return;
      const line = data.slice(0, newline);
      client.end();
      try { resolve(JSON.parse(line)); } catch (error) { reject(error); }
    });
    client.on("error", reject);
  });
}

const input = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
input.on("line", async (line) => {
  let request;
  try { request = JSON.parse(line); } catch (_) { return; }
  if (request.id === undefined) return;
  try {
    if (request.method === "initialize") {
      reply({jsonrpc: "2.0", id: request.id, result: {
        protocolVersion: request.params?.protocolVersion || "2024-11-05",
        capabilities: {tools: {listChanged: false}},
        serverInfo: {name: "environment-contacts", version: "1.0.0"}
      }});
    } else if (request.method === "ping") {
      reply({jsonrpc: "2.0", id: request.id, result: {}});
    } else if (request.method === "tools/list") {
      reply({jsonrpc: "2.0", id: request.id, result: {tools: [tool]}});
    } else if (request.method === "tools/call") {
      if (request.params?.name !== "send_message") throw new Error("Unknown tool");
      const args = request.params?.arguments || {};
      const result = await callBroker(args.actor_id, args.message);
      reply({jsonrpc: "2.0", id: request.id, result: {
        content: [{type: "text", text: result.reply || result.error || "No reply."}],
        isError: !result.ok
      }});
    } else {
      reply({jsonrpc: "2.0", id: request.id, error: {code: -32601, message: "Method not found"}});
    }
  } catch (error) {
    reply({jsonrpc: "2.0", id: request.id, result: {
      content: [{type: "text", text: `Contact failed: ${error.message}`}], isError: true
    }});
  }
});
""".strip()


def _workspace_path(root: Path, raw_path: object) -> tuple[str, Path]:
    text = str(raw_path).replace("\\", "/").strip()
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Path must stay inside the task workspace: {raw_path!r}.")
    relative = path.as_posix()
    candidate = root.resolve()
    for part in path.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError(f"Workspace path contains a symbolic link: {raw_path!r}.")
    candidate = candidate.resolve(strict=False)
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes the task workspace: {raw_path!r}.")
    return relative, candidate


def _path_allowed(path: str, roots: list[str]) -> bool:
    normalized = path.strip("/")
    for raw_root in roots:
        root = raw_root.replace("\\", "/").strip().strip("/")
        if root in {"", "."} or normalized == root or normalized.startswith(root + "/"):
            return True
    return False


def _open_workspace_parent(root: Path, relative: str, *, create: bool) -> tuple[int, str]:
    """Open a workspace parent without following target-controlled symlinks."""
    parts = PurePosixPath(relative).parts
    if not parts:
        raise ValueError("A file path is required.")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open(root, flags)
    try:
        for part in parts[:-1]:
            try:
                child = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, dir_fd=current)
                child = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = child
        return current, parts[-1]
    except Exception:
        os.close(current)
        raise


def _read_workspace_file(root: Path, relative: str) -> str:
    parent, name = _open_workspace_parent(root, relative, create=False)
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _write_workspace_file(root: Path, relative: str, content: str) -> None:
    parent, name = _open_workspace_parent(root, relative, create=True)
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o644,
            dir_fd=parent,
        )
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


class ActorToolExecutor:
    def __init__(
        self,
        *,
        workdir: Path,
        image: str,
        environment: dict[str, Any],
        toolset: dict[str, Any],
        config: BenchmarkConfig,
    ) -> None:
        self.workdir = workdir
        self.image = image
        self.environment = environment
        self.toolset = toolset
        self.config = config
        self._active_containers: set[str] = set()
        self._lock = threading.Lock()
        self._closed = False

    def specs(self) -> list[ToolSpec]:
        available = set(self.toolset.get("tools") or [])
        specs = [
            ToolSpec(
                name="list_files",
                description="List files visible to you in the shared task workspace.",
                parameters=object_schema(
                    {"path": {"type": "string"}}, additional_properties=False
                ),
            ),
            ToolSpec(
                name="read_file",
                description="Read a file from the shared task workspace.",
                parameters=object_schema(
                    {"path": {"type": "string"}}, required=["path"]
                ),
            ),
            ToolSpec(
                name="write_file",
                description="Write complete content to a file in the shared task workspace.",
                parameters=object_schema(
                    {"path": {"type": "string"}, "content": {"type": "string"}},
                    required=["path", "content"],
                ),
            ),
            ToolSpec(
                name="run_command",
                description="Run a bounded shell command in the shared task workspace.",
                parameters=object_schema(
                    {"command": {"type": "string"}, "timeout": {"type": "integer"}},
                    required=["command"],
                ),
            ),
        ]
        return [spec for spec in specs if spec.name in available]

    def execute(self, call: ToolCall, *, timeout_s: int | None = None) -> ToolResult:
        if self._closed:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                error="The actor tool session has ended.",
                content="Error: The actor tool session has ended.",
            )
        errors = validate_tool_call(call, self.specs())
        if errors:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                error=" ".join(errors),
                content="Error: " + " ".join(errors),
            )
        try:
            content = self._execute(call.name, call.arguments, timeout_s=timeout_s)
            return ToolResult(tool_call_id=call.id, name=call.name, content=content)
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                error=str(exc),
                content=f"Error: {exc}",
            )

    def _execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_s: int | None,
    ) -> str:
        read_paths = list(self.toolset.get("read_paths") or ["."])
        write_paths = list(self.toolset.get("write_paths") or ["."])
        if name == "list_files":
            relative, path = _workspace_path(self.workdir, arguments.get("path") or ".")
            if not _path_allowed(relative, read_paths):
                raise PermissionError(f"Path is outside this role's readable paths: {relative}")
            if not path.exists():
                raise FileNotFoundError(relative)
            files = [
                child.relative_to(self.workdir).as_posix()
                for child in path.rglob("*")
                if child.is_file() and not child.is_symlink()
            ]
            return "Visible files:\n" + "\n".join(files[:500])
        if name == "read_file":
            relative, _ = _workspace_path(self.workdir, arguments.get("path"))
            if not _path_allowed(relative, read_paths):
                raise PermissionError(f"Path is outside this role's readable paths: {relative}")
            content = _read_workspace_file(self.workdir, relative)
            if len(content) > 12_000:
                content = content[:6000] + "\n... file content truncated ...\n" + content[-6000:]
            return content
        if name == "write_file":
            relative, _ = _workspace_path(self.workdir, arguments.get("path"))
            if not _path_allowed(relative, write_paths):
                raise PermissionError(f"Path is outside this role's writable paths: {relative}")
            content = arguments.get("content")
            if not isinstance(content, str):
                raise ValueError("write_file requires string content.")
            _write_workspace_file(self.workdir, relative, content)
            return f"Wrote {relative} ({len(content)} chars)."
        if name == "run_command":
            command = str(arguments.get("command") or "").strip()
            if not command:
                raise ValueError("run_command requires command.")
            requested = int(arguments.get("timeout") or self.config.actor_timeout_s)
            limit = self.config.actor_timeout_s if timeout_s is None else timeout_s
            return self._run_command(command, min(requested, limit))
        raise ValueError(f"Unsupported actor tool: {name}")

    def _run_command(self, command: str, timeout: int) -> str:
        docker = resolve_docker_executable(self.config.docker_executable)
        if not docker:
            raise RuntimeError(f"Docker executable {self.config.docker_executable!r} not found.")
        name = f"evalclaw-actor-tool-{uuid.uuid4().hex[:12]}"
        network = "bridge" if self.toolset.get("network") == "internet" else "none"
        limits = (
            self.environment.get("resource_limits")
            if isinstance(self.environment.get("resource_limits"), dict)
            else {}
        )
        args = [
            docker,
            "run",
            "--rm",
            "--name",
            name,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--network",
            network,
            "--pids-limit",
            str(limits.get("pids") or 256),
            "-v",
            f"{self.workdir}:/workspace",
            "-w",
            "/workspace",
        ]
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            args += ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp"]
        for key, flag in (("memory", "--memory"), ("cpus", "--cpus")):
            if limits.get(key):
                args += [flag, str(limits[key])]
        args += [self.image, "sh", "-lc", command]
        with self._lock:
            if self._closed:
                raise RuntimeError("The actor tool session has ended.")
            self._active_containers.add(name)
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=max(1, timeout),
                env=docker_subprocess_env(self.config.docker_executable),
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                [docker, "rm", "-f", name],
                capture_output=True,
                env=docker_subprocess_env(self.config.docker_executable),
            )
            raise TimeoutError(f"Command timed out after {timeout} seconds.") from None
        finally:
            with self._lock:
                self._active_containers.discard(name)
        output = (proc.stdout + proc.stderr).strip()
        if len(output) > 8000:
            output = output[:4000] + "\n...\n" + output[-4000:]
        return f"Command finished with returncode {proc.returncode}.\n{output}"

    def close(self) -> None:
        with self._lock:
            self._closed = True
            containers = list(self._active_containers)
        docker = resolve_docker_executable(self.config.docker_executable)
        if not docker:
            return
        for name in containers:
            subprocess.run(
                [docker, "rm", "-f", name],
                capture_output=True,
                env=docker_subprocess_env(self.config.docker_executable),
            )


def _tool_result_messages(adapter: str, results: list[ToolResult]) -> list[dict[str, Any]]:
    if adapter == "anthropic":
        return [
            {
                "role": "user",
                "content": [evalclaw_tool_result_to_anthropic(result) for result in results],
            }
        ]
    return [evalclaw_tool_result_to_openai(result) for result in results]


def _usage(raw_response: Any) -> dict[str, Any]:
    if not isinstance(raw_response, dict):
        return {}
    usage = raw_response.get("usage")
    return usage if isinstance(usage, dict) else {}


class ActorRuntime:
    def __init__(
        self,
        *,
        actors: list[EnvironmentActorSpec],
        toolsets: dict[str, dict[str, Any]],
        workdir: Path,
        image: str,
        environment: dict[str, Any],
        config: BenchmarkConfig,
        artifact_dir: Path | None,
    ) -> None:
        if not config.actor_model:
            raise RuntimeError(
                "This task defines environment actors; configure --actor-model and its connection."
            )
        provider, base_url = infer_provider(
            config.actor_model, config.actor_base_url, config.actor_provider
        )
        extra_body = dict(config.actor_extra_body)
        self.model = TargetModelConfig(
            id="environment-actor",
            provider=provider,
            model=config.actor_model,
            api_key=config.actor_api_key,
            base_url=base_url,
            extra_body=extra_body,
        )
        self.actors = {actor.id: actor for actor in actors}
        self.toolsets = toolsets
        self.executors = {
            actor.id: ActorToolExecutor(
                workdir=workdir,
                image=image,
                environment=environment,
                toolset=toolsets.get(actor.toolset, {}),
                config=config,
            )
            for actor in actors
        }
        self.histories: dict[str, list[dict[str, Any]]] = {actor.id: [] for actor in actors}
        self.config = config
        self.artifact_dir = artifact_dir
        self.interactions: list[dict[str, Any]] = []
        self.fatal_error: str | None = None
        self.lock = threading.Lock()
        self.closed = threading.Event()

    def interact(self, actor_id: str, message: object) -> str:
        if actor_id not in self.actors:
            raise ValueError(f"Unknown contact: {actor_id}")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string.")
        with self.lock:
            if self.closed.is_set():
                raise RuntimeError("The contact service is no longer available.")
            return self._interact(actor_id, message)

    def _interact(self, actor_id: str, message: str) -> str:
        actor = self.actors[actor_id]
        executor = self.executors[actor_id]
        history = self.histories[actor_id]
        history_start = len(history)
        history.append({"role": "user", "content": message})
        started = time.monotonic()
        record: dict[str, Any] = {
            "actor_id": actor_id,
            "message": message,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "turns": [],
        }
        self.interactions.append(record)
        deadline = started + self.config.actor_timeout_s
        tool_calls_used = 0
        system_prompt = actor.system_prompt.strip() + "\n\n" + ACTOR_RUNTIME_PROMPT
        try:
            for turn_index in range(self.config.actor_max_turns):
                if time.monotonic() >= deadline or self.closed.is_set():
                    raise TimeoutError("The contact did not reply before the interaction deadline.")
                try:
                    response: TargetToolModelResponse = call_target_model_with_tools(
                        history,
                        self.model,
                        executor.specs(),
                        system_prompt=system_prompt,
                        backend=self.config.llm_backend,
                        max_tokens=self.config.actor_max_tokens,
                        timeout_s=max(0.1, deadline - time.monotonic()),
                        trace_dir=(
                            self.artifact_dir / "actors" / "llm" / actor_id
                            if self.artifact_dir is not None
                            else None
                        ),
                        trace_name=(
                            f"interaction-{len(self.interactions):03d}-"
                            f"turn-{turn_index + 1:03d}"
                        ),
                        failover=self.config.failover_endpoint,
                    )
                except Exception as exc:
                    raise ActorInfrastructureError(
                        f"Actor model call failed: {type(exc).__name__}: {exc}"
                    ) from exc
                history.append(response.assistant_message)
                turn = {
                    "turn": turn_index + 1,
                    "content": response.content,
                    "tool_calls": [call.model_dump(mode="json") for call in response.tool_calls],
                    "usage": _usage(response.raw_response),
                }
                record["turns"].append(turn)
                if time.monotonic() >= deadline or self.closed.is_set():
                    raise TimeoutError("The contact did not reply before the interaction deadline.")
                if not response.tool_calls:
                    reply = response.content.strip()
                    if not reply:
                        raise RuntimeError("The contact returned an empty reply.")
                    record.update(
                        {
                            "status": "completed",
                            "reply": reply,
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "duration_ms": round((time.monotonic() - started) * 1000),
                        }
                    )
                    self.save()
                    return reply
                if tool_calls_used + len(response.tool_calls) > self.config.actor_max_tool_calls:
                    raise RuntimeError("The contact exhausted its tool-call budget.")
                results: list[ToolResult] = []
                for call in response.tool_calls:
                    if time.monotonic() >= deadline or self.closed.is_set():
                        raise TimeoutError(
                            "The contact did not reply before the interaction deadline."
                        )
                    remaining = max(1, int(deadline - time.monotonic()))
                    result = executor.execute(call, timeout_s=remaining)
                    tool_calls_used += 1
                    results.append(result)
                turn["tool_results"] = [result.model_dump(mode="json") for result in results]
                history.extend(_tool_result_messages(response.adapter, results))
                self.save()
            raise RuntimeError("The contact exhausted its model-turn budget.")
        except Exception as exc:
            del history[history_start:]
            if isinstance(exc, ActorInfrastructureError):
                self.fatal_error = str(exc)
            record.update(
                {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": round((time.monotonic() - started) * 1000),
                }
            )
            self.save()
            raise

    def close(self) -> None:
        self.closed.set()
        for executor in self.executors.values():
            executor.close()
        with self.lock:
            self.save()

    def summary(self) -> dict[str, Any]:
        usage: dict[str, int] = {}
        model_calls = 0
        tool_calls = 0
        by_actor = {
            actor_id: {
                "interaction_count": 0,
                "model_call_count": 0,
                "tool_call_count": 0,
                "usage": {},
            }
            for actor_id in self.actors
        }
        for interaction in self.interactions:
            actor_summary = by_actor[interaction["actor_id"]]
            actor_summary["interaction_count"] += 1
            for turn in interaction.get("turns", []):
                model_calls += 1
                actor_summary["model_call_count"] += 1
                turn_tool_calls = len(turn.get("tool_calls", []))
                tool_calls += turn_tool_calls
                actor_summary["tool_call_count"] += turn_tool_calls
                for key, value in turn.get("usage", {}).items():
                    if isinstance(value, int) and not isinstance(value, bool):
                        usage[key] = usage.get(key, 0) + value
                        actor_usage = actor_summary["usage"]
                        actor_usage[key] = actor_usage.get(key, 0) + value
        return {
            "model": self.model.model,
            "provider": self.model.provider,
            "base_url": self.model.base_url,
            "extra_body": self.model.extra_body,
            "limits": {
                "max_turns_per_interaction": self.config.actor_max_turns,
                "max_tool_calls_per_interaction": self.config.actor_max_tool_calls,
                "max_tokens_per_model_call": self.config.actor_max_tokens,
                "timeout_s_per_interaction": self.config.actor_timeout_s,
            },
            "interaction_count": len(self.interactions),
            "model_call_count": model_calls,
            "tool_call_count": tool_calls,
            "usage": usage,
            "by_actor": by_actor,
            "infrastructure_error": self.fatal_error,
        }

    def evidence(self) -> dict[str, Any]:
        """Return complete benchmark-authored actor context and episode interactions."""
        return {
            "definitions": [
                actor.model_dump(mode="json") for actor in self.actors.values()
            ],
            "toolsets": self.toolsets,
            "summary": self.summary(),
            "interactions": self.interactions,
        }

    def save(self) -> None:
        if self.artifact_dir is None:
            return
        definitions = [actor.model_dump(mode="json") for actor in self.actors.values()]
        write_json(
            self.artifact_dir / "actors" / "trace.json",
            {
                "actors": definitions,
                "actor_toolsets": self.toolsets,
                "runtime_protocol": ACTOR_RUNTIME_PROMPT,
                "runtime": self.summary(),
                "interactions": self.interactions,
            },
            redact=True,
        )


class _ActorRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(1024 * 1024)
        response: dict[str, Any]
        try:
            request = json.loads(raw)
            session = self.server.session  # type: ignore[attr-defined]
            if not secrets.compare_digest(str(request.get("token") or ""), session.token):
                raise PermissionError("Invalid contact-service capability.")
            reply = session.runtime.interact(request.get("actor_id"), request.get("message"))
            response = {"ok": True, "reply": reply}
        except Exception as exc:
            response = {"ok": False, "error": f"Contact failed: {exc}"}
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


class _ActorServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class ActorSession:
    def __init__(
        self,
        *,
        actors: list[EnvironmentActorSpec],
        toolsets: dict[str, dict[str, Any]],
        workdir: Path,
        image: str,
        environment: dict[str, Any],
        config: BenchmarkConfig,
        artifact_dir: Path | None,
    ) -> None:
        self.actors = actors
        self.token = secrets.token_urlsafe(32)
        self.runtime = ActorRuntime(
            actors=actors,
            toolsets=toolsets,
            workdir=workdir,
            image=image,
            environment=environment,
            config=config,
            artifact_dir=artifact_dir,
        )
        self._tmp = Path(tempfile.mkdtemp(prefix="evalclaw-actors-"))
        self.socket_path = self._tmp / "broker.sock"
        self.proxy_path = self._tmp / "mcp-proxy.js"
        self.proxy_path.write_text(_MCP_PROXY + "\n", encoding="utf-8")
        self._server = _ActorServer(str(self.socket_path), _ActorRequestHandler)
        self._server.session = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def mount(self) -> str:
        return f"{self._tmp}:{_CONTAINER_RUNTIME_DIR}"

    @property
    def mcp_config(self) -> str:
        return json.dumps(
            {
                "command": "node",
                "args": [f"{_CONTAINER_RUNTIME_DIR}/mcp-proxy.js"],
                "env": {
                    "EVALCLAW_ACTOR_SOCKET": f"{_CONTAINER_RUNTIME_DIR}/broker.sock",
                    "EVALCLAW_ACTOR_TOKEN": self.token,
                    "EVALCLAW_ACTORS": json.dumps(
                        [
                            {"id": actor.id, "description": actor.description}
                            for actor in self.actors
                        ],
                        ensure_ascii=False,
                    ),
                },
                "requestTimeoutMs": self.runtime.config.actor_timeout_s * 1000,
                "codexApprovalMode": "approve",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @property
    def setup_command(self) -> str:
        return (
            f"openclaw mcp set {_MCP_SERVER_NAME} "
            + shlex.quote(self.mcp_config)
        )

    def close(self) -> None:
        self.runtime.close()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def raise_if_failed(self) -> None:
        if self.runtime.fatal_error:
            raise ActorInfrastructureError(self.runtime.fatal_error)

    def __enter__(self) -> "ActorSession":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def actor_configuration(
    environment: dict[str, Any],
) -> tuple[list[EnvironmentActorSpec], dict[str, dict[str, Any]]]:
    spec = AgentEnvironmentSpec.model_validate(environment)
    toolsets = {
        name: toolset.model_dump(mode="json")
        for name, toolset in spec.actor_toolsets.items()
    }
    return spec.actors, toolsets


__all__ = [
    "ActorInfrastructureError",
    "ActorRuntime",
    "ActorSession",
    "ActorToolExecutor",
    "actor_configuration",
]
