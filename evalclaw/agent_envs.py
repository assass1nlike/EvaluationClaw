"""Deterministic toy environments for agent-interaction evaluations."""
from __future__ import annotations

import copy
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .types import BenchmarkItem


DEFAULT_WORKSPACE_ENV: dict[str, Any] = {
    "type": "workspace",
    "start_room": "office",
    "rooms": {
        "office": ["blue_notebook", "red_notebook"],
        "lab": ["charged_tablet", "dead_tablet"],
        "mailroom": [],
    },
    "item_descriptions": {
        "blue_notebook": "A blue notebook labeled project plan.",
        "red_notebook": "A red notebook labeled old draft.",
        "charged_tablet": "A tablet showing 100% battery.",
        "dead_tablet": "A tablet with an empty battery icon.",
    },
    "goal": {"outgoing_bin": ["blue_notebook", "charged_tablet"]},
    "max_steps": 8,
}


@dataclass
class AgentStepOutcome:
    observation: str
    done: bool = False
    error: str | None = None


@dataclass
class WorkspaceAgentEnvironment:
    """A small stateful room-and-inventory environment.

    The environment is intentionally simple: it validates whether a model can
    inspect observations, choose structured actions, move between rooms, carry
    items, and place the required objects in a destination bin.
    """

    rooms: dict[str, list[str]]
    start_room: str
    goal: dict[str, list[str]]
    item_descriptions: dict[str, str] = field(default_factory=dict)
    max_steps: int = 8
    room: str = ""
    inventory: list[str] = field(default_factory=list)
    outgoing_bin: list[str] = field(default_factory=list)
    steps: int = 0
    invalid_actions: int = 0
    done: bool = False

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "WorkspaceAgentEnvironment":
        rooms = {
            str(room): [str(item) for item in items]
            for room, items in dict(config.get("rooms") or DEFAULT_WORKSPACE_ENV["rooms"]).items()
            if isinstance(items, list)
        }
        start_room = str(config.get("start_room") or next(iter(rooms), "office"))
        if start_room not in rooms:
            rooms[start_room] = []
        goal = config.get("goal")
        if not isinstance(goal, dict):
            goal = DEFAULT_WORKSPACE_ENV["goal"]
        item_descriptions = {
            str(key): str(value)
            for key, value in dict(config.get("item_descriptions") or {}).items()
        }
        max_steps = int(config.get("max_steps") or DEFAULT_WORKSPACE_ENV["max_steps"])
        return cls(
            rooms=rooms,
            start_room=start_room,
            goal={"outgoing_bin": [str(item) for item in goal.get("outgoing_bin", [])]},
            item_descriptions=item_descriptions,
            max_steps=max(1, max_steps),
            room=start_room,
        )

    @property
    def required_items(self) -> set[str]:
        return set(self.goal.get("outgoing_bin", []))

    def action_schema(self) -> str:
        rooms = ", ".join(sorted(self.rooms))
        return (
            "Return exactly one JSON object per turn. Valid actions:\n"
            '- {"action":"look","args":{}}\n'
            f'- {{"action":"move","args":{{"room":"<one of: {rooms}>"}}}}\n'
            '- {"action":"inspect","args":{"item":"<visible or carried item>"}}\n'
            '- {"action":"take","args":{"item":"<visible item>"}}\n'
            '- {"action":"place","args":{"item":"<carried item>"}}  # only works in mailroom\n'
            '- {"action":"final","args":{"answer":"brief completion summary"}}'
        )

    def observation(self) -> str:
        visible = self.rooms.get(self.room, [])
        required = sorted(self.required_items)
        missing = sorted(self.required_items - set(self.outgoing_bin))
        return (
            f"Room: {self.room}\n"
            f"Visible items: {visible or 'none'}\n"
            f"Inventory: {self.inventory or 'empty'}\n"
            f"Outgoing bin: {self.outgoing_bin or 'empty'}\n"
            f"Goal: place {required} in the outgoing bin.\n"
            f"Missing required items: {missing or 'none'}\n"
            f"Steps used: {self.steps}/{self.max_steps}"
        )

    def step(self, action: dict[str, Any]) -> AgentStepOutcome:
        if self.done:
            return AgentStepOutcome(self.observation(), done=True)
        self.steps += 1
        name = str(action.get("action") or action.get("tool") or "").strip().lower()
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        error: str | None = None

        if name == "look":
            pass
        elif name == "move":
            room = str(args.get("room") or "").strip()
            if room in self.rooms:
                self.room = room
            else:
                error = f"Unknown room: {room}"
        elif name == "inspect":
            item = str(args.get("item") or "").strip()
            if item in self.rooms.get(self.room, []) or item in self.inventory:
                desc = self.item_descriptions.get(item, "No extra details.")
                return AgentStepOutcome(f"Inspection result for {item}: {desc}\n\n{self.observation()}")
            error = f"Cannot inspect item that is not visible or carried: {item}"
        elif name == "take":
            item = str(args.get("item") or "").strip()
            if item in self.rooms.get(self.room, []):
                self.rooms[self.room].remove(item)
                self.inventory.append(item)
            else:
                error = f"Item is not visible in {self.room}: {item}"
        elif name == "place":
            item = str(args.get("item") or "").strip()
            if self.room != "mailroom":
                error = "Items can only be placed in the outgoing bin from the mailroom."
            elif item not in self.inventory:
                error = f"Cannot place item that is not in inventory: {item}"
            else:
                self.inventory.remove(item)
                self.outgoing_bin.append(item)
        elif name == "final":
            self.done = True
        else:
            error = f"Unknown action: {name or '<missing>'}"

        if error:
            self.invalid_actions += 1
        if self.score() >= 1.0 or self.steps >= self.max_steps:
            self.done = True
        prefix = f"Error: {error}\n\n" if error else ""
        return AgentStepOutcome(prefix + self.observation(), done=self.done, error=error)

    def score(self) -> float:
        required = self.required_items
        if not required:
            return 0.0
        placed = set(self.outgoing_bin)
        base = len(required & placed) / len(required)
        extras = placed - required
        if extras:
            base *= 0.8
        if self.invalid_actions:
            base -= min(0.2, self.invalid_actions * 0.05)
        return max(0.0, min(1.0, base))

    def summary(self) -> str:
        missing = sorted(self.required_items - set(self.outgoing_bin))
        extra = sorted(set(self.outgoing_bin) - self.required_items)
        return (
            f"score={self.score():.2f}; steps={self.steps}/{self.max_steps}; "
            f"missing={missing or 'none'}; extra={extra or 'none'}; "
            f"invalid_actions={self.invalid_actions}"
        )

    def state(self) -> dict[str, Any]:
        return {
            "room": self.room,
            "rooms": self.rooms,
            "inventory": self.inventory,
            "outgoing_bin": self.outgoing_bin,
            "required_items": sorted(self.required_items),
            "steps": self.steps,
            "max_steps": self.max_steps,
            "invalid_actions": self.invalid_actions,
            "done": self.done,
            "score": self.score(),
        }

    def cleanup(self) -> None:
        return None


@dataclass
class CodeSandboxAgentEnvironment:
    """A persistent local code sandbox for multi-step coding agents.

    This is a lightweight execution environment, not a container security
    boundary. It keeps task files in a temporary directory, exposes controlled
    file tools, and scores the task by the most recent test run.
    """

    visible_files: dict[str, str]
    hidden_files: dict[str, str]
    test_command: str
    max_steps: int = 8
    timeout: int = 10
    steps: int = 0
    invalid_actions: int = 0
    done: bool = False
    last_test: dict[str, Any] | None = None
    test_runs: int = 0
    _tmp: tempfile.TemporaryDirectory[str] | None = None
    _root: Path | None = None
    _visible_paths: set[str] = field(default_factory=set)
    _hidden_paths: set[str] = field(default_factory=set)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "CodeSandboxAgentEnvironment":
        visible = config.get("visible_files")
        if not isinstance(visible, dict):
            visible = config.get("files") if isinstance(config.get("files"), dict) else {}
        hidden = config.get("hidden_files") if isinstance(config.get("hidden_files"), dict) else {}
        env = cls(
            visible_files={str(path): str(content) for path, content in visible.items()},
            hidden_files={str(path): str(content) for path, content in hidden.items()},
            test_command=str(config.get("test_command") or "python3 tests.py"),
            max_steps=max(1, int(config.get("max_steps") or 8)),
            timeout=max(1, int(config.get("timeout") or 10)),
        )
        env._setup()
        return env

    @property
    def root(self) -> Path:
        if self._root is None:
            self._setup()
        assert self._root is not None
        return self._root

    def _setup(self) -> None:
        if self._root is not None:
            return
        self._tmp = tempfile.TemporaryDirectory(prefix="evalclaw-agent-code-")
        self._root = Path(self._tmp.name)
        for path, content in self.visible_files.items():
            clean = self._clean_path(path)
            if clean is None:
                continue
            self._write_file(clean, content)
            self._visible_paths.add(clean)
        for path, content in self.hidden_files.items():
            clean = self._clean_path(path)
            if clean is None:
                continue
            self._write_file(clean, content)
            self._hidden_paths.add(clean)

    def _clean_path(self, value: object) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts:
            return None
        return str(path)

    def _write_file(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _read_file(self, path: str, limit: int = 6000) -> str:
        content = (self.root / path).read_text(encoding="utf-8")
        if len(content) <= limit:
            return content
        half = max(1, limit // 2)
        return content[:half] + "\n...\n" + content[-half:]

    def _list_visible_files(self) -> list[str]:
        files: list[str] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            if rel in self._hidden_paths or "__pycache__/" in rel or rel.endswith(".pyc"):
                continue
            else:
                files.append(rel)
        return sorted(files)

    def action_schema(self) -> str:
        return (
            "Return exactly one JSON object per turn. Valid actions:\n"
            '- {"action":"list_files","args":{}}\n'
            '- {"action":"read_file","args":{"path":"relative/path.py"}}\n'
            '- {"action":"write_file","args":{"path":"relative/path.py","content":"full file content"}}\n'
            '- {"action":"run_tests","args":{}}\n'
            '- {"action":"final","args":{"answer":"brief completion summary"}}'
        )

    def observation(self) -> str:
        test_summary = "not run"
        if self.last_test:
            status = "passed" if self.last_test.get("passed") else "failed"
            test_summary = f"{status}; returncode={self.last_test.get('returncode')}"
        return (
            f"Visible files: {self._list_visible_files() or 'none'}\n"
            f"Hidden files: {len(self._hidden_paths)} file(s) available only to run_tests.\n"
            f"Test command: {self.test_command}\n"
            f"Last test: {test_summary}\n"
            f"Test runs: {self.test_runs}\n"
            f"Steps used: {self.steps}/{self.max_steps}"
        )

    def step(self, action: dict[str, Any]) -> AgentStepOutcome:
        if self.done:
            return AgentStepOutcome(self.observation(), done=True)
        self.steps += 1
        name = str(action.get("action") or action.get("tool") or "").strip().lower()
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        error: str | None = None
        detail = ""

        if name == "list_files":
            detail = "Visible files:\n" + "\n".join(self._list_visible_files())
        elif name == "read_file":
            clean = self._clean_path(args.get("path"))
            if clean is None:
                error = "Invalid path."
            elif clean in self._hidden_paths:
                error = f"Cannot read hidden test file: {clean}"
            elif not (self.root / clean).is_file():
                error = f"File not found: {clean}"
            else:
                detail = f"File {clean}:\n{self._read_file(clean)}"
        elif name == "write_file":
            clean = self._clean_path(args.get("path"))
            content = args.get("content")
            if clean is None:
                error = "Invalid path."
            elif clean in self._hidden_paths:
                error = f"Cannot overwrite hidden test file: {clean}"
            elif not isinstance(content, str):
                error = "write_file requires string content."
            else:
                self._write_file(clean, content)
                self._visible_paths.add(clean)
                detail = f"Wrote {clean} ({len(content)} chars)."
        elif name in {"run_tests", "run_test"}:
            self.test_runs += 1
            try:
                proc = subprocess.run(
                    self.test_command,
                    shell=True,
                    cwd=self.root,
                    input="",
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
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
            except subprocess.TimeoutExpired as exc:
                self.last_test = {
                    "passed": False,
                    "returncode": "timeout",
                    "stdout": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
                    "stderr": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
                }
                detail = f"Tests timed out after {self.timeout} seconds."
        elif name == "final":
            self.done = True
            detail = str(args.get("answer") or "Final answer received.")
        else:
            error = f"Unknown action: {name or '<missing>'}"

        if error:
            self.invalid_actions += 1
        if self.score() >= 1.0 or self.steps >= self.max_steps:
            self.done = True
        prefix = f"Error: {error}\n\n" if error else ""
        suffix = f"\n\n{detail}" if detail else ""
        return AgentStepOutcome(prefix + self.observation() + suffix, done=self.done, error=error)

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
            "environment": "code_sandbox",
            "visible_files": self._list_visible_files(),
            "hidden_files": sorted(self._hidden_paths),
            "steps": self.steps,
            "max_steps": self.max_steps,
            "invalid_actions": self.invalid_actions,
            "test_runs": self.test_runs,
            "last_test": self.last_test,
            "done": self.done,
            "score": self.score(),
        }

    def cleanup(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
            self._root = None


def build_agent_environment(item: BenchmarkItem) -> WorkspaceAgentEnvironment | CodeSandboxAgentEnvironment:
    config = item.metadata.get("agent_env")
    if not isinstance(config, dict):
        config = copy.deepcopy(DEFAULT_WORKSPACE_ENV)
    env_type = str(config.get("type") or "workspace")
    if env_type == "workspace":
        return WorkspaceAgentEnvironment.from_config(config)
    if env_type == "code_sandbox":
        return CodeSandboxAgentEnvironment.from_config(config)
    raise ValueError(f"Unsupported agent environment type: {env_type}")
