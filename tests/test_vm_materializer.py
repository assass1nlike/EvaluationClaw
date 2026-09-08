import base64
from pathlib import Path

from evalclaw.execution.environment_claw import run_environment_claw
from evalclaw.execution.vm_materializer import (
    VmTaskMaterializationError,
    VmTaskMaterializationResult,
    _collect_guest_files,
    materialize_vm_task,
)
from evalclaw.execution.vm_provider import VmProviderStatus
from evalclaw.types import BenchmarkConfig, BenchmarkItem, TaskType


def test_materialize_vm_task_creates_seed_iso_and_updates_agent_env(monkeypatch, tmp_path) -> None:
    def fake_build_seed_iso(seed_dir: Path, iso_path: Path, *, timeout: int = 60) -> None:
        iso_path.write_bytes(b"fake iso")

    monkeypatch.setattr("evalclaw.execution.vm_materializer._build_seed_iso", fake_build_seed_iso)
    item = BenchmarkItem(
        id="vm_materialized_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Use the prepared VM files.",
        metadata={
            "agent_task_package": {
                "schema_version": "evalclaw.agent_task_package.v1",
                "capability_target": {"name": "VM file setup"},
                "visible_inputs": {
                    "instructions": "Use visible VM files.",
                    "file_names": ["Desktop/package_visible.txt"],
                },
                "hidden_references": {
                    "staging_phase": "post_agent_or_runner_private",
                    "file_names": ["reference/answer.txt"],
                    "reference_artifacts": ["Desktop/output.txt"],
                },
                "output_contract": {"expected_artifacts": ["Desktop/output.txt"]},
                "execution": {"run": "Use GUI bridge", "evaluate": "artifact check"},
                "evaluation": {"method": "artifact_check", "pass_criteria": "done"},
                "artifact_collection": {
                    "collect_paths": ["Desktop/output.txt"],
                    "collect_trajectory": True,
                },
                "trajectory_requirements": {"required_tools": ["screenshot", "write_file"]},
                "environment_requirements": {"type": "vm", "requires_vm": True},
            },
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "evalclaw-gui"},
                "visible_files": {
                    "Desktop/readme.md": "# Read me\n",
                    "Desktop/package_visible.txt": "visible package file",
                },
                "hidden_files": {"reference/answer.txt": "private answer"},
                "session": {
                    "application": "file_manager",
                    "baseline_checks": [
                        {
                            "method": "file_exists",
                            "path": "/home/ubuntu/Desktop/readme.md",
                        }
                    ],
                },
                "evaluation": {"method": "artifact_check", "pass_criteria": "done"},
            },
            "task_agent": {
                "initial_content": {
                    "files": {"Desktop/input.txt": "hello from initial content"},
                    "session": {"asset_files": {"Desktop/session.csv": "region,profit\nNA,3\n"}},
                },
                "execution": {
                    "environment_type": "vm",
                    "environment_ref": "metadata.agent_env",
                },
            },
        },
    )

    result = materialize_vm_task(item, work_dir=tmp_path)

    env = item.metadata["agent_env"]
    assert result.applied is True
    assert Path(result.seed_iso).read_bytes() == b"fake iso"
    assert env["vm"]["seed_iso"] == result.seed_iso
    assert "agent_env" not in item.metadata["task_agent"]["execution"]
    assert env["vm_materialization"]["file_count"] >= 5

    user_data = Path(result.work_dir, "seed", "user-data").read_text(encoding="utf-8")
    assert "/home/ubuntu/Desktop/input.txt" in user_data
    assert "/home/ubuntu/Desktop/session.csv" in user_data
    assert "/home/ubuntu/Desktop/readme.md" in user_data
    assert "/home/ubuntu/Desktop/package_visible.txt" in user_data
    assert "/opt/evalclaw/task/public/agent_task_package.json" in user_data
    assert "/opt/evalclaw/task/private/agent_task_package_private.json" in user_data
    assert "/opt/evalclaw/task/private/hidden_references/reference/answer.txt" in user_data
    assert "/opt/evalclaw/task/private/evaluation.json" in user_data
    assert base64.b64encode(b"hello from initial content").decode("ascii") in user_data
    assert base64.b64encode(b"private answer").decode("ascii") in user_data


def test_vm_public_manifests_do_not_expose_runner_private_evaluation() -> None:
    private_command = "PRIVATE-EVALUATOR-COMMAND"
    item = BenchmarkItem(
        id="private_vm_metadata",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Repair the visible project.",
        rubric="PRIVATE-RUBRIC-ANSWER",
        metadata={
            "task_agent": {
                "initial_content": {
                    "scenario": "The project is failing.",
                    "evaluation": {"checks": [{"command": private_command}]},
                    "session": {
                        "application": "Windows Desktop",
                        "baseline_checks": [{"command": "PRIVATE-BASELINE-COMMAND"}],
                    },
                }
            },
            "agent_task_package": {
                "schema_version": "evalclaw.agent_task_package.v1",
                "capability_target": {
                    "name": "Project repair",
                    "description": "PRIVATE-TASK-DESCRIPTION",
                },
                "visible_inputs": {"instructions": "Repair the project."},
                "hidden_references": {
                    "file_names": ["private/oracle.json"],
                    "reference_artifacts": ["private/reference-output.json"],
                },
                "execution": {"run": "Use the desktop.", "evaluate": private_command},
                "evaluation": {"checks": [{"command": private_command}]},
            },
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"guest_os": "windows"},
                "session": {
                    "application": "Windows Desktop",
                    "baseline_checks": [{"command": "PRIVATE-BASELINE-COMMAND"}],
                },
                "evaluation": {"checks": [{"command": private_command}]},
            },
        },
    )

    files = _collect_guest_files(item, item.metadata["agent_env"])
    public_files = "\n".join(file.content for file in files if not file.root_only)
    private_files = "\n".join(file.content for file in files if file.root_only)

    assert item.prompt in public_files
    assert "Windows Desktop" in public_files
    assert "PRIVATE-" not in public_files
    assert "PRIVATE-TASK-DESCRIPTION" in private_files
    assert "private/oracle.json" not in public_files
    assert "private/reference-output.json" not in public_files
    assert private_command in private_files


def test_materialize_vm_task_preserves_explicit_seed_iso(monkeypatch, tmp_path) -> None:
    def fail_build_seed_iso(seed_dir: Path, iso_path: Path, *, timeout: int = 60) -> None:
        raise AssertionError("explicit seed ISO should not be rebuilt")

    monkeypatch.setattr("evalclaw.execution.vm_materializer._build_seed_iso", fail_build_seed_iso)
    existing_seed = tmp_path / "existing.iso"
    existing_seed.write_bytes(b"existing")
    item = BenchmarkItem(
        id="vm_explicit_seed",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Use the VM.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"seed_iso": str(existing_seed)},
                "visible_files": {"Desktop/input.txt": "content"},
                "session": {
                    "baseline_checks": [
                        {"method": "command", "command": "test -d /", "expected_exit_code": 0}
                    ]
                },
            }
        },
    )

    result = materialize_vm_task(item, work_dir=tmp_path)

    assert result.applied is False
    assert result.seed_iso == str(existing_seed)
    assert item.metadata["agent_env"]["vm"]["seed_iso"] == str(existing_seed)
    assert (
        item.metadata["agent_env"]["vm_materialization"]["skipped_reason"]
        == "existing VM config-drive ISO preserved"
    )


def test_materialize_windows_vm_uses_cloudbase_init_powershell(monkeypatch, tmp_path) -> None:
    def fake_build_seed_iso(seed_dir: Path, iso_path: Path, *, timeout: int = 60) -> None:
        iso_path.write_bytes(b"fake windows iso")

    monkeypatch.setattr("evalclaw.execution.vm_materializer._build_seed_iso", fake_build_seed_iso)
    item = BenchmarkItem(
        id="windows_hidden_fault",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Repair the hidden Windows configuration fault.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "windows-11-cloudbase", "guest_os": "windows"},
                "visible_files": {"Desktop/readme.txt": "Inspect the workstation."},
                "hidden_files": {"expected/registry.json": '{"enabled": true}'},
                "session": {
                    "baseline_checks": [
                        {
                            "id": "fault_exists",
                            "method": "command",
                            "command": "if ((Get-ItemProperty 'HKLM:\\Software\\EvalClaw').Broken -eq 1) { exit 0 } else { exit 1 }",
                            "expected_exit_code": 0,
                        }
                    ]
                },
                "vm_provisioning": {
                    "choco_packages": ["sysinternals"],
                    "windows_features": ["TelnetClient"],
                    "restart_after_provisioning": True,
                    "interactive_powershell_commands": [
                        "New-Item -Path 'HKCU:\\Software\\EvalClaw' -Force | Out-Null"
                    ],
                    "powershell_commands": [
                        "New-Item -Path 'HKLM:\\Software\\EvalClaw' -Force | Out-Null",
                        "Set-ItemProperty -Path 'HKLM:\\Software\\EvalClaw' -Name Broken -Value 1",
                    ],
                },
            }
        },
    )

    result = materialize_vm_task(item, work_dir=tmp_path)
    user_data = Path(result.work_dir, "seed", "user-data").read_text(encoding="utf-8")

    assert result.applied is True
    assert result.guest_os == "windows"
    assert result.strategy == "cloudbase_init.nocloud.v1"
    assert user_data.startswith("#ps1_sysnative")
    assert r"C:\Users\Public\Desktop\readme.txt" in user_data
    assert (
        r"C:\ProgramData\EvalClaw\task\private\hidden_references\expected\registry.json"
        in user_data
    )
    assert base64.b64encode(b"Inspect the workstation.").decode("ascii") in user_data
    assert "choco install -y 'sysinternals'" in user_data
    assert "Enable-WindowsOptionalFeature" in user_data
    assert "Set-ItemProperty -Path 'HKLM:\\Software\\EvalClaw'" in user_data
    assert r"C:\ProgramData\EvalClaw\vm-provisioned" in user_data
    assert r"C:\ProgramData\EvalClaw\restart-after-provisioning" in user_data
    assert r"C:\ProgramData\EvalClaw\interactive-provisioning\setup.ps1" in user_data
    assert "CurrentVersion\\RunOnce" not in user_data
    assert user_data.index("icacls.exe $interactiveRoot") < user_data.index(
        r"interactive-provisioning\setup.ps1"
    )
    assert r"C:\ProgramData\EvalClaw\vm-materialized" in user_data
    assert result.provisioning["restart_after_provisioning"] is True
    assert result.provisioning["interactive_command_count"] == 1
    env = item.metadata["agent_env"]
    assert env["vm"]["seed_iso"] == result.seed_iso
    assert env["vm"]["config_drive_type"] == "nocloud"
    assert env["vm"]["required_capabilities"] == [
        "desktop_bridge",
        "cloudbase_init_nocloud",
        "powershell",
    ]
    baseline_checks = env["session"]["baseline_checks"]
    assert baseline_checks[0]["id"] == "fault_exists"
    baseline_paths = {check["path"] for check in baseline_checks if "path" in check}
    assert r"C:\ProgramData\EvalClaw\vm-materialized" in baseline_paths
    assert r"C:\ProgramData\EvalClaw\vm-provisioned" in baseline_paths


def test_windows_vm_rejects_linux_only_provisioning(tmp_path) -> None:
    item = BenchmarkItem(
        id="windows_bad_packages",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Use the Windows VM.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "windows-base", "guest_os": "windows"},
                "session": {
                    "baseline_checks": [
                        {"method": "command", "command": "exit 0", "expected_exit_code": 0}
                    ]
                },
                "vm_provisioning": {"apt_packages": ["curl"]},
            }
        },
    )

    try:
        materialize_vm_task(item, work_dir=tmp_path)
    except VmTaskMaterializationError as exc:
        assert "apt_packages" in str(exc)
    else:
        raise AssertionError("Windows provisioning should reject Linux-only package fields")


def test_materialize_vm_task_adds_cloud_init_vm_provisioning(monkeypatch, tmp_path) -> None:
    def fake_build_seed_iso(seed_dir: Path, iso_path: Path, *, timeout: int = 60) -> None:
        iso_path.write_bytes(b"fake iso")

    monkeypatch.setattr("evalclaw.execution.vm_materializer._build_seed_iso", fake_build_seed_iso)
    item = BenchmarkItem(
        id="vm_provisioned_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Use the provisioned VM.",
        metadata={
            "agent_env": {
                "type": "vm",
                "requires_vm": True,
                "vm": {"image": "ubuntu-base"},
                "session": {
                    "baseline_checks": [
                        {"method": "command", "command": "test -d /", "expected_exit_code": 0}
                    ]
                },
                "vm_provisioning": {
                    "enabled": True,
                    "apt_packages": ["kicad", "freecad", "blender"],
                    "pip_packages": ["pytest"],
                    "snap_packages": ["hello-world"],
                    "commands": ["echo ready >/opt/evalclaw/provisioning.txt"],
                },
            }
        },
    )

    result = materialize_vm_task(item, work_dir=tmp_path)
    user_data = Path(result.work_dir, "seed", "user-data").read_text(encoding="utf-8")

    assert result.applied is True
    assert result.file_count >= 1
    assert result.provisioning["apt_packages"] == ["kicad", "freecad", "blender"]
    assert "package_update: true" in user_data
    assert '- "kicad"' in user_data
    assert '- "freecad"' in user_data
    assert '- "blender"' in user_data
    assert "python3 -m pip install --no-cache-dir pytest" in user_data
    assert "snap install hello-world" in user_data
    assert "echo ready >/opt/evalclaw/provisioning.txt" in user_data
    assert "touch /opt/evalclaw/vm-provisioned" in user_data
    env = item.metadata["agent_env"]
    assert env["vm"]["seed_iso"] == result.seed_iso
    assert env["vm"]["required_capabilities"] == [
        "desktop_bridge",
        "cloud_init_nocloud",
    ]
    assert env["vm_materialization"]["provisioning"]["command_count"] >= 3


def test_environment_claw_materializes_and_probes_gui_vm_items(monkeypatch) -> None:
    called: list[str] = []

    def fake_materialize(item: BenchmarkItem) -> VmTaskMaterializationResult:
        called.append(item.id)
        return VmTaskMaterializationResult(
            item_id=item.id,
            applied=True,
            seed_iso="D:/localwork/vm_backends/materialized/item/seed.iso",
            file_count=1,
        )

    monkeypatch.setattr("evalclaw.execution.environment_claw.materialize_vm_task", fake_materialize)
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.probe_vm_provider",
        lambda *args, **kwargs: VmProviderStatus(True, provider_url="local://qemu", detail="ok"),
    )
    item = BenchmarkItem(
        id="gui_vm_item",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Run a VM-backed desktop task.",
        metadata={
            "agent_env": {"type": "vm", "requires_vm": True, "vm": {"image": "base-vm"}}
        },
    )

    _, report = run_environment_claw([item], BenchmarkConfig())

    assert called == ["gui_vm_item"]
    assert any(
        action.action == "materialize VM task content" and action.applied
        for action in report.actions
    )
    assert any(probe.name == "vm_provider" and probe.ok for probe in report.probes)


def test_windows_bridge_closes_command_stdin() -> None:
    bridge = (
        Path(__file__).parents[1] / "scripts" / "windows_vm" / "EvalClawBridge.ps1"
    ).read_text(encoding="utf-8")

    assert "$psi.RedirectStandardInput = $true" in bridge
    assert "$process.StandardInput.Close()" in bridge
