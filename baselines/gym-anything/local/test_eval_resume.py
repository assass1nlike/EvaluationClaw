import json
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock

from local import evaluate_batch as batch
from local import eval_runtime


def test_adopted_worker_remains_running_and_keeps_exit_code(tmp_path):
    script = tmp_path / 'worker.py'
    script.write_text('import sys,json,time\nfrom pathlib import Path\nr=Path(sys.argv[1]);(r/"ready").touch()\nwhile not (r/"release").exists():time.sleep(.01)\n(r/"exit.json").write_text(json.dumps({"returncode":7}))\n')
    process = subprocess.Popen([sys.executable, str(script), str(tmp_path)])
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / 'ready').exists():
            assert time.monotonic() < deadline
            time.sleep(.01)
        adopted = batch.ExistingRun(process.pid, tmp_path)
        assert adopted.poll() is None
        (tmp_path / 'release').touch()
        process.wait(timeout=10)
        assert adopted.poll() == 7
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_resumed_queue_does_not_repeat_active_or_completed_tasks(tmp_path, monkeypatch):
    jobs = [dict(id=f'{i:03}', run=str(tmp_path / str(i)), env='env', task=str(i), source='/source') for i in range(3)]
    started = []
    class Process:
        pid = 123
        def __init__(self, command, **kwargs):
            started.append(command[command.index('--run')+1])
        def poll(self):
            return 0
    active = mock.Mock(pid=42)
    active.poll.side_effect = [None, 0]
    result = dict(infrastructure_errors=[])
    (tmp_path / 'jobs').mkdir()
    monkeypatch.setattr(batch.subprocess, 'Popen', Process)
    monkeypatch.setattr(batch, 'check_host', lambda: {})
    monkeypatch.setattr(batch, 'collect_result', lambda job, code: dict(result, task=job['task']))
    monkeypatch.setattr(batch.time, 'sleep', lambda _: None)
    assert batch.run_queue(tmp_path, jobs, 2, {'001':(active, jobs[1], None)}, [dict(result, task='0')], 2) == 0
    assert started == [jobs[2]['run']]
    state = json.loads((tmp_path / 'completion.json').read_text())
    assert state['finished'] == 3 and state['queued'] == 0


def test_transient_proxy_failure_is_retried_without_changing_resource_checks(tmp_path, monkeypatch):
    (tmp_path / 'READY').touch()
    (tmp_path / 'verification.json').write_text('{}')
    monkeypatch.setattr(eval_runtime, 'BASE_CACHE', tmp_path)
    original = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda self, *a, **kw: '1024' if str(self)=='/proc/sys/fs/inotify/max_user_instances' else original(self,*a,**kw))
    monkeypatch.setattr(eval_runtime.subprocess, 'check_output', lambda *a, **kw: '/data1/evaluationclaw/docker')
    with mock.patch.object(eval_runtime.urllib.request, 'build_opener') as opener, \
         mock.patch.object(eval_runtime.subprocess, 'run') as run, \
         mock.patch.object(eval_runtime.time, 'sleep') as sleep:
        response=mock.MagicMock()
        response.__enter__.return_value.status=401
        opener.return_value.open.side_effect=[OSError('transient TLS error'), response]
        assert eval_runtime.check_host()['registry_status']==401
        assert opener.return_value.open.call_count==2
        run.assert_called_once()
        sleep.assert_called_once_with(5)


def test_retry_waits_for_shared_capacity_and_original_task(tmp_path, monkeypatch):
    (tmp_path / 'jobs').mkdir()
    job = dict(id='007', run=str(tmp_path / '007'), source='/source', env='redmine', task='same')
    observations = iter([
        [dict(env='other', task='one'), dict(env='other', task='two')],
        [dict(env='redmine', task='same')],
        [], [],
    ])
    phases = []
    def active(_):
        value = next(observations)
        phases.append(value)
        return value
    class Process:
        pid = 123
        def __init__(self, *args, **kwargs):
            assert len(phases) == 3
        def poll(self):
            return 0
    monkeypatch.setattr(batch, 'alongside_active', active)
    monkeypatch.setattr(batch, 'check_host', lambda: {})
    monkeypatch.setattr(batch, 'collect_result', lambda j,c: dict(infrastructure_errors=[]))
    monkeypatch.setattr(batch.subprocess, 'Popen', Process)
    monkeypatch.setattr(batch.time, 'sleep', lambda _: None)
    assert batch.run_queue(tmp_path, [job], 2, {}, [], 0, '/original') == 0
    assert json.loads((tmp_path / 'completion.json').read_text())['finished'] == 1
