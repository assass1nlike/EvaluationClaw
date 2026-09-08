"""Environment persistence and file handoffs for staged agent tasks."""
from __future__ import annotations

import base64
import json
import shlex
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..types import BenchmarkConfig
from .desktop_agent_env import DesktopBridgeAgentEnvironment
from .docker_agent_env import DockerWorkspaceAgentEnvironment
from .vm_provider import _run_command, _virtualbox_executable, trust_env_for_url


def _vbox(vm_id: str, *args: str) -> None:
    executable = _virtualbox_executable()
    if not executable:
        raise RuntimeError("GUI workflow checkpoints require VirtualBox.")
    ok, output = _run_command([executable, *args[:1], vm_id, *args[1:]], timeout=300)
    if not ok:
        raise RuntimeError(f"VM checkpoint operation failed: {output}")


def save_environment(env: Any, directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    if isinstance(env, DockerWorkspaceAgentEnvironment):
        tag = f"evalclaw-checkpoint:{uuid.uuid4().hex}"
        archive = directory / "environment.tar"
        env._require_ok(env._run_docker(["commit", env._container_name, tag], timeout=300), "checkpoint")
        try:
            env._require_ok(
                env._run_docker(["save", "-o", str(archive.resolve()), tag], timeout=300),
                "save checkpoint",
            )
        finally:
            env._run_docker(["image", "rm", tag], timeout=60)
        return {
            "kind": "docker_workspace", "archive": str(archive.resolve()), "image": tag,
            "config": {
                "hidden_files": env.hidden_files, "network": env.network,
                "workdir": env.workdir, "timeout": env.timeout,
                "test_command": env.test_command, "evaluation": env.evaluation,
                "browser": env.browser, "resource_limits": {"memory": env.memory, "cpus": env.cpus},
                "expose_test_tool": env.expose_test_tool,
                "auto_evaluate_on_final": env.auto_evaluate_on_final,
                "workspace_tools": sorted(env.allowed_workspace_tools),
            },
            "runtime_paths": sorted(env._runtime_paths),
            "visible_paths": sorted(env._visible_paths),
        }
    if isinstance(env, DesktopBridgeAgentEnvironment):
        if env.vm_session_data.get("backend") != "virtualbox":
            raise RuntimeError(
                "Resuming a reused VM environment requires a local VirtualBox VM snapshot. "
                "This VM backend does not implement workflow checkpoints."
            )
        snapshot = f"workflow-{uuid.uuid4().hex}"
        _vbox(env.vm_id, "snapshot", "take", snapshot, "--live")
        return {
            "kind": "vm", "snapshot": snapshot,
            "attributes": {
                key: value for key, value in vars(env).items()
                if key not in {"_client", "bridge_api_key", "vm_provider_api_key"}
            },
        }
    raise TypeError(f"Unsupported workflow environment: {type(env).__name__}")


def restore_environment(saved: dict[str, Any], config: BenchmarkConfig) -> Any:
    if saved["kind"] == "docker_workspace":
        loader = DockerWorkspaceAgentEnvironment(image=saved["image"], visible_files={}, hidden_files={})
        from .docker import resolve_docker_executable

        loader._docker = resolve_docker_executable(config.docker_executable) or config.docker_executable
        loader.docker_executable = config.docker_executable
        loader._require_ok(
            loader._run_docker(["load", "-i", saved["archive"]], timeout=300), "load checkpoint",
        )
        try:
            env = DockerWorkspaceAgentEnvironment.from_config({
                **saved["config"], "image": saved["image"], "auto_select_image": False,
                "pull_image": False, "docker_executable": config.docker_executable,
            })
        finally:
            loader._run_docker(["image", "rm", saved["image"]], timeout=60)
        env._runtime_paths = set(saved["runtime_paths"])
        env._visible_paths = set(saved["visible_paths"])
        return env
    attributes = saved["attributes"]
    vm_id = attributes["vm_id"]
    _vbox(vm_id, "controlvm", "poweroff")
    _vbox(vm_id, "snapshot", "restore", saved["snapshot"])
    _vbox(vm_id, "startvm", "--type", "headless")
    env = DesktopBridgeAgentEnvironment.__new__(DesktopBridgeAgentEnvironment)
    vars(env).update(attributes)
    env.bridge_api_key = config.gui_bridge_api_key
    env.vm_provider_api_key = config.vm_provider_api_key
    env._client = httpx.Client(
        base_url=env.bridge_url, timeout=env.timeout,
        headers={"Authorization": f"Bearer {env.bridge_api_key}"} if env.bridge_api_key else {},
        trust_env=trust_env_for_url(env.bridge_url),
    )
    deadline = time.monotonic() + 120
    while True:
        try:
            env._request("GET", "/health")
            return env
        except httpx.HTTPError:
            if time.monotonic() >= deadline:
                env._client.close()
                raise
            time.sleep(1)


def _gui_python(env: DesktopBridgeAgentEnvironment, code: str) -> str:
    # Both bundled GUI bridges use Python. Base64 keeps shell quoting OS-independent.
    encoded = base64.b64encode(code.encode()).decode()
    data = env._request("POST", f"/sessions/{env.session_id}/actions", json_payload={
        "action": "run_command",
        "args": {"command": f'python -c "import base64;exec(base64.b64decode(\'{encoded}\'))"'},
    })
    result = data.get("result", data)
    if data.get("error") or result.get("returncode", 0):
        raise RuntimeError(f"GUI workflow file operation failed: {data}")
    return str(result.get("stdout", ""))


def export_file(env: Any, guest_path: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(env, DockerWorkspaceAgentEnvironment):
        clean = env._clean_path(guest_path)
        if clean is None or clean in env._runtime_paths | env._hidden_paths:
            raise ValueError(f"Invalid or protected workflow output path: {guest_path}")
        env._require_ok(env._exec_shell(f"test -f {shlex.quote(clean)}"), "check output file")
        env._require_ok(env._run_docker([
            "cp", f"{env._container_name}:{env.workdir}/{clean}", str(destination.resolve()),
        ], timeout=env.timeout + 10), "export stage file")
    else:
        output = _gui_python(env, f"import base64,pathlib;print(base64.b64encode(pathlib.Path({guest_path!r}).read_bytes()).decode())")
        destination.write_bytes(base64.b64decode(output.strip(), validate=True))


def import_file(env: Any, source: Path, guest_path: str) -> None:
    if isinstance(env, DockerWorkspaceAgentEnvironment):
        clean = env._clean_path(guest_path)
        if clean is None or clean in env._runtime_paths | env._hidden_paths:
            raise ValueError(f"Invalid or protected workflow input path: {guest_path}")
        env._copy_workspace_file(source, clean)
        env._visible_paths.add(clean)
    else:
        encoded = base64.b64encode(source.read_bytes()).decode()
        _gui_python(env, f"import base64,pathlib;p=pathlib.Path({guest_path!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode({encoded!r}))")


def evaluate_environment(env: Any, results: dict[str, Any]) -> dict[str, Any]:
    if isinstance(env, DockerWorkspaceAgentEnvironment):
        path = "__workflow_results__.json"
        old = env.hidden_files.get(path)
        env._write_local_file(path, json.dumps(results, ensure_ascii=False), area="hidden")
        env._hidden_paths.add(path)
        try:
            env._run_configured_tests()
            return dict(env.last_test["evaluator"])
        finally:
            if old is None:
                env._hidden_paths.discard(path)
            else:
                env._write_local_file(path, old, area="hidden")
    original = env.evaluation_config
    env.evaluation_config = {**original, "workflow_results": results}
    try:
        outcome = env._evaluate()
        if outcome.error:
            raise RuntimeError(outcome.error)
        return {**env.last_evaluation, "score": env.score()}
    finally:
        env.evaluation_config = original


def release_environment(env: Any, *, keep_checkpoint: bool) -> None:
    if keep_checkpoint and isinstance(env, DesktopBridgeAgentEnvironment):
        env._client.close()
    else:
        env.cleanup()
