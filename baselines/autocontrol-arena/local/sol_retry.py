"""Launch selected GPT retries and audit already-running older workers."""

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from dotenv import load_dotenv
import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def launch(source, selected, concurrent_with=(), model_mismatch_max_retries=None,
           max_workers=10, target_profile=None, target_key_envs=(), omit_temperature=False,
           target_rpm=None):
    load_dotenv(ROOT / '.env')
    for name in target_key_envs:
        assert os.environ.get(name), f'Missing credential: {name}'
    now = datetime.now(timezone.utc)
    tag = now.strftime('%Y%m%d-%H%M%S-%f')
    run = ROOT / 'results' / f'sol-high-retry-{tag}'
    native = ROOT / 'results' / f'native-sol-high-retry-{tag}'
    previous = Path((ROOT / 'local/sol-high-latest.txt').read_text().strip())
    previous_native = Path((ROOT / 'local/native-sol-high-latest.txt').read_text().strip())
    excluded = set()
    ancestor = previous
    while ancestor:
        ancestor_manifest = read(ancestor / 'manifest.json')
        for status_path in (ancestor / 'items').glob('*/status.json'):
            if read(status_path).get('exclude_from_future_retries'):
                excluded.add(status_path.parent.name)
        ancestor = Path(ancestor_manifest['retry_of']) if ancestor_manifest.get('retry_of') else None
    skipped = sorted(set(selected) & excluded)
    selected = {key: value for key, value in selected.items() if key not in excluded}
    if skipped:
        print(json.dumps({'excluded_from_future_retries': skipped}), flush=True)
    if not selected:
        raise ValueError('No eligible questions remain after retry exclusions')
    manifest = copy.deepcopy(read(source / 'manifest.json'))
    policy_path = ROOT / 'local/sol-retry-policy.json'
    policy = read(policy_path) if policy_path.exists() else {}
    manifest['retire_error_codes'] = policy.get('retire_error_codes', [])
    if target_rpm is None:
        target_rpm = policy.get('target_rpm', manifest.get('target_rpm', 45))
    manifest['items'] = [item for item in manifest['items'] if item['id'] in selected]
    assert len(manifest['items']) == len(selected)
    for item in manifest['items']:
        destination = run / item['environment']
        shutil.copytree(source / item['environment'], destination)
        for name, digest in item['sha256'].items():
            assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
    shutil.copytree(source / 'config', run / 'config')
    if policy_path.exists():
        shutil.copyfile(policy_path, run / 'config/retry-policy.json')
    if target_profile:
        profile_path = ROOT / 'configs/profiles' / f'{target_profile}.yaml'
        target = yaml.safe_load(profile_path.read_text())
        shutil.copyfile(profile_path, run / 'config/target.yaml')
        manifest.update(target_profile=target_profile, target_model=target['model_name'],
                        api_base_url=target['api_base_url'], target_max_tokens=target['max_tokens'])
    if target_key_envs:
        for index, item in enumerate(manifest['items']):
            item['target_api_key_env'] = target_key_envs[index % len(target_key_envs)]
    for name in ['responses_provider.py', 'request_rate.py', 'sol_retry.py', 'test_responses_provider.py', 'rerun.py']:
        shutil.copyfile(ROOT / 'local' / name, run / 'config' / name)
    model_retries = (manifest.get('model_mismatch_max_retries', 5)
                     if model_mismatch_max_retries is None else model_mismatch_max_retries)
    manifest.update(created_at=now.isoformat(), total=len(selected), max_workers=min(max_workers, len(selected)),
                    status='prepared', retry_of=str(previous), retry_reasons=selected,
                    scope='Selected retries of saved questions; IDs and reasons are listed in retry_reasons.',
                    model_mismatch_max_retries=model_retries, cyber_policy_automatic_retries=0)
    manifest['target_rpm'] = target_rpm
    manifest['transient_retries'] = policy.get('transient_retries', 8)
    manifest['transient_retry_delays_seconds'] = [10, 20, 40, 80, 160, 300, 300, 300]
    manifest['deferred_failure_policy'] = (
        f'Retry model mismatch up to {model_retries} additional times per request; '
        f'retry transient request failures up to {manifest["transient_retries"]} additional times '
        'with exponential backoff and Retry-After. Budgets are independent; all attempts share RPM pacing. '
        'Policy, authentication, context limits and validation failures are not retried.')
    manifest['concurrent_with'] = [str(path) for path in concurrent_with]
    for key in ['runner_pid', 'launched_at']:
        manifest.pop(key, None)
    nm = copy.deepcopy(read(previous_native / 'manifest.json'))
    nm.update(created_at=now.isoformat(), status='prepared', max_workers=min(4, len(selected)),
              previous_supplement=str(previous_native), batches=[{'name': 'sol', 'source': str(run)}])
    for key in ['runner_pid', 'launched_at']:
        nm.pop(key, None)
    shutil.copytree(previous_native / 'config', native / 'config')
    (run / 'README.md').write_text(
        'Selected retries of saved questions; original environments and settings preserved. '
        'See manifest.json for per-question reasons and retry ancestry. GPT effort=high; all original and retry '
        f'workers share the same {target_rpm} RPM pacing file, with at most {manifest["max_workers"]} concurrent scenarios. '
        f'Responses from another model are discarded; additional retry budget: {model_retries}. '
        'All returned usages, including discarded responses, are recorded '
        'in responses-usage.jsonl; only accepted responses enter the trajectory. Report token totals cover '
        'accepted responses only. Rejected responses and instruction echoes are retained in rejected-responses.jsonl. '
        f'Transient failures get {manifest["transient_retries"]} additional request retries; '
        'backoff starts at 10 seconds and doubles to 300 seconds, respecting longer Retry-After values. '
        'Errors and retry decisions are saved in request-errors.jsonl. '
        'No automatic policy retries are enabled.\n')
    env = dict(os.environ, AUTOCONTROL_ARENA_TARGET_RPM=str(target_rpm),
               AUTOCONTROL_ARENA_TARGET_RATE_LIMIT_FILE=manifest['rate_limit_file'],
               AUTOCONTROL_ARENA_MODEL_MISMATCH_RETRIES=str(model_retries),
               AUTOCONTROL_ARENA_TRANSIENT_RETRIES=str(manifest['transient_retries']),
               AUTOCONTROL_ARENA_OMIT_TEMPERATURE='1' if omit_temperature else '0')
    manifest['runtime_environment'] = {key: env[key] for key in [
        'AUTOCONTROL_ARENA_TARGET_RPM', 'AUTOCONTROL_ARENA_TARGET_RATE_LIMIT_FILE',
        'AUTOCONTROL_ARENA_MODEL_MISMATCH_RETRIES', 'AUTOCONTROL_ARENA_OMIT_TEMPERATURE',
        'AUTOCONTROL_ARENA_TRANSIENT_RETRIES']}
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    for folder, module, data in [(run, 'local.rerun', manifest), (native, 'local.native_rejudge', nm)]:
        save(folder / 'manifest.json', data)
        with (folder / 'runner.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-m', module, str(folder)], cwd=ROOT, env=env,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        data.update(status='launched', launched_at=datetime.now(timezone.utc).isoformat(), runner_pid=process.pid)
        save(folder / 'manifest.json', data)
    (ROOT / 'local/sol-high-latest.txt').write_text(str(run) + '\n')
    (ROOT / 'local/native-sol-high-latest.txt').write_text(str(native) + '\n')
    print(json.dumps({'run': str(run), 'native': str(native), 'items': selected}), flush=True)
    return run


def audit(source, item_ids):
    """Retain older clean runs; retry any that finish with mixed model responses."""
    pending = set(item_ids)
    results = {}
    while pending:
        for item_id in sorted(pending):
            folder = source / 'items' / item_id
            status = read(folder / 'status.json')
            if status['state'] == 'running':
                continue
            responses = [json.loads(line) for line in (folder / 'responses-usage.jsonl').read_text().splitlines()]
            models = sorted({r['model'] for r in responses})
            results[item_id] = {'returned_models': models, 'source_state': status['state'],
                                'has_report': bool(status.get('reports')), 'retry_run': None}
            if any(model != 'gpt-5.6-sol' for model in models):
                results[item_id]['retry_run'] = str(launch(source, {item_id: 'mixed_model_in_older_worker'}))
            pending.remove(item_id)
            save(source / 'model-audit.json', {'pending': sorted(pending), 'results': results})
        if pending:
            time.sleep(15)


if __name__ == '__main__':
    audit(Path(sys.argv[1]).resolve(), sys.argv[2:])
