import json
import threading
from types import SimpleNamespace

from local import resume_eval


def test_handoff_keeps_active_slots_and_never_restarts_completed_tasks(tmp_path, monkeypatch):
    jobs = [dict(id=i, env='test', task=i) for i in ['001', '002', '003', '004', '005', '061']]
    (tmp_path/'jobs').mkdir()
    (tmp_path/'config.json').write_text(json.dumps({'jobs': jobs, 'limits': {'parallel': 3}}))
    (tmp_path/'prepared.json').write_text(json.dumps({'test': {'run': 'original-cache'}}))
    original = {'id': '061', 'env': 'test', 'task': '061', 'outcome': 'framework_failure_no_rerun', 'verifier': None}
    handoff = {'results': [original], 'active_processes': {'001': {}, '002': {}}, 'controller_pid': 123}
    new_started = threading.Event()
    observed, launched, progress = [], [], []

    def finish(job, *args):
        observed.append(job['id'])
        assert new_started.wait(3)
        return dict(job, outcome='scored', verifier={'score': 40, 'passed': False})

    def evaluate(job, *args):
        launched.append(job['id'])
        new_started.set()
        return dict(job, outcome='scored', verifier={'score': 20, 'passed': False})

    original_publish = resume_eval.publish
    def publish(*args, **kwargs):
        progress.append(kwargs)
        original_publish(*args, **kwargs)

    monkeypatch.setattr(resume_eval, 'finish_existing', finish)
    monkeypatch.setattr(resume_eval, 'evaluate_one', evaluate)
    monkeypatch.setattr(resume_eval, 'publish', publish)
    resume_eval.resume(tmp_path, handoff, SimpleNamespace(slots=lambda _: 3, state={}))
    assert sorted(observed) == ['001', '002']
    assert sorted(launched) == ['003', '004', '005']
    assert all(s.get('combined_active', 0) <= 3 for s in progress)
    rows = json.loads((tmp_path/'results.json').read_text())
    assert len(rows) == 6 and rows[-1] == original


def test_existing_exit_is_collected_without_launch_or_signal(tmp_path, monkeypatch):
    run = tmp_path/'jobs'/'001'
    run.mkdir(parents=True)
    (run/'exit.json').write_text('{"returncode": 0}')
    collected = []
    monkeypatch.setattr(resume_eval, 'collect_result', lambda job, rc: collected.append(rc) or {'returncode': rc})
    monkeypatch.setattr(resume_eval, 'evaluate_one', lambda *args: {'outcome': 'scored'})
    monkeypatch.setattr(resume_eval.os, 'killpg', lambda *_: (_ for _ in ()).throw(AssertionError('No signals allowed')))
    assert resume_eval.finish_existing({'id': '001'}, tmp_path, None, {}) == {'outcome': 'scored'}
    assert collected == [0]
