"""Prepare software, run bounded isolated evaluations, and publish final outcomes."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from local.evaluate_batch import collect_result, write_json
from local.eval_runtime import check_host

ROOT = Path(__file__).resolve().parents[1]


def capacity(jobs, *, shared=False):
    resources = [json.loads((Path(j['source']) / 'env.json').read_text())['resources'] for j in jobs]
    cpu = len(os.sched_getaffinity(0))
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))) / 1024**2
    per_cpu = max(r['cpu'] for r in resources)
    per_mem = max(r['mem_gb'] for r in resources) + 2  # CLI and runner overhead
    limit = max(1, min(int(cpu / per_cpu), int((available - 32) / per_mem)))
    if not shared:
        limit = min(len(jobs), limit)
    return dict(parallel=limit, initialization_parallel=limit, host_cpus=cpu, available_mem_gib=available,
                cpu_per_job=per_cpu, memory_per_job_gib=per_mem, memory_reserve_gib=32)


def invoke(job, run, extra):
    command = [str(ROOT / '.venv/bin/python'), '-u', str(ROOT / 'local/evaluate.py'),
               '--source', job['source'], '--task', job['task'], '--run', str(run), *extra]
    with run.with_suffix('.log').open('w') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        timeout = 39600 if '--prepare-only' in extra else 86400
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Only this attempt's mount copies and runtime container are owned here.
            ids = subprocess.check_output(['docker', 'ps', '-q'], text=True, timeout=30).split()
            own = []
            runtime_name = 'ga-eval-' + hashlib.sha256(str(run).encode()).hexdigest()[:12]
            for cid in ids:
                info = json.loads(subprocess.check_output(['docker', 'inspect', '--format',
                    '{"name":{{json .Name}},"mounts":{{json .Mounts}}}', cid], text=True, timeout=30))
                if info['name'].lstrip('/') == runtime_name or any(
                    Path(m['Source']).is_relative_to(run) for m in info['mounts'] if m['Type'] == 'bind'):
                    own.append(cid)
            try:
                if own:
                    subprocess.run(['docker', 'rm', '-f', *own], capture_output=True, timeout=120, check=True)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
            write_json(run.with_suffix('.timeout.json'), {'timeout_seconds': timeout, 'containers': own})
            return 124


def prepare_one(job, directory):
    directory.mkdir(exist_ok=True)
    for attempt in range(4):
        run = directory / f'attempt{attempt}'
        manifest = run / 'software.json'
        if manifest.exists():
            result = json.loads(manifest.read_text())
        elif run.exists():
            result = {'status': 'failed', 'detail': 'Interrupted preparation attempt'}
        else:
            rc = invoke(job, run, ['--prepare-only'])
            result = json.loads(manifest.read_text()) if manifest.exists() else {'status': 'failed', 'returncode': rc}
        if result['status'] == 'ready':
            from local.eval_readiness import source_digest
            if result['source_sha256'] != source_digest(job['source']):
                raise RuntimeError('Prepared software source changed')
            return {'status': 'ready', 'run': str(run), 'attempt': attempt}
    return {'status': 'failed', 'run': str(run), 'attempt': 3, 'detail': result}


def classify(result, readiness):
    if readiness.get('status') == 'failed':
        return 'task_initialization_failed' if readiness.get('stage') == 'pre_task' else 'environment_initialization_failed'
    if result.get('infrastructure_errors'):
        return 'infrastructure_failed'
    cli = result.get('cli') or {}
    if cli.get('terminal_reason') == 'api_error':
        return 'api_failed'
    if cli.get('is_error') or cli.get('returncode') not in (None, 0):
        return 'execution_failed'
    if result.get('returncode') != 0:
        return 'execution_failed'
    if readiness.get('status') != 'ready' or not (cli.get('terminal_reason') == 'completed' or result.get('answer_time_limit_reached')):
        return 'execution_failed'
    if result.get('verifier') is None:
        return 'scoring_failed'
    return 'scored'


def evaluate_one(job, batch, settings, prepared):
    run = batch / 'jobs' / job['id']
    if (run / 'result.json').exists():
        result = json.loads((run / 'result.json').read_text())
    elif run.exists():
        result = {'returncode': None, 'verifier': None, 'outcome': 'interrupted', 'detail': 'Existing incomplete attempt; not repeated automatically'}
    else:
        rc = invoke(job, run, ['--settings', str(settings), '--prepared', prepared['run']])
        if run.exists():
            result = collect_result(dict(job, run=str(run)), rc)
        else:
            result = {'returncode': rc, 'verifier': None, 'outcome': 'infrastructure_failed',
                      'detail': 'Launcher preflight failed before environment creation'}
    ready_path = run / 'readiness.json'
    readiness = json.loads(ready_path.read_text()) if ready_path.exists() else {}
    events = [json.loads(line) for path in run.glob('episodes/*/cli_harness/sandbox-events.jsonl')
              for line in path.read_text().splitlines()]
    limit = json.loads(settings.read_text())['cli_timeout_sec']
    result['answer_time_limit_reached'] = any(e.get('stage') == 'exec' and e.get('error') == 'TimeoutExpired'
                                            and e.get('timeout_seconds') == limit for e in events)
    result.update(id=job['id'], env=job['env'], task=job['task'], run=str(run))
    result['outcome'] = result.get('outcome') or classify(result, readiness)
    result['readiness'] = readiness
    if 'initialization_issues' in readiness:
        result['initialization_issues'] = readiness['initialization_issues']
    if run.exists():
        write_json(run / 'result.json', result)
    return result


def publish(batch, results, total, phase, active=0, **state):
    results = sorted(results, key=lambda row: row['id'])
    write_json(batch / 'results.json', results)
    counts = {}
    for row in results:
        counts[row['outcome']] = counts.get(row['outcome'], 0) + 1
    write_json(batch / 'progress.json', dict(time=time.time(), phase=phase, total=total,
                                           finished=len(results), active=active, outcomes=counts, **state))
    temporary = batch / 'results.csv.tmp'
    with temporary.open('w') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'env', 'task', 'outcome', 'score', 'passed', 'run'])
        writer.writeheader()
        for row in results:
            verifier = row.get('verifier') or {}
            writer.writerow({**{k: row.get(k) for k in ['id', 'env', 'task', 'outcome', 'run']},
                             'score': verifier.get('score') if row['outcome'] == 'scored' else None,
                             'passed': verifier.get('passed') if row['outcome'] == 'scored' else None})
    temporary.replace(batch / 'results.csv')


def alongside_active(batches):
    count = 0
    for batch in batches:
        progress = json.loads((batch / 'progress.json').read_text())
        config = json.loads((batch / 'config.json').read_text())
        limit = config.get('limits', {}).get('parallel', config.get('parallel', 1))
        count += min(limit, max(0, progress['total'] - progress['finished']))
    return count


def run_schedule(jobs, batch, settings, prepare_root, parallel, ledger, *, alongside=(), prepare_only=False, ramp_seconds=0):
    from local.eval_ramp import Ramp
    ramp = Ramp(parallel, ramp_seconds, batch) if ramp_seconds else None
    if alongside and ramp is None:
        ramp = Ramp(parallel, 0, batch)
        ramp.limit = parallel  # Existing batch has already completed the ramp.
    sources = {job['env']: job for job in jobs}
    prepared, pending_jobs, active = {}, [], {}
    results = [dict(id=j['id'], env=j['env'], task=j['task'], verifier=None,
                    outcome='framework_failure_no_rerun', evidence=ledger['tasks'][j['id']].get('evidence'))
               for j in jobs if ledger['tasks'][j['id']].get('rerun_allowed') is False]
    allowed = [j for j in jobs if ledger['tasks'][j['id']].get('rerun_allowed') is not False]
    if prepare_only:
        results = []
    with ThreadPoolExecutor(max_workers=min(4, parallel)) as installers, ThreadPoolExecutor(max_workers=parallel) as workers:
        preparing = {installers.submit(prepare_one, j, prepare_root / env): env for env, j in sources.items()}
        while preparing or active or pending_jobs:
            for future in list(preparing):
                if not future.done():
                    continue
                env = preparing.pop(future)
                try:
                    prepared[env] = future.result()
                except Exception as error:
                    prepared[env] = {'status': 'failed', 'error': type(error).__name__}
                write_json(batch / 'prepared.json', prepared)
                if not prepare_only:
                    group = [j for j in allowed if j['env'] == env]
                    if prepared[env]['status'] == 'ready':
                        pending_jobs.extend(group)
                    else:
                        results.extend(dict(id=j['id'], env=env, task=j['task'], verifier=None,
                                            outcome='software_preparation_failed', evidence=prepared[env]) for j in group)
            for future in list(active):
                if not future.done():
                    continue
                job = active.pop(future)
                try:
                    results.append(future.result())
                except Exception as error:
                    results.append(dict(id=job['id'], env=job['env'], task=job['task'], verifier=None,
                                        outcome='execution_failed', error=type(error).__name__))
            external = alongside_active(alongside)
            # Reserve slots for all unfinished preparation work, including queued installers.
            prep_slots = min(4, parallel, len(preparing))
            admission = ramp.slots(len(active) + prep_slots + external) if ramp else parallel
            if ramp:
                pending_jobs.sort(key=lambda job: job['id'])
            while pending_jobs and len(active) + prep_slots + external < admission:
                job = pending_jobs.pop(0)
                active[workers.submit(evaluate_one, job, batch, settings, prepared[job['env']])] = job
            phase = 'preparing_and_evaluating' if preparing and active else 'preparing' if preparing else 'evaluating'
            publish(batch, results, len(jobs), phase, len(active), active_ids=sorted(j['id'] for j in active.values()),
                    ready_queued=len(pending_jobs), preparing_software=sorted(preparing.values()),
                    alongside_active=external, reserved_preparation_slots=prep_slots,
                    combined_active=len(active) + prep_slots + external,
                    resource_monitor=ramp.state if ramp else None)
            futures = [*preparing, *active]
            if futures:
                wait(futures, timeout=5, return_when=FIRST_COMPLETED)
            elif pending_jobs:
                time.sleep(2)
    success = all(p['status'] == 'ready' for p in prepared.values())
    phase = ('prepared' if success else 'preparation_failed') if prepare_only else 'complete'
    publish(batch, results, len(jobs), phase)
    return 0 if not prepare_only or success else 1


def main():
    os.umask(0o077)
    from local.eval_docker import use_dedicated_docker, setup_proxy
    use_dedicated_docker()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', required=True, type=Path)
    parser.add_argument('--settings', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--prepare-root', required=True, type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--parallel', type=int, help='Maximum total concurrent initializations and evaluations')
    parser.add_argument('--ramp-seconds', type=int, default=0, help='Healthy observation period before adding eight slots')
    parser.add_argument('--alongside', action='append', default=[], type=Path, help='Share the resource limit with an existing batch')
    args = parser.parse_args()
    if (args.parallel is not None and args.parallel < 1) or args.ramp_seconds < 0:
        parser.error('parallel must be positive and ramp-seconds nonnegative')
    batch = args.batch.resolve()
    batch.mkdir(parents=True, exist_ok=False)
    (batch / 'jobs').mkdir()
    jobs = json.loads(args.manifest.read_text())['jobs']
    ledger = json.loads((ROOT / 'local/evaluation_results.json').read_text())
    for job in jobs:
        for name, expected in job['hashes'].items():
            if hashlib.sha256((Path(job['source']) / 'tasks' / job['task'] / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f'Task changed: {job["id"]}/{name}')
    try:
        setup_proxy()
        write_json(batch / 'preflight.json', check_host())
    except Exception as error:
        write_json(batch / 'preflight.json', {'status': 'failed', 'error': type(error).__name__, 'detail': str(error)})
        publish(batch, [dict(id=j['id'], env=j['env'], task=j['task'], verifier=None,
                            outcome='framework_failure_no_rerun' if ledger['tasks'][j['id']].get('rerun_allowed') is False
                            else 'batch_preflight_failed') for j in jobs], len(jobs), 'preflight_failed')
        return 1
    limits = capacity(jobs, shared=bool(args.alongside))
    if args.parallel:
        limits['parallel'] = min(args.parallel, limits['parallel'])
        limits['initialization_parallel'] = limits['parallel']
    settings = batch / 'model.json'
    shutil.copy2(args.settings, settings)
    write_json(batch / 'config.json', dict(jobs=jobs, limits=limits, settings=json.loads(settings.read_text()),
                                          pid=os.getpid(), started=time.time(), preparation_parallel=4,
                                          alongside=[str(p.resolve()) for p in args.alongside],
                                          ramp_seconds=args.ramp_seconds))
    snapshot = batch / 'source'
    snapshot.mkdir(exist_ok=True)
    for name in ['automatic_eval.py', 'evaluate.py', 'eval_readiness.py', 'prepare_software.py', 'eval_setup.py',
                 'eval_runtime.py', 'eval_api_retry.py', 'eval_docker.py', 'eval_proxy.py', 'seed_batch.py', 'eval_ramp.py']:
        shutil.copy2(ROOT / 'local' / name, snapshot / name)
    args.prepare_root.mkdir(parents=True, exist_ok=True)
    return run_schedule(jobs, batch, settings, args.prepare_root.resolve(), limits['parallel'], ledger,
                        alongside=args.alongside, prepare_only=args.prepare_only, ramp_seconds=args.ramp_seconds)


if __name__ == '__main__':
    raise SystemExit(main())
