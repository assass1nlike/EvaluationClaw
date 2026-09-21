import pytest

from local import eval_ramp


@pytest.fixture
def monitor(tmp_path, monkeypatch):
    now = [1000.0]
    sample = dict(available_gib=900, memory_full_avg10=0, oom_kills=0,
                  swap_used_gib=0, load1=0, disk_free_gib=3000)
    monkeypatch.setattr(eval_ramp.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(eval_ramp, 'resources', lambda _: sample.copy())
    monkeypatch.setattr(eval_ramp, 'container_ooms', lambda: {})
    return eval_ramp.Ramp(48, 300, tmp_path), now, sample


def test_ramp_waits_at_each_level_and_caps_at_48(monitor):
    ramp, now, _ = monitor
    assert ramp.slots(0) == 8
    for expected in (16, 24, 32, 40, 48, 48):
        before = ramp.limit
        now[0] += 299
        assert ramp.slots(before) == before
        now[0] += 1
        assert ramp.slots(before) == expected


@pytest.mark.parametrize('field,value', [('available_gib', 127), ('memory_full_avg10', 1),
                                         ('disk_free_gib', 63)])
def test_pressure_blocks_new_tasks_and_requires_fresh_observation(monitor, field, value):
    ramp, now, sample = monitor
    old = sample[field]
    now[0] += 300
    sample[field] = value
    assert ramp.slots(8) == 0
    assert ramp.state['hold_reasons']
    sample[field] = old
    now[0] += 299
    assert ramp.slots(8) == 8
    now[0] += 1
    assert ramp.slots(8) == 16


def test_oom_prevents_automatic_resumption(monitor):
    ramp, now, sample = monitor
    sample['oom_kills'] = 1
    assert ramp.slots(8) == 0
    now[0] += 3600
    assert ramp.slots(0) == 0


def test_headroom_limits_new_admissions_without_killing_active_tasks(monitor):
    ramp, now, sample = monitor
    sample['available_gib'] = 147
    assert ramp.slots(4) == 5
    now[0] += 300
    assert ramp.slots(8) == 8
    assert ramp.limit == 8


def test_verified_foreign_container_oom_does_not_pause(monitor, monkeypatch):
    ramp, _, sample = monitor
    counters = {'docker-other.scope': {'oom': 28, 'kills': 12}}
    monkeypatch.setattr(eval_ramp, 'container_ooms', lambda: counters)
    monkeypatch.setattr(eval_ramp, 'foreign_container', lambda _: True)
    sample['oom_kills'] = 12
    assert ramp.slots(8) == 8
    assert ramp.ignored_oom == 12
    assert ramp.slots(8) == 8
    assert ramp.ignored_oom == 12
    counters.clear()  # Removal of an already attributed container must not lose evidence.
    assert ramp.slots(8) == 8
    sample['oom_kills'] += 1  # An unattributed kill must still stop admission.
    assert ramp.slots(8) == 0


def test_own_container_oom_still_pauses(monitor, monkeypatch):
    ramp, _, sample = monitor
    monkeypatch.setattr(eval_ramp, 'container_ooms', lambda: {'docker-ours.scope': {'oom': 1, 'kills': 1}})
    monkeypatch.setattr(eval_ramp, 'foreign_container', lambda _: False)
    sample['oom_kills'] = 1
    assert ramp.slots(8) == 0


def test_kill_without_local_limit_event_is_not_discounted(monitor, monkeypatch):
    ramp, _, sample = monitor
    monkeypatch.setattr(eval_ramp, 'container_ooms', lambda: {'docker-other.scope': {'oom': 0, 'kills': 1}})
    monkeypatch.setattr(eval_ramp, 'foreign_container', lambda _: True)
    sample['oom_kills'] = 1
    assert ramp.slots(8) == 0


@pytest.mark.parametrize('own_mount,limit,expected', [(True, 8, False), (False, 0, False), (False, 8, True)])
def test_foreign_oom_requires_limit_and_no_gym_mount(monkeypatch, own_mount, limit, expected):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    source = str(Path(eval_ramp.__file__).resolve().parents[1] / 'local/outputs/task') if own_mount else '/other-project'
    info = dict(memory=limit, mounts=[{'Type': 'bind', 'Source': source}])
    monkeypatch.setattr(eval_ramp.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(info)))
    assert eval_ramp.foreign_container('docker-example.scope') == expected
