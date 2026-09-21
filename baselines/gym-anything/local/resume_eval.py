"""Replace a batch controller while preserving its independently running attempts."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from local.automatic_eval import collect_result, evaluate_one, publish, write_json
from local.eval_ramp import Ramp


def alive(process):
    try:
        fields = Path('/proc', str(process['pid']), 'stat').read_text().rsplit(')', 1)[1].split()
        return fields[0] != 'Z' and fields[19] == process['start_ticks']
    except FileNotFoundError:
        return False


def finish_existing(job, batch, process, prepared):
    run = batch / 'jobs' / job['id']
    settings = batch / 'model.json'
    if (run / 'result.json').exists():
        return evaluate_one(job, batch, settings, prepared)
    deadline = process['started_epoch'] + 86400 if process else 0
    while not (run / 'exit.json').exists() and process and alive(process) and time.time() < deadline:
        time.sleep(2)
    if (run / 'exit.json').exists():
        rc = json.loads((run / 'exit.json').read_text())['returncode']
    elif process and alive(process):
        runtime_name = 'ga-eval-' + hashlib.sha256(str(run).encode()).hexdigest()[:12]
        ids = subprocess.check_output(['docker', 'ps', '-q'], text=True, timeout=30).split()
        owned = []
        for cid in ids:
            info = json.loads(subprocess.check_output(['docker', 'inspect', '--format',
                '{"name":{{json .Name}},"mounts":{{json .Mounts}}}', cid], text=True, timeout=30))
            if info['name'].lstrip('/') == runtime_name or any(
                Path(m['Source']).is_relative_to(run) for m in info['mounts'] if m['Type'] == 'bind'):
                owned.append(cid)
        try:
            if owned:
                subprocess.run(['docker', 'rm', '-f', *owned], capture_output=True, timeout=120, check=True)
        finally:
            if alive(process):
                os.killpg(process['pgid'], signal.SIGTERM)
            until = time.monotonic() + 30
            while alive(process) and time.monotonic() < until:
                time.sleep(1)
            if alive(process):
                os.killpg(process['pgid'], signal.SIGKILL)
        write_json(run.with_suffix('.timeout.json'), {'timeout_seconds': 86400, 'containers': owned})
        rc = 124
    else:
        result = dict(job, verifier=None, returncode=None, outcome='infrastructure_failed',
                      detail='Original launcher exited without exit.json; attempt not restarted')
        write_json(run / 'result.json', result)
        return result
    write_json(run / 'result.json', collect_result(dict(job, run=str(run)), rc))
    return evaluate_one(job, batch, settings, prepared)


def resume(batch, handoff, ramp):
    config = json.loads((batch / 'config.json').read_text())
    by_id = {job['id']: job for job in config['jobs']}
    results = list(handoff['results'])
    finished_ids = {row['id'] for row in results}
    existing = handoff['active_processes']
    if finished_ids & existing.keys():
        raise RuntimeError('Attempt is both completed and active')
    pending = [job for job in config['jobs'] if job['id'] not in existing and job['id'] not in finished_ids]
    if any((batch / 'jobs' / job['id']).exists() for job in pending):
        raise RuntimeError('Unaccounted existing attempt; refusing to duplicate it')
    prepared = json.loads((batch / 'prepared.json').read_text())
    parallel = config['limits']['parallel']
    config.update(pid=os.getpid(), previous_controller_pid=handoff['controller_pid'], resumed=time.time())
    write_json(batch / 'config.json', config)
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        active = {pool.submit(finish_existing, by_id[i], batch, process, prepared[by_id[i]['env']]): by_id[i]
                  for i, process in existing.items()}
        while active or pending:
            for future in list(active):
                if future.done():
                    job = active.pop(future)
                    try:
                        results.append(future.result())
                    except Exception as error:
                        results.append(dict(id=job['id'], env=job['env'], task=job['task'], verifier=None,
                                            outcome='execution_failed', error=type(error).__name__))
            admission = ramp.slots(len(active))
            while pending and len(active) < admission:
                job = pending.pop(0)
                active[pool.submit(evaluate_one, job, batch, batch / 'model.json', prepared[job['env']])] = job
            publish(batch, results, len(by_id), 'evaluating', len(active),
                    active_ids=sorted(j['id'] for j in active.values()), ready_queued=len(pending),
                    preparing_software=[], alongside_active=0, reserved_preparation_slots=0,
                    combined_active=len(active), resource_monitor=ramp.state)
            if active:
                wait(active, timeout=5, return_when=FIRST_COMPLETED)
            elif pending:
                time.sleep(2)
    publish(batch, results, len(by_id), 'complete')


def main():
    from local.eval_docker import use_dedicated_docker
    use_dedicated_docker()
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--handoff', type=Path, required=True)
    args = parser.parse_args()
    batch = args.batch.resolve()
    handoff = json.loads(args.handoff.read_text())
    if alive(handoff['controller_process']):
        raise RuntimeError('Previous controller still exists; refusing dual scheduling')
    config = json.loads((batch / 'config.json').read_text())
    ramp = Ramp(config['limits']['parallel'], config['ramp_seconds'], batch)
    # Preserve the original baseline so only evidenced foreign OOMs are discounted.
    ramp.baseline_oom = handoff['oom_baseline']
    ramp.ignored_oom = handoff['verified_foreign_oom_kills']
    ramp.foreign_oom_evidence = handoff['foreign_oom_evidence']
    ramp.limit = handoff['progress']['resource_monitor']['limit']
    resume(batch, handoff, ramp)


if __name__ == '__main__':
    main()
