import json
import subprocess

import pytest

from evalclaw.execution import docker_networks as module


def test_network_disappearing_during_inspection_is_ignored(monkeypatch):
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, json.dumps([{"Id": "aaa"}]), "missing network"))
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **k: "aaa\n")
    assert module.inspect_networks(["docker"], ["aaa", "bbb"]) == [{"Id": "aaa"}]


def test_inspection_error_for_live_network_is_not_hidden(monkeypatch):
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, "[]", "inspection failed"))
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **k: "aaa\n")
    with pytest.raises(subprocess.CalledProcessError):
        module.inspect_networks(["docker"], ["aaa"])


def test_allocator_avoids_existing_networks_and_host_routes(monkeypatch):
    monkeypatch.setattr(module, "inspect_networks", lambda *a: [
        {"IPAM": {"Config": [{"Subnet": "172.16.0.0/27"}]}}
    ])
    def output(args, **kwargs):
        return 'aaa\n' if args[0] == "docker" else '[{"dst":"172.16.0.32/27"}]'
    monkeypatch.setattr(module.subprocess, "check_output", output)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(module.subprocess, "run", run)
    module.create_network(["docker"], ["network", "create", "--internal", "example"], "172.16.0.0/24")
    assert calls == [["docker", "network", "create", "--subnet", "172.16.0.64/27", "--internal", "example"]]
