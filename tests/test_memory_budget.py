from __future__ import annotations

import json
import multiprocessing as mp
import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import CancelledError
from pathlib import Path

import pytest
from pydantic import ValidationError

from evalclaw.execution import memory_budget as module
from evalclaw.execution.budget_docker import command
from evalclaw.types import BenchmarkConfig

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux cgroup v2")


def make_group(path):
    path.mkdir()
    (path / "memory.current").write_text("0")
    (path / "memory.stat").write_text("inactive_file 0\n")
    (path / "memory.events").write_text("oom 0\noom_kill 0\n")
    (path / "memory.events.local").write_text("oom 0\noom_kill 0\n")
    return path


def claim_in_process(group, state, ready, release):
    manager = module.MemoryBudget(group, 100, 10, state)
    with manager.reserve(60):
        ready.set()
        release.wait(10)


def test_budget_is_shared_across_processes_and_reclaims_crashed_owner(tmp_path):
    group = make_group(tmp_path / "group")
    state = tmp_path / "state"
    ctx = mp.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    holder = ctx.Process(target=claim_in_process, args=(group, state, ready, release))
    holder.start()
    admitted = threading.Event()
    manager = module.MemoryBudget(group, 100, 10, state)

    def waiter():
        with manager.reserve(60):
            admitted.set()

    thread = threading.Thread(target=waiter)
    try:
        assert ready.wait(10)
        thread.start()
        assert not admitted.wait(0.2)
        holder.kill()
        holder.join(5)
        assert admitted.wait(5)
        thread.join(5)
        assert json.loads((state / "claims.json").read_text()) == {}
    finally:
        if holder.is_alive():
            holder.terminate()
        holder.join(5)


def test_live_memory_blocks_admission_but_reclaimable_cache_does_not(tmp_path):
    group = make_group(tmp_path / "group")
    manager = module.MemoryBudget(group, 100, 10, tmp_path / "state")
    (group / "memory.current").write_text("85")
    admitted = threading.Event()

    def waiter():
        with manager.reserve(20):
            admitted.set()

    thread = threading.Thread(target=waiter)
    thread.start()
    try:
        assert not admitted.wait(0.2)
        (group / "memory.stat").write_text("inactive_file 70\n")
        assert admitted.wait(5)
    finally:
        (group / "memory.current").write_text("0")
        thread.join(5)


def test_exception_releases_reservation_and_oom_invalidates_work(tmp_path):
    group = make_group(tmp_path / "group")
    manager = module.MemoryBudget(group, 100, 10, tmp_path / "state")
    with pytest.raises(ValueError):
        with manager.reserve(60):
            raise ValueError("task failed")
    assert json.loads((manager.state / "claims.json").read_text()) == {}
    with pytest.raises(module.MemoryBudgetError):
        with manager.reserve(60):
            (group / "memory.events.local").write_text("oom 1\noom_kill 1\n")
    assert json.loads((manager.state / "claims.json").read_text()) == {}
    with pytest.raises(module.MemoryBudgetError):
        with manager.reserve(10):
            pytest.fail("must not admit after shared OOM")


def test_cancellation_and_oversize_fail_without_hanging(tmp_path):
    group = make_group(tmp_path / "group")
    manager = module.MemoryBudget(group, 100, 10, tmp_path / "state")
    with pytest.raises(module.MemoryBudgetError):
        with manager.reserve(91):
            pytest.fail("over budget")
    stop = threading.Event()
    stop.set()
    with pytest.raises(CancelledError):
        with manager.reserve(10, stop):
            pytest.fail("cancelled")


def test_task_local_oom_does_not_invalidate_other_jobs(tmp_path):
    group = make_group(tmp_path / "group")
    manager = module.MemoryBudget(group, 100, 10, tmp_path / "state")
    with manager.reserve(10):
        (group / "memory.events").write_text("oom 1\noom_kill 1\n")
    manager.check()


def test_policy_is_shared_while_active_and_can_change_between_batches(tmp_path):
    group = make_group(tmp_path / "group")
    first = module.MemoryBudget(group, 100, 10, tmp_path / "state")
    second = module.MemoryBudget(group, 100, 20, tmp_path / "state")
    token = first.join({"budget": 100, "headroom": 10})
    with pytest.raises(module.MemoryBudgetError):
        second.join({"budget": 100, "headroom": 20})
    first.leave(token)
    token = second.join({"budget": 100, "headroom": 20})
    second.leave(token)


def test_hard_limit_requires_host_process_to_be_in_slice():
    with pytest.raises(module.MemoryBudgetError, match="Launch the framework"):
        module._verify_group(
            "/sys/fs/cgroup/evalclaw.slice",
            600 * module.GIB,
            own_group="/sys/fs/cgroup/user.slice/session.scope",
        )
    with pytest.raises(module.MemoryBudgetError, match="system-level slice"):
        module._verify_group(
            "/sys/fs/cgroup/user.slice/user-1005.slice/user@1005.service/app.slice",
            600 * module.GIB,
        )


def test_automatic_concurrency_requires_budget():
    with pytest.raises(ValidationError):
        BenchmarkConfig(task_builder_max_workers=0)
    config = BenchmarkConfig(
        memory_budget_gib=600,
        memory_cgroup="/sys/fs/cgroup/evalclaw.slice",
        task_builder_max_workers=0,
        runner_max_workers=0,
    )
    assert module.worker_count(config.task_builder_max_workers, 28) == 28
    assert module.worker_count(4, 28) == 4
    assert module.worker_count(4, 2) == 2
    measured = BenchmarkConfig(memory_budget_gib=600, task_builder_max_workers=0, runner_max_workers=0)
    assert not measured.memory_cgroup


def test_measured_memory_and_host_pressure_gate_admission(monkeypatch, tmp_path):
    from evalclaw.execution import memory_usage

    usage = [85, 100]
    monkeypatch.setattr(memory_usage, "sample_usage", lambda *a: tuple(usage))
    manager = module.MemoryBudget(None, 100, 10, tmp_path)
    admitted = threading.Event()

    def waiter():
        with manager.reserve(20):
            admitted.set()

    thread = threading.Thread(target=waiter)
    thread.start()
    try:
        assert not admitted.wait(0.2)
        usage[:] = [0, 15]  # Other workloads still leave too little host memory.
        assert not admitted.wait(1.2)
        usage[:] = [0, 100]
        assert admitted.wait(5)
    finally:
        usage[:] = [0, 100]
        thread.join(5)
    assert json.loads((tmp_path / "claims.json").read_text()) == {}


def test_measured_wrapper_labels_containers_without_privileged_parent():
    spec = {"docker": "/usr/bin/docker", "label": "evalclaw.memory-owner=1005"}
    assert command(["run", "--rm", "alpine"], spec) == [
        "/usr/bin/docker", "run", "--label",
        "evalclaw.memory-owner=1005", "--rm", "alpine",
    ]
    assert command(["build", "-t", "example", "."], spec) == [
        "/usr/bin/docker", "buildx", "build", "--builder",
        "default", "--load", "-t", "example", ".",
    ]


def test_process_measurement_counts_descendants_and_retains_orphans(tmp_path):
    from evalclaw.execution.memory_usage import process_usage

    def process(pid, parent, identity, pages):
        folder = tmp_path / str(pid)
        folder.mkdir(exist_ok=True)
        fields = ["0"] * 22
        fields[0], fields[1], fields[19], fields[21] = "S", str(parent), identity, str(pages)
        (folder / "stat").write_text(f"{pid} (worker) " + " ".join(fields))

    process(100, 1, "root", 10)
    process(200, 100, "child", 20)
    process(300, 1, "unrelated", 30)
    owners = {"run": {"pid": 100, "identity": "root"}}
    total, tracked = process_usage(owners, {}, tmp_path)
    assert total == 30 * os.sysconf("SC_PAGE_SIZE")
    process(200, 1, "child", 20)
    total, tracked = process_usage({}, tracked, tmp_path)
    assert total == 30 * os.sysconf("SC_PAGE_SIZE")
    process(200, 1, "reused-pid", 20)
    total, _ = process_usage({}, tracked, tmp_path)
    assert total == 10 * os.sysconf("SC_PAGE_SIZE")


def test_container_transition_defers_admission_instead_of_failing_run(monkeypatch, tmp_path):
    from evalclaw.execution import memory_usage

    monkeypatch.setattr(memory_usage, "process_usage", lambda *a: (100, {}))
    def transitioning(*args):
        raise memory_usage.MemorySamplePending("teardown")
    monkeypatch.setattr(memory_usage, "container_usage", transitioning)
    usage, available = memory_usage.sample_usage(tmp_path, "docker")
    assert usage > 600 * module.GIB
    assert available == 0
    assert not (tmp_path / "usage.json").exists()


@pytest.mark.parametrize("operation", ["run", "create"])
def test_all_container_creation_gets_shared_parent(operation):
    spec = dict(docker="/usr/bin/docker", parent="evalclaw.slice", builder="dedicated")
    assert command([operation, "--memory", "8g", "image"], spec) == [
        "/usr/bin/docker",
        operation,
        "--cgroup-parent",
        "evalclaw.slice",
        "--memory",
        "8g",
        "image",
    ]
    with pytest.raises(ValueError):
        command([operation, "--cgroup-parent=system.slice", "image"], spec)


def test_build_preserves_local_images_and_uses_full_cgroup_path():
    spec = dict(
        docker="/usr/bin/docker",
        parent="evalclaw-batch.slice",
        build_parent="/evalclaw.slice/evalclaw-batch.slice",
    )
    assert command(["build", "-t", "task:test", "/context"], spec) == [
        "/usr/bin/docker",
        "buildx",
        "build",
        "--builder",
        "default",
        "--load",
        "--cgroup-parent",
        "/evalclaw.slice/evalclaw-batch.slice",
        "-t",
        "task:test",
        "/context",
    ]
    with pytest.raises(ValueError):
        command(["build", "--builder=default", "/context"], spec)


def test_budget_pins_selected_daemon_for_checks_measurement_and_children(monkeypatch, tmp_path):
    from evalclaw.execution import memory_usage
    from evalclaw.execution.budget_docker import docker_env

    endpoint = "unix:///run/experiment/docker.sock"
    monkeypatch.setenv("DOCKER_CONTEXT", "experiment")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/docker")
    calls = []

    def output(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["context", "inspect"]:
            assert args[3:] == ["--format", "{{json .Endpoints.docker.Host}}"]
            return json.dumps(endpoint)
        env = kwargs["env"]
        assert env["DOCKER_HOST"] == endpoint
        assert "DOCKER_CONTEXT" not in env and "DOCKER_TLS_VERIFY" not in env
        if args[1] == "info":
            return json.dumps({"CgroupDriver": "systemd", "CgroupVersion": "2"})
        if args[1:3] == ["buildx", "ls"]:
            return json.dumps({"Name": "default", "Driver": "docker"})
        assert args[1] == "ps"
        return ""

    monkeypatch.setattr(module.subprocess, "check_output", output)
    original_init = module.MemoryBudget.__init__

    def init(self, group, budget, headroom, state, **kwargs):
        original_init(self, group, budget, headroom, tmp_path / "state", **kwargs)

    monkeypatch.setattr(module.MemoryBudget, "__init__", init)
    with module.memory_budget(BenchmarkConfig(memory_budget_gib=600), tmp_path):
        spec = json.loads(Path(os.environ[module.SPEC_ENV]).read_text())
        assert spec["endpoint"] == endpoint
        assert docker_env(spec["endpoint"])["DOCKER_HOST"] == endpoint
        assert memory_usage.container_usage(spec["docker"], spec["endpoint"]) == (0, 0)
        assert json.loads((tmp_path / "memory-budget.json").read_text())["docker_endpoint"] == endpoint
    assert any(args[1] == "ps" for args in calls)
    assert os.environ["DOCKER_CONTEXT"] == "experiment"


def test_shared_budget_rejects_mixed_daemons_and_clears_stale_usage(tmp_path):
    manager = module.MemoryBudget(None, 100, 10, tmp_path)
    first = {"budget": 100, "docker_endpoint": "unix:///run/a.sock"}
    second = {**first, "docker_endpoint": "unix:///run/b.sock"}
    token = manager.join(first)
    (tmp_path / "usage.json").write_text('{"bytes": 50}')
    with pytest.raises(module.MemoryBudgetError):
        manager.join(second)
    manager.leave(token)
    token = manager.join(second)
    assert not (tmp_path / "usage.json").exists()
    manager.leave(token)


@pytest.mark.parametrize("endpoint", ["ssh://other-host", "tcp://127.0.0.1:2375"])
def test_budget_rejects_endpoints_without_local_container_accounting(monkeypatch, endpoint):
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **k: json.dumps(endpoint))
    with pytest.raises(module.MemoryBudgetError, match="Unix socket"):
        with module.memory_budget(BenchmarkConfig(memory_budget_gib=600)):
            pytest.fail("must reject before work")


def test_oom_result_keeps_response_and_is_excluded_from_score(monkeypatch, tmp_path):
    from evalclaw.execution import runner
    from evalclaw.types import (
        EvalDimension,
        EvalSpec,
        ItemResult,
        QcReport,
        TargetModelConfig,
        TaskSuite,
    )

    group = make_group(tmp_path / "group")
    manager = module.MemoryBudget(group, 600 * module.GIB, 16 * module.GIB, tmp_path / "state")
    monkeypatch.setattr(module, "_active", manager)
    dimension = EvalDimension(id="d", name="d", description="d", approach="d")
    spec = EvalSpec(objective="test", scale=1, dimensions=[dimension])
    suite = TaskSuite(
        objective="test",
        spec=spec,
        dimensions=[dimension],
        tasks=[
            dict(
                id="item",
                dimension_id="d",
                task_type="fill_blank",
                prompt="p",
                expected_texts=["a"],
            )
        ],
    )
    config = BenchmarkConfig(
        targets=[TargetModelConfig(id="t", model="test", provider="openai_compatible")],
        memory_budget_gib=600,
        memory_cgroup="/sys/fs/cgroup/evalclaw.slice",
        runner_max_workers=0,
    )

    def answer(item, config, target_id, **kwargs):
        (group / "memory.events.local").write_text("oom 1\noom_kill 1\n")
        return ItemResult(
            item_id=item.id, target_id=target_id, raw_response="preserved evidence", score=1
        )

    monkeypatch.setattr(runner, "_run_item", answer)
    result = runner.run_eval(
        suite, QcReport(passed_item_ids=["item"]), config, trace_dir=tmp_path / "run"
    )
    assert result.results[0].raw_response == "preserved evidence"
    assert result.results[0].execution["infrastructure_error"] is True
    assert result.summaries[0].errors == 1
    assert json.loads((tmp_path / "run/t/item/result.json").read_text())["error"]


def test_pipeline_fails_before_model_calls_outside_resource_group(monkeypatch, tmp_path):
    from evalclaw import pipeline

    monkeypatch.setattr(pipeline, "_run_pipeline", lambda *a, **k: pytest.fail("must not run"))
    monkeypatch.setattr(
        module, "_own_group", lambda: Path("/sys/fs/cgroup/user.slice/session.scope")
    )
    config = BenchmarkConfig(
        memory_budget_gib=600,
        memory_cgroup="/sys/fs/cgroup/evalclaw.slice",
        output_dir=str(tmp_path),
    )
    with pytest.raises(module.MemoryBudgetError):
        pipeline.run_pipeline("test", config, interactive=False)
    failure = json.loads(next(tmp_path.glob("debug/runs/*/failure.json")).read_text())
    assert failure["error_type"] == "MemoryBudgetError"
    assert module.SPEC_ENV not in os.environ


@pytest.mark.skipif(
    os.environ.get("EVALCLAW_DOCKER_TESTS") != "1",
    reason="requires local Docker images",
)
def test_real_selected_daemon_memory_build_and_network(monkeypatch, tmp_path):
    from evalclaw.execution.docker import resolve_docker_executable
    from evalclaw.execution.docker_images import build_docker_image_from_context
    from evalclaw.execution.memory_usage import container_usage

    # Diagnostic checks must not join the accounting of active experiments.
    original_init = module.MemoryBudget.__init__
    def init(self, group, budget, headroom, state, **kwargs):
        original_init(self, group, budget, headroom, tmp_path / "state", **kwargs)
    monkeypatch.setattr(module.MemoryBudget, "__init__", init)
    expected_id = subprocess.check_output(["docker", "info", "--format", "{{.ID}}"], text=True).strip()
    name = "evalclaw-memory-test-" + uuid.uuid4().hex[:12]
    tag = name + ":test"
    network = name + "-net"
    config = BenchmarkConfig(memory_budget_gib=600, memory_job_gib=1)
    with module.memory_budget(config, tmp_path):
        docker = resolve_docker_executable()
        spec = json.loads(Path(os.environ[module.SPEC_ENV]).read_text())
        # The runtime remains pinned even if a child's environment selects elsewhere.
        with monkeypatch.context() as child:
            child.setenv("DOCKER_CONTEXT", "default")
            child.setenv("DOCKER_HOST", "unix:///nonexistent.sock")
            def run(*args):
                return subprocess.check_output([docker, *args], text=True, timeout=120).strip()
            try:
                assert run("info", "--format", "{{.ID}}") == expected_id
                run("network", "create", "--internal", network)
                run("run", "-d", "--pull", "never", "--name", name, "--network", network,
                    "python:3.11-slim", "python", "-c",
                    "import time; from pathlib import Path; data=bytearray(32*1024**2); "
                    "Path('/tmp/ready').touch(); time.sleep(120)")
                run("exec", name, "python", "-c",
                    "import time; from pathlib import Path\n"
                    "for _ in range(100):\n"
                    " if Path('/tmp/ready').exists(): break\n"
                    " time.sleep(.1)\n"
                    "assert Path('/tmp/ready').exists()")
                usage, count = container_usage(spec["docker"], spec["endpoint"])
                assert count >= 1 and usage >= 32 * 1024**2
                context = tmp_path / "context"
                context.mkdir()
                (context / "Dockerfile").write_text(
                    "FROM python:3.11-slim\nRUN printf ready > /prepared\n")
                built = build_docker_image_from_context(context, tag=tag, timeout_s=120)
                assert built.built
                assert run("run", "--rm", "--pull", "never", "--network", "none",
                           tag, "cat", "/prepared") == "ready"
                inspected = json.loads(run("network", "inspect", network))[0]
                assert inspected["Internal"] is True
            finally:
                for args in [("rm", "-f", name), ("network", "rm", network), ("image", "rm", tag)]:
                    subprocess.run([docker, *args], capture_output=True, timeout=30)


@pytest.mark.skipif(
    not os.environ.get("EVALCLAW_MEMORY_TEST_CGROUP"),
    reason="requires administrator-provisioned system slice and framework launched inside it",
)
def test_real_shared_slice_contains_host_child_and_docker(tmp_path):
    from evalclaw.execution.docker import resolve_docker_executable

    group = Path(os.environ["EVALCLAW_MEMORY_TEST_CGROUP"]).resolve()
    budget = int((group / "memory.max").read_text()) // module.GIB
    config = BenchmarkConfig(
        memory_budget_gib=budget, memory_cgroup=str(group), memory_job_gib=1, memory_headroom_gib=1
    )
    name = "evalclaw-memory-test-" + uuid.uuid4().hex[:12]
    with module.memory_budget(config, tmp_path):
        own = subprocess.check_output(
            [
                sys.executable,
                "-c",
                'from pathlib import Path; print(Path("/proc/self/cgroup").read_text())',
            ],
            text=True,
        )
        assert str(group.relative_to("/sys/fs/cgroup")) in own
        docker = resolve_docker_executable()
        try:
            subprocess.run(
                [
                    docker,
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    "alpine:3.21.5",
                    "sleep",
                    "60",
                ],
                check=True,
                capture_output=True,
            )
            container = json.loads(subprocess.check_output([docker, "inspect", name]))[0]
            assert container["HostConfig"]["CgroupParent"] == group.name
            actual = Path(f"/proc/{container['State']['Pid']}/cgroup").read_text()
            cgroup = Path("/sys/fs/cgroup") / actual.split("0::", 1)[1].strip().lstrip("/")
            assert group in cgroup.parents
            module.check_memory_budget()
        finally:
            subprocess.run([docker, "rm", "-f", name], check=True, capture_output=True)
    assert (tmp_path / "memory-budget.json").is_file()
