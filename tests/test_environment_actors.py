from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.runners import environment_actors as actor_module
from evalclaw.runners.environment_actors import (
    ActorInfrastructureError,
    ActorRuntime,
    ActorSession,
    ActorToolExecutor,
)
from evalclaw.runners.harness import ManifestHarness, ManifestHarnessRunner
from evalclaw.types import (
    AgentEnvironmentSpec,
    BenchmarkConfig,
    BenchmarkItem,
    EnvironmentActorSpec,
    TargetModelConfig,
    TaskType,
)


def _config() -> BenchmarkConfig:
    return BenchmarkConfig(
        actor_model="actor-model",
        actor_provider="openai_compatible",
        actor_api_key="secret",
        actor_base_url="https://actor.invalid/v1",
    )


def test_actor_schema_supports_reused_and_distinct_toolsets() -> None:
    environment = AgentEnvironmentSpec.model_validate(
        {
            "type": "docker_workspace",
            "actor_toolsets": {
                "developer": {"tools": ["read_file", "write_file", "run_command"]},
                "reviewer": {
                    "tools": ["read_file"],
                    "read_paths": ["docs"],
                    "write_paths": [],
                },
            },
            "actors": [
                {
                    "id": "alice",
                    "description": "developer",
                    "system_prompt": "You are Alice.",
                    "toolset": "developer",
                },
                {
                    "id": "bob",
                    "description": "developer",
                    "system_prompt": "You are Bob.",
                    "toolset": "developer",
                },
                {
                    "id": "reviewer",
                    "system_prompt": "Review documents only.",
                    "toolset": "reviewer",
                },
            ],
        }
    )

    assert [actor.toolset for actor in environment.actors] == [
        "developer",
        "developer",
        "reviewer",
    ]


def test_actor_schema_rejects_unknown_toolset_and_false_shell_path_boundary() -> None:
    with pytest.raises(ValidationError, match="unknown toolset"):
        AgentEnvironmentSpec.model_validate(
            {
                "actors": [
                    {"id": "alice", "system_prompt": "You are Alice.", "toolset": "missing"}
                ]
            }
        )
    with pytest.raises(ValidationError, match="run_command grants access"):
        AgentEnvironmentSpec.model_validate(
            {
                "actor_toolsets": {
                    "restricted": {
                        "tools": ["run_command"],
                        "read_paths": ["src"],
                        "write_paths": ["src"],
                    }
                }
            }
        )


def test_actor_file_tools_enforce_read_and_write_roots(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "input.txt").write_text("visible", encoding="utf-8")
    (tmp_path / "private.txt").write_text("private", encoding="utf-8")
    executor = ActorToolExecutor(
        workdir=tmp_path,
        image="unused",
        environment={},
        toolset={
            "tools": ["read_file", "write_file"],
            "read_paths": ["docs"],
            "write_paths": ["out"],
        },
        config=_config(),
    )

    allowed = executor.execute(
        actor_module.ToolCall(id="1", name="read_file", arguments={"path": "docs/input.txt"})
    )
    denied = executor.execute(
        actor_module.ToolCall(id="2", name="read_file", arguments={"path": "private.txt"})
    )
    written = executor.execute(
        actor_module.ToolCall(
            id="3",
            name="write_file",
            arguments={"path": "out/result.txt", "content": "done"},
        )
    )

    assert allowed.content == "visible"
    assert "outside this role's readable paths" in (denied.error or "")
    assert written.error is None
    assert (tmp_path / "out" / "result.txt").read_text(encoding="utf-8") == "done"


def test_actor_file_tools_do_not_follow_workspace_symlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / "actor-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(outside)
    executor = ActorToolExecutor(
        workdir=tmp_path,
        image="unused",
        environment={},
        toolset={"tools": ["read_file", "write_file"]},
        config=_config(),
    )

    read = executor.execute(
        actor_module.ToolCall(id="1", name="read_file", arguments={"path": "link.txt"})
    )
    write = executor.execute(
        actor_module.ToolCall(
            id="2",
            name="write_file",
            arguments={"path": "link.txt", "content": "changed"},
        )
    )

    assert "symbolic link" in (read.error or "")
    assert "symbolic link" in (write.error or "")
    assert outside.read_text(encoding="utf-8") == "outside"


def test_actor_history_persists_per_actor_and_is_isolated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict] = []

    def fake_call(messages, _target, _tools, **kwargs):
        calls.append(
            {
                "messages": json.loads(json.dumps(messages)),
                "system_prompt": kwargs["system_prompt"],
                "timeout_s": kwargs["timeout_s"],
            }
        )
        reply = f"reply to {messages[-1]['content']}"
        return TargetToolModelResponse(
            adapter="openai",
            content=reply,
            tool_calls=[],
            assistant_message={"role": "assistant", "content": reply},
            raw_response={"usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        )

    monkeypatch.setattr(actor_module, "call_target_model_with_tools", fake_call)
    runtime = ActorRuntime(
        actors=[
            EnvironmentActorSpec(id="alice", system_prompt="You are Alice."),
            EnvironmentActorSpec(id="bob", system_prompt="You are Bob."),
        ],
        toolsets={},
        workdir=tmp_path,
        image="unused",
        environment={},
        config=_config(),
        artifact_dir=tmp_path / "artifacts",
    )

    assert runtime.interact("alice", "first") == "reply to first"
    assert runtime.interact("alice", "second") == "reply to second"
    assert runtime.interact("bob", "hello") == "reply to hello"

    assert [message["content"] for message in calls[1]["messages"]] == [
        "first",
        "reply to first",
        "second",
    ]
    assert [message["content"] for message in calls[2]["messages"]] == ["hello"]
    assert "You are Alice." in calls[0]["system_prompt"]
    assert "When you return a natural-language message" in calls[0]["system_prompt"]
    assert 0 < calls[0].get("timeout_s", 0) <= 300
    assert runtime.summary()["usage"] == {"prompt_tokens": 9, "completion_tokens": 6}
    assert runtime.summary()["by_actor"] == {
        "alice": {
            "interaction_count": 2,
            "model_call_count": 2,
            "tool_call_count": 0,
            "usage": {"prompt_tokens": 6, "completion_tokens": 4},
        },
        "bob": {
            "interaction_count": 1,
            "model_call_count": 1,
            "tool_call_count": 0,
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
    }
    trace = json.loads((tmp_path / "artifacts" / "actors" / "trace.json").read_text())
    assert trace["actors"][0]["system_prompt"] == "You are Alice."


def test_actor_tool_loop_changes_shared_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    responses = iter(
        [
            TargetToolModelResponse(
                adapter="openai",
                content="",
                tool_calls=[
                    actor_module.ToolCall(
                        id="write-1",
                        name="write_file",
                        arguments={"path": "result.txt", "content": "actor output"},
                    )
                ],
                assistant_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "write-1",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"path":"result.txt","content":"actor output"}',
                            },
                        }
                    ],
                },
                raw_response={},
            ),
            TargetToolModelResponse(
                adapter="openai",
                content="I updated the file.",
                tool_calls=[],
                assistant_message={"role": "assistant", "content": "I updated the file."},
                raw_response={},
            ),
        ]
    )
    monkeypatch.setattr(
        actor_module, "call_target_model_with_tools", lambda *_args, **_kwargs: next(responses)
    )
    runtime = ActorRuntime(
        actors=[
            EnvironmentActorSpec(
                id="worker", system_prompt="You are a worker.", toolset="writer"
            )
        ],
        toolsets={
            "writer": {
                "tools": ["write_file"],
                "read_paths": ["."],
                "write_paths": ["."],
                "network": "none",
            }
        },
        workdir=tmp_path,
        image="unused",
        environment={},
        config=_config(),
        artifact_dir=None,
    )

    assert runtime.interact("worker", "Please update it.") == "I updated the file."
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "actor output"
    assert runtime.histories["worker"][-1]["role"] == "assistant"


def test_actor_model_failure_is_marked_as_infrastructure_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        actor_module,
        "call_target_model_with_tools",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )
    runtime = ActorRuntime(
        actors=[EnvironmentActorSpec(id="alice", system_prompt="You are Alice.")],
        toolsets={},
        workdir=tmp_path,
        image="unused",
        environment={},
        config=_config(),
        artifact_dir=tmp_path / "artifacts",
    )

    with pytest.raises(ActorInfrastructureError, match="provider unavailable"):
        runtime.interact("alice", "hello")

    assert "provider unavailable" in (runtime.summary()["infrastructure_error"] or "")
    assert runtime.histories["alice"] == []
    trace = json.loads((tmp_path / "artifacts" / "actors" / "trace.json").read_text())
    assert trace["interactions"][0]["status"] == "failed"


def test_actor_runtime_close_waits_for_an_inflight_interaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def fake_call(*_args, **_kwargs):
        entered.set()
        release.wait()
        return TargetToolModelResponse(
            adapter="openai",
            content="reply",
            tool_calls=[],
            assistant_message={"role": "assistant", "content": "reply"},
            raw_response={},
        )

    monkeypatch.setattr(actor_module, "call_target_model_with_tools", fake_call)
    runtime = ActorRuntime(
        actors=[EnvironmentActorSpec(id="alice", system_prompt="You are Alice.")],
        toolsets={},
        workdir=tmp_path,
        image="unused",
        environment={},
        config=_config(),
        artifact_dir=None,
    )
    interaction = threading.Thread(
        target=lambda: pytest.raises(TimeoutError, runtime.interact, "alice", "hello")
    )
    interaction.start()
    assert entered.wait(timeout=1)
    closer = threading.Thread(target=runtime.close)
    closer.start()
    assert runtime.closed.wait(timeout=1)
    assert closer.is_alive()

    release.set()
    interaction.join(timeout=1)
    closer.join(timeout=1)
    assert not interaction.is_alive()
    assert not closer.is_alive()


def test_actor_session_broker_exposes_only_fixed_interaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = ActorSession(
        actors=[
            EnvironmentActorSpec(
                id="alice", description="project colleague", system_prompt="You are Alice."
            )
        ],
        toolsets={},
        workdir=tmp_path,
        image="unused",
        environment={},
        config=_config(),
        artifact_dir=None,
    )
    monkeypatch.setattr(
        session.runtime,
        "interact",
        lambda actor_id, message: f"{actor_id} received {message}",
    )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(session.socket_path))
            client.sendall(
                (
                    json.dumps(
                        {
                            "token": session.token,
                            "actor_id": "alice",
                            "message": "hello",
                        }
                    )
                    + "\n"
                ).encode()
            )
            response = json.loads(client.makefile().readline())
        assert response == {"ok": True, "reply": "alice received hello"}
        config = json.loads(session.mcp_config)
        assert config["requestTimeoutMs"] == 300_000
        assert config["codexApprovalMode"] == "approve"
        assert "secret" not in session.mcp_config
    finally:
        session.close()


def test_environment_actors_reject_non_openclaw_harness() -> None:
    item = BenchmarkItem(
        id="actor-task",
        dimension_id="d1",
        task_type=TaskType.agent,
        prompt="Work with Alice to finish the task.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "actors": [{"id": "alice", "system_prompt": "You are Alice."}],
            }
        },
    )
    runner = ManifestHarnessRunner(
        ManifestHarness(name="codex", run="codex {task}", model_env={})
    )

    with pytest.raises(RuntimeError, match="require the OpenClaw harness"):
        runner.run(
            item,
            TargetModelConfig(provider="openai", model="gpt-5"),
            BenchmarkConfig(actor_model="actor-model"),
        )
