"""Live, no-model isolation check in separate evaluation worker containers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import random
import subprocess
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def wait_files(root, pattern, count, timeout=360):
    deadline = time.monotonic() + timeout
    while len(list(root.glob(pattern))) != count:
        if time.monotonic() > deadline:
            raise TimeoutError(pattern)
        time.sleep(0.2)


def worker(root, index):
    os.environ.update(GYM_ANYTHING_QEMU_CACHE=str(ROOT / 'local/runtime/qemu/evaluation-cache'),
                      GYM_ANYTHING_QEMU_WORK_DIR=str(ROOT / 'local/q/isolation-check'),
                      GYM_ANYTHING_QEMU_SSH_KEY=str(ROOT / 'local/runtime/qemu/ssh/key'))
    random.seed(42)
    from gym_anything.runtime.runners.qemu_native import QemuNativeRunner
    from gym_anything.specs import EnvSpec
    from PIL import Image
    spec = EnvSpec.from_dict({'id': f'isolation-{index}', 'resources': {'cpu': 2, 'mem_gb': 3, 'net': True},
                              'recording': {'enable': False}, 'vnc': {'password': 'password'}})
    runner = QemuNativeRunner(spec)
    bad = QemuNativeRunner(spec)
    def guest(command):
        result = runner._ssh_command(command, use_pty=False)
        assert result.returncode == 0, result.stderr
        return result.stdout.decode().strip()
    original_start = runner._start_vm
    def delayed_start(*args, **kwargs):
        (root / f'{index}.ports.json').write_text(json.dumps([runner.vnc_port, runner.ssh_port]))
        wait_files(root, '*.ports.json', 3)
        return original_start(*args, **kwargs)
    try:
        # All three have reserved ports before any QEMU process starts.
        with mock.patch.object(runner, '_start_vm', side_effect=delayed_start):
            runner.start(seed=42)
        guest(f'echo {index} > /tmp/isolation-sentinel')
        auth = guest('sudo /usr/sbin/sshd -T -C user=ga,host=localhost,addr=10.0.2.2')
        settings = dict(line.split(None, 1) for line in auth.splitlines())
        assert settings['passwordauthentication'] == 'no'
        assert settings['authenticationmethods'] == 'publickey'
        screenshot = root / f'{index}.png'
        assert runner.capture_screenshot(screenshot)
        with Image.open(screenshot) as img:
            img.load()
            assert img.width > 100
        # Real child process exits during boot; then recreate the old stale-port state.
        with mock.patch.object(bad, '_build_qemu_cmd', return_value=['/bin/false']):
            try:
                bad.start(seed=42)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Failed VM was accepted')
        assert bad.ssh_port is None
        bad.ssh_port = runner.ssh_port
        blocked = 0
        for operation in (lambda: bad.exec('echo contaminated > /tmp/isolation-sentinel'),
                          lambda: bad.copy_to(__file__, '/tmp/isolation-sentinel'),
                          lambda: bad.capture_screenshot(root / f'{index}.foreign.png')):
            try:
                operation()
            except RuntimeError:
                blocked += 1
        assert blocked == 3
        bad.stop()
        assert guest('cat /tmp/isolation-sentinel') == str(index)
        (root / f'{index}.checked').touch()
        wait_files(root, '*.checked', 3)
        # Exercise disk-checkpoint boot while two independent VMs remain alive.
        if index == 0:
            runner.stop()
            runner._start_from_image(runner.base_qcow2, seed=42)
            assert guest('test ! -e /tmp/isolation-sentinel; echo $?') == '0'
            guest('echo 0 > /tmp/isolation-sentinel')
            (root / 'restarted').touch()
        else:
            wait_files(root, 'restarted', 1)
        assert guest('cat /tmp/isolation-sentinel') == str(index)
        (root / f'{index}.result.json').write_text(json.dumps(dict(index=index, sentinel_intact=True,
            blocked_stale_operations=blocked, ssh_authentication=settings['authenticationmethods'], screenshot=True)))
    finally:
        bad.stop()
        runner.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', type=int)
    args = parser.parse_args()
    root = args.output.resolve()
    if args.worker is not None:
        worker(root, args.worker)
        return
    from local.eval_docker import use_dedicated_docker
    from local.seed_batch import runtime_command
    from local.eval_runtime import check_host
    use_dedicated_docker()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'preflight.json').write_text(json.dumps(check_host(), indent=2))
    def launch(index):
        job = root / str(index)
        (job / 'workspace').mkdir(parents=True)
        (job / 'config.json').write_text(json.dumps({'env': f'isolation-{index}', 'runner': 'qemu'}))
        environ = dict(os.environ, PYTHONPATH=f'{ROOT}/src:{ROOT}', PYTHONHASHSEED='42',
                       PATH=f'{ROOT}/local/runtime/qemu/bin:{ROOT}/.venv/bin:/usr/local/bin:/usr/bin:/bin')
        cmd = runtime_command(job, [str(ROOT / '.venv/bin/python'), '-u', __file__, '--output', str(root), '--worker', str(index)], environ)
        position = cmd.index('type=bind,src=/tmp,dst=/tmp')
        del cmd[position-1:position+1]
        with (job / 'run.log').open('w') as log:
            result = subprocess.run(cmd, env=environ, stdout=log, stderr=subprocess.STDOUT)
        return result.returncode
    with ThreadPoolExecutor(max_workers=3) as pool:
        codes = list(pool.map(launch, range(3)))
    assert codes == [0, 0, 0], codes
    ports = [port for path in root.glob('*.ports.json') for port in json.loads(path.read_text())]
    assert len(set(ports)) == 6
    results = [json.loads(path.read_text()) for path in sorted(root.glob('*.result.json'))]
    (root / 'verification.json').write_text(json.dumps(dict(seed=42, workers=3, ports=ports,
        checkpoint_restart=True, results=results), indent=2))
    print('Three independent VM workers, failed-start protection and checkpoint restart passed.')


if __name__ == '__main__':
    main()
