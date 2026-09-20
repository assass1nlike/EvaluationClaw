import multiprocessing
import os
from pathlib import Path
import random
import socket
import subprocess
from unittest import mock

import pytest

from gym_anything.env import GymAnythingEnv
from gym_anything.runtime.runners.qemu_apptainer import QemuApptainerRunner
from gym_anything.runtime.runners.qemu_ports import PortLeases
from gym_anything.specs import EnvSpec, TaskSpec


def reserve_worker(directory, barrier, queue):
    os.environ['GYM_ANYTHING_QEMU_PORT_LOCK_DIR'] = directory
    random.seed(42)
    leases = PortLeases()
    try:
        ports = [leases.reserve(start) for start in (5900, 2222, 5555, 15555, 45500)]
        # All workers finish probing before any starts listening: reproduce the gap.
        barrier.wait(timeout=60)
        listeners = []
        try:
            for port in ports:
                sock = socket.socket()
                sock.bind(('0.0.0.0', port))
                sock.listen()
                listeners.append(sock)
            queue.put(ports)
            barrier.wait(timeout=60)
        finally:
            for sock in listeners:
                sock.close()
    finally:
        leases.close()


def test_same_seed_processes_reserve_distinct_ports(tmp_path):
    context = multiprocessing.get_context('spawn')
    barrier = context.Barrier(30)
    queue = context.Queue()
    workers = [context.Process(target=reserve_worker, args=(str(tmp_path), barrier, queue)) for _ in range(30)]
    try:
        for worker in workers:
            worker.start()
        ports = [port for _ in workers for port in queue.get(timeout=90)]
        for worker in workers:
            worker.join(timeout=30)
            assert worker.exitcode == 0
        assert len(set(ports)) == 150
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join()


def test_time_wait_and_lease_release(tmp_path, monkeypatch):
    monkeypatch.setenv('GYM_ANYTHING_QEMU_PORT_LOCK_DIR', str(tmp_path))
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    listener.listen()
    client = socket.create_connection(('127.0.0.1', port))
    server, _ = listener.accept()
    server.close()  # Active closer: leaves this server port in TIME_WAIT.
    assert client.recv(1) == b''
    client.close()
    listener.close()
    with socket.socket() as probe, pytest.raises(OSError):
        probe.bind(('0.0.0.0', port))
    leases = PortLeases()
    with mock.patch('random.randint', return_value=0):
        selected = leases.reserve(port)
        assert selected != port
        leases.close()
        assert leases.reserve(selected) == selected
    leases.close()


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv('GYM_ANYTHING_QEMU_PORT_LOCK_DIR', str(tmp_path / 'locks'))
    with mock.patch.object(QemuApptainerRunner, '_check_prerequisites'), mock.patch.object(QemuApptainerRunner, '_detect_acceleration', return_value=False):
        instance = QemuApptainerRunner(EnvSpec.from_dict({'id': 'isolation-test'}))
    yield instance
    instance.stop()


@pytest.mark.parametrize('boot', ['start', '_boot_vm_from_overlay', '_boot_vm_with_loadvm'])
def test_failed_boot_clears_all_endpoints(runner, tmp_path, boot):
    runner.base_qcow2 = tmp_path / 'base.qcow2'
    runner.base_qcow2.touch()
    runner._work_dir = tmp_path / 'work'
    runner._work_dir.mkdir()
    runner._instance_qcow2 = runner._work_dir / 'disk.qcow2'
    with mock.patch.object(runner, '_get_work_base', return_value=tmp_path), \
         mock.patch.object(runner, '_run_qemu_img', return_value=subprocess.CompletedProcess([], 0)), \
         mock.patch.object(runner, '_build_qemu_cmd', return_value=['/bin/false']), \
         mock.patch.object(runner, '_start_fast_io_display_listener'):
        with pytest.raises(RuntimeError):
            getattr(runner, boot)(seed=42)
    assert runner.ssh_port is runner.vnc_port is runner.adb_port is None
    assert runner._port_leases._files == []
    assert runner._process is None


@pytest.mark.parametrize('operation', ['exec', 'copy_to', 'copy_from', 'screenshot', 'ssh_wait'])
def test_dead_vm_cannot_contact_reused_endpoint(runner, tmp_path, operation):
    runner.ssh_port = 2222  # A stale endpoint now owned by another task.
    runner._process = mock.Mock()
    runner._process.poll.return_value = 1
    with mock.patch('subprocess.run') as remote, mock.patch('paramiko.SSHClient') as ssh, mock.patch('socket.socket') as sock:
        if operation == 'ssh_wait':
            assert not runner._wait_for_ssh(2222, timeout=1)
        else:
            with pytest.raises(RuntimeError, match='VM is not running'):
                if operation == 'exec':
                    runner.exec('touch /tmp/foreign')
                elif operation == 'copy_to':
                    runner.copy_to('file', '/tmp/foreign')
                elif operation == 'copy_from':
                    runner.copy_from('/tmp/foreign', str(tmp_path / 'out'))
                else:
                    runner.capture_screenshot(tmp_path / 'screen.png')
        remote.assert_not_called()
        ssh.assert_not_called()
        sock.assert_not_called()


def test_reset_failure_close_skips_remote_finalization(tmp_path):
    runner = mock.Mock()
    runner.start.side_effect = RuntimeError('VM boot failed')
    spec = EnvSpec.from_dict({'id': 'failed-init', 'recording': {'enable': False, 'output_dir': str(tmp_path)}})
    task = TaskSpec.from_dict({'id': 'task', 'hooks': {'post_task': 'touch /tmp/foreign'}})
    with mock.patch.object(GymAnythingEnv, '_select_runner', return_value=runner):
        env = GymAnythingEnv(spec, task)
    with mock.patch.object(env, '_complete_episode') as finalize:
        with pytest.raises(RuntimeError, match='VM boot failed'):
            env.reset(seed=42)
        runner.reset_mock()
        env.close()
        finalize.assert_not_called()
        runner.stop.assert_called_once()
        runner.exec.assert_not_called()
        runner.capture_screenshot.assert_not_called()


def test_launch_exception_releases_reservations(runner, tmp_path):
    runner._work_dir = tmp_path / 'boot'
    runner._work_dir.mkdir()
    runner._instance_qcow2 = runner._work_dir / 'disk.qcow2'
    runner._allocate_ports()
    with mock.patch.object(runner, '_build_qemu_cmd', return_value=['/nonexistent/qemu']), \
         mock.patch('subprocess.Popen', side_effect=OSError('launch failed')):
        with pytest.raises(OSError, match='launch failed'):
            runner._start_vm()
    assert runner.ssh_port is None
    assert runner._port_leases._files == []


def test_crashed_owner_releases_lease(tmp_path, monkeypatch):
    monkeypatch.setenv('GYM_ANYTHING_QEMU_PORT_LOCK_DIR', str(tmp_path))
    import sys
    proc = subprocess.Popen([sys.executable, '-u', '-c',
        'from gym_anything.runtime.runners.qemu_ports import PortLeases; '
        'import time; leases=PortLeases(); print(leases.reserve(26000)); time.sleep(60)'], stdout=subprocess.PIPE)
    try:
        port = int(proc.stdout.readline())
        proc.kill()
        proc.wait(timeout=10)
        leases = PortLeases()
        try:
            with mock.patch('random.randint', return_value=0):
                assert leases.reserve(port) == port
        finally:
            leases.close()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
