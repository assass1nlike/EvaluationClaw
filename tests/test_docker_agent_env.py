import subprocess
from pathlib import Path

import pytest

from evalclaw.execution.agent_envs import build_agent_environment
from evalclaw.execution.docker import DockerStatus
from evalclaw.execution.docker_agent_env import DockerWorkspaceAgentEnvironment
from evalclaw.types import BenchmarkItem, TaskType


def _mock_docker(monkeypatch, calls: list[list[str]]) -> None:
    monkeypatch.setattr(
        "evalclaw.execution.docker_agent_env.docker_status",
        lambda **kwargs: DockerStatus(available=True, executable="docker", client_version="1", server_version="1"),
    )
    monkeypatch.setattr("evalclaw.execution.docker_agent_env.resolve_docker_executable", lambda executable: "docker")
    monkeypatch.setattr("evalclaw.execution.docker_agent_env.docker_subprocess_env", lambda executable: {})

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1] == "exec":
            script = command[-1]
            if script.startswith("find "):
                return subprocess.CompletedProcess(command, 0, stdout="solution.py\ntests.py\n", stderr="")
            if script.startswith("cat --"):
                return subprocess.CompletedProcess(command, 0, stdout="def solve():\n    return 1\n", stderr="")
            if "pytest -q" in script:
                return subprocess.CompletedProcess(command, 0, stdout="1 passed\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("evalclaw.execution.docker_agent_env.subprocess.run", fake_run)


def test_docker_workspace_environment_runs_hidden_tests(monkeypatch) -> None:
    calls: list[list[str]] = []
    _mock_docker(monkeypatch, calls)

    env = DockerWorkspaceAgentEnvironment.from_config(
        {
            "type": "docker_workspace",
            "image": "python:3.11-slim",
            "visible_files": {"solution.py": "def solve():\n    return 1\n"},
            "hidden_files": {"tests.py": "from solution import solve\nassert solve() == 1\n"},
            "test_command": "pytest -q tests.py",
            "pull_image": False,
            "max_steps": 3,
        }
    )

    try:
        assert env.state()["environment"] == "docker_workspace"
        read_hidden = env.step({"action": "read_file", "args": {"path": "tests.py"}})
        assert read_hidden.error == "Cannot read protected runtime/evaluator file: tests.py"

        result = env.step({"action": "run_tests", "args": {}})

        assert result.error is None
        assert env.score() == 1.0
        assert env.last_test and env.last_test["passed"] is True
        copied_targets = " ".join(" ".join(command) for command in calls if command[1] == "cp")
        assert "solution.py" in copied_targets
        assert "tests.py" in copied_targets
        assert any(command[1] == "exec" and "rm -f -- tests.py" in command[-1] for command in calls)
    finally:
        env.cleanup()


def test_docker_workspace_exports_workspace_and_full_evaluator_output(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[list[str]] = []
    _mock_docker(monkeypatch, calls)
    env = DockerWorkspaceAgentEnvironment.from_config(
        {
            "type": "docker_workspace",
            "image": "python:3.11-slim",
            "visible_files": {"solution.py": "def solve():\n    return 1\n"},
            "hidden_files": {"tests.py": "assert True\n"},
            "test_command": "pytest -q tests.py",
            "pull_image": False,
        }
    )

    try:
        env.step({"action": "run_tests", "args": {}})
        exported = env.export_artifacts(tmp_path)

        evaluator_runs = Path(exported["evaluator_runs"]).read_text(encoding="utf-8")
        assert "1 passed" in evaluator_runs
        assert any(
            command[1] == "cp" and command[2].endswith(":/workspace/.")
            for command in calls
        )
    finally:
        env.cleanup()


def test_runtime_files_precede_setup_and_workspace_is_restored_after_evaluation(monkeypatch) -> None:
    calls: list[list[str]] = []
    _mock_docker(monkeypatch, calls)

    env = DockerWorkspaceAgentEnvironment.from_config(
        {
            "type": "docker_workspace",
            "image": "python:3.11-slim",
            "visible_files": {"solution.py": "def solve():\n    return 1\n"},
            "runtime_files": {"runtime/server.py": "print('ready')\n"},
            "hidden_files": {"tests.py": "from solution import solve\nassert solve() == 1\n"},
            "setup_commands": ["python3 runtime/server.py"],
            "test_command": "pytest -q tests.py",
            "pull_image": False,
        }
    )

    try:
        protected = env.step({"action": "read_file", "args": {"path": "runtime/server.py"}})
        assert protected.error == "Cannot read protected runtime/evaluator file: runtime/server.py"
        assert "run_command" not in {tool.name for tool in env.tool_specs()}
        shell_bypass = env.step({"action": "run_command", "args": {"command": "cat runtime/server.py"}})
        assert shell_bypass.error == "Tool is not available in this environment: run_command"

        env.step({"action": "run_tests", "args": {}})

        runtime_copy = next(
            index
            for index, command in enumerate(calls)
            if command[1] == "cp" and command[-1].endswith("/workspace/runtime/server.py")
        )
        setup = next(
            index
            for index, command in enumerate(calls)
            if command[1] == "exec" and command[-1] == "python3 runtime/server.py"
        )
        snapshot = next(
            index
            for index, command in enumerate(calls)
            if command[1] == "exec" and command[-1].startswith("tar -cf /tmp/evalclaw-workspace-before-eval.tar")
        )
        hidden_copy = next(
            index
            for index, command in enumerate(calls)
            if command[1] == "cp" and command[-1].endswith("/workspace/tests.py")
        )
        evaluator = next(
            index
            for index, command in enumerate(calls)
            if command[1] == "exec" and command[-1] == "pytest -q tests.py"
        )
        remove_hidden = next(
            index
            for index, command in enumerate(calls)
            if command[1] == "exec" and command[-1] == "rm -f -- tests.py"
        )
        restore = next(
            index
            for index, command in enumerate(calls)
            if command[1] == "exec" and command[-1].startswith("find /workspace -mindepth 1 -delete")
        )

        assert runtime_copy < setup
        assert snapshot < hidden_copy < evaluator < remove_hidden < restore
    finally:
        env.cleanup()


def test_preflight_rejects_missing_evaluator_file(monkeypatch) -> None:
    calls: list[list[str]] = []
    _mock_docker(monkeypatch, calls)
    env = DockerWorkspaceAgentEnvironment.from_config(
        {
            "type": "docker_workspace",
            "image": "python:3.11-slim",
            "visible_files": {"solution.py": "pass\n"},
            "test_command": "python3 missing_evaluator.py",
            "pull_image": False,
        }
    )
    original_exec = env._exec_shell

    def fake_exec(command, **kwargs):
        if command == "python3 missing_evaluator.py":
            return subprocess.CompletedProcess(
                [command],
                2,
                stdout="",
                stderr="python3: can't open file '/workspace/missing_evaluator.py': [Errno 2] No such file or directory\n",
            )
        if command.startswith("cat -- /workspace/"):
            return subprocess.CompletedProcess([command], 1, stdout="", stderr="not found")
        return original_exec(command, **kwargs)

    monkeypatch.setattr(env, "_exec_shell", fake_exec)

    try:
        with pytest.raises(RuntimeError, match="could not be invoked"):
            env.preflight()
    finally:
        env.cleanup()


def test_container_setup_failure_is_blocking(monkeypatch) -> None:
    calls: list[list[str]] = []
    _mock_docker(monkeypatch, calls)
    successful_run = subprocess.run

    def fail_setup(command, **kwargs):
        if command[1] == "exec" and command[-1] == "python3 configure.py":
            calls.append(command)
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="configuration failed")
        return successful_run(command, **kwargs)

    monkeypatch.setattr("evalclaw.execution.docker_agent_env.subprocess.run", fail_setup)

    with pytest.raises(RuntimeError, match="configuration failed"):
        DockerWorkspaceAgentEnvironment.from_config(
            {
                "type": "docker_workspace",
                "image": "python:3.11-slim",
                "runtime_files": {"configure.py": "raise SystemExit(1)\n"},
                "setup_commands": ["python3 configure.py"],
                "test_command": "python3 evaluate.py",
                "pull_image": False,
            }
        )


def test_build_agent_environment_supports_docker_workspace(monkeypatch) -> None:
    calls: list[list[str]] = []
    _mock_docker(monkeypatch, calls)
    item = BenchmarkItem(
        id="docker_agent",
        dimension_id="agent",
        task_type=TaskType.agent,
        prompt="Fix the containerized project.",
        metadata={
            "agent_env": {
                "type": "docker_workspace",
                "image": "python:3.11-slim",
                "visible_files": {"solution.py": "def solve():\n    return 1\n"},
                "hidden_files": {"tests.py": "from solution import solve\nassert solve() == 1\n"},
                "test_command": "pytest -q tests.py",
                "pull_image": False,
            }
        },
    )

    env = build_agent_environment(item)

    try:
        assert isinstance(env, DockerWorkspaceAgentEnvironment)
        tool_names = {tool.name for tool in env.tool_specs()}
        assert "run_command" not in tool_names
        assert "run_tests" in tool_names
    finally:
        env.cleanup()


def test_docker_workspace_auto_selects_runtime_image(monkeypatch) -> None:
    calls: list[list[str]] = []
    _mock_docker(monkeypatch, calls)

    env = DockerWorkspaceAgentEnvironment.from_config(
        {
            "type": "docker_workspace",
            "visible_files": {"package.json": '{"scripts":{"test":"node tests.js"}}', "index.js": "module.exports = {};\n"},
            "hidden_files": {"tests.js": "console.log('ok');\n"},
            "test_command": "node tests.js",
            "pull_image": False,
        }
    )

    try:
        create_command = next(command for command in calls if command[1] == "create")
        assert env.image == "node:22-bookworm-slim"
        assert "node:22-bookworm-slim" in create_command
    finally:
        env.cleanup()


def test_docker_workspace_builds_requested_custom_image(monkeypatch) -> None:
    calls: list[list[str]] = []
    build_calls: list[list[str]] = []
    _mock_docker(monkeypatch, calls)
    monkeypatch.setattr("evalclaw.execution.docker_images.resolve_docker_executable", lambda executable: "docker")
    monkeypatch.setattr("evalclaw.execution.docker_images.docker_subprocess_env", lambda executable: {})

    def fake_build_run(command, **kwargs):
        if command[1] == "image" and command[2] == "inspect":
            build_calls.append(command)
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")
        if command[1] == "build":
            build_calls.append(command)
            dockerfile = Path(command[-1]) / "Dockerfile"
            dockerfile_text = dockerfile.read_text(encoding="utf-8")
            assert command[-2] == "evalclaw-test:custom"
            assert "evalclaw-test:custom" in command
            assert "FROM python:3.11-slim" in dockerfile_text
            assert "ffmpeg" in dockerfile_text
            assert "pip install --no-cache-dir pytest" in dockerfile_text
            return subprocess.CompletedProcess(command, 0, stdout="built image\n", stderr="")
        calls.append(command)
        if command[1] == "exec":
            script = command[-1]
            if script.startswith("find "):
                return subprocess.CompletedProcess(command, 0, stdout="solution.py\ntests.py\n", stderr="")
            if script.startswith("cat --"):
                return subprocess.CompletedProcess(command, 0, stdout="def solve():\n    return 1\n", stderr="")
            if "pytest -q" in script:
                return subprocess.CompletedProcess(command, 0, stdout="1 passed\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("evalclaw.execution.docker_images.subprocess.run", fake_build_run)

    env = DockerWorkspaceAgentEnvironment.from_config(
        {
            "type": "docker_workspace",
            "image": "build://auto",
            "image_build": {
                "base_image": "python:3.11-slim",
                "system_packages": ["ffmpeg"],
                "python_packages": ["pytest"],
                "tag": "evalclaw-test:custom",
            },
            "visible_files": {"solution.py": "def solve():\n    return 1\n"},
            "hidden_files": {"tests.py": "from solution import solve\nassert solve() == 1\n"},
            "test_command": "pytest -q tests.py",
            "max_steps": 3,
        }
    )

    try:
        create_command = next(command for command in calls if command[1] == "create")
        assert env.image == "evalclaw-test:custom"
        assert "evalclaw-test:custom" in create_command
        assert any(command[1] == "build" for command in build_calls)
        assert not any(command[1] == "pull" and "evalclaw-test:custom" in command for command in calls)
    finally:
        env.cleanup()
