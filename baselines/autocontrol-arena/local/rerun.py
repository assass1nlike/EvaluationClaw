"""Run prepared environments through the original CLI with bounded concurrency."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def run_item(item, manifest, run_dir):
    output = run_dir / 'items' / item['id']
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.update({
        'AUTOCONTROL_ARENA_RESULTS_DIR': str(output),
        'AUTOCONTROL_ARENA_RUNTIME_ENV_DIR': str(output / 'runtime_envs'),
        'AUTOCONTROL_ARENA_SIMULATION_MAX_STEPS': str(manifest['max_steps']),
        'AUTOCONTROL_ARENA_SCENARIO_TIMEOUT_SECONDS': str(manifest['timeout_seconds']),
    })
    if manifest.get('environment_profile'):
        env['AUTOCONTROL_ARENA_ENVIRONMENT_PROFILE'] = manifest['environment_profile']
    if item.get('target_api_key_env'):
        env['AUTOCONTROL_ARENA_TARGET_API_KEY'] = os.environ[item['target_api_key_env']]
    command = [
        sys.executable, '-m', 'local.run', 'run',
        '--profile', manifest['profile'], '--intent', item['user_intent'],
        '--env-path', str(run_dir / item['environment']),
        '--stress-level', str(item['stress_level']),
        '--temptation-level', str(item['temptation_level']),
        '--env-complexity-level', str(item['env_complexity_level']),
        '--output-dir', str(output), '--no-interactive-design',
    ]
    if manifest.get('target_profile'):
        command.extend(['--target-profile', manifest['target_profile'], '--models', manifest['target_model']])
    result = {'id': item['id'], 'started_at': now(), 'state': 'running'}
    with (output / 'run.log').open('ab') as log:
        process = subprocess.Popen(
            command, cwd=manifest['root'], env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        result['pid'] = process.pid
        save(output / 'status.json', result)
        try:
            result['exit_code'] = process.wait(timeout=manifest['timeout_seconds'] + 3600)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            result['exit_code'] = process.wait()
            result['hard_timeout'] = True
    reports = []
    for path in output.rglob('report.json'):
        report = json.loads(path.read_text())
        reports.append({
            'path': str(path.relative_to(run_dir)),
            'execution_status': report['metadata']['execution_status'],
        })
    result.update(state='finished', finished_at=now(), reports=reports)
    retired_codes = set(manifest.get('retire_error_codes', []))
    rejected = output / 'rejected-responses.jsonl'
    if retired_codes:
        observed = {(json.loads(line)['response'].get('error') or {}).get('code')
                    for line in rejected.read_text().splitlines()} if rejected.exists() else set()
        errors = output / 'request-errors.jsonl'
        if errors.exists():
            observed.update(json.loads(line).get('code') for line in errors.read_text().splitlines())
        matched = sorted(retired_codes & observed)
        if matched:
            result.update(exclude_from_future_retries=True, retry_exclusion_codes=matched)
    save(output / 'status.json', result)
    return result


def main():
    run_dir = Path(sys.argv[1]).resolve()
    manifest = json.loads((run_dir / 'manifest.json').read_text())
    os.nice(5)
    completed = []
    save(run_dir / 'progress.json', {'started_at': now(), 'total': len(manifest['items']), 'completed': 0})
    pending = iter(manifest['items'])
    remaining = len(manifest['items'])
    with ThreadPoolExecutor(max_workers=manifest['max_workers']) as pool:
        futures = {}
        while remaining or futures:
            reserved = 0
            for previous in manifest.get('concurrent_with', []):
                previous = Path(previous)
                previous_manifest = json.loads((previous / 'manifest.json').read_text())
                for item in previous_manifest['items']:
                    status = previous / 'items' / item['id'] / 'status.json'
                    if not status.exists() or json.loads(status.read_text())['state'] == 'running':
                        reserved += 1
            available = max(0, manifest['max_workers'] - reserved - len(futures))
            for _ in range(min(remaining, available)):
                item = next(pending)
                futures[pool.submit(run_item, item, manifest, run_dir)] = item
                remaining -= 1
            if not futures:
                time.sleep(2)
                continue
            done, _ = wait(futures, timeout=2, return_when=FIRST_COMPLETED)
            for future in done:
                item = futures.pop(future)
                try:
                    result = future.result()
                except Exception as error:
                    result = {'id': item['id'], 'state': 'runner_error', 'error': str(error)}
                    save(run_dir / 'items' / item['id'] / 'status.json', result)
                completed.append(result)
                save(run_dir / 'progress.json', {
                    'updated_at': now(), 'total': len(manifest['items']),
                    'completed': len(completed), 'results': completed,
                })
                print(f"{len(completed)}/{len(manifest['items'])} {result}", flush=True)
    save(run_dir / 'summary.json', {'finished_at': now(), 'results': completed})


if __name__ == '__main__':
    main()
