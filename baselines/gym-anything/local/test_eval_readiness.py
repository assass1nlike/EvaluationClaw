import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from local.eval_readiness import observe_prepared_initialization, source_digest
from local.automatic_eval import classify, publish


def environment(rc=0):
    runner = Mock()
    runner.exec.return_value = rc
    runner.checkpoint_exists.return_value = True
    env = SimpleNamespace(_runner=runner, _reset_complete=False,
                          env_spec=SimpleNamespace(id='vscode_env@0.1', hooks={'post_start': '/start.sh'}),
                          task_spec=SimpleNamespace(hooks=SimpleNamespace(pre_task='/seed.sh')))
    def reset(**kwargs):
        # The official reset ignores return codes and catches hook exceptions.
        for command in ['bash -lc /start.sh > /home/ga/env_setup_post_start.log 2>&1',
                        'bash -lc /seed.sh > /home/ga/task_pre_task.log 2>&1']:
            try:
                runner.exec(command, timeout=20)
            except Exception:
                pass
        env._reset_complete = True
        return {'screen': 'original'}
    env.reset = reset
    return env


def test_hook_failure_keeps_official_continuation_and_score(tmp_path):
    env = environment(126)
    agent = Mock()
    with observe_prepared_initialization(env, tmp_path):
        env.reset(seed=42)
        agent()
    agent.assert_called_once()
    assert env._runner.exec.call_count == 2
    assert env._reset_complete
    result = json.loads((tmp_path/'readiness.json').read_text())
    assert len(result['initialization_issues']) == 2
    assert classify({'returncode': 0, 'cli': {'terminal_reason': 'completed'},
                     'verifier': {'score': 75, 'passed': False}}, result) == 'scored'


def test_success_preserves_observation_and_original_hook_order(tmp_path):
    env = environment()
    original = env.reset
    with observe_prepared_initialization(env, tmp_path):
        assert env.reset(seed=42) == {'screen': 'original'}
    assert env.reset == original
    commands = [c.args[0] for c in env._runner.exec.call_args_list]
    assert commands[0] == 'bash -lc /start.sh > /home/ga/env_setup_post_start.log 2>&1'
    assert commands[-1] == 'bash -lc /seed.sh > /home/ga/task_pre_task.log 2>&1'
    assert json.loads((tmp_path/'readiness.json').read_text())['status'] == 'ready'


def test_software_check_failure_is_recorded_without_blocking_official_reset(tmp_path):
    env = environment()
    env._runner.exec.side_effect = [0, 1, 0]
    with observe_prepared_initialization(env, tmp_path):
        env.reset()
    assert env._runner.exec.call_count == 3
    assert env._reset_complete
    result = json.loads((tmp_path/'readiness.json').read_text())
    assert result['initialization_issues'][0]['software_check_returncode'] == 1


def test_original_hook_exception_is_left_to_official_reset(tmp_path):
    env = environment()
    env._runner.exec.side_effect = [TimeoutError('original timeout'), 0]
    with observe_prepared_initialization(env, tmp_path):
        assert env.reset() == {'screen': 'original'}
    result = json.loads((tmp_path/'readiness.json').read_text())
    assert result['status'] == 'ready'
    assert result['initialization_issues'][0]['error'] == 'TimeoutError'


def test_unsuppressed_official_reset_exception_keeps_its_type(tmp_path):
    env = environment()
    original_error = ValueError('reset failed')
    env.reset = Mock(side_effect=original_error)
    with observe_prepared_initialization(env, tmp_path), pytest.raises(ValueError) as caught:
        env.reset()
    assert caught.value is original_error
    assert json.loads((tmp_path/'readiness.json').read_text())['status'] == 'failed'


def test_failed_frontend_reload_cannot_pass_readiness(tmp_path, monkeypatch):
    env = environment()
    env.env_spec.id = 'erpnext_env@0.1'
    monkeypatch.setattr('local.eval_readiness.configure_container_proxy', lambda _: None)
    env._runner.exec.side_effect = [0, 1]
    with observe_prepared_initialization(env, tmp_path), pytest.raises(RuntimeError):
        env.reset()
    assert not env._reset_complete
    assert env._runner.exec.call_count == 2
    result = json.loads((tmp_path/'readiness.json').read_text())
    assert result['events'][0]['frontend_reload_returncode'] == 1


def test_source_digest_invalidates_changed_install_content_and_execute_mode(tmp_path):
    (tmp_path/'scripts').mkdir()
    p = tmp_path/'scripts/start.sh'
    p.write_text('echo original')
    original = source_digest(tmp_path)
    p.write_text('echo changed')
    assert source_digest(tmp_path) != original
    original = source_digest(tmp_path)
    p.chmod(0o755)
    assert source_digest(tmp_path) != original


def test_invalid_initialization_cannot_publish_a_model_score(tmp_path):
    result = {'returncode': 0, 'verifier': {'score': 100, 'passed': True}}
    result['outcome'] = classify(result, {'status': 'failed', 'stage': 'pre_task'})
    publish(tmp_path, [dict(result, id='001', env='e', task='t', run='/r')], 1, 'complete')
    import csv
    with (tmp_path/'results.csv').open() as f:row = next(csv.DictReader(f))
    assert row['outcome'] == 'task_initialization_failed'
    assert row['score'] == '' and row['passed'] == ''


def test_low_official_score_is_published_without_manual_review(tmp_path):
    result = {'returncode': 0, 'verifier': {'score': 4, 'passed': False},
              'cli': {'terminal_reason': 'completed'}}
    assert classify(result, {'status': 'ready'}) == 'scored'


def test_configured_answer_time_limit_keeps_official_score():
    result = {'returncode': 0, 'verifier': {'score': 4, 'passed': False},
              'cli': None, 'answer_time_limit_reached': True}
    assert classify(result, {'status': 'ready'}) == 'scored'
    assert classify(result, {'status': 'failed'}) != 'scored'


def test_worker_deadline_cleans_only_its_own_containers(tmp_path, monkeypatch):
    import subprocess
    from local import automatic_eval as automatic
    run = tmp_path / 'attempt'
    process = Mock(pid=12345)
    process.wait.side_effect = [subprocess.TimeoutExpired('worker', 86400), 0]
    process.poll.return_value = None
    monkeypatch.setattr(automatic.subprocess, 'Popen', Mock(return_value=process))
    inspect = Mock(side_effect=['ours\nother\n',
        json.dumps({'name': '/desktop', 'mounts': [{'Type': 'bind', 'Source': str(run / 'environment')}]}),
        json.dumps({'name': '/other', 'mounts': [{'Type': 'bind', 'Source': str(tmp_path / 'unrelated')}]}),
    ])
    monkeypatch.setattr(automatic.subprocess, 'check_output', inspect)
    remove = Mock()
    monkeypatch.setattr(automatic.subprocess, 'run', remove)
    monkeypatch.setattr(automatic.os, 'killpg', Mock())
    assert automatic.invoke({'source': '/source', 'task': 'task'}, run, []) == 124
    assert remove.call_args.args[0] == ['docker', 'rm', '-f', 'ours']
    assert json.loads(run.with_suffix('.timeout.json').read_text())['timeout_seconds'] == 86400


def test_ready_software_starts_without_waiting_for_slow_install(tmp_path, monkeypatch):
    import threading
    from local import automatic_eval as automatic
    model_started = threading.Event()
    slow_ready = threading.Event()
    jobs = [dict(id='001', env='fast', task='one'), dict(id='002', env='slow', task='two'),
            dict(id='061', env='fast', task='forbidden')]
    ledger = {'tasks': {j['id']: {'rerun_allowed': j['id'] != '061'} for j in jobs}}
    def prepare(job, directory):
        if job['env'] == 'slow':
            assert model_started.wait(3), 'Ready environment was blocked by another installation'
            slow_ready.set()
        return {'status': 'ready', 'run': str(directory)}
    calls = []
    def evaluate(job, *args):
        calls.append(job['id'])
        if job['env'] == 'fast':
            model_started.set()
        else:
            assert slow_ready.is_set()
        return dict(job, outcome='scored', verifier={'score': 4, 'passed': False})
    monkeypatch.setattr(automatic, 'prepare_one', prepare)
    monkeypatch.setattr(automatic, 'evaluate_one', evaluate)
    monkeypatch.setattr(automatic, 'alongside_active', lambda _: 1)
    states = []
    real_publish = automatic.publish
    def publish(*args, **kwargs):
        states.append(kwargs)
        return real_publish(*args, **kwargs)
    monkeypatch.setattr(automatic, 'publish', publish)
    assert automatic.run_schedule(jobs, tmp_path, tmp_path/'model.json', tmp_path, 3, ledger) == 0
    assert sorted(calls) == ['001', '002']
    assert all(s.get('combined_active', 0) <= 3 for s in states)
    outcomes = {r['id']: r['outcome'] for r in json.loads((tmp_path/'results.json').read_text())}
    assert outcomes == {'001': 'scored', '002': 'scored', '061': 'framework_failure_no_rerun'}


def test_shared_limit_does_not_trust_stale_active_counter(tmp_path):
    from local.automatic_eval import alongside_active
    (tmp_path/'config.json').write_text(json.dumps({'limits': {'parallel': 3}}))
    (tmp_path/'progress.json').write_text(json.dumps({'total': 3, 'finished': 0, 'active': 0}))
    assert alongside_active([tmp_path]) == 3
    (tmp_path/'progress.json').write_text(json.dumps({'total': 3, 'finished': 2, 'active': 1}))
    assert alongside_active([tmp_path]) == 1
    (tmp_path/'progress.json').write_text(json.dumps({'total': 3, 'finished': 3, 'active': 0}))
    assert alongside_active([tmp_path]) == 0


def test_small_retry_batch_keeps_shared_machine_capacity(tmp_path, monkeypatch):
    from local import automatic_eval as automatic
    source = tmp_path / 'software'
    source.mkdir()
    (source / 'env.json').write_text(json.dumps({'resources': {'cpu': 4, 'mem_gb': 8}}))
    jobs = [{'source': str(source)} for _ in range(27)]
    monkeypatch.setattr(automatic.os, 'sched_getaffinity', lambda _: set(range(192)))
    original_read = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda path, *a, **kw:
                        'MemAvailable: 1048576000 kB\n' if str(path) == '/proc/meminfo'
                        else original_read(path, *a, **kw))
    assert automatic.capacity(jobs)['parallel'] == 27
    assert automatic.capacity(jobs, shared=True)['parallel'] == 48
    monkeypatch.setattr(automatic.os, 'sched_getaffinity', lambda _: set(range(32)))
    assert automatic.capacity(jobs, shared=True)['parallel'] == 8
