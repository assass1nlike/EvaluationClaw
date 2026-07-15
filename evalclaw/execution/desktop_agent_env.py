"""Remote GUI/desktop bridge environment for agent-interaction evaluations."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..protocols.tool import ToolSpec, format_tool_specs_for_prompt, object_schema
from .vm_provider import (
    VM_PROVIDER_API_KEY_ENV_VAR,
    VM_PROVIDER_URL_ENV_VAR,
    create_vm_session,
    destroy_vm_session,
    trust_env_for_url,
    vm_provider_setup_message,
)

GUI_BRIDGE_ENV_VAR = "EVALCLAW_GUI_BRIDGE_URL"
GUI_BRIDGE_API_KEY_ENV_VAR = "EVALCLAW_GUI_BRIDGE_API_KEY"


@dataclass
class DesktopBridgeStatus:
    available: bool
    bridge_url: str = ""
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DesktopAgentStepOutcome:
    observation: str
    done: bool = False
    error: str | None = None


def desktop_bridge_setup_message() -> str:
    return (
        "A GUI desktop task requires a CUA/desktop bridge, but no reachable bridge is configured.\n\n"
        "Configure one of:\n"
        f"1. Set {GUI_BRIDGE_ENV_VAR}=http://127.0.0.1:<port>\n"
        "2. Pass --gui-bridge-url http://127.0.0.1:<port>\n"
        "3. Put bridge_url in metadata.agent_env for this item.\n\n"
        "Expected bridge contract:\n"
        "- GET /health\n"
        "- POST /sessions\n"
        "- POST /sessions/{session_id}/actions\n"
        "- POST /sessions/{session_id}/evaluate\n"
        "- DELETE /sessions/{session_id}\n\n"
        "When POST /sessions receives non-empty session.baseline_checks, it must verify them before exposing "
        "the session and return baseline_verified=true; EvaluationClaw fails closed otherwise.\n\n"
        "The bridge backend can wrap a local VM, VNC/RDP desktop, browser automation service, "
        "or an MCP/CUA server. For isolated VM lifecycle, configure the VM provider options."
    )


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def probe_desktop_bridge(
    bridge_url: str | None,
    *,
    api_key: str | None = None,
    timeout: int = 10,
) -> DesktopBridgeStatus:
    url = (bridge_url or os.environ.get(GUI_BRIDGE_ENV_VAR) or "").strip().rstrip("/")
    if not url:
        return DesktopBridgeStatus(False, detail=f"{GUI_BRIDGE_ENV_VAR} is not set.")
    try:
        with httpx.Client(base_url=url, timeout=timeout, headers=_headers(api_key), trust_env=trust_env_for_url(url)) as client:
            response = client.get("/health")
            response.raise_for_status()
            data = response.json() if response.content else {}
    except Exception as exc:
        return DesktopBridgeStatus(False, bridge_url=url, detail=str(exc))
    return DesktopBridgeStatus(True, bridge_url=url, detail="GUI desktop bridge is reachable.", data=data if isinstance(data, dict) else {})


def _shorten(value: str, limit: int = 6000) -> str:
    if len(value) <= limit:
        return value
    half = max(1, limit // 2)
    return value[:half] + "\n...\n" + value[-half:]


def _payload_observation(payload: dict[str, Any], fallback: str) -> str:
    for key in ("observation", "text", "summary", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _shorten(value.strip())
    screenshot = payload.get("screenshot")
    if isinstance(screenshot, dict):
        path = screenshot.get("path") or screenshot.get("uri") or screenshot.get("id")
        if path:
            return f"Screenshot captured: {path}"
    if isinstance(payload.get("screenshot_path"), str):
        return f"Screenshot captured: {payload['screenshot_path']}"
    return fallback


def _payload_score(payload: dict[str, Any]) -> float | None:
    value = payload.get("score")
    if value is None and isinstance(payload.get("evaluation"), dict):
        value = payload["evaluation"].get("score")
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


class DesktopBridgeAgentEnvironment:
    """A generic HTTP bridge for GUI and desktop-software tasks.

    EvaluationClaw owns the task protocol and trace. The bridge owns the actual
    desktop runtime: VM/container/session lifecycle, screenshots, mouse/keyboard
    actions, file transfer, shell commands, and artifact evaluation.
    """

    def __init__(
        self,
        *,
        bridge_url: str,
        bridge_api_key: str | None,
        session_config: dict[str, Any],
        evaluation_config: dict[str, Any],
        max_steps: int = 40,
        timeout: int = 30,
        vm_provider_url: str = "",
        vm_provider_api_key: str | None = None,
        vm_id: str = "",
        destroy_vm_on_cleanup: bool = True,
    ) -> None:
        self.bridge_url = bridge_url.rstrip("/")
        self.bridge_api_key = bridge_api_key
        self.session_config = session_config
        self.evaluation_config = evaluation_config
        self.vm_provider_url = vm_provider_url.rstrip("/")
        self.vm_provider_api_key = vm_provider_api_key
        self.vm_id = vm_id
        self.destroy_vm_on_cleanup = destroy_vm_on_cleanup
        self.max_steps = max(1, max_steps)
        self.timeout = max(1, timeout)
        self.steps = 0
        self.invalid_actions = 0
        self.done = False
        self.session_id = ""
        self.last_observation = ""
        self.last_action: dict[str, Any] | None = None
        self.last_evaluation: dict[str, Any] | None = None
        self._client = httpx.Client(
            base_url=self.bridge_url,
            timeout=self.timeout,
            headers=_headers(bridge_api_key),
            trust_env=trust_env_for_url(self.bridge_url),
        )
        try:
            self._start()
        except Exception:
            try:
                self.cleanup()
            except Exception:
                pass
            raise

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "DesktopBridgeAgentEnvironment":
        requires_vm = bool(config.get("requires_vm") or config.get("vm"))
        explicit_bridge_url = str(config.get("bridge_url") or "").strip()
        bridge_url = explicit_bridge_url or ("" if requires_vm else os.environ.get(GUI_BRIDGE_ENV_VAR) or "").strip()
        api_key = str(config.get("bridge_api_key") or os.environ.get(GUI_BRIDGE_API_KEY_ENV_VAR) or "").strip() or None
        vm_provider_url = str(config.get("vm_provider_url") or os.environ.get(VM_PROVIDER_URL_ENV_VAR) or "").strip()
        vm_provider_api_key = str(config.get("vm_provider_api_key") or os.environ.get(VM_PROVIDER_API_KEY_ENV_VAR) or "").strip() or None
        destroy_vm_on_cleanup = bool(config.get("destroy_vm_on_cleanup", True))
        if not bridge_url:
            if requires_vm:
                vm_session = create_vm_session(
                    vm_provider_url,
                    api_key=vm_provider_api_key,
                    vm_spec=config.get("vm") if isinstance(config.get("vm"), dict) else {},
                    session_spec=config.get("session") if isinstance(config.get("session"), dict) else {},
                    timeout=int(config.get("vm_provider_timeout") or 120),
                )
                bridge_url = vm_session.bridge_url
                api_key = vm_session.bridge_api_key or api_key
                vm_provider_url = str(vm_session.data.get("provider_url") or vm_provider_url)
                if not bridge_url:
                    raise RuntimeError("VM provider created a VM but did not return bridge_url for the desktop session.")
            else:
                raise RuntimeError(desktop_bridge_setup_message())
        else:
            vm_session = None
        session = config.get("session") if isinstance(config.get("session"), dict) else {}
        evaluation = config.get("evaluation") if isinstance(config.get("evaluation"), dict) else {}
        payload = {
            key: value
            for key, value in config.items()
            if key
            not in {
                "type",
                "bridge_url",
                "bridge_api_key",
                "max_steps",
                "timeout",
                "session",
                "evaluation",
                "requires_vm",
                "vm_provider_url",
                "vm_provider_api_key",
                "vm_provider_timeout",
                "destroy_vm_on_cleanup",
                "vm",
                "vm_materialization",
            }
        }
        if payload:
            session = {**payload, **session}
        if requires_vm:
            if not vm_provider_url and vm_session is None:
                raise RuntimeError(vm_provider_setup_message())
            session = {
                **session,
                "vm": config.get("vm") if isinstance(config.get("vm"), dict) else {},
                "vm_id": vm_session.vm_id if vm_session else str(config.get("vm_id") or ""),
                "requires_vm": True,
            }
        return cls(
            bridge_url=bridge_url,
            bridge_api_key=api_key,
            session_config=session,
            evaluation_config=evaluation,
            max_steps=int(config.get("max_steps") or 40),
            timeout=int(config.get("timeout") or 30),
            vm_provider_url=vm_provider_url,
            vm_provider_api_key=vm_provider_api_key,
            vm_id=vm_session.vm_id if vm_session else str(config.get("vm_id") or ""),
            destroy_vm_on_cleanup=destroy_vm_on_cleanup,
        )

    def _request(self, method: str, path: str, *, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._client.request(method, path, json=json_payload)
        response.raise_for_status()
        if not response.content:
            return {}
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {"result": parsed}

    def _start(self) -> None:
        health = self._request("GET", "/health")
        payload = self._request("POST", "/sessions", json_payload={"session": self.session_config})
        self.session_id = str(payload.get("session_id") or payload.get("id") or "")
        if not self.session_id:
            raise RuntimeError("GUI desktop bridge did not return session_id from POST /sessions.")
        baseline_checks = self.session_config.get("baseline_checks")
        if isinstance(baseline_checks, list) and baseline_checks and payload.get("baseline_verified") is not True:
            raise RuntimeError(
                "GUI desktop bridge did not confirm the requested initial-state baseline checks."
            )
        self.last_observation = _payload_observation(
            payload,
            fallback=_payload_observation(health, "GUI desktop session started."),
        )

    def tool_specs(self) -> list[ToolSpec]:
        string = {"type": "string"}
        integer = {"type": "integer"}
        number = {"type": "number"}
        boolean = {"type": "boolean"}
        return [
            ToolSpec(
                name="screenshot",
                description="Capture the current desktop screenshot and return an observation or image reference.",
                parameters=object_schema({"path": string}, additional_properties=True),
            ),
            ToolSpec(
                name="cursor_position",
                description="Return current cursor coordinates.",
                parameters=object_schema(),
            ),
            ToolSpec(
                name="key",
                description="Press and release one or more keys, including hotkeys.",
                parameters=object_schema({"keys": {"type": "array"}}, required=["keys"], additional_properties=True),
            ),
            ToolSpec(
                name="key_down",
                description="Press one or more keys down without releasing them.",
                parameters=object_schema({"keys": {"type": "array"}}, required=["keys"], additional_properties=True),
            ),
            ToolSpec(
                name="key_up",
                description="Release one or more previously held keys.",
                parameters=object_schema({"keys": {"type": "array"}}, required=["keys"], additional_properties=True),
            ),
            ToolSpec(
                name="type",
                description="Type text into the focused field.",
                parameters=object_schema({"text": string}, required=["text"], additional_properties=True),
            ),
            ToolSpec(
                name="hold_key",
                description="Hold keys for a duration, then release them.",
                parameters=object_schema(
                    {"keys": {"type": "array"}, "duration_ms": integer},
                    required=["keys"],
                    additional_properties=True,
                ),
            ),
            ToolSpec(
                name="mouse_move",
                description="Move cursor to screen coordinates.",
                parameters=object_schema({"x": number, "y": number}, required=["x", "y"], additional_properties=True),
            ),
            ToolSpec(
                name="click",
                description="Click at coordinates or current cursor position.",
                parameters=object_schema(
                    {"x": number, "y": number, "button": string, "count": integer},
                    additional_properties=True,
                ),
            ),
            ToolSpec(
                name="drag",
                description="Drag from start coordinates to end coordinates.",
                parameters=object_schema(
                    {"x1": number, "y1": number, "x2": number, "y2": number, "button": string},
                    required=["x1", "y1", "x2", "y2"],
                    additional_properties=True,
                ),
            ),
            ToolSpec(
                name="mouse_down",
                description="Press a mouse button.",
                parameters=object_schema({"button": string}, additional_properties=True),
            ),
            ToolSpec(
                name="mouse_up",
                description="Release a mouse button.",
                parameters=object_schema({"button": string}, additional_properties=True),
            ),
            ToolSpec(
                name="scroll",
                description="Scroll the desktop or focused application.",
                parameters=object_schema(
                    {"direction": string, "amount": integer, "x": number, "y": number},
                    required=["direction"],
                    additional_properties=True,
                ),
            ),
            ToolSpec(
                name="wait",
                description="Wait for UI changes or long-running operations.",
                parameters=object_schema({"seconds": number}, required=["seconds"], additional_properties=True),
            ),
            ToolSpec(
                name="list_files",
                description="List files visible to the desktop session.",
                parameters=object_schema({"path": string}, additional_properties=True),
            ),
            ToolSpec(
                name="read_file",
                description="Read a text file from the desktop session.",
                parameters=object_schema({"path": string}, required=["path"], additional_properties=True),
            ),
            ToolSpec(
                name="write_file",
                description="Write complete text content to a file in the desktop session.",
                parameters=object_schema({"path": string, "content": string}, required=["path", "content"]),
            ),
            ToolSpec(
                name="run_command",
                description="Run a shell command in the desktop session.",
                parameters=object_schema({"command": string, "timeout": integer}, required=["command"], additional_properties=True),
            ),
            ToolSpec(
                name="evaluate",
                description="Run the configured artifact evaluator and return score feedback.",
                parameters=object_schema(),
            ),
            ToolSpec(
                name="final",
                description="Finish the task and run final evaluation.",
                parameters=object_schema({"answer": string}, additional_properties=True),
            ),
        ]

    def action_schema(self) -> str:
        return format_tool_specs_for_prompt(self.tool_specs())

    def observation(self) -> str:
        return (
            "Environment: gui_desktop\n"
            f"Bridge: {self.bridge_url}\n"
            f"VM: {self.vm_id or 'none'}\n"
            f"Session: {self.session_id}\n"
            f"Last observation:\n{self.last_observation or 'GUI desktop session is ready.'}\n"
            f"Steps used: {self.steps}/{self.max_steps}"
        )

    def _evaluate(self, *, final_answer: str = "") -> DesktopAgentStepOutcome:
        payload = {
            "evaluation": self.evaluation_config,
            "final_answer": final_answer,
            "steps": self.steps,
        }
        data = self._request("POST", f"/sessions/{self.session_id}/evaluate", json_payload=payload)
        self.last_evaluation = data
        score = _payload_score(data)
        if score is not None:
            data["score"] = score
        self.last_observation = _payload_observation(data, "Desktop evaluation completed.")
        self.done = bool(data.get("done", score is not None and score >= 1.0)) or self.done
        return DesktopAgentStepOutcome(self.observation(), done=self.done, error=str(data.get("error") or "") or None)

    def step(self, action: dict[str, Any]) -> DesktopAgentStepOutcome:
        if self.done:
            return DesktopAgentStepOutcome(self.observation(), done=True)
        self.steps += 1
        name = str(action.get("action") or action.get("tool") or "").strip().lower()
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        self.last_action = {"action": name, "args": args}
        if name in {"evaluate", "run_tests"}:
            return self._evaluate()
        if name == "final":
            final_answer = str(args.get("answer") or "")
            self.done = True
            return self._evaluate(final_answer=final_answer)
        try:
            data = self._request(
                "POST",
                f"/sessions/{self.session_id}/actions",
                json_payload={"action": name, "args": args, "step": self.steps},
            )
        except Exception as exc:
            self.invalid_actions += 1
            if self.steps >= self.max_steps:
                self.done = True
            self.last_observation = f"Bridge action failed: {exc}"
            return DesktopAgentStepOutcome(self.observation(), done=self.done, error=str(exc))
        error = str(data.get("error") or "") or None
        if error:
            self.invalid_actions += 1
        score = _payload_score(data)
        if score is not None:
            data["score"] = score
            self.last_evaluation = data
        self.last_observation = _payload_observation(data, f"Action {name} completed.")
        self.done = bool(data.get("done", False)) or self.steps >= self.max_steps or (score is not None and score >= 1.0)
        return DesktopAgentStepOutcome(self.observation(), done=self.done, error=error)

    def score(self) -> float:
        if self.last_evaluation:
            score = _payload_score(self.last_evaluation)
            if score is not None:
                return score
        return 0.0

    def summary(self) -> str:
        return (
            f"score={self.score():.2f}; steps={self.steps}/{self.max_steps}; "
            f"invalid_actions={self.invalid_actions}; session_id={self.session_id or 'none'}"
        )

    def state(self) -> dict[str, Any]:
        return {
            "environment": "gui_desktop",
            "bridge_url": self.bridge_url,
            "vm_id": self.vm_id,
            "session_id": self.session_id,
            "steps": self.steps,
            "max_steps": self.max_steps,
            "invalid_actions": self.invalid_actions,
            "done": self.done,
            "last_action": self.last_action,
            "last_evaluation": self.last_evaluation,
            "score": self.score(),
        }

    def cleanup(self) -> None:
        try:
            if self.session_id:
                self._client.delete(f"/sessions/{self.session_id}")
        finally:
            self._client.close()
            if self.destroy_vm_on_cleanup and self.vm_provider_url and self.vm_id:
                destroy_vm_session(
                    self.vm_provider_url,
                    self.vm_id,
                    api_key=self.vm_provider_api_key,
                    timeout=min(self.timeout, 30),
                )
