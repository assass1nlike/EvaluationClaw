"""Review import of Gym-Anything's audited local task/attempt ledger."""
import base64
import csv
import hashlib
import json
from pathlib import Path
import shutil

from ..diagnostics import redact_secrets, write_json
from ..execution.task_runtime import contract_issues, task_digest
from ..protocols.task_definition import EpisodeRecord, MetricResult
from ..types import BenchmarkItem, EvalDimension, EvalRun, EvalSpec, ItemResult, QcReport, TaskSuite

REQUIREMENTS = (1, 2, 3, 4, 6)
LOCAL_REQUIREMENTS = dict(enumerate(REQUIREMENTS, 1))
RUNTIME_FILES = ('agents/shared/cli_harness.py', 'agents/shared/qwen_computer_use.py',
                 'agents/evaluation/run_single.py', 'src/gym_anything/env.py',
                 'src/gym_anything/verification/runner.py', 'src/gym_anything/verification/pipeline.py')


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def copy_file(source, destination, manifest):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    manifest[str(source)] = sha256(source)
    if sha256(destination) != manifest[str(source)]:
        raise ValueError(f'Source changed during import: {source}')


def extract_images(value, folder):
    """Keep CLI message structure, replacing inline image bytes with viewable files."""
    if isinstance(value, dict):
        source_image = value.get('type') == 'base64' and str(value.get('media_type', '')).startswith('image/')
        cli_image = 'base64' in value and str(value.get('type', '')).startswith('image/')
        if source_image or cli_image:
            media_type = value['media_type'] if source_image else value['type']
            data = base64.b64decode(value['data'] if source_image else value['base64'], validate=True)
            extension = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[media_type]
            path = folder/'cli-images'/(hashlib.sha256(data).hexdigest()+extension)
            path.parent.mkdir(exist_ok=True)
            if not path.exists():
                path.write_bytes(data)
            metadata = {k: v for k, v in value.items() if k not in {'data', 'base64', 'type', 'media_type'}}
            return {**metadata, 'type': 'file', 'media_type': media_type,
                    'path': (Path('native')/folder.name/path.relative_to(folder)).as_posix(),
                    'original_encoding': 'base64'}
        return {k: extract_images(v, folder) for k, v in value.items()}
    if isinstance(value, list):
        return [extract_images(v, folder) for v in value]
    return value


def import_cli(episode, folder, manifest):
    """Stream CLI events once; stdout is a duplicate and private CLI homes are excluded."""
    counts, final = {}, ''
    paths = sorted((episode/'cli_harness').glob('api_attempt_*.jsonl'),
                   key=lambda p: int(p.stem.rsplit('_', 1)[1]))
    for source in paths:
        digest = hashlib.sha256()
        count = 0
        with source.open('rb') as stream, (folder/source.name).open('w') as output:
            for count, line in enumerate(stream, 1):
                digest.update(line)
                row = json.loads(line)
                row = redact_secrets(extract_images(row, folder))
                output.write(json.dumps(row, ensure_ascii=False)+'\n')
                if row.get('type') == 'result' and isinstance(row.get('result'), str):
                    final = row['result']
        counts[source.name] = count
        manifest[str(source)] = digest.hexdigest()
    return counts, final


def convert_requirement(local_dir, requirement, output_dir):
    local, output = Path(local_dir).resolve(), Path(output_dir).resolve()
    ledger_path = local/'evaluation_results.json'
    ledger = load(ledger_path)
    generation = Path(ledger['source'])
    manifest_path = local/'outputs/eval114_rerun_0920/config.json'
    jobs = {j['id']: j for j in load(manifest_path)['jobs']}
    summary = load(local/'outputs/deepseek_final/summary.json')
    if summary['ledger_sha256'] != sha256(ledger_path):
        raise ValueError('Final summary does not describe the current adoption ledger')
    with (local/'outputs/deepseek_final/results.csv').open() as stream:
        accepted = {r['id']: r for r in csv.DictReader(stream)}
    if set(jobs) != set(ledger['tasks']) or set(accepted) != set(jobs):
        raise ValueError('Task manifest, adoption ledger and final results disagree')
    groups = {env: LOCAL_REQUIREMENTS[n] for n, _, env, _ in load(generation/'batch.json')['jobs']}
    goal = (generation/'user-inputs.txt').read_text().splitlines()[requirement-1]
    selected = [(key, entry) for key, entry in sorted(ledger['tasks'].items())
                if groups[entry['env']] == requirement]
    if not selected:
        raise ValueError(f'No native tasks for D{requirement}')
    dimension = EvalDimension(id=f'D{requirement}', name=f'D{requirement}', description=goal,
                              approach='Native computer-use task in real software')
    spec = EvalSpec(objective=goal, scale=len(selected), dimensions=[dimension], task_types=['agent'])
    tasks, results, checks = [], [], []
    unavailable = {'status': 'not_provided', 'unavailable_reason':
        'Native source and recorded desktop evidence are available for review. A live Gym-Anything/QEMU/GUI execution adapter is not connected to EvalClaw; this is not evidence of a defective native task.'}
    for key, entry in selected:
        job = jobs[key]
        source = Path(job['source'])
        task_source = source/'tasks'/entry['task']
        result_path = Path(entry['accepted_result'])
        result, config = load(result_path), load(result_path.parent/'config.json')
        if (str(result_path) != accepted[key]['result_path'] or sha256(result_path) != accepted[key]['result_sha256']
                or result_path.parent != Path(entry['required_attempt'])
                or any(x['env'] != entry['env'] or x['task'] != entry['task'] for x in (job, result, config))
                or config['model'] != 'deepseek-flash'):
            raise ValueError(f'Accepted attempt mismatch: {key}')
        for name, expected in job['hashes'].items():
            config_key = {'task.json': 'task_sha256', 'verifier.py': 'verifier_sha256'}[name]
            if sha256(task_source/name) != expected or config[config_key] != expected:
                raise ValueError(f'Generated task changed: {key}/{name}')
        native = load(task_source/'task.json')
        if native['id'].split('@')[0] != entry['task'] or native['env_id'].split('@')[0] != entry['env']:
            raise ValueError(f'Native task identity mismatch: {key}')
        task_id = f'gym-anything-{key}'
        folder = output/'native'/task_id
        folder.mkdir(parents=True, exist_ok=False)
        hashes = {}
        # Retain shared environment files and this task; unrelated task definitions
        # are not part of this item's review input or diversity sample.
        sibling_roots = {p.parent for p in (source/'tasks').glob('*/task.json') if p.parent != task_source}
        for path in sorted(source.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and not any(p in path.parents for p in sibling_roots):
                copy_file(path, folder/'environment'/path.relative_to(source), hashes)
        runtime_files = set(RUNTIME_FILES) | {str(p.relative_to(local.parent))
            for p in (local.parent/'src/gym_anything/verification').glob('*.py')}
        for name in sorted(runtime_files):
            copy_file(local.parent/name, folder/'runtime'/name, hashes)
        copy_file(result_path, folder/'result.json', hashes)
        for name in ('driver.log', 'cli-version.txt'):
            path = result_path.parent/name
            if path.exists():
                copy_file(path, folder/name, hashes)
        for path in sorted((result_path.parent/'initialization').rglob('*')):
            if path.is_file():
                copy_file(path, folder/'initialization'/path.relative_to(result_path.parent/'initialization'), hashes)
        write_json(folder/'runtime-config.json', config, redact=True)
        hashes[str(result_path.parent/'config.json')] = sha256(result_path.parent/'config.json')
        write_json(folder/'adoption.json', entry, redact=True)
        if entry.get('evidence'):
            copy_file(Path(entry['evidence']), folder/'adoption-evidence.json', hashes)
        episode_path = Path(result['summary']).parent if result.get('summary') else None
        trajectory, cli_counts, final = {}, {}, ''
        if episode_path:
            summary = load(episode_path/'summary.json')
            trajectory = load(episode_path/'trajectory.json')
            if summary['verifier'] != result['verifier'] or trajectory['model'] != config['model']:
                raise ValueError(f'Grade/trajectory mismatch: {key}')
            for pattern in ('summary.json', 'trajectory.json', 'traj.jsonl', 'timing.jsonl', '*.log', 'frame_*.png'):
                for path in sorted(episode_path.glob(pattern)):
                    copy_file(path, folder/path.name, hashes)
            for name in ('prompt.txt', 'api-retries.jsonl', 'sandbox-events.jsonl'):
                path = episode_path/'cli_harness'/name
                if path.exists():
                    copy_file(path, folder/name, hashes)
            cli_counts, final = import_cli(episode_path, folder, hashes)
            prompt = (folder/'prompt.txt').read_text()
            if native['description'] not in trajectory['task'] or trajectory['task'] not in prompt:
                raise ValueError(f'Target prompt does not match task: {key}')
        else:
            prompt = native['description']
        write_json(folder/'evidence-index.json', {'source_sha256': hashes, 'cli_records': cli_counts,
            'source_root': str(source), 'source_mount': '/workspace',
            'excluded_sibling_tasks': [str(p.relative_to(source)) for p in sorted(sibling_roots)],
            'cli_format': 'Recorded CLI stream, not a complete provider API transcript. Image data is extracted to files. Credentials are redacted. Retries remain separate.',
            'images': 'frame_* are native desktop frames; cli-images are the actual image bytes in recorded CLI messages. Gateway coordinates use its resized screenshots.',
            'image_tool': 'view_benchmark_image(source=run_artifact, path=<relative path below or in CLI stream>)',
            'screenshots': [(Path('native')/task_id/p.relative_to(folder)).as_posix()
                            for p in sorted(folder.glob('frame_*.png'))],
            'cli_images': [(Path('native')/task_id/p.relative_to(folder)).as_posix()
                           for p in sorted((folder/'cli-images').glob('*'))],
            'terminal_state': 'No complete final VM snapshot or independent verifier input export is supplied; native feedback and visible outcomes are retained.'})
        assets = [{'id': p.relative_to(folder).as_posix(), 'path': str(p), 'visibility': ['reviewer'], 'sha256': sha256(p)}
                  for p in sorted(folder.rglob('*')) if p.is_file()
                  and p.parent != folder/'cli-images' and not (p.parent == folder and p.name.startswith('frame_'))]
        task_prefix = 'environment/tasks/'+entry['task']+'/'
        task = BenchmarkItem(id=task_id, dimension_id=dimension.id, task_type='agent',
            content={'messages': [{'role': 'user', 'content': prompt}]}, assets=assets,
            environment={'type': 'tool_service', 'service': {**unavailable,
                'assets': ['environment/env.json', 'runtime/agents/shared/cli_harness.py'],
                'config': {'native_runner': config['runner'], 'workspace_source': str(source)}},
                'tools': [{'name': 'act', 'description': 'Native shell command controlling the remote desktop. Syntax and actions are in the saved prompt and gateway source; not a provider function tool.',
                           'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}]},
            interaction={'protocol': 'program', 'controller': {**unavailable,
                'assets': ['runtime/agents/shared/cli_harness.py', 'runtime-config.json'],
                'config': {'native_max_steps': config['max_steps'], 'native_cli_timeout_sec': config['cli_timeout_sec'],
                           'native_episode_timeout_sec': config['episode_timeout_sec']}}},
            evaluation={'references': [{'id': 'native-test', 'kind': 'tests', 'asset_ids': [task_prefix+'verifier.py']}],
                'metrics': [{'id': 'native_score', 'minimum': 0, 'maximum': 100, 'description': 'Original program verifier score; not binary accuracy.'},
                            {'id': 'native_passed', 'value_type': 'boolean', 'description': 'Original verifier pass flag, independent of score.'}],
                'scorers': [{'id': 'native-verifier', 'kind': 'component', 'metrics': ['native_score', 'native_passed'],
                    'references': ['native-test'], 'component': {**unavailable,
                        'assets': [task_prefix+'task.json', task_prefix+'verifier.py', 'runtime/src/gym_anything/verification/runner.py'],
                        'config': {'native_success': native['success'], 'native_hooks': native.get('hooks', {}),
                                   'ordering': 'post_task/export hook executes before verification'}}}],
                'scalar': {'metric': 'native_score', 'minimum': 0, 'maximum': 100}},
            annotations={'native_status': entry['status'], 'review_note': entry.get('review_note', ''),
                'input_fidelity': 'Saved CLI user prompt; CLI system prompt and full API requests are not captured.' if episode_path else 'Native task description only; the model never started, so no executed CLI prompt is fabricated.',
                'environment_access': 'Target controls the remote environment through act. CLI sandbox Bash/Read operate in a separate sandbox, not directly on the task VM. Reviewer-only source files are not target-visible.',
                'budget_semantics': 'Native gateway counts valid environment steps, including screenshot; this is distinct from total CLI tool calls. Saved prompt and native implementation are preserved even when their budget descriptions differ.',
                'evidence_guide': 'Read evidence-index.json, environment/tasks/<task>/task.json and verifier.py, trajectory.json, result.json, and api_attempt_*.jsonl. Screenshots are execution artifacts: view_benchmark_image(source=run_artifact, path=<relative path from evidence-index or CLI record>).',
                'evidence_limits': 'Frozen review only; no complete terminal VM snapshot or independently replayable verifier inputs. Inspect setup and runtime logs; an initialization failure is not automatically a model capability failure.'},
            source={'kind': 'imported'}, provenance={'dataset': ledger['dataset'], 'source': str(task_source),
                'ledger_sha256': sha256(ledger_path), 'accepted_result': str(result_path), 'result_sha256': sha256(result_path),
                'task_sha256': job['hashes'], 'native_source_commit': config.get('source_commit')})
        issues = contract_issues(task)
        if issues:
            raise ValueError(f'Invalid Gym task {key}: {issues}')
        grade = result.get('verifier') or {}
        score = grade.get('score')
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100):
            raise ValueError(f'Invalid native score: {key}')
        metrics = [MetricResult(metric='native_score', value=score, status='valid' if score is not None else 'error',
                                reason='' if score is not None else 'No native grade; target did not start'),
                   MetricResult(metric='native_passed', value=grade.get('passed'),
                                status='valid' if isinstance(grade.get('passed'), bool) else 'error')]
        error = None if entry['status'] == 'accepted' else entry['status']+': '+entry.get('review_note', '')
        if score is None:
            error = error or 'No native grade'
        evidence = [str(p.relative_to(output)) for p in sorted(folder.rglob('*')) if p.is_file()]
        episode = EpisodeRecord(task_id=task_id, task_digest=task_digest(task),
            bindings={'runtime': 'imported.GymAnything', 'target_model': config['model'], 'native_config': config},
            outputs=trajectory.get('steps', []), metrics=metrics, native_evidence=evidence,
            artifacts={'evidence_index': str((folder/'evidence-index.json').relative_to(output))},
            termination=(result.get('cli') or {}).get('terminal_reason') or entry['status'])
        tasks.append(task)
        results.append(ItemResult(item_id=task_id, target_id=config['model'], raw_response=final,
            score=score/100 if score is not None else 0, error=error, judge_reasoning=grade.get('feedback', ''), episode=episode,
            execution={'imported': True, 'native_grade': grade, 'native_status': entry['status'], 'valid_native_score': score is not None}))
        checks.append({'id': task_id, 'status': entry['status'], 'score': score, 'passed': grade.get('passed'),
                       'assets': len(assets), 'cli_records': cli_counts, 'accepted_result': str(result_path)})
    suite = TaskSuite(objective=goal, spec=spec, dimensions=[dimension], tasks=tasks,
                      evaluation_plan=[{'id': 'native-score', 'metric': 'native_score', 'aggregation': 'mean'}])
    run = EvalRun(suite=suite, qc_report=QcReport(summary='Imported native tasks and accepted attempts; no target rerun'), results=results)
    return suite, run, {'count': len(tasks), 'items': checks, 'ledger_sha256': sha256(ledger_path),
                        'manifest_sha256': sha256(manifest_path), 'replay_supported': False}
