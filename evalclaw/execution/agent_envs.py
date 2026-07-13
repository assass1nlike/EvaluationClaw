"""Deterministic toy environments for agent-interaction evaluations."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from ..protocols.tool import ToolSpec, format_tool_specs_for_prompt, object_schema
from ..types import BenchmarkConfig, BenchmarkItem
from .desktop_agent_env import DesktopBridgeAgentEnvironment
from .docker_agent_env import DockerWorkspaceAgentEnvironment
from .docker_images import apply_docker_image_selection

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

    def tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="look",
                description="Inspect the current room, inventory, outgoing bin, and goal state.",
                parameters=object_schema(),
            ),
            ToolSpec(
                name="move",
                description="Move to another room in the workspace.",
                parameters=object_schema(
                    {"room": {"type": "string", "enum": sorted(self.rooms)}},
                    required=["room"],
                ),
            ),
            ToolSpec(
                name="inspect",
                description="Inspect a visible or carried item for extra details.",
                parameters=object_schema({"item": {"type": "string"}}, required=["item"]),
            ),
            ToolSpec(
                name="take",
                description="Pick up a visible item in the current room.",
                parameters=object_schema({"item": {"type": "string"}}, required=["item"]),
            ),
            ToolSpec(
                name="place",
                description="Place a carried item into the outgoing bin. Only works in the mailroom.",
                parameters=object_schema({"item": {"type": "string"}}, required=["item"]),
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


def build_agent_environment(
    item: BenchmarkItem,
    config: BenchmarkConfig | None = None,
) -> WorkspaceAgentEnvironment | DockerWorkspaceAgentEnvironment | DesktopBridgeAgentEnvironment:
    env_config = item.metadata.get("agent_env")
    if not isinstance(env_config, dict):
        env_config = copy.deepcopy(DEFAULT_WORKSPACE_ENV)
    else:
        env_config = copy.deepcopy(env_config)
    env_type = str(env_config.get("type") or "workspace")
    if env_type in {"code_sandbox", "docker_workspace"}:
        task_text = "\n".join(
            value
            for value in (
                item.prompt,
                item.rubric or "",
                " ".join(item.tags),
                str(item.metadata.get("task_agent") or ""),
            )
            if value
        )
        if config is not None and not config.docker_auto_select_image:
            env_config["auto_select_image"] = False
        if env_type == "code_sandbox":
            env_config.setdefault(
                "image",
                config.container_sandbox_image if config is not None else "python:3.11-slim",
            )
            env_config.setdefault("workspace_tools", ["list_files", "read_file", "write_file"])
            env_config.setdefault("expose_test_tool", True)
        env_config, _ = apply_docker_image_selection(env_config, task_text=task_text)
        if config is not None:
            env_config.setdefault("pull_timeout", config.docker_pull_timeout_s)
            env_config.setdefault("docker_executable", config.docker_executable)
    if env_type == "gui_desktop" and config is not None:
        requires_vm = bool(env_config.get("requires_vm") or env_config.get("vm"))
        env_config = {
            **env_config,
            "bridge_url": env_config.get("bridge_url") or ("" if requires_vm else config.gui_bridge_url or ""),
            "bridge_api_key": env_config.get("bridge_api_key") or config.gui_bridge_api_key,
            "timeout": env_config.get("timeout") or config.gui_bridge_timeout_s,
            "vm_provider_url": env_config.get("vm_provider_url") or config.vm_provider_url or ("local://auto" if requires_vm else ""),
            "vm_provider_api_key": env_config.get("vm_provider_api_key") or config.vm_provider_api_key,
            "vm_provider_timeout": env_config.get("vm_provider_timeout") or config.vm_provider_timeout_s,
            "destroy_vm_on_cleanup": env_config.get("destroy_vm_on_cleanup", config.vm_provider_destroy_on_cleanup),
        }
    if env_type == "workspace":
        return WorkspaceAgentEnvironment.from_config(env_config)
    if env_type in {"code_sandbox", "docker_workspace"}:
        return DockerWorkspaceAgentEnvironment.from_config(env_config)
    if env_type == "gui_desktop":
        return DesktopBridgeAgentEnvironment.from_config(env_config)
    raise ValueError(f"Unsupported agent environment type: {env_type}")
