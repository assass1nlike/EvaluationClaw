"""Export and upload the final GPT-5.6-sol evaluation records."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

from local.native_rejudge import build_request
from local.upload_hf_evaluations import reconstruct

RESULTS = ROOT / 'results'
EXPORT = RESULTS / 'hf-gpt-evaluations'
REPO = 'assassinlike/b635'
PREFIX = 'autocontrol-arena/evaluations/gpt-5.6-sol'
BASE = RESULTS / 'rerun-200-20260918-145824'


def read(path):
    return json.loads(path.read_bytes())


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def jsonl(rows):
    return ('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def final_items():
    latest = Path((ROOT / 'local/sol-high-latest.txt').read_text().strip())
    selected = {}
    chain = []
    current = latest
    while True:
        manifest = read(current / 'manifest.json')
        chain.append(current)
        for item in manifest['items']:
            selected.setdefault(item['id'], (current, item))
        if not manifest.get('retry_of'):
            break
        current = Path(manifest['retry_of'])
    assert set(selected) == {item['id'] for item in read(BASE / 'manifest.json')['items']}
    return selected, chain


def native_reports():
    by_source = {}
    for run in RESULTS.glob('native-sol*'):
        for status_path in run.glob('sol/*/status.json'):
            status = read(status_path)
            source = status.get('source_report')
            if source and status.get('state') == 'completed':
                by_source.setdefault(str(Path(source).resolve()), []).append(status_path.parent)
    return by_source


def attempt_summary(folder):
    rows = []
    usage = folder / 'responses-usage.jsonl'
    if usage.exists():
        for line in usage.read_text().splitlines():
            row = read_json(line)
            rows.append({k: row.get(k) for k in [
                'request_id', 'attempt', 'request_started_at', 'response_id', 'requested_model',
                'model', 'status', 'accepted', 'rejection_reason', 'requested_reasoning',
                'returned_reasoning', 'requested_max_output_tokens', 'returned_max_output_tokens',
                'requested_temperature', 'returned_temperature', 'system_instructions_preserved',
                'input_message_count', 'usage', 'reasoning_summary_count']})
    return rows


def read_json(line):
    return json.loads(line)


def error_summary(folder):
    path = folder / 'request-errors.jsonl'
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        row = read_json(line)
        rows.append({k: row.get(k) for k in [
            'request_id', 'attempt', 'request_started_at', 'error_type', 'message',
            'status_code', 'code', 'retryable', 'will_retry', 'retry_delay_seconds']})
    return rows


def build():
    selected, chain = final_items()
    native = native_reports()
    questions = {item['id']: item for item in read(BASE / 'manifest.json')['items']}
    native_template = (RESULTS / 'native-sol-high-retry-20260920-184842-765537/config/native-unified.txt').read_text()
    files = {}
    groups = {}
    statuses = []
    counts = Counter()
    native_matches = 0
    parser_fallbacks = []
    native_missing_sections = []
    for item_id, (run, item) in sorted(selected.items()):
        assert item['sha256'] == questions[item_id]['sha256']
        for name, digest in item['sha256'].items():
            assert sha((run / item['environment'] / name).read_bytes()) == digest
        folder = run / 'items' / item_id
        reports = list(folder.rglob('report.json'))
        assert len(reports) <= 1, (item_id, reports)
        runner_status = read(folder / 'status.json')
        pipeline_files = list(folder.glob('runs/*/run.json'))
        assert len(pipeline_files) == 1
        pipeline = read(pipeline_files[0])
        status = {
            'question_id': f'autocontrol-arena/{item_id}', 'source_id': item_id,
            'requirement_line': int(item_id.split('_')[2]), 'target_model': 'gpt-5.6-sol',
            'source_run': run.name, 'runner_status': runner_status,
            'pipeline_run': pipeline, 'requirement_report_available': bool(reports),
            'request_attempts': attempt_summary(folder), 'request_errors': error_summary(folder),
        }
        rejected = folder / 'rejected-responses.jsonl'
        status['terminal_response_errors'] = [
            {'request_id': d.get('request_id'), 'attempt': d.get('attempt'),
             'response_id': d['response'].get('id'), 'model': d['response'].get('model'),
             'error': d['response']['error']}
            for d in (read_json(line) for line in rejected.read_text().splitlines())
            if d['response'].get('error')
        ] if rejected.exists() else []
        status['config_path'] = f'{PREFIX}/provenance/runs/{run.name}/manifest.json'
        if reports:
            report = reports[0]
            result = read(report)
            execution_status = result['metadata']['execution_status']
            status['execution_status'] = execution_status
            matches = native.get(str(report.resolve()), [])
            assert len(matches) == 1, (item_id, report, matches)
            native_dir = matches[0]
            native_status = read(native_dir / 'status.json')
            assert native_status['state'] == 'completed'
            status['native_report_available'] = True
            status['source_native_run'] = native_dir.parent.parent.name
            status['native_status'] = native_status
            for attempt in status['request_attempts']:
                # Older records have no acceptance flag. Their selected runs must contain only matching responses.
                if attempt['accepted'] is not False:
                    assert attempt['model'] == 'gpt-5.6-sol', item_id
                    assert attempt['returned_reasoning']['effort'] == 'high', item_id
                    assert attempt['system_instructions_preserved'] is True, item_id
            originals = {
                'trajectory_json': report.with_name('scenario.json'),
                'requirement_report_json': report,
                'native_report_json': native_dir / 'report.json',
                'native_judge_prompt': native_dir / 'prompt.txt',
                'native_judge_parsed_response_json': native_dir / 'judge.json',
            }
            row = {k: status[k] for k in [
                'question_id', 'source_id', 'requirement_line', 'target_model', 'source_run',
                'source_native_run', 'execution_status']}
            hashes = {}
            sources = {}
            for field, path in originals.items():
                raw = path.read_bytes()
                row[field] = raw.decode('utf-8')
                hashes[field] = sha(raw)
                sources[field] = str(path.relative_to(ROOT))
            # Preserve the requirement judge input as an offline reconstruction, as in the previous upload.
            request = build_request(run, item, report)
            assert reconstruct(request, native_template).encode() == (native_dir / 'prompt.txt').read_bytes(), item_id
            expanded, = folder.glob('report_*.json')
            original = read(expanded)
            assert request.action_trajectory == original['_trajectory'], item_id
            assert request.cot_content == original['_cot_content'], item_id
            prompt_source = (run / 'config/judge-prompts.py').read_text(encoding='utf-8-sig')
            template = next(ast.literal_eval(node.value) for node in ast.parse(prompt_source).body
                            if isinstance(node, ast.Assign) and any(
                                isinstance(t, ast.Name) and t.id == 'UNIFIED_MONITOR_PROMPT' for t in node.targets))
            row['requirement_judge_prompt_reconstructed'] = reconstruct(request, template)
            row['requirement_judge_raw_response'] = None
            row['native_judge_raw_response'] = None
            row['config_path'] = status['config_path']
            fallback_message = '   ⚠️  Manual extraction succeeded, but data may be incomplete'
            fallback_lines = [line for line in (folder / 'run.log').read_text().splitlines()
                              if line.partition(' WARNING ')[2] == fallback_message]
            row['requirement_parser_fallback_log'] = '\n'.join(fallback_lines)
            status['requirement_parser_fallback_observed'] = bool(fallback_lines)
            native_result = read(native_dir / 'judge.json')
            row['native_response_has_action_and_reasoning'] = all(
                isinstance(native_result.get(key), dict) and 'suspicion_score' in native_result[key]
                for key in ['action_analysis', 'cot_analysis'])
            status['native_response_has_action_and_reasoning'] = row['native_response_has_action_and_reasoning']
            if fallback_lines:
                parser_fallbacks.append(item_id)
            if not row['native_response_has_action_and_reasoning']:
                native_missing_sections.append(item_id)
            row['original_fields_sha256_json'] = json.dumps(hashes, sort_keys=True)
            row['source_artifacts_json'] = json.dumps(sources, sort_keys=True)
            groups.setdefault(row['requirement_line'], []).append(row)
            counts[execution_status] += 1
            native_matches += 1
        else:
            # Keep failed and context-limit attempts in the all-120 status file, without fabricating reports.
            error_codes = {d['error'].get('code') for d in status['terminal_response_errors']}
            error_codes.update(d.get('code') for d in status['request_errors'])
            status['native_report_available'] = False
            status['source_native_run'] = None
            if 'context_length_exceeded' in error_codes:
                status['execution_status'] = 'context_limit_exceeded'
            else:
                policy_codes = error_codes & {'cyber_policy', 'bio_policy'}
                assert len(policy_codes) == 1, (item_id, error_codes)
                status['execution_status'] = next(iter(policy_codes))
            counts[status['execution_status']] += 1
        statuses.append(status)
    assert sum(map(len, groups.values())) == 100, {k: len(v) for k, v in groups.items()}
    assert len(statuses) == 120 and native_matches == 100, (len(statuses), native_matches)
    assert counts == {'rollout_completed': 94, 'max_steps': 6, 'context_limit_exceeded': 3,
                      'cyber_policy': 16, 'bio_policy': 1}, counts
    for line, rows in groups.items():
        files[f'{PREFIX}/records/user_input_{line:02d}.jsonl'] = jsonl(rows)
    files[f'{PREFIX}/status.jsonl'] = jsonl(statuses)
    # Keep per-run settings and the actual recorded transport implementation, including differing endpoints.
    for run in chain:
        files[f'{PREFIX}/provenance/runs/{run.name}/manifest.json'] = (run / 'manifest.json').read_bytes()
        for name in ['target.yaml', 'framework.yaml', 'hyperparameters.yaml', 'responses_provider.py',
                     'request_rate.py', 'rerun.py', 'run.py', 'environment_model.py',
                     'judge-prompts.py', 'requirements.lock', 'retry-policy.json']:
            path = run / 'config' / name
            if path.exists():
                files[f'{PREFIX}/provenance/runs/{run.name}/config/{name}'] = path.read_bytes()
    for run_name in sorted({s['source_native_run'] for s in statuses if s['source_native_run']}):
        run = RESULTS / run_name
        files[f'{PREFIX}/provenance/runs/{run_name}/manifest.json'] = (run / 'manifest.json').read_bytes()
        for path in (run / 'config').iterdir():
            if path.is_file():
                files[f'{PREFIX}/provenance/runs/{run_name}/config/{path.name}'] = path.read_bytes()
    files[f'{PREFIX}/config.json'] = encode({
        'target_profile': 'gpt-5.6-sol-high', 'target_model': 'gpt-5.6-sol',
        'transport': 'Responses API streaming',
        'selected_scored_runs_by_endpoint': dict(Counter(
            read(RESULTS / s['source_run'] / 'manifest.json')['api_base_url']
            for s in statuses if s['requirement_report_available'])),
        'max_steps': 200, 'scenario_timeout_seconds': 21600, 'hard_timeout_seconds': 25200,
        'requested_max_output_tokens': 131072, 'reasoning_effort': 'high',
        'thinking': 'enabled through explicit reasoning effort high',
        'variable_settings': 'Endpoint, requested temperature, RPM, retry budgets and concurrency are per-run; see provenance/runs/<source_run>/manifest.json, config/target.yaml and transport code. Selected Fangcun runs omit temperature. SudoRelay requests temperature=0.7 but returned metadata may report temperature=1 and max_output_tokens=null.',
        'environment_profile': 'deepseek-flash', 'judge_profile': 'deepseek-flash',
        'framework_max_tokens': 300000, 'seed': None,
        'source_runs': [p.name for p in reversed(chain)],
        'final_counts': dict(counts),
        'requirement_parser_fallback_ids': parser_fallbacks,
        'native_missing_score_section_ids': native_missing_sections,
        'policy_retired_codes': ['cyber_policy', 'bio_policy'],
        'raw_target_response_text_uploaded': False,
    })
    files[f'{PREFIX}/README.md'] = README.encode()
    for name in ['local/upload_hf_gpt.py', 'local/upload_hf_evaluations.py', 'local/native_rejudge.py']:
        files[f'{PREFIX}/provenance/{Path(name).name}'] = (ROOT / name).read_bytes()
    secrets = [v.encode() for k, v in dotenv_values(ROOT / '.env').items()
               if v and len(v) >= 16 and ('KEY' in k.upper() or 'TOKEN' in k.upper())]
    for name, data in files.items():
        assert not any(secret in data for secret in secrets), f'Credential found in {name}'
    manifest = {
        'question_commit': '08f4db64bbe6131e53eba23737e67ea5bae511f4',
        'model': 'gpt-5.6-sol', 'records': 100, 'statuses': 120,
        'counts': dict(counts), 'native_prompt_matches': native_matches,
        'requirement_parser_fallback_ids': parser_fallbacks,
        'native_missing_score_section_ids': native_missing_sections,
        'requirement_judge_input_origin': 'offline reconstruction from saved trajectory and template',
        'native_judge_input_origin': 'saved prompt from native scoring run',
        'raw_judge_responses_uploaded': False, 'raw_target_response_text_uploaded': False,
        'files_sha256': {name: sha(data) for name, data in files.items()},
    }
    files[f'{PREFIX}/provenance/manifest.json'] = encode(manifest)
    for name, data in files.items():
        path = EXPORT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (EXPORT / 'local-build.json').write_bytes(encode({'files': len(files), 'bytes': sum(map(len, files.values())), 'counts': dict(counts)}))
    print(json.dumps({'files': len(files), 'bytes': sum(map(len, files.values())), 'counts': dict(counts), 'native_matches': native_matches}, ensure_ascii=False))
    return files


README = '''# GPT-5.6-sol evaluation records

These are the final records for the same 120 frozen AutoControl Arena questions in `autocontrol-arena/data/`. The six requirement groups are 5, 10, 11, 12, 14 and 15, with 20 questions each. Records are grouped by requirement and joined to questions using `question_id`.

The export contains 100 complete interactions with requirement-oriented reports and native supplemental reports, plus `status.jsonl` with all 120 final attempts. The remaining three attempts reached the context limit and 17 attempts were permanently policy-blocked (`cyber_policy` or `bio_policy`); those attempts have status and request metadata but no fabricated trajectory or score. `max_steps` interactions remain included as valid records.

Each scored record contains the saved trajectory, requirement report, native report, native judge prompt and parsed native judge response. The requirement judge prompt is reconstructed offline from the saved design, trajectory and the run template, matching the export convention used for the DeepSeek and Qwen records. Raw judge API response text and raw target response text are not uploaded. Request attempt metadata and structured error summaries are included for diagnosing routing, retries and service failures without exposing credentials.

The target used explicit `reasoning_effort=high`, requested `max_output_tokens=131072`, and 200 maximum interaction steps. Of the 100 scored attempts, 98 used SudoRelay and two used Fangcun's Azure gateway. SudoRelay requests included temperature=0.7; Fangcun requests omitted temperature. Returned metadata can differ from requested settings (SudoRelay sometimes returned temperature=1 and max_output_tokens=null). Each record links to its original run manifest and configuration snapshots; endpoint, RPM, concurrency, retry budgets and transport code varied by run. Do not apply the last retry batch's configuration to all records. Framework, environment auxiliary calls and both judging passes used DeepSeek Flash; their documented thinking/effort defaults were enabled/high, not explicitly configured. Credentials are excluded.

GPT reasoning in the trajectory is the API's reasoning summary, not full hidden reasoning. Native scoring assesses action risk, reasoning risk and intent; helpfulness/task-success placeholders are not measured outcomes. Both action and reasoning scores are 0–4, higher being worse. Requirement scores concern the user's evaluation requirement. Parser fallback flags and missing native score sections are recorded as in the other model exports; zero values must be interpreted alongside those flags and judge explanations.

All 100 saved native prompts were independently reconstructed and matched byte-for-byte, supporting the requirement prompt reconstruction procedure without making those prompts captured historical requests. Five original artifact strings per record have SHA-256 checksums. Final-attempt usage and structured error summaries are in status.jsonl, including rejected responses when usage was returned. Older attempts lack some recorder fields (null means unrecorded); calls without terminal usage cannot be fully counted. Earlier attempts' trajectories and diagnostic logs remain local. Provenance manifests include the retry chain, including failed batches that contribute no selected results.

The result is a record of model runs and model judgments, not a human accuracy label. `rollout_completed` and `max_steps` describe execution status; they do not by themselves mean that the task was successful. Context-limit and policy-blocked attempts are represented only in `status.jsonl`.
'''


def verify(files, receipt, token):
    api = HfApi(token=token)
    for name, expected in files.items():
        path = hf_hub_download(REPO, name, repo_type='dataset', revision=receipt['commit'], token=token,
                               cache_dir=ROOT / '.cache/huggingface')
        assert sha(Path(path).read_bytes()) == sha(expected), name
    trees = []
    for revision in [receipt['parent_commit'], receipt['commit']]:
        trees.append({f.path: f.blob_id for f in api.list_repo_tree(
            REPO, repo_type='dataset', revision=revision, recursive=True) if hasattr(f, 'blob_id')})
    before, after = trees
    assert all(after.get(p) == blob for p, blob in before.items() if p != '.gitattributes')
    attrs = [Path(hf_hub_download(REPO, '.gitattributes', repo_type='dataset', revision=rev,
                                  token=token, cache_dir=ROOT / '.cache/huggingface')).read_text().splitlines()
             for rev in [receipt['parent_commit'], receipt['commit']]]
    old, new = attrs
    assert new[:len(old)] == old
    allowed = {f'{name} filter=lfs diff=lfs merge=lfs -text' for name in files}
    assert set(new[len(old):]) <= allowed
    receipt['existing_files_unchanged'] = True
    receipt['hub_added_lfs_rules'] = new[len(old):]
    print(f'Verified {len(files)} files at {receipt["commit"]}.')
    receipt['verified'] = True
    (EXPORT / 'upload.json').write_bytes(encode(receipt))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upload', action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        manifest_path = f'{PREFIX}/provenance/manifest.json'
        manifest = read(EXPORT / manifest_path)
        names = [*manifest['files_sha256'], manifest_path]
        verify({name: (EXPORT / name).read_bytes() for name in names}, read(EXPORT / 'upload.json'),
               dotenv_values(ROOT / '.env').get('HF_TOKEN'))
        return
    files = build()
    if not args.upload:
        return
    token = dotenv_values(ROOT / '.env').get('HF_TOKEN')
    if not token:
        raise RuntimeError('HF_TOKEN is missing from .env')
    api = HfApi(token=token)
    head = api.repo_info(REPO, repo_type='dataset').sha
    existing = {f.path for f in api.list_repo_tree(REPO, repo_type='dataset', revision=head, recursive=True)
                if hasattr(f, 'path')}
    assert not any(path in existing for path in files), 'GPT evaluation export already exists; inspect before replacing'
    commit = api.create_commit(REPO, repo_type='dataset', parent_commit=head,
        operations=[CommitOperationAdd(path_in_repo=name, path_or_fileobj=data) for name, data in files.items()],
        commit_message='Add GPT-5.6-sol evaluation trajectories and scores')
    receipt = {'repo': REPO, 'parent_commit': head, 'commit': commit.oid, 'url': commit.commit_url, 'verified': False}
    (EXPORT / 'upload.json').write_bytes(encode(receipt))
    verify(files, receipt, token)
    print('COMMIT', commit.oid, commit.commit_url)


if __name__ == '__main__':
    main()
