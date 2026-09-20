from __future__ import annotations

import subprocess
import threading
import time

import pytest
from pydantic import ValidationError

from evalclaw.execution.interventions import InterventionController
from evalclaw.types import AgentEnvironmentSpec, AgentEnvironmentType


def _result(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_episode_end_settles_in_order_once_and_not_on_cleanup():
    commands = []
    specs = [{"id": name, "trigger": {"type": "episode_end"},
              "action": {"type": "run_command", "command": name}} for name in ["close", "audit"]]
    assert AgentEnvironmentSpec(interventions=specs).interventions[0].trigger.type == "episode_end"
    controller = InterventionController(specs, lambda command, timeout: (commands.append(command), _result())[1])
    controller.start()
    controller.stop()
    assert commands == []  # infrastructure cleanup must not commit business state
    controller.finish()
    controller.finish()
    assert commands == ["close", "audit"]
    assert [r["id"] for r in controller.records] == commands


def test_failed_settlement_stays_failed_and_does_not_run_later_actions():
    specs = [{"id": name, "trigger": {"type": "episode_end"},
              "action": {"command": name}} for name in ["broken", "later"]]
    controller = InterventionController(specs, lambda *args: _result(1, stderr="failed business transition"))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="failed business transition"):
            controller.finish()
    assert [r["id"] for r in controller.records] == ["broken"]


def test_elapsed_intervention_runs_once_and_records_result() -> None:
    commands: list[str] = []

    def run(command: str, timeout: int):
        commands.append(command)
        return _result(stdout="changed")

    controller = InterventionController(
        [
            {
                "id": "failure",
                "trigger": {"type": "elapsed_time", "after_seconds": 0.01},
                "action": {
                    "type": "run_command",
                    "command": "stop-service",
                    "timeout_seconds": 2,
                },
            }
        ],
        run,
    )
    controller.start()
    deadline = time.monotonic() + 1
    while not controller.records and time.monotonic() < deadline:
        time.sleep(0.01)
    controller.stop()

    assert commands == ["stop-service"]
    assert controller.records[0]["status"] == "completed"
    assert controller.records[0]["stdout"] == "changed"


def test_condition_intervention_waits_for_success() -> None:
    ready = threading.Event()
    actions: list[str] = []

    def run(command: str, timeout: int):
        if command == "test-ready":
            return _result(0 if ready.is_set() else 1)
        actions.append(command)
        return _result()

    controller = InterventionController(
        [
            {
                "id": "rotate",
                "trigger": {
                    "type": "condition",
                    "command": "test-ready",
                    "poll_interval_seconds": 0.01,
                },
                "action": {"type": "run_command", "command": "rotate-state"},
            }
        ],
        run,
    )
    controller.start()
    time.sleep(0.03)
    assert actions == []
    ready.set()
    deadline = time.monotonic() + 1
    while not controller.records and time.monotonic() < deadline:
        time.sleep(0.01)
    controller.stop()

    assert actions == ["rotate-state"]
    assert controller.records[0]["status"] == "completed"


def test_unmet_condition_is_not_an_intervention_failure() -> None:
    controller = InterventionController(
        [
            {
                "id": "never",
                "trigger": {
                    "type": "condition",
                    "command": "false",
                    "poll_interval_seconds": 0.01,
                },
                "action": {"type": "run_command", "command": "change"},
            }
        ],
        lambda command, timeout: _result(1),
    )
    controller.start()
    time.sleep(0.03)
    controller.stop()
    controller.raise_if_failed()

    assert controller.records == [
        {
            "id": "never",
            "status": "not_triggered",
            "trigger": {
                "type": "condition",
                "command": "false",
                "poll_interval_seconds": 0.01,
            },
            "action": {"type": "run_command", "command": "change"},
        }
    ]


def test_failed_intervention_is_a_runner_failure() -> None:
    controller = InterventionController(
        [
            {
                "id": "broken",
                "trigger": {"type": "elapsed_time", "after_seconds": 0.01},
                "action": {"type": "run_command", "command": "break"},
            }
        ],
        lambda command, timeout: _result(2, stderr="denied"),
    )
    controller.start()
    deadline = time.monotonic() + 1
    while not controller.records and time.monotonic() < deadline:
        time.sleep(0.01)
    controller.stop()

    with pytest.raises(RuntimeError, match="denied"):
        controller.raise_if_failed()


def test_intervention_schema_rejects_invalid_or_non_docker_specs() -> None:
    valid = {
        "id": "service_failure",
        "trigger": {"type": "elapsed_time", "after_seconds": 5},
        "action": {"type": "run_command", "command": "kill 1"},
    }
    assert AgentEnvironmentSpec(interventions=[valid]).interventions[0].id == "service_failure"

    with pytest.raises(ValidationError, match="requires command"):
        AgentEnvironmentSpec(
            interventions=[
                {
                    **valid,
                    "trigger": {"type": "condition", "command": ""},
                }
            ]
        )
    with pytest.raises(ValidationError, match="require type=docker_workspace"):
        AgentEnvironmentSpec(type=AgentEnvironmentType.vm, interventions=[valid])
