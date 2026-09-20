import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from unittest import mock

import pytest

from local.eval_setup import prepare_environment, observe_initialization
from local import evaluate_batch as batch
from local.eval_runtime import NetworkPreflightError


def test_mount_copy_is_readable_without_mutating_source_or_executable_bits(tmp_path):
    source = tmp_path / 'source'
    (source / 'config').mkdir(parents=True, mode=0o700)
    (source / 'scripts').mkdir(mode=0o700)
    plain = source / 'config/settings.json'
    plain.write_text('{}'); plain.chmod(0o600)
    executable = source / 'scripts/start.sh'
    executable.write_text('echo ok'); executable.chmod(0o700)
    broken_script = source / 'scripts/generated.sh'
    broken_script.write_text('echo generated'); broken_script.chmod(0o600)
    (source / 'env.json').write_text(json.dumps({'mounts':[
        {'source':str(source/'config'),'target':'/workspace/config','mode':'ro'},
        {'source':str(source/'scripts'),'target':'/workspace/scripts','mode':'ro'}], 'recording':{}}))
    destination=tmp_path/'environment'
    spec, changed=prepare_environment(source,destination,tmp_path/'episodes')
    assert stat.S_IMODE(plain.stat().st_mode)==0o600
    assert stat.S_IMODE((source/'config').stat().st_mode)==0o700
    assert stat.S_IMODE((destination/'config/settings.json').stat().st_mode)==0o644
    assert stat.S_IMODE((destination/'scripts/start.sh').stat().st_mode)==0o755
    assert stat.S_IMODE((destination/'scripts/generated.sh').stat().st_mode)==0o644
    for path in source.rglob('*'):
        if path.is_file() and path.name!='env.json':
            assert path.read_bytes()==(destination/path.relative_to(source)).read_bytes()
    assert all(Path(m['source']).is_relative_to(destination) for m in spec['mounts'])
    assert changed


@pytest.mark.parametrize('failure',[False,True])
def test_initialization_observer_preserves_results_and_exceptions(tmp_path,failure):
    runner=mock.Mock()
    error=subprocess.TimeoutExpired(['setup'],1800)
    runner.exec.side_effect=error if failure else [0,126]
    class Env:
        _runner=runner
        def reset(self,seed):
            runner.exec('first',timeout=1800)
            runner.exec('second',timeout=1800)
            return {'screen':'unchanged'}
    env=Env(); original=env.reset
    with observe_initialization(env,tmp_path):
        if failure:
            with pytest.raises(subprocess.TimeoutExpired) as raised:env.reset(seed=42)
            assert raised.value is error
        else:assert env.reset(seed=42)=={'screen':'unchanged'}
    events=[json.loads(l) for l in (tmp_path/'initialization/commands.jsonl').read_text().splitlines()]
    assert len(events)==(1 if failure else 2)
    if failure:assert events[0]['timeout_seconds']==1800
    else:assert [e['returncode'] for e in events]==[0,126]
    assert env.reset==original
    assert runner.copy_from.call_count==3


def test_queue_automatically_recovers_without_repeating_tasks(tmp_path,monkeypatch):
    (tmp_path/'jobs').mkdir()
    jobs=[dict(id='001',run=str(tmp_path/'001'),source='/source',task='one',env='env')]
    started=[];clock=[1000]
    class Process:
        pid=123
        def __init__(self,command,**kwargs):started.append(command)
        def poll(self):return 0
    checks=mock.Mock(side_effect=[NetworkPreflightError('offline'),{}])
    monkeypatch.setattr(batch,'check_host',checks)
    monkeypatch.setattr(batch.subprocess,'Popen',Process)
    monkeypatch.setattr(batch,'collect_result',lambda j,c:dict(infrastructure_errors=[]))
    monkeypatch.setattr(batch.time,'time',lambda:clock[0])
    monkeypatch.setattr(batch.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    assert batch.run_queue(tmp_path,jobs,30,{},[],0)==0
    assert checks.call_count==2 and len(started)==1
    assert clock[0]>=1060
    assert (tmp_path/'network-recoveries.jsonl').exists()
    assert json.loads((tmp_path/'completion.json').read_text())['finished']==1


def test_non_network_preflight_failure_still_halts(tmp_path,monkeypatch):
    jobs=[dict(id='001',run=str(tmp_path/'001'),source='/source',task='one',env='env')]
    monkeypatch.setattr(batch,'check_host',mock.Mock(side_effect=RuntimeError('wrong daemon')))
    monkeypatch.setattr(batch.time,'sleep',lambda _:None)
    with mock.patch.object(batch.subprocess,'Popen') as launch:
        assert batch.run_queue(tmp_path,jobs,30,{},[],0)==2
        launch.assert_not_called()
    assert json.loads((tmp_path/'halted.json').read_text())['queued']==1


def test_missing_directory_mount_is_staged_without_creating_source(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    missing = source / 'utils'
    (source / 'env.json').write_text(json.dumps({'mounts':[
        {'source':str(missing),'target':'/workspace/utils','mode':'ro'}], 'recording':{}}))
    spec, _ = prepare_environment(source, tmp_path / 'environment', tmp_path / 'episodes')
    assert not missing.exists()
    assert Path(spec['mounts'][0]['source']).is_dir()
