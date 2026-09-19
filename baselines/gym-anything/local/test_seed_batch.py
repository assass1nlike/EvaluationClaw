"""Exercise upstream continuation and process cleanup with real subprocesses."""
import json
from pathlib import Path
import sys

import pytest

from extras.research.task_generation.propose_and_amplify.pipeline import propose_cc
from local.seed_batch import record_claude


def test_docker_runtime_uses_host_network_kvm_and_existing_daemon(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from local import seed_batch
    job = tmp_path / 'software'
    job.mkdir()
    (job / 'config.json').write_text('{"env":"test_env"}')
    monkeypatch.setattr(seed_batch.os, 'stat', lambda p: SimpleNamespace(st_gid=109))
    env = {'PATH': '/tools/bin', 'https_proxy': 'http://127.0.0.1:17891',
           'OPENAI_API_KEY': 'unrelated-secret'}
    command = seed_batch.runtime_command(job, ['/tools/python', 'build.py'], env)
    assert command[command.index('--network')+1] == 'host'
    assert command[command.index('--device')+1] == '/dev/kvm'
    mounts = [command[i+1] for i, arg in enumerate(command) if arg == '--mount']
    assert 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock' in mounts
    assert 'type=bind,src=/tmp,dst=/tmp' in mounts
    passed = [command[i+1] for i, arg in enumerate(command) if arg == '--env']
    assert passed == ['PATH', 'https_proxy']
    assert command[-3:] == [seed_batch.RUNTIME_IMAGE, '/tools/python', 'build.py']


def test_host_launch_uses_default_network_and_retains_model_configuration(tmp_path, monkeypatch):
    from local import seed_batch
    job = tmp_path / 'batch' / 'vscode_env'
    job.mkdir(parents=True)
    (job / 'workspace').mkdir()
    (job / 'config.json').write_text('{"env":"vscode_env","runner":"docker"}')
    monkeypatch.setenv('GYM_ANYTHING_DOCKER_NETWORK', 'old-private-network')
    seen = {}

    class Process:
        pid = 123
        def __init__(self, command, **kwargs):
            seen.update(command=command, **kwargs)
        def wait(self):
            return 0

    monkeypatch.setattr(seed_batch.subprocess, 'Popen', Process)
    assert seed_batch.launch(job)['returncode'] == 0
    assert 'GYM_ANYTHING_DOCKER_NETWORK' not in seen['env']
    assert seen['env']['CLAUDE_CODE_EFFORT_LEVEL'] == 'high'
    assert seen['env']['CLAUDE_CODE_SUBAGENT_MODEL'] == 'deepseek-flash'
    assert seen['env']['CLAUDE_CONFIG_DIR'] == str(job / 'claude-config')
    assert seen['env']['GYM_ANYTHING_QEMU_CACHE'] == str(job / 'qemu_cache')
    assert seen['env']['GYM_ANYTHING_QEMU_SSH_KEY'] == str(seed_batch.ROOT / 'local/runtime/qemu/ssh/key')


@pytest.mark.parametrize('exit_code,is_error,timeout', [
    (0, False, False), (7, False, False), (0, True, False), (0, False, True),
])
def test_recording_preserves_upstream_exit_and_cleanup(tmp_path, exit_code, is_error, timeout):
    child_pid = tmp_path / 'child.pid'
    script = tmp_path / 'cli.py'
    script.write_text(
        'import json, subprocess, sys, time\n'
        'from pathlib import Path\n'
        'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
        f'Path({str(child_pid)!r}).write_text(str(p.pid))\n'
        f'print(json.dumps({{"type": "result", "is_error": {is_error!r}}}), flush=True)\n'
        + ('time.sleep(60)\n' if timeout else f'sys.exit({exit_code})\n')
    )
    record_claude(propose_cc.run_claude, Path(sys.executable), [str(script)],
                 cwd=tmp_path, timeout=0.3 if timeout else 5, job=tmp_path, phase=1)
    status = json.loads((tmp_path / 'phase_1.result.json').read_text())
    assert status.get('timeout', False) is timeout
    assert status['result']['is_error'] is is_error
    assert status['returncode'] == (-15 if timeout else exit_code)
    state = Path('/proc') / child_pid.read_text() / 'stat'
    assert not state.exists() or state.read_text().split()[2] == 'Z'
