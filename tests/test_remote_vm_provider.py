from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evalclaw.execution.environment_claw import run_environment_claw
from evalclaw.execution.vm_materializer import VmTaskMaterializationResult
from evalclaw.execution.vm_provider import (
    VmProviderStatus,
    create_vm_session,
    resolve_vm_image_spec,
)
from evalclaw.types import BenchmarkConfig, BenchmarkItem, TaskType


class _Response:
    def __init__(self, status_code: int, payload: object = None, *, headers: dict | None = None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}
        self.content = b"" if payload is None else json.dumps(payload).encode()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def _capabilities(*, upload_sha: str = "") -> dict:
    return {
        "protocol_version": "evalclaw.vm_provider.v2",
        "features": ["image_inventory", "config_drive_upload", "async_create"],
        "images": [
            {
                "id": "windows-11-evalclaw-v2",
                "guest_os": "windows",
                "architecture": "x86_64",
                "capabilities": [
                    "desktop_bridge",
                    "cloudbase_init_nocloud",
                    "powershell",
                ],
                "digest": "sha256:base-image",
                "default": True,
            }
        ],
        "upload_sha": upload_sha,
    }


def test_remote_provider_uploads_config_drive_resolves_image_and_polls(monkeypatch, tmp_path) -> None:
    seed = tmp_path / "seed.iso"
    seed.write_bytes(b"portable config drive")
    digest = hashlib.sha256(seed.read_bytes()).hexdigest()
    requests: list[tuple[str, str, object]] = []

    class Client:
        def __init__(self, **kwargs):
            self.base_url = kwargs["base_url"]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, path):
            requests.append(("GET", str(path), None))
            if path == "/capabilities":
                return _Response(200, _capabilities())
            if str(path).endswith("/operations/op-1"):
                return _Response(
                    200,
                    {
                        "status": "ready",
                        "vm_id": "vm-remote-1",
                        "bridge_url": "https://provider.test/vms/vm-remote-1/bridge",
                        "bridge_api_key": "short-lived-secret",
                    },
                )
            raise AssertionError(path)

        def post(self, path, **kwargs):
            if path == "/artifacts/config-drives":
                uploaded = kwargs["files"]["file"][1].read()
                requests.append(("POST", path, uploaded))
                assert kwargs["data"]["sha256"] == digest
                assert kwargs["headers"]["Idempotency-Key"] == f"config-drive-{digest}"
                return _Response(
                    201,
                    {
                        "artifact_id": "artifact-1",
                        "url": "https://provider.test/artifacts/artifact-1",
                        "sha256": digest,
                    },
                )
            if path == "/vms":
                payload = kwargs["json"]
                requests.append(("POST", path, payload))
                assert payload["protocol_version"] == "evalclaw.vm_provider.v2"
                assert payload["vm"]["image"] == "windows-11-evalclaw-v2"
                assert "seed_iso" not in payload["vm"]
                assert payload["vm"]["config_drive"]["artifact_id"] == "artifact-1"
                return _Response(
                    202,
                    {"operation_id": "op-1", "status": "creating"},
                    headers={"Location": "/operations/op-1"},
                )
            raise AssertionError(path)

        def delete(self, path):
            requests.append(("DELETE", str(path), None))
            return _Response(204)

    monkeypatch.setattr("evalclaw.execution.vm_provider.httpx.Client", Client)
    monkeypatch.setattr("evalclaw.execution.vm_provider.time.sleep", lambda _: None)

    session = create_vm_session(
        "https://provider.test",
        api_key="provider-secret",
        vm_spec={
            "guest_os": "windows",
            "architecture": "x86_64",
            "required_capabilities": [
                "desktop_bridge",
                "cloudbase_init_nocloud",
                "powershell",
            ],
            "seed_iso": str(seed),
        },
        session_spec={"application": "Windows Desktop"},
        timeout=20,
    )

    assert session.vm_id == "vm-remote-1"
    assert session.bridge_url.endswith("/vms/vm-remote-1/bridge")
    assert session.bridge_api_key == "short-lived-secret"
    assert session.data["resolved_image"]["id"] == "windows-11-evalclaw-v2"
    assert session.data["config_drive"]["sha256"] == digest
    assert "bridge_api_key" not in session.data
    assert ("POST", "/artifacts/config-drives", b"portable config drive") in requests


def test_remote_provider_without_capabilities_keeps_legacy_sync_contract(monkeypatch) -> None:
    create_payload: dict = {}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, path):
            assert path == "/capabilities"
            return _Response(404)

        def post(self, path, **kwargs):
            assert path == "/vms"
            create_payload.update(kwargs["json"])
            return _Response(
                200,
                {
                    "vm_id": "legacy-vm",
                    "bridge_url": "http://legacy-provider/bridge",
                },
            )

    monkeypatch.setattr("evalclaw.execution.vm_provider.httpx.Client", Client)

    session = create_vm_session(
        "http://legacy-provider",
        vm_spec={"image": "legacy-image", "seed_iso": "/shared/seed.iso"},
        session_spec={"application": "desktop"},
    )

    assert session.vm_id == "legacy-vm"
    assert create_payload == {
        "vm": {"image": "legacy-image", "seed_iso": "/shared/seed.iso"},
        "session": {"application": "desktop"},
    }


def test_remote_provider_rejects_upload_hash_mismatch(monkeypatch, tmp_path) -> None:
    seed = tmp_path / "seed.iso"
    seed.write_bytes(b"seed")
    deleted: list[str] = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, path):
            return _Response(200, _capabilities())

        def post(self, path, **kwargs):
            assert path == "/artifacts/config-drives"
            return _Response(201, {"artifact_id": "bad", "sha256": "0" * 64})

        def delete(self, path):
            deleted.append(path)
            return _Response(204)

    monkeypatch.setattr("evalclaw.execution.vm_provider.httpx.Client", Client)

    with pytest.raises(RuntimeError, match="does not match"):
        create_vm_session(
            "https://provider.test",
            vm_spec={
                "guest_os": "windows",
                "required_capabilities": ["desktop_bridge"],
                "seed_iso": str(seed),
            },
        )
    assert deleted == ["/artifacts/bad"]


def test_remote_provider_rejects_missing_local_config_drive(monkeypatch, tmp_path) -> None:
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, path):
            return _Response(200, _capabilities())

    monkeypatch.setattr("evalclaw.execution.vm_provider.httpx.Client", Client)

    with pytest.raises(RuntimeError, match="does not point to a readable local file"):
        create_vm_session(
            "https://provider.test",
            vm_spec={
                "guest_os": "windows",
                "required_capabilities": ["desktop_bridge"],
                "seed_iso": str(tmp_path / "missing.iso"),
            },
        )


def test_image_resolution_fails_closed_when_inventory_cannot_satisfy_requirements() -> None:
    with pytest.raises(RuntimeError, match="no enabled image"):
        resolve_vm_image_spec(
            {
                "guest_os": "windows",
                "required_capabilities": ["desktop_bridge", "gpu"],
            },
            _capabilities(),
            capabilities_discovered=True,
        )


def test_image_resolution_does_not_guess_missing_os_or_architecture() -> None:
    capabilities = _capabilities()
    capabilities["images"][0].pop("guest_os")

    with pytest.raises(RuntimeError, match="no enabled image"):
        resolve_vm_image_spec(
            {"guest_os": "windows", "required_capabilities": ["desktop_bridge"]},
            capabilities,
            capabilities_discovered=True,
        )


def test_capabilities_without_explicit_v2_version_keep_legacy_contract(monkeypatch) -> None:
    seed_path = "C:/shared/task.iso"
    create_payload: dict = {}
    create_headers: dict = {}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, path):
            assert path == "/capabilities"
            capabilities = _capabilities()
            capabilities.pop("protocol_version")
            return _Response(200, capabilities)

        def post(self, path, **kwargs):
            assert path == "/vms"
            create_payload.update(kwargs["json"])
            create_headers.update(kwargs.get("headers") or {})
            return _Response(
                200,
                {"vm_id": "legacy-vm", "bridge_url": "http://legacy-provider/bridge"},
            )

    monkeypatch.setattr("evalclaw.execution.vm_provider.httpx.Client", Client)

    create_vm_session(
        "http://legacy-provider",
        vm_spec={"image": "legacy-image", "seed_iso": seed_path},
    )

    assert create_payload == {
        "vm": {"image": "legacy-image", "seed_iso": seed_path},
        "session": {},
    }
    assert create_headers == {}


def test_remote_provider_cleans_resources_after_malformed_create_response(
    monkeypatch, tmp_path
) -> None:
    seed = tmp_path / "seed.iso"
    seed.write_bytes(b"seed")
    digest = hashlib.sha256(seed.read_bytes()).hexdigest()
    deleted: list[str] = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, path):
            return _Response(200, _capabilities())

        def post(self, path, **kwargs):
            if path == "/artifacts/config-drives":
                return _Response(201, {"artifact_id": "artifact-1", "sha256": digest})
            assert path == "/vms"
            return _Response(200, {"vm_id": "vm-1"})

        def delete(self, path):
            deleted.append(path)
            return _Response(204)

    monkeypatch.setattr("evalclaw.execution.vm_provider.httpx.Client", Client)

    with pytest.raises(RuntimeError, match="bridge_url"):
        create_vm_session(
            "https://provider.test",
            vm_spec={
                "guest_os": "windows",
                "required_capabilities": ["desktop_bridge"],
                "seed_iso": str(seed),
            },
        )

    assert deleted == ["/vms/vm-1", "/artifacts/artifact-1"]


def test_remote_provider_redacts_nested_bridge_credentials(monkeypatch) -> None:
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, path):
            return _Response(404)

        def post(self, path, **kwargs):
            return _Response(
                200,
                {
                    "vm_id": "vm-1",
                    "bridge_url": "https://provider.test/vms/vm-1/bridge",
                    "bridge_api_key": "top-level-secret",
                    "bridge": {
                        "api_key": "nested-api-key",
                        "access_token": "nested-secret",
                        "status": "ready",
                    },
                },
            )

    monkeypatch.setattr("evalclaw.execution.vm_provider.httpx.Client", Client)

    session = create_vm_session("https://provider.test", vm_spec={"image": "legacy"})

    assert session.bridge_api_key == "top-level-secret"
    assert session.data["bridge"] == {"status": "ready"}
    assert "bridge_api_key" not in session.data


def test_environment_claw_resolves_remote_image_before_target_execution(monkeypatch) -> None:
    item = BenchmarkItem(
        id="remote_windows",
        dimension_id="vm",
        task_type=TaskType.agent,
        prompt="Repair the Windows workstation.",
        metadata={
            "agent_env": {
                "type": "gui_desktop",
                "requires_vm": True,
                "vm": {"guest_os": "windows"},
                "session": {
                    "application": "Windows Desktop",
                    "baseline_checks": [{"method": "command", "command": "exit 0"}],
                },
                "evaluation": {"method": "bridge_state_check"},
            }
        },
    )

    def fake_materialize(target: BenchmarkItem) -> VmTaskMaterializationResult:
        target.metadata["agent_env"]["vm"]["required_capabilities"] = [
            "desktop_bridge",
            "cloudbase_init_nocloud",
            "powershell",
        ]
        return VmTaskMaterializationResult(item_id=target.id, applied=False)

    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.materialize_vm_task",
        fake_materialize,
    )
    monkeypatch.setattr(
        "evalclaw.execution.environment_claw.probe_vm_provider",
        lambda *args, **kwargs: VmProviderStatus(
            True,
            provider_url="https://provider.test",
            data={
                "capabilities_discovered": True,
                "protocol_v2": True,
                "capabilities": _capabilities(),
            },
        ),
    )

    _, report = run_environment_claw(
        [item],
        BenchmarkConfig(
            run_targets=False,
            vm_provider_url="https://provider.test",
        ),
    )

    assert report.blocking_errors == []
    assert item.metadata["agent_env"]["vm"]["image"] == "windows-11-evalclaw-v2"
    assert any(action.action == "resolve VM image" and action.applied for action in report.actions)
