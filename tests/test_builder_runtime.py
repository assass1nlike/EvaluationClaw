"""Real Docker lifecycle checks; opt in with EVALCLAW_DOCKER_TESTS=1."""

import json
import os
import subprocess
import sys
import time

import pytest

from evalclaw.construction.runtime import BuilderRuntime
from evalclaw.types import BenchmarkConfig

pytestmark = pytest.mark.skipif(
    os.environ.get("EVALCLAW_DOCKER_TESTS") != "1",
    reason="requires local Docker images",
)


def test_isolation_limits_and_persistence(tmp_path):
    workspace = tmp_path / "builder"
    workspace.mkdir()
    secret = tmp_path / "sibling-secret"
    secret.write_text("other job")
    runtime = BuilderRuntime(
        workspace, BenchmarkConfig(builder_memory_mb=128, builder_pids_limit=32)
    )
    try:
        result = runtime.run(
            "from pathlib import Path; import os; "
            f"assert not Path({str(secret)!r}).exists(); "
            "assert not Path('/var/run/docker.sock').exists(); "
            "assert 'DEEPSEEK_API_KEY' not in os.environ; "
            "Path('asset.txt').write_text('retained'); "
            "Path('/tmp/session.txt').write_text('persistent')",
            timeout=10,
            max_chars=1000,
        )
        assert result.returncode == 0, result.stderr
        result = runtime.run(
            "from pathlib import Path; print(Path('/tmp/session.txt').read_text())",
            timeout=10,
            max_chars=1000,
        )
        assert result.stdout.strip() == "persistent"
        info = json.loads(subprocess.check_output([runtime.docker, "inspect", runtime.name]))[0]
        assert info["HostConfig"]["Memory"] == 128 * 1024 * 1024
        assert info["HostConfig"]["MemorySwap"] == 128 * 1024 * 1024
        assert info["HostConfig"]["PidsLimit"] == 32
        result = runtime.run("x=bytearray(512*1024*1024)", timeout=15, max_chars=1000)
        assert result.returncode != 0
    finally:
        runtime.close()
    assert (workspace / "asset.txt").read_text() == "retained"
    assert (
        subprocess.run([runtime.docker, "inspect", runtime.name], capture_output=True).returncode
        != 0
    )


def test_timeout_removes_detached_background_process(tmp_path):
    runtime = BuilderRuntime(tmp_path, BenchmarkConfig(builder_memory_mb=128))
    child_code = "import time,pathlib\nwhile True:\n pathlib.Path('heartbeat').write_text(str(time.time()))\n time.sleep(.05)"
    try:
        result = runtime.run(
            "import subprocess,sys; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}],start_new_session=True,"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "print(p.pid)",
            timeout=10,
            max_chars=1000,
        )
        assert result.returncode == 0
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            runtime.run(
                "import time;print('partial',flush=True);time.sleep(30)", timeout=1, max_chars=1000
            )
        assert "partial" in caught.value.stdout
        heartbeat = (tmp_path / "heartbeat").read_text()
        time.sleep(0.2)
        assert (tmp_path / "heartbeat").read_text() == heartbeat
        assert (
            subprocess.run(
                [runtime.docker, "inspect", runtime.name], capture_output=True
            ).returncode
            != 0
        )
    finally:
        runtime.close()


def test_owner_sigkill_cleans_container_and_network(tmp_path):
    code = (
        "from pathlib import Path; import time; "
        "from evalclaw.construction.runtime import BuilderRuntime; "
        "from evalclaw.types import BenchmarkConfig; "
        f"r=BuilderRuntime(Path({str(tmp_path)!r}),BenchmarkConfig(builder_memory_mb=128)); "
        "print(r.name,flush=True);time.sleep(60)"
    )
    owner = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    name = owner.stdout.readline().strip()
    assert name.startswith("evalclaw-builder-")
    try:
        owner.kill()
        owner.wait(timeout=5)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            container = subprocess.run(["docker", "inspect", name], capture_output=True)
            network = subprocess.run(["docker", "network", "inspect", name], capture_output=True)
            if container.returncode and network.returncode:
                break
            time.sleep(0.1)
        assert container.returncode != 0
        assert network.returncode != 0
    finally:
        owner.kill()
        owner.wait()
        owner.stdout.close()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", name], capture_output=True)


def test_inspection_reads_builder_assets_and_stops_on_timeout(tmp_path):
    import shlex

    from evalclaw.execution.docker import docker_subprocess_env
    from evalclaw.execution.docker_images import (
        run_in_inspection_container,
        start_inspection_container,
    )
    from evalclaw.execution.resource_guard import DockerResourceGuard

    (tmp_path / "downloaded.txt").write_text("downloaded resource")
    guard = DockerResourceGuard("docker", docker_subprocess_env())
    try:
        result = start_inspection_container(
            "python:3.11-slim",
            memory_mb=128,
            workspace=tmp_path,
            resource_guard=guard,
        )
        checked = run_in_inspection_container(
            result.container, "cat " + shlex.quote(str(tmp_path / "downloaded.txt"))
        )
        assert checked.stdout == "downloaded resource"
        checked = run_in_inspection_container(
            result.container, "echo partial; sleep 30", timeout_s=1
        )
        assert checked.timed_out and "partial" in checked.stdout
        info = json.loads(subprocess.check_output(["docker", "inspect", result.container]))[0]
        assert info["State"]["Running"] is False
    finally:
        guard.close()


def test_image_check_timeout_removes_container():
    from evalclaw.execution.docker_images import run_docker_image_check

    result = run_docker_image_check(
        "python:3.11-slim",
        "echo partial; sleep 30",
        timeout_s=1,
        memory_mb=128,
    )
    assert result.timed_out and "partial" in result.stdout
