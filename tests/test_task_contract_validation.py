from __future__ import annotations

import json

import pytest

from evalclaw.construction.packaging import (
    _agent_task_package_for_task,
    _task_agent_metadata_for_task,
)
from evalclaw.construction.parsing import _task_from_raw
from evalclaw.construction.suite import _preflight_builder_environments
from evalclaw.construction.validation import task_structure_issues
from evalclaw.protocols.task_agent import compact_task_agent_for_qc
from evalclaw.quality.dataset_checks import _coverage_issues, _duplicate_issues
from evalclaw.quality.llm_checks import _compact_metadata_for_qc, _llm_qc
from evalclaw.quality.qc import run_qc_gate
from evalclaw.quality.static_checks import _static_item_issues
from evalclaw.types import (
    AgentEnvironmentSpec,
    AgentEnvironmentType,
    BenchmarkConfig,
    BenchmarkItem,
    ChoiceOption,
    EvalDimension,
    EvalSpec,
    JudgeToolRef,
    QcCategory,
    QcIssue,
    QcReport,
    QcSeverity,
    TaskDefinition,
    TaskDesign,
    TaskSuite,
    TaskType,
)
from tests.blueprint_factory import make_blueprint
from tests.config_helpers import dummy_config_kwargs


def _task(
    task_type: TaskType,
    *,
    environment: AgentEnvironmentSpec | None = None,
    expected_text: str | None = None,
    rubric: str | None = None,
    judge_tools: list[JudgeToolRef] | None = None,
    interaction: dict | None = None,
) -> TaskDefinition:
    return TaskDefinition(
        id="task_1",
        dimension_id="dimension_1",
        task_type=task_type,
        title="Contract test",
        prompt="Complete the requested benchmark task and return the required result.",
        expected_text=expected_text,
        rubric=rubric,
        judge_tools=judge_tools or [],
        environment=environment,
        interaction=interaction or {},
    )


def test_fill_blank_requires_one_exact_expected_text() -> None:
    missing = _task(TaskType.fill_blank, rubric="Accept any equivalent explanation of the result.")
    valid = _task(TaskType.fill_blank, expected_text="4")

    assert any("expected_text" in issue for issue in task_structure_issues(missing))
    assert task_structure_issues(valid) == []


def test_python_tests_judge_tool_must_consume_model_output() -> None:
    rubric_only = _task(TaskType.generation, rubric="Score correctness.")
    unrelated = _task(
        TaskType.generation,
        rubric="Score correctness.",
        judge_tools=[JudgeToolRef(tool="python_tests", config={"test_code": "assert 2 + 2 == 4"})],
    )
    valid = _task(
        TaskType.generation,
        rubric="Score correctness.",
        judge_tools=[JudgeToolRef(tool="python_tests", config={"test_code": "assert {model_output} == '4'"})],
    )

    assert task_structure_issues(rubric_only) == []
    assert any("consume {model_output}" in issue for issue in task_structure_issues(unrelated))
    assert task_structure_issues(valid) == []


def test_empty_code_sandbox_is_valid_when_the_agent_creates_files() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.code_sandbox,
            test_command="python3 verify.py",
        ),
    )

    assert task_structure_issues(task) == []


def test_container_asset_uses_host_path_internally_and_guest_filename_in_prompt(
    tmp_path,
) -> None:
    work_dir = tmp_path / "builder"
    work_dir.mkdir()
    asset_path = work_dir / "TASK.md"
    asset_path.write_text("Implement the requested change.\n", encoding="utf-8")
    environment = AgentEnvironmentSpec(
        type=AgentEnvironmentType.code_sandbox,
        test_command="python3 verify.py",
    )
    leaked = TaskDefinition(
        id="task_1",
        dimension_id="dimension_1",
        task_type=TaskType.agent,
        title="Container asset",
        prompt=f"Read {asset_path} and implement the requested change.",
        assets=[{"path": str(asset_path)}],
        environment=environment,
    )
    valid = leaked.model_copy(
        update={"prompt": "Read TASK.md and implement the requested change."}
    )

    leaked_issues = task_structure_issues(leaked, builder_work_dir=work_dir)

    assert any("Builder-host paths" in issue for issue in leaked_issues)
    assert task_structure_issues(valid, builder_work_dir=work_dir) == []


def test_task_builder_environment_rejects_invalid_field_types() -> None:
    raw = {
        "task_type": "agent",
        "prompt": "Implement the service described by the supplied files.",
        "environment": {
            "type": "docker_workspace",
            "visible_files": [{"path": "spec.md", "content": "Specification"}],
            "hidden_files": [{"path": "evaluate.py", "content": "assert True"}],
            "network": {"enabled": False},
            "setup_commands": "pip install flask",
        },
    }

    with pytest.raises(ValueError) as raised:
        _task_from_raw(raw, "task_1", default_dimension_id="dimension_1")

    message = str(raised.value)
    for field in ("visible_files", "hidden_files", "network", "setup_commands"):
        assert field in message


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        (None, "environment must be a JSON object"),
        ({"runtime": "docker_workspace"}, "environment.type is required"),
        ({"type": "docker_workspace", "resources": {}}, "resources"),
    ],
)
def test_task_builder_environment_rejects_invalid_shape(
    environment: object,
    message: str,
) -> None:
    raw = {
        "task_type": "agent",
        "prompt": "Implement the requested service.",
        "environment": environment,
    }

    with pytest.raises(ValueError, match=message):
        _task_from_raw(raw, "task_1", default_dimension_id="dimension_1")


def test_container_asset_filenames_must_be_unique(tmp_path) -> None:
    first = tmp_path / "first" / "input.bin"
    second = tmp_path / "second" / "input.bin"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    task = TaskDefinition(
        id="task_1",
        dimension_id="dimension_1",
        task_type=TaskType.agent,
        title="Container assets",
        prompt="Compare the two input.bin files.",
        assets=[{"path": str(first)}, {"path": str(second)}],
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.docker_workspace,
            test_command="python3 verify.py",
        ),
    )

    assert any("filenames must be unique" in issue for issue in task_structure_issues(task))


def test_builder_environment_preflight_reports_item_failure_and_cleans_up(
    monkeypatch,
    tmp_path,
) -> None:
    dimension = EvalDimension(
        id="dimension_1",
        name="Code execution",
        description="Evaluate code execution.",
        approach="Use an executable task.",
    )
    blueprint = make_blueprint(
        "code_task",
        dimension.id,
        "Code task",
        task_type=TaskType.agent,
        environment_type=AgentEnvironmentType.code_sandbox,
    )
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.code_sandbox,
            test_command="python3 missing_evaluator.py",
        ),
    )
    task.metadata["task_design_id"] = blueprint.task_designs[0].id
    cleaned = False

    class BrokenEnvironment:
        def preflight(self):
            raise RuntimeError("missing_evaluator.py does not exist")

        def state(self):
            return {"status": "failed"}

        def export_artifacts(self, path):
            return {"workspace": str(path)}

        def cleanup(self):
            nonlocal cleaned
            cleaned = True

    monkeypatch.setattr(
        "evalclaw.construction.suite.build_agent_environment",
        lambda item, config: BrokenEnvironment(),
    )

    issues, failed_ids = _preflight_builder_environments(
        [task],
        dimension=dimension,
        blueprint=blueprint,
        resources=[],
        config=BenchmarkConfig(),
        trace_dir=tmp_path,
    )

    assert failed_ids == {task.id}
    assert "missing_evaluator.py does not exist" in issues[0]
    assert cleaned is True
    assert (
        json.loads(next(tmp_path.rglob("failure.json")).read_text(encoding="utf-8"))["error_type"]
        == "RuntimeError"
    )
    assert json.loads(next(tmp_path.rglob("state.json")).read_text(encoding="utf-8")) == {
        "status": "failed"
    }
    assert next(tmp_path.rglob("artifacts.json")).is_file()


def test_docker_browser_validation_does_not_guess_capabilities_from_image_name() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.docker_workspace,
            image="organization/custom-runtime:1",
            test_command="python3 verify.py",
            browser={
                "enabled": True,
                "runtime": "playwright_python",
                "start_url": "http://127.0.0.1:8000",
                "allowed_origins": ["http://127.0.0.1:8000"],
            },
        ),
    )

    assert task_structure_issues(task) == []


def test_workspace_contract_matches_the_builtin_room_inventory_runtime() -> None:
    valid = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.workspace,
            workspace={
                "start_room": "office",
                "rooms": {"office": ["brief"], "mailroom": []},
                "goal": {"outgoing_bin": ["brief"]},
            },
        ),
    )
    invalid = valid.model_copy(
        update={
            "environment": valid.environment.model_copy(
                update={
                    "workspace": {
                        "rooms": {"office": []},
                        "goal": {"outgoing_bin": ["missing_brief"]},
                    }
                }
            )
        }
    )

    assert task_structure_issues(valid) == []
    invalid_issues = task_structure_issues(invalid)
    assert any("mailroom" in issue for issue in invalid_issues)
    assert any("must exist" in issue for issue in invalid_issues)


def test_workspace_contract_explains_the_executable_state_shape() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.workspace,
            workspace={
                "rooms": [{"id": "office", "objects": ["brief"]}],
                "goal": {"outgoing_bin": "mailroom"},
            },
        ),
    )

    issues = task_structure_issues(task)

    assert any("mapping room names to arrays of item IDs" in issue for issue in issues)
    assert any("array of required item IDs" in issue for issue in issues)


def test_task_agent_qc_excerpt_preserves_prompt_ending_and_marks_clipping() -> None:
    system_prompt = "BEGIN " + ("adaptive policy " * 100) + " COMPLETE END"

    compact = compact_task_agent_for_qc(
        {
            "schema_version": "evalclaw.task_agent.v1",
            "agent_role": "dialogue_simulator",
            "system_prompt": system_prompt,
        }
    )

    excerpt = compact["system_prompt"]
    assert excerpt.startswith("BEGIN ")
    assert excerpt.endswith(" COMPLETE END")
    assert "QC review excerpt clipped" in excerpt
    assert compact["system_prompt_character_count"] == len(system_prompt)


def test_gui_contract_requires_a_startable_session_evaluator_and_vm_source() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.gui_desktop,
            requires_vm=True,
            vm={"display": "1920x1080"},
            session={"workflow": "Edit the document."},
            evaluation={"description": "Check the document."},
        ),
    )

    issues = task_structure_issues(task)

    assert any("environment.session.application" in issue for issue in issues)
    assert any("environment.session.launch_state" in issue for issue in issues)
    assert any("environment.evaluation" in issue for issue in issues)
    assert any("runner-resolvable" in issue for issue in issues)
    assert any("baseline_checks" in issue for issue in issues)


def test_gui_vm_contract_treats_vm_as_requires_vm_and_rejects_placeholder_sources() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.gui_desktop,
            vm={
                "guest_os": "windows",
                "template": "<runner-resolvable Windows template identifier>",
            },
            session={
                "application": "Windows Desktop",
                "launch_state": "The signed-in desktop is visible.",
                "baseline_checks": [
                    {"method": "command", "command": "exit 0", "expected_exit_code": 0}
                ],
            },
            evaluation={"method": "bridge_state_check"},
        ),
    )

    issues = task_structure_issues(task)

    assert any("environment.vm.template" in issue for issue in issues)


def test_windows_capability_vm_requires_concrete_named_user_setup() -> None:
    environment = AgentEnvironmentSpec(
        type=AgentEnvironmentType.gui_desktop,
        requires_vm=True,
        vm={
            "guest_os": "windows",
            "required_capabilities": ["desktop_bridge", "cloudbase_init_nocloud"],
        },
        vm_provisioning={
            "powershell_commands": ["icacls 'C:\\Work' /grant 'worker:(OI)(CI)M'"],
        },
        session={
            "application": "Windows Desktop",
            "launch_state": "The worker desktop is signed in.",
            "baseline_checks": [
                {
                    "method": "command",
                    "command": "if ($env:USERNAME -ne 'worker') { exit 1 }; exit 0",
                    "expected_exit_code": 0,
                }
            ],
        },
        evaluation={
            "method": "bridge_state_check",
            "checks": [
                {
                    "method": "command",
                    "command": "if (Test-Path 'C:\\Work') { exit 0 } else { exit 1 }",
                    "expected_exit_code": 0,
                }
            ],
        },
    )

    issues = task_structure_issues(_task(TaskType.agent, environment=environment))

    assert any("does not create a local user" in issue for issue in issues)
    assert any("concrete logon mechanism" in issue for issue in issues)

    windows_identity_environment = environment.model_copy(
        update={
            "session": {
                **environment.session,
                "baseline_checks": [
                    {
                        "method": "command",
                        "command": (
                            "$u=[Security.Principal.WindowsIdentity]::GetCurrent().Name; "
                            "if ($u -notmatch '\\\\worker$') { exit 1 }; exit 0"
                        ),
                        "expected_exit_code": 0,
                    }
                ],
            }
        }
    )
    windows_identity_issues = task_structure_issues(
        _task(TaskType.agent, environment=windows_identity_environment)
    )

    assert any("does not create a local user" in issue for issue in windows_identity_issues)
    assert any("concrete logon mechanism" in issue for issue in windows_identity_issues)

    valid = environment.model_copy(
        update={
            "vm_provisioning": {
                "powershell_commands": [
                    "$pw=ConvertTo-SecureString 'local-only' -AsPlainText -Force; "
                    "New-LocalUser -Name 'worker' -Password $pw | Out-Null; "
                    "$w='HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon'; "
                    "Set-ItemProperty $w AutoAdminLogon '1'; "
                    "Set-ItemProperty $w DefaultUserName 'worker'; "
                    "Set-ItemProperty $w DefaultPassword 'local-only'"
                ],
                "restart_after_provisioning": True,
            }
        }
    )

    assert task_structure_issues(_task(TaskType.agent, environment=valid)) == []


def test_windows_vm_rejects_target_inaccessible_evaluator_oracle() -> None:
    environment = AgentEnvironmentSpec(
        type=AgentEnvironmentType.gui_desktop,
        requires_vm=True,
        vm={
            "guest_os": "windows",
            "required_capabilities": ["desktop_bridge", "cloudbase_init_nocloud"],
        },
        vm_provisioning={
            "powershell_commands": [
                "$oracle='C:\\ProgramData\\PrivateOracle'\n"
                "New-Item -ItemType Directory -Force $oracle | Out-Null\n"
                "icacls $oracle /inheritance:r | Out-Null\n"
                "icacls $oracle /grant:r 'SYSTEM:(OI)(CI)(F)' "
                "'Administrators:(OI)(CI)(F)' | Out-Null"
            ]
        },
        session={
            "application": "Windows Desktop",
            "launch_state": "The signed-in desktop is visible.",
            "baseline_checks": [
                {
                    "method": "file_exists",
                    "path": "C:\\Users\\Public\\Desktop\\task.txt",
                }
            ],
        },
        evaluation={
            "method": "bridge_state_check",
            "checks": [
                {
                    "method": "command",
                    "command": (
                        "$ref='C:\\ProgramData\\PrivateOracle'; "
                        "if ((Get-FileHash (Join-Path $ref 'expected.txt')).Hash) "
                        "{ exit 0 } else { exit 1 }"
                    ),
                    "expected_exit_code": 0,
                }
            ],
        },
    )

    issues = task_structure_issues(_task(TaskType.agent, environment=environment))

    assert any("cannot read" in issue and "Embed expected values or hashes" in issue for issue in issues)


def test_gui_desktop_rejects_unresolved_private_command_identifiers() -> None:
    environment = AgentEnvironmentSpec(
        type=AgentEnvironmentType.gui_desktop,
        requires_vm=True,
        vm={"image": "windows-11-cloudbase", "guest_os": "windows"},
        session={
            "application": "Windows Desktop",
            "launch_state": "The signed-in desktop is visible.",
            "baseline_checks": [
                {
                    "id": "fault_exists",
                    "method": "command",
                    "command": "RUNNER_PRIVATE_BRIDGE_COMMAND:verify_fault",
                    "expected_exit_code": 0,
                }
            ],
        },
        evaluation={
            "method": "bridge_state_check",
            "checks": [
                {
                    "id": "repair_complete",
                    "method": "command",
                    "command": "RUNNER_PRIVATE_BRIDGE_COMMAND:verify_repair",
                    "expected_exit_code": 0,
                }
            ],
        },
    )
    task = _task(TaskType.agent, environment=environment)

    issues = task_structure_issues(task)

    assert sum("opaque runner-private command identifiers" in issue for issue in issues) == 2

    valid = task.model_copy(
        update={
            "environment": environment.model_copy(
                update={
                    "session": {
                        **environment.session,
                        "baseline_checks": [
                                {
                                    "method": "command",
                                    "command": (
                                        "if (Test-Path 'C:\\Windows') { exit 0 } else { exit 1 }"
                                    ),
                                    "expected_exit_code": 0,
                                }
                        ],
                    },
                    "evaluation": {
                        "method": "bridge_state_check",
                        "checks": [
                                {
                                    "method": "command",
                                    "command": (
                                        "if (Test-Path 'C:\\Windows') { exit 0 } else { exit 1 }"
                                    ),
                                    "expected_exit_code": 0,
                                }
                        ],
                    },
                }
            )
        }
    )
    assert task_structure_issues(valid) == []


def test_gui_desktop_rejects_probe_only_evaluation_and_metadata_evaluator() -> None:
    environment = AgentEnvironmentSpec(
        type=AgentEnvironmentType.gui_desktop,
        session={
            "application": "Windows Desktop",
            "launch_state": "The signed-in desktop is visible.",
        },
        evaluation={
            "checks": [
                {
                    "method": "command",
                    "command": (
                        "powershell.exe -NoProfile -Command \"$state=Get-Service spooler; "
                        "$state | ConvertTo-Json -Compress; exit 0\""
                    ),
                    "expected_exit_code": 0,
                }
            ]
        },
    )
    task = _task(TaskType.agent, environment=environment)
    task.metadata["runner_private_evaluator"] = {
        "location": "runner_private://evaluators/check.py",
        "entrypoint": "python check.py",
    }

    issues = task_structure_issues(task)

    assert any("succeeds unconditionally" in issue for issue in issues)
    assert any("ordinary task metadata is not executable" in issue for issue in issues)


def test_gui_desktop_accepts_command_that_directly_asserts_final_state() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.gui_desktop,
            session={
                "application": "Windows Desktop",
                "launch_state": "The signed-in desktop is visible.",
            },
            evaluation={
                "checks": [
                    {
                        "method": "command",
                        "command": (
                            "powershell.exe -NoProfile -Command \"$svc=Get-Service spooler; "
                            "if($svc.Status -ne 'Running'){exit 1}; exit 0\""
                        ),
                        "expected_exit_code": 0,
                    }
                ]
            },
        ),
    )

    assert task_structure_issues(task) == []


def test_gui_vm_provisioning_matches_declared_guest_os() -> None:
    base_environment = AgentEnvironmentSpec(
        type=AgentEnvironmentType.gui_desktop,
        requires_vm=True,
        vm={"image": "windows-11-cloudbase", "guest_os": "windows"},
        session={
            "application": "desktop",
            "start_state": "Signed in at the desktop.",
            "baseline_checks": [
                {"method": "file_exists", "path": r"C:\EvalClaw"},
            ],
        },
        evaluation={"method": "bridge_state_check"},
        vm_provisioning={"powershell_commands": ["New-Item C:\\EvalClaw -ItemType Directory -Force"]},
    )
    valid = _task(TaskType.agent, environment=base_environment)
    invalid = valid.model_copy(
        update={
            "environment": base_environment.model_copy(
                update={"vm_provisioning": {"apt_packages": ["curl"]}}
            )
        }
    )
    unchecked = valid.model_copy(
        update={
            "environment": base_environment.model_copy(
                update={"session": {"application": "desktop", "start_state": "Signed in."}}
            )
        }
    )
    unsupported_check = valid.model_copy(
        update={
            "environment": base_environment.model_copy(
                update={
                    "session": {
                        **base_environment.session,
                        "baseline_checks": [{"method": "path_exists", "path": r"C:\EvalClaw"}],
                    }
                }
            )
        }
    )
    linux_restart = valid.model_copy(
        update={
            "environment": base_environment.model_copy(
                update={
                    "vm": {"image": "linux-base", "guest_os": "linux"},
                    "vm_provisioning": {"restart_after_provisioning": True},
                }
            )
        }
    )

    assert task_structure_issues(valid) == []
    assert any("Linux-only package fields" in issue for issue in task_structure_issues(invalid))
    assert any("baseline_checks" in issue for issue in task_structure_issues(unchecked))
    assert any("Windows-only fields" in issue for issue in task_structure_issues(linux_restart))
    assert any("unsupported method path_exists" in issue for issue in task_structure_issues(unsupported_check))


def test_windows_vm_provisioning_rejects_powershell_syntax_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        "evalclaw.construction.validation._parse_powershell_syntax_errors",
        lambda command: ["Unexpected token"] if "broken" in command else [],
    )
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.gui_desktop,
            requires_vm=True,
            vm={"image": "windows-base", "guest_os": "windows"},
            vm_provisioning={"powershell_commands": ["broken syntax"]},
            session={
                "application": "Windows Desktop",
                "launch_state": "The signed-in desktop is visible.",
                "baseline_checks": [
                    {"method": "command", "command": "exit 0", "expected_exit_code": 0}
                ],
            },
            evaluation={"method": "bridge_state_check"},
        ),
    )

    assert any("invalid syntax" in issue for issue in task_structure_issues(task))


def test_windows_vm_checks_use_raw_powershell_bodies() -> None:
    environment = AgentEnvironmentSpec(
        type=AgentEnvironmentType.gui_desktop,
        requires_vm=True,
        vm={"image": "windows-base", "guest_os": "windows"},
        session={
            "application": "Windows Desktop",
            "launch_state": "The signed-in desktop is visible.",
            "baseline_checks": [
                {
                    "method": "command",
                    "command": 'powershell.exe -NoProfile -Command "exit 0"',
                    "expected_exit_code": 0,
                }
            ],
        },
        evaluation={
            "method": "bridge_state_check",
            "checks": [{"method": "command", "command": "if ($true) { exit 0 } else { exit 1 }"}],
        },
    )
    invalid = _task(TaskType.agent, environment=environment)
    valid = invalid.model_copy(
        update={
            "environment": environment.model_copy(
                update={
                    "session": {
                        **environment.session,
                        "baseline_checks": [
                            {"method": "command", "command": "exit 0", "expected_exit_code": 0}
                        ],
                    }
                }
            )
        }
    )

    assert any("raw PowerShell script body" in issue for issue in task_structure_issues(invalid))
    assert task_structure_issues(valid) == []


def test_windows_interactive_provisioning_requires_restart() -> None:
    environment = AgentEnvironmentSpec(
        type=AgentEnvironmentType.gui_desktop,
        requires_vm=True,
        vm={"image": "windows-base", "guest_os": "windows"},
        vm_provisioning={
            "interactive_powershell_commands": [
                "New-Item -Path 'HKCU:\\Software\\EvalClaw' -Force | Out-Null"
            ]
        },
        session={
            "application": "Windows Desktop",
            "launch_state": "The signed-in desktop is visible.",
            "baseline_checks": [
                {"method": "command", "command": "exit 0", "expected_exit_code": 0}
            ],
        },
        evaluation={
            "method": "bridge_state_check",
            "checks": [
                {"method": "command", "command": "if ($true) { exit 0 } else { exit 1 }"}
            ],
        },
    )
    invalid = _task(TaskType.agent, environment=environment)
    valid = invalid.model_copy(
        update={
            "environment": environment.model_copy(
                update={
                    "vm_provisioning": {
                        **environment.vm_provisioning,
                        "restart_after_provisioning": True,
                    }
                }
            )
        }
    )
    duplicate = valid.model_copy(
        update={
            "environment": valid.environment.model_copy(
                update={
                    "vm_provisioning": {
                        **valid.environment.vm_provisioning,
                        "powershell_commands": valid.environment.vm_provisioning[
                            "interactive_powershell_commands"
                        ],
                    }
                }
            )
        }
    )
    separate = valid.model_copy(
        update={
            "environment": valid.environment.model_copy(
                update={
                    "vm_provisioning": {
                        **valid.environment.vm_provisioning,
                        "powershell_commands": ["Write-Output 'system setup'"],
                    }
                }
            )
        }
    )

    assert any("requires restart_after_provisioning=true" in issue for issue in task_structure_issues(invalid))
    assert task_structure_issues(valid) == []
    assert any("exactly one execution identity" in issue for issue in task_structure_issues(duplicate))
    assert task_structure_issues(separate) == []
    assert separate.environment.vm_provisioning["powershell_commands"] == [
        "Write-Output 'system setup'"
    ]


def test_windows_vm_provisioning_rejects_ambiguous_scheduled_task_parameters() -> None:
    invalid = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.gui_desktop,
            requires_vm=True,
            vm={"image": "windows-base", "guest_os": "windows"},
            vm_provisioning={
                "powershell_commands": [
                    "Register-ScheduledTask Report -Action $action -Trigger $trigger "
                    "-Principal $principal -Password $password -Force"
                ]
            },
            session={
                "application": "Windows Desktop",
                "launch_state": "The signed-in desktop is visible.",
                "baseline_checks": [
                    {"method": "command", "command": "exit 0", "expected_exit_code": 0}
                ],
            },
            evaluation={"method": "bridge_state_check"},
        ),
    )
    valid = invalid.model_copy(
        update={
            "environment": invalid.environment.model_copy(
                update={
                    "vm_provisioning": {
                        "powershell_commands": [
                            "Register-ScheduledTask Report -Action $action -Trigger $trigger "
                            "-User $user -Password $password -RunLevel Limited -Force"
                        ]
                    }
                }
            )
        }
    )
    separate_calls = invalid.model_copy(
        update={
            "environment": invalid.environment.model_copy(
                update={
                    "vm_provisioning": {
                        "powershell_commands": [
                            "Register-ScheduledTask Final -Action $action -Trigger $trigger "
                            "-Principal $principal -Force; "
                            "Register-ScheduledTask Helper -Action $helper -Trigger $trigger "
                            "-User $user -Password $password -RunLevel Limited -Force"
                        ]
                    }
                }
            )
        }
    )

    assert any("different parameter sets" in issue for issue in task_structure_issues(invalid))
    assert task_structure_issues(valid) == []
    assert task_structure_issues(separate_calls) == []


def test_qc_warnings_do_not_make_a_runner_ready_dataset_unacceptable() -> None:
    warning = QcIssue(
        item_id="task_1",
        severity=QcSeverity.warning,
        category=QcCategory.clarity,
        message="Optional clarification.",
    )
    report = QcReport(
        issues=[warning],
        passed_item_ids=["task_1"],
        quality_score=0.75,
    )

    assert report.is_acceptable is True


def test_qc_severity_contains_only_problem_levels() -> None:
    assert set(QcSeverity) == {QcSeverity.warning, QcSeverity.error}


def test_agent_task_package_preserves_alternative_artifact_semantics() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.gui_desktop,
            session={
                "application": "Windows Desktop",
                "launch_state": "The signed-in desktop is visible.",
            },
            evaluation={"method": "bridge_state_check"},
        ),
    )
    task.metadata.update(
        {
            "expected_artifacts": ["C:/output/report.md", "C:/output/report.txt"],
            "artifact_requirement": "exactly_one",
        }
    )
    agent_env = task.environment.model_dump(mode="json")

    package = _agent_task_package_for_task(task, agent_env)

    assert package["output_contract"]["artifact_requirement"] == "exactly_one"
    assert package["output_contract"]["expected_artifacts"] == [
        "C:/output/report.md",
        "C:/output/report.txt",
    ]
    assert package["output_contract"]["required_outputs"] == [
        "Exactly one of: C:/output/report.md; C:/output/report.txt"
    ]

    task.environment.session["expected_artifacts"] = [
        {
            "path": "C:/output/report.json",
            "kind": "file",
            "format": "json",
            "required": True,
        }
    ]
    object_package = _agent_task_package_for_task(
        task,
        task.environment.model_dump(mode="json"),
    )

    assert object_package["output_contract"]["expected_artifacts"] == [
        "C:/output/report.json"
    ]
    assert object_package["artifact_collection"]["collect_paths"] == [
        "C:/output/report.json"
    ]

    task.metadata = {
        "output_contract": {
            "required_outputs": ["A final incident report"],
            "schema": {"type": "string"},
            "constraints": "must not be expanded character by character",
        }
    }
    declared_package = _agent_task_package_for_task(task, agent_env)

    assert declared_package["output_contract"]["required_outputs"] == [
        "A final incident report"
    ]
    assert declared_package["output_contract"]["schema"] == {"type": "string"}
    assert len(declared_package["output_contract"]["constraints"]) == 2


def test_workspace_agent_task_package_uses_builtin_runtime_tools() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.workspace,
            workspace={
                "start_room": "office",
                "rooms": {"office": ["brief"], "mailroom": []},
                "goal": {"outgoing_bin": ["brief"]},
            },
        ),
    )

    package = _agent_task_package_for_task(
        task,
        task.environment.model_dump(mode="json"),
    )

    assert package["trajectory_requirements"]["required_tools"] == [
        "look",
        "move",
        "inspect",
        "take",
        "place",
        "final",
    ]


def test_agent_task_package_exposes_provider_image_capability_requirements() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(
            type=AgentEnvironmentType.gui_desktop,
            requires_vm=True,
            vm={
                "guest_os": "windows",
                "required_capabilities": [
                    "desktop_bridge",
                    "cloudbase_init_nocloud",
                    "powershell",
                ],
            },
            session={"application": "Windows Desktop"},
            evaluation={"method": "bridge_state_check"},
        ),
    )
    agent_env = task.environment.model_dump(mode="json")

    package = _agent_task_package_for_task(task, agent_env)

    assert package["environment_requirements"]["required_capabilities"] == [
        "desktop_bridge",
        "cloudbase_init_nocloud",
        "powershell",
    ]


def test_multi_turn_contract_requires_bounded_scripted_or_dynamic_followups() -> None:
    invalid = _task(
        TaskType.multi_turn,
        rubric="Score the complete dialogue.",
        interaction={"max_turns": 3},
    )
    valid = invalid.model_copy(
        update={"interaction": {"max_turns": 3, "user_turns": ["Please revise the answer."]}}
    )
    structured_turns = invalid.model_copy(
        update={
            "interaction": {
                "max_turns": 3,
                "user_turns": [{"message": "Please revise the answer."}],
            }
        }
    )
    excessive_turns = invalid.model_copy(
        update={"interaction": {"max_turns": 8, "followup_instruction": "Keep probing."}}
    )

    assert any("interaction.user_turns" in issue for issue in task_structure_issues(invalid))
    assert task_structure_issues(valid) == []
    assert any("non-empty strings" in issue for issue in task_structure_issues(structured_turns))
    assert any("between 1 and 5" in issue for issue in task_structure_issues(excessive_turns))


def test_adaptive_multi_turn_contract_rejects_scripted_followups() -> None:
    design = TaskDesign(
        id="adaptive_dialogue",
        task_type=TaskType.multi_turn,
        task_count=1,
        content_design={"description": "Adaptive pressure dialogue."},
        interaction_requirements={"followup_mode": "adaptive"},
    )
    scripted = _task(
        TaskType.multi_turn,
        rubric="Score the complete dialogue.",
        interaction={"max_turns": 3, "user_turns": ["Please reconsider."]},
    ).model_copy(update={"system_prompt": "Adapt pressure to the target reply."})
    adaptive = scripted.model_copy(
        update={
            "interaction": {
                "max_turns": 3,
                "followup_instruction": "Read the transcript and adapt the next pressure turn.",
            }
        }
    )

    assert any(
        "Adaptive multi_turn" in issue
        for issue in task_structure_issues(scripted, task_design=design)
    )
    assert task_structure_issues(adaptive, task_design=design) == []


def test_multi_turn_packaging_uses_simulator_role() -> None:
    task = _task(
        TaskType.multi_turn,
        rubric="Score the complete dialogue.",
        interaction={"max_turns": 2, "followup_instruction": "Adapt to the transcript."},
    ).model_copy(update={"system_prompt": "Act as the other participant."})
    task.metadata["task_agent"] = {"agent_role": "target_agent_executor"}

    metadata = _task_agent_metadata_for_task(task, {})

    assert metadata["agent_role"] == "dialogue_simulator"


def test_task_agent_packaging_keeps_runner_private_vm_state_out_of_target_context() -> None:
    task = _task(
        TaskType.agent,
        environment=AgentEnvironmentSpec(type=AgentEnvironmentType.gui_desktop),
    ).model_copy(update={"description": "Inspect and repair the visible Windows project."})
    task.metadata["task_agent"] = {
        "initial_content": {
            "notes": "Public task note.",
            "hidden_file_names": ["private-oracle.json"],
            "evaluation": {"checks": [{"command": "PRIVATE-EVALUATOR-COMMAND"}]},
        }
    }
    agent_env = {
        "type": "gui_desktop",
        "visible_files": {"Desktop/readme.txt": "Public input."},
        "hidden_files": {"private-oracle.json": "PRIVATE-ANSWER"},
        "session": {
            "application": "Windows Desktop",
            "launch_state": "The desktop is visible.",
            "baseline_checks": [{"command": "PRIVATE-BASELINE-COMMAND"}],
        },
        "vm": {
            "guest_os": "windows",
            "bridge_api_key": "PRIVATE-BRIDGE-KEY",
            "vm_provider_api_key": "PRIVATE-PROVIDER-KEY",
            "seed_iso": "D:/private/seed.iso",
        },
        "vm_provisioning": {"powershell_commands": ["PRIVATE-PROVISION-COMMAND"]},
        "evaluation": {"checks": [{"command": "PRIVATE-EVALUATOR-COMMAND"}]},
    }

    initial = _task_agent_metadata_for_task(task, agent_env)["initial_content"]
    serialized = json.dumps(initial)

    assert initial["scenario"] == task.description
    assert initial["files"] == agent_env["visible_files"]
    assert initial["session"] == {
        "application": "Windows Desktop",
        "launch_state": "The desktop is visible.",
    }
    assert initial["vm"] == {"guest_os": "windows"}
    assert initial["notes"] == "Public task note."
    assert "PRIVATE-" not in serialized
    assert "hidden_file_names" not in serialized
    assert "vm_provisioning" not in serialized
    assert "evaluation" not in serialized


def test_removed_reference_model_tool_is_always_rejected() -> None:
    dimension = EvalDimension(
        id="comparison",
        name="Comparison",
        description="Compare response quality.",
        approach="Use pairwise judging.",
        task_types=[TaskType.generation],
    )
    spec = EvalSpec(
        objective="Compare model responses.",
        dimensions=[dimension],
        task_types=[TaskType.generation],
    )
    item = BenchmarkItem(
        id="pairwise_1",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt="Write a concise explanation of why the proposed change is safe and effective.",
        rubric="Prefer correctness, completeness, and clarity; return a tie when quality is equivalent.",
        judge_tools=[JudgeToolRef(tool="reference_model_response")],
    )
    suite = TaskSuite(spec=spec, objective=spec.objective, tasks=[item])

    draft_qc = run_qc_gate(suite, BenchmarkConfig(run_targets=False))
    execution_qc = run_qc_gate(suite, BenchmarkConfig(run_targets=True))

    assert any("Unsupported judge tool" in issue.message for issue in draft_qc.issues)
    assert any("Unsupported judge tool" in issue.message for issue in execution_qc.issues)


def test_dataset_checks_duplicate_ids_unknown_dimensions_and_near_duplicates() -> None:
    item_a = BenchmarkItem(
        id="same_id",
        dimension_id="known",
        task_type=TaskType.generation,
        prompt="Analyze the supplied dataset and explain the first trend in detail.",
        rubric="Score factual accuracy.",
    )
    item_b = item_a.model_copy(
        update={"prompt": "Analyze the supplied dataset and explain the second trend in detail."}
    )
    duplicate_issues = _duplicate_issues([item_a, item_b])

    assert any("duplicated" in issue.message for issue in duplicate_issues)
    near = [issue for issue in duplicate_issues if "very similar" in issue.message]
    assert near and all(issue.severity == QcSeverity.warning for issue in near)

    spec = EvalSpec(
        objective="Test coverage.",
        dimensions=[
            EvalDimension(
                id="known",
                name="Known",
                description="Known capability.",
                approach="Use direct tasks.",
            )
        ],
    )
    unknown = item_a.model_copy(update={"id": "unknown", "dimension_id": "missing"})
    assert any(
        "unknown dimension" in issue.message
        for issue in _coverage_issues(
            TaskSuite(spec=spec, objective=spec.objective, tasks=[unknown])
        )
    )


def test_dataset_duplicate_check_includes_choice_options() -> None:
    first = BenchmarkItem(
        id="choice_1",
        dimension_id="vision",
        task_type=TaskType.choice,
        prompt="What object is shown in the blurred image?",
        choices=[
            {"id": "A", "text": "Lion"},
            {"id": "B", "text": "Tiger"},
        ],
        correct_choice_ids=["A"],
    )
    different_options = first.model_copy(
        update={
            "id": "choice_2",
            "choices": [
                ChoiceOption(id="A", text="Bus"),
                ChoiceOption(id="B", text="Truck"),
            ],
        }
    )
    identical = first.model_copy(update={"id": "choice_3"})

    assert not any(
        issue.severity == QcSeverity.error
        and issue.category == QcCategory.duplicate
        for issue in _duplicate_issues([first, different_options])
    )
    assert any(
        issue.item_id == identical.id
        and issue.severity == QcSeverity.error
        and issue.category == QcCategory.duplicate
        for issue in _duplicate_issues([first, identical])
    )


def test_asset_qc_requires_existing_prompt_referenced_paths(tmp_path) -> None:
    missing_path = tmp_path / "missing.png"
    item = BenchmarkItem(
        id="image_1",
        dimension_id="vision",
        task_type=TaskType.generation,
        prompt="Inspect the supplied image and describe the main visible anomaly.",
        assets=[{"path": str(missing_path)}],
        rubric="Score against visible evidence.",
    )

    messages = [issue.message for issue in _static_item_issues(item)]

    assert any("do not reference asset path" in message for message in messages)
    assert any("does not exist" in message for message in messages)


def test_choice_asset_path_may_be_referenced_by_choice(tmp_path) -> None:
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    task = TaskDefinition(
        id="image_choice_1",
        dimension_id="vision",
        task_type=TaskType.choice,
        title="Image choice",
        prompt="Select the matching candidate image.",
        assets=[{"path": str(image_path)}],
        choices=[
            ChoiceOption(id="A", text=str(image_path)),
            ChoiceOption(id="B", text="None of the above"),
        ],
        correct_choice_ids=["A"],
    )
    item = BenchmarkItem(
        id=task.id,
        dimension_id=task.dimension_id,
        task_type=task.task_type,
        prompt=task.prompt,
        assets=task.assets,
        choices=task.choices,
        correct_choice_ids=task.correct_choice_ids,
    )

    assert task_structure_issues(task) == []
    assert not any("reference asset path" in issue.message for issue in _static_item_issues(item))


def test_non_agent_tasks_reject_non_image_assets(tmp_path) -> None:
    text_path = tmp_path / "input.txt"
    text_path.write_text("task input", encoding="utf-8")
    task = TaskDefinition(
        id="text_asset_task",
        dimension_id="text",
        task_type=TaskType.generation,
        title="Text asset task",
        prompt=f"Use {text_path} to answer the question.",
        assets=[{"path": str(text_path)}],
        rubric="Score correctness.",
    )
    item = BenchmarkItem(
        id=task.id,
        dimension_id=task.dimension_id,
        task_type=task.task_type,
        prompt=task.prompt,
        assets=task.assets,
        rubric=task.rubric,
    )

    assert any("only image assets" in issue for issue in task_structure_issues(task))
    assert any(
        "only image assets" in issue.message for issue in _static_item_issues(item)
    )


def test_task_design_file_inputs_require_assets(tmp_path) -> None:
    design = TaskDesign(
        id="vision_design",
        task_type=TaskType.generation,
        task_count=1,
        input_requirements={
            "modalities": ["text", "image"],
            "asset_requirements": [{"asset_ref": "question_image"}],
        },
    )
    missing = _task(TaskType.generation, rubric="Score correctness.")
    image_path = tmp_path / "question.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    valid = TaskDefinition(
        id="task_2",
        dimension_id="dimension_1",
        task_type=TaskType.generation,
        title="Asset contract test",
        prompt=f"Inspect {image_path} and describe the object.",
        assets=[{"path": str(image_path)}],
        rubric="Score correctness.",
    )

    assert any("must provide assets" in issue for issue in task_structure_issues(missing, task_design=design))
    assert task_structure_issues(valid, task_design=design) == []


def test_llm_qc_receives_task_design_and_execution_relevant_environment_details(monkeypatch) -> None:
    captured: dict = {}

    def fake_call_llm(messages, *args, **kwargs):
        captured.update(json.loads(messages[0].content))
        return json.dumps({"issues": [], "summary": "ok"})

    monkeypatch.setattr("evalclaw.quality.llm_checks.call_llm", fake_call_llm)
    dimension = EvalDimension(
        id="analysis",
        name="Analysis",
        description="Evaluate analysis.",
        approach="Use an open response.",
        task_types=[TaskType.generation],
    )
    spec = EvalSpec(
        objective="Evaluate analysis.",
        dimensions=[dimension],
        task_types=[TaskType.generation],
    )
    blueprint = make_blueprint(
        "analysis_blueprint",
        dimension.id,
        "Analysis task",
        task_type=TaskType.generation,
    )
    design_id = blueprint.task_designs[0].id
    item = BenchmarkItem(
        id="analysis_1",
        dimension_id=dimension.id,
        task_type=TaskType.generation,
        prompt=(
            "Analyze the evidence and explain the most defensible conclusion. "
            + "Preserve all relevant evidence. " * 80
        ),
        rubric="Score evidence use and correctness.",
        metadata={
            "task_design_id": design_id,
            "agent_env": {
                "type": "gui_desktop",
                "requires_vm": True,
                "vm": {"template": "windows-template", "guest_os": "windows"},
                "session": {
                    "baseline_checks": [
                        {
                            "id": "fault_exists",
                            "method": "command",
                            "command": "Write-Output baseline " * 200,
                        }
                    ]
                },
                "vm_provisioning": {
                    "powershell_commands": ["Write-Output provision " * 200]
                },
            },
        },
    )
    suite = TaskSuite(spec=spec, objective=spec.objective, tasks=[item], blueprints=[blueprint])

    _llm_qc(suite, BenchmarkConfig(**dummy_config_kwargs()))

    assert captured["task_designs"][0]["id"] == design_id
    assert captured["items"][0]["prompt"] == item.prompt
    assert captured["items"][0]["prompt_is_complete"] is True
    assert captured["items"][0]["prompt_character_count"] == len(item.prompt)
    captured_env = captured["items"][0]["metadata"]["agent_env"]
    assert captured_env["vm"]["guest_os"] == "windows"
    assert captured_env["session"]["baseline_checks"][0]["id"] == "fault_exists"
    assert "QC review excerpt clipped" not in captured_env["session"]["baseline_checks"][0]["command"]
    assert "QC review excerpt clipped" not in captured_env["vm_provisioning"]["powershell_commands"][0]


def _minimal_llm_qc_suite() -> TaskSuite:
    dimension = EvalDimension(
        id="analysis",
        name="Analysis",
        description="Evaluate analysis.",
        approach="Use an open response.",
        task_types=[TaskType.generation],
    )
    spec = EvalSpec(
        objective="Evaluate analysis.",
        dimensions=[dimension],
        task_types=[TaskType.generation],
    )
    return TaskSuite(
        spec=spec,
        objective=spec.objective,
        tasks=[
            BenchmarkItem(
                id="analysis_1",
                dimension_id=dimension.id,
                task_type=TaskType.generation,
                prompt="Analyze the supplied evidence and explain the conclusion.",
                rubric="Score correctness.",
            )
        ],
    )


def test_configured_llm_qc_retries_then_raises_on_failure(monkeypatch) -> None:
    attempts = 0

    def fail_qc(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise ConnectionError("endpoint unavailable")

    monkeypatch.setattr("evalclaw.quality.llm_checks.call_llm", fail_qc)
    trace: dict[str, object] = {}

    with pytest.raises(RuntimeError, match="LLM QC failed after 3 attempts"):
        _llm_qc(
            _minimal_llm_qc_suite(),
            BenchmarkConfig(**dummy_config_kwargs()),
            trace=trace,
        )

    assert attempts == 3
    assert trace["status"] == "failed"
    assert trace["attempt"] == 3


def test_configured_llm_qc_retries_invalid_responses_until_success(monkeypatch) -> None:
    responses = iter(
        [
            "not json",
            json.dumps({"issues": [{"item_id": None}]}),
            json.dumps({"issues": [], "summary": "ok"}),
        ]
    )
    attempts = 0

    def answer_qc(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return next(responses)

    monkeypatch.setattr("evalclaw.quality.llm_checks.call_llm", answer_qc)
    trace: dict[str, object] = {}

    issues = _llm_qc(
        _minimal_llm_qc_suite(),
        BenchmarkConfig(**dummy_config_kwargs()),
        trace=trace,
    )

    assert issues == []
    assert attempts == 3
    assert trace["status"] == "completed"
    assert trace["attempt"] == 3


def test_llm_qc_metadata_compaction_keeps_execution_details() -> None:

    compact = _compact_metadata_for_qc(
        {
            "agent_env": {
                "type": "gui_desktop",
                "session": {"application": "desktop", "launch_state": "Start menu is open."},
                "evaluation": {"checks": [{"command": "verify-state"}]},
                "vm": {
                    "template": "windows-template",
                    "snapshot": "broken-state",
                    "required_capabilities": [
                        "desktop_bridge",
                        "cloudbase_init_nocloud",
                    ],
                },
                "vm_provisioning": {"install_steps": ["prepare-state"]},
            }
        }
    )["agent_env"]
    assert compact["session"]["launch_state"] == "Start menu is open."
    assert compact["evaluation"]["checks"][0]["command"] == "verify-state"
    assert compact["vm"]["snapshot"] == "broken-state"
    assert compact["vm"]["required_capabilities"] == [
        "desktop_bridge",
        "cloudbase_init_nocloud",
    ]
    assert compact["vm_provisioning"]["install_steps"] == ["prepare-state"]
