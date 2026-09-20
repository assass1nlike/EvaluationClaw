"""Isolated, stateful JSON-lines components for environments and evaluators."""
from __future__ import annotations

import base64
import hashlib
import json
import queue
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import jsonschema

from ..protocols.task_definition import ComponentSpec
from .docker import docker_subprocess_env, resolve_docker_executable
from .image_acquisition import acquire_image, image_pull_options
from .resource_guard import DockerResourceGuard
from .component_contract import validate_component_result

COMPONENT_PROTOCOL = {
    "transport": "stdin/stdout JSON lines; logs go to stderr. One container instance persists between calls.",
    "request": {"id": "request id", "method": "method name", "params": {}, "config": "ComponentSpec.config"},
    "response": {"id": "same request id", "result": "object matching output_schema"},
    "error": {"id": "same request id", "error": "diagnostic; never a task score"},
    "handshake": "Every component implements describe: params {}; result {methods:[supported method names],version:ComponentSpec.version}. The handshake is checked before target execution and bypasses method-specific schemas.",
    "events": "Components may emit {event:{kind,data,...}} at any time. Runtime records the component origin and receipt time; include source timestamps/causal ids in data when known. Events cannot impersonate target responses.",
    "environment": {
        "initialize": "params initial_state, seed; result state, tools (ToolSpec[]), optional messages (TaskMessage[])",
        "call_tool": "params name, arguments, participant; result content and optional error; optional user messages carry text or inline base64 image observations",
        "finalize": "params episode; perform original post-task/export hooks BEFORE returning state and artifacts; artifact_files maps stable names to container file paths to export and hash",
        "score": "params task, episode, references; score the supplied exported state in a fresh instance; result metrics",
        "inspect": "reviewer-only: params query and optional state/episode. With state supplied inspect that exported state in a fresh instance; otherwise inspect current private exploration state. Never expose as target tool",
        "checkpoint": "return an opaque JSON checkpoint; only when capability is declared",
        "restore": "params checkpoint; restore exactly the declared state scopes",
    },
    "scorer": {"score": "params task, episode, references; result {metrics:[{metric,value,status,reason,evidence,raw}]}"},
    "controller": {"next": "params events since last call, state; result state and nonempty actions, ending with {action:end}"},
    "model_callback": "Emit {id,model_request:{role,messages}}; receive {id,model_result:{content,raw}}. role must be in model_roles and runtime-bound. No credentials are mounted.",
    "files": "Component files are in /component; explicitly granted assets are in /component/assets/<mount_path or id>. Scorers receive exported files under /component/outputs/<artifact name>, verified against recorded SHA-256.",
    "permissions": "Only declared tools reach target. Controller action grants are explicit. Conversation rollback never resets budgets or deletes evidence.",
}


def asset_bytes(asset, root: Path | None = None) -> bytes:
    if asset.status != "available":
        raise ValueError(f"Asset {asset.id or asset.path} is {asset.status}")
    path = Path(asset.path)
    if root is not None and not path.is_absolute():
        path = root / path
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Asset path escapes the task package")
    data = path.read_bytes()
    if asset.sha256 and hashlib.sha256(data).hexdigest() != asset.sha256:
        raise ValueError(f"Asset digest mismatch: {asset.id or asset.path}")
    return data


def safe_relative(path: str) -> str:
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or str(parsed) in {".", ""}:
        raise ValueError(f"Component path must be package-relative: {path!r}")
    return str(parsed)


class JsonComponent:
    """One container per component instance. No target shell or host mounts.

    Request: {id, method, params, config}; reply: {id, result} or {id, error}.
    Components can request an explicitly bound model with {id, model_request:
    {role, messages}} and receive {id, model_result}. Stdout is protocol only.
    """

    def __init__(self, spec: ComponentSpec, assets=(), *, model_call: Callable | None = None, artifacts=None, on_event: Callable | None = None):
        if spec.status != "available":
            raise ValueError(f"Component is {spec.status}: {spec.unavailable_reason}")
        self.spec = spec
        self.model_call = model_call
        self.on_event = on_event
        self.name = "evalclaw-component-" + uuid.uuid4().hex
        self.executable = resolve_docker_executable("docker")
        self.process = None
        self.temp = tempfile.TemporaryDirectory(prefix="evalclaw-component-")
        self.stderr = tempfile.TemporaryFile()
        self.responses: queue.Queue = queue.Queue()
        self.sequence = 0
        self.methods = None
        self.guard = None
        try:
            directory = Path(self.temp.name)
            for name, contents in spec.files.items():
                path = directory / safe_relative(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
            by_id = {a.id: a for a in assets}
            for asset_id in spec.assets:
                asset = by_id[asset_id]
                if asset.writable is False:
                    raise ValueError(f"Component cannot enforce read-only asset grant: {asset_id}")
                path = directory / "assets" / safe_relative(asset.mount_path or asset.id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(asset_bytes(asset))
            for name, artifact in (artifacts or {}).items():
                if not isinstance(artifact, dict) or artifact.get("kind") != "file":
                    continue
                data = base64.b64decode(artifact["base64"], validate=True) if "base64" in artifact else Path(artifact["path"]).read_bytes()
                if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
                    raise ValueError(f"Produced artifact digest mismatch: {name}")
                path = directory / "outputs" / safe_relative(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            image = acquire_image(spec.image, allow_pull=spec.pull_image)
            self.guard = DockerResourceGuard(self.executable, docker_subprocess_env("docker"))
            self.guard.register("container", self.name)
            create = subprocess.run([
                self.executable, "create", *(image_pull_options() if spec.pull_image else ["--pull", "never"]), "-i", "--name", self.name,
                "--network", "bridge" if spec.network else "none", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--workdir", "/component",
                image, *spec.command,
            ], capture_output=True, text=True, timeout=spec.timeout_seconds,
                env=docker_subprocess_env("docker"))
            if create.returncode:
                raise RuntimeError(create.stderr)
            inspected = subprocess.run([self.executable, "inspect", "--format", "{{.Image}}", self.name],
                capture_output=True, text=True, timeout=spec.timeout_seconds, env=docker_subprocess_env("docker"), check=True)
            self.identity = {"image": spec.image, "image_id": inspected.stdout.strip(), "version": spec.version}
            copied = subprocess.run([self.executable, "cp", str(directory) + "/.", self.name + ":/component"],
                                    capture_output=True, text=True, timeout=spec.timeout_seconds,
                                    env=docker_subprocess_env("docker"))
            if copied.returncode:
                raise RuntimeError(copied.stderr)
            self.process = subprocess.Popen([self.executable, "start", "-ai", self.name],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
                text=True, encoding="utf-8", bufsize=1, env=docker_subprocess_env("docker"))
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            description = self.call("describe", {})
            if description.get("version") != spec.version or not isinstance(description.get("methods"), list):
                raise ValueError("Component handshake must report its version and supported methods")
            self.methods = description["methods"]
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                value = json.loads(line)
                if "event" in value:
                    if self.on_event is None:
                        raise ValueError("Component event sink is unavailable")
                    self.on_event(value["event"])
                else:
                    self.responses.put(value)
        except Exception as exc:
            self.responses.put(exc)
        finally:
            self.responses.put(EOFError("Component closed its response stream"))

    def _send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def call(self, method: str, params: dict[str, Any], *, timeout_seconds: float | None = None) -> Any:
        import time
        if self.methods is not None and method not in self.methods:
            raise ValueError(f"Component does not implement method {method}")
        if method != "describe":
            jsonschema.validate(params, self.spec.input_schema)
        self.sequence += 1
        request_id = str(self.sequence)
        self._send({"id": request_id, "method": method, "params": params, "config": self.spec.config})
        timeout = self.spec.timeout_seconds if timeout_seconds is None else min(timeout_seconds, self.spec.timeout_seconds)
        deadline = time.monotonic() + timeout
        while True:
            try:
                response = self.responses.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError(f"Component {method} exceeded {timeout}s") from exc
            if isinstance(response, BaseException):
                raise response
            if "model_request" in response:
                request = response["model_request"]
                if request.get("role") not in self.spec.model_roles or self.model_call is None:
                    raise PermissionError("Component requested an unbound model role")
                self._send({"id": response["id"], "model_result": self.model_call(request)})
                continue
            if response.get("id") != request_id:
                raise ValueError("Component response id does not match its request")
            if "error" in response:
                raise RuntimeError(f"Component {method}: {response['error']}")
            result = response["result"]
            if method != "describe":
                jsonschema.validate(result, self.spec.output_schema)
            try:
                validate_component_result(method, result)
            except (ValueError, jsonschema.ValidationError) as exc:
                raise ValueError(f"Component {method} returned an invalid result: {exc}") from exc
            return result

    def export_files(self, files: dict[str, str], destination: Path | None):
        exported = {}
        for name, source in files.items():
            relative = safe_relative(name)
            root = destination if destination is not None else Path(self.temp.name) / "export"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run([self.executable, "cp", f"{self.name}:{source}", str(path)],
                capture_output=True, text=True, timeout=self.spec.timeout_seconds, env=docker_subprocess_env("docker"))
            if result.returncode or not path.is_file() or path.is_symlink():
                raise ValueError(f"Artifact {name} must export an ordinary file: {result.stderr}")
            data = path.read_bytes()
            exported[name] = {"kind": "file", "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data), **({"path": str(path.resolve())} if destination is not None
                    else {"base64": base64.b64encode(data).decode("ascii")})}
        return exported

    def close(self):
        if getattr(self, "closed", False):
            return
        self.closed = True
        if self.guard:
            self.guard.close()
        elif self.executable:
            subprocess.run([self.executable, "rm", "-f", self.name], capture_output=True,
                           timeout=30, env=docker_subprocess_env("docker"))
        if self.process is not None:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            self.reader.join(timeout=10)
        self.stderr.close()
        self.temp.cleanup()
