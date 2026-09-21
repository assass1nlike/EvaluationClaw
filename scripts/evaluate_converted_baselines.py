"""Review frozen converted baseline suites through one rate-limited LaaJ gateway."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import sys
import threading
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import numpy as np
from dotenv import load_dotenv
from evalclaw.authoring.batch_gateway import Gateway
from evalclaw.diagnostics import redact_secrets, write_json
from evalclaw.execution.memory_budget import memory_budget
from evalclaw.quality.contamination import evaluate_contamination
from evalclaw.quality.laaj import evaluate_with_laaj
from evalclaw.types import BenchmarkConfig, EvalRun, LaajReport, QcReport, TargetModelConfig, TaskSuite


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    if os.environ.get('PYTHONHASHSEED') != str(seed):
        raise ValueError(f'Launch with PYTHONHASHSEED={seed}')


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(manifest, output):
    prepared = {}
    for baseline in manifest['baselines']:
        source = Path(baseline['source'])
        for suite_path in sorted(source.glob('*/suite.json')):
            directory = suite_path.parent
            job = baseline['id']+'--'+directory.name
            suite = TaskSuite.model_validate_json(suite_path.read_text())
            selected = random.Random(manifest['seed']).sample(sorted(suite.tasks, key=lambda t: t.id),
                min(baseline['sample_size'], len(suite.tasks)))
            ids = {t.id for t in selected}
            sampled = suite.model_copy(update={'tasks': [t for t in suite.tasks if t.id in ids]})
            run = EvalRun.model_validate({**json.loads((directory/'run.json').read_text()),
                                         'suite': suite, 'qc_report': QcReport()})
            config_path = directory/'config.json' if (directory/'config.json').is_file() else source/'config.json'
            config = BenchmarkConfig.model_validate_json(config_path.read_text())
            record = {'baseline': baseline['id'], 'requirement': directory.name, 'source': str(directory),
                'seed': manifest['seed'], 'strategy': 'uniform_without_replacement',
                'population': len(suite.tasks), 'item_ids': [t.id for t in sampled.tasks],
                'source_sha256': {p.name: sha256(p) for p in (suite_path, directory/'run.json', directory/'conversion.json')}}
            sample_path = output/job/'sample.json'
            if sample_path.exists() and json.loads(sample_path.read_text()) != record:
                raise ValueError(f'Frozen sample or source changed: {job}')
            write_json(sample_path, record)
            prepared[job] = (directory, suite, sampled, run, config)
    if len(prepared) != manifest['expected_groups']:
        raise ValueError(f'Expected {manifest["expected_groups"]} groups, found {len(prepared)}')
    count = sum(len(p[2].tasks) for p in prepared.values())
    if count != manifest['expected_items']:
        raise ValueError(f'Expected {manifest["expected_items"]} sampled items, found {count}')
    return prepared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--defer-contamination', action='store_true',
                        help='Run quality judgments and retain contamination as pending for a later invocation.')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    seed_everything(manifest['seed'])
    for path in manifest['credential_files']:
        load_dotenv(path)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    prepared = prepare(manifest, output)
    print(f'Prepared {len(prepared)} groups, {manifest["expected_items"]} sampled items', flush=True)
    if args.prepare_only:
        return
    record = {**manifest, 'credential_files': manifest['credential_files'],
        'code_sha256': {str(p.relative_to(REPO)): sha256(p) for p in sorted((REPO/'evalclaw').rglob('*.py'))},
        'driver_sha256': sha256(Path(__file__)), 'target_rerun': False,
        'metrics': ['correctness', 'faithfulness', 'diversity', 'contamination'],
        'analyser_evaluation': False}
    experiment = output/'experiment.json'
    if experiment.exists() and json.loads(experiment.read_text()) != record:
        raise ValueError('Experiment settings/code changed; use a new output directory')
    write_json(experiment, record)
    model = TargetModelConfig(id='laaj', model=manifest['model'], provider=manifest['provider'],
                              base_url=manifest['base_url'], extra_body={'reasoning_effort': 'high'})
    settings = SimpleNamespace(gateway_host='127.0.0.1', key_pools={},
        request_spacing_seconds=60/manifest['rpm']+0.01,
        model_identity_attempts=3, proxy=manifest['proxy'])
    gateway = Gateway(output, settings, {})
    bindings = {}
    for job in prepared:
        token = secrets.token_urlsafe(32)
        gateway.runtime_tokens[token] = (job, 'laaj', model, 'FORMAL_LAAJ_API_KEY')
        bindings[job] = token
    threading.Thread(target=gateway.serve_forever, daemon=True).start()
    base_url = f'http://127.0.0.1:{gateway.server_address[1]}/v1'

    def review(job):
        source, suite, sampled, run, original = prepared[job]
        directory = output/job
        # Preserve models that belong to the original task; only the meta-evaluator changes.
        def native_models(models):
            for model_config in models:
                if model_config.model != 'deepseek-flash':
                    raise ValueError(f'Configure original task-model credentials explicitly: {model_config.model}')
            return [m.model_copy(update={'api_key': os.environ['DEEPSEEK_API_KEY']}) for m in models]
        config = original.model_copy(update={
            'seed': manifest['seed'], 'targets': native_models(original.targets),
            'task_models': native_models(original.task_models),
            'laaj_model': model.model, 'laaj_provider': model.provider, 'laaj_base_url': base_url,
            'laaj_api_key': bindings[job], 'laaj_reasoning_effort': 'high', 'laaj_extra_body': model.extra_body,
            'laaj_sample_size': len(sampled.tasks), 'laaj_evaluate_analyser': False,
            'contamination_enabled': True, 'contamination_sample_size': len(sampled.tasks),
            'search_backend': 'gemini', 'memory_budget_gib': 600, 'memory_job_gib': 1,
            'memory_headroom_gib': 16, 'output_dir': str(directory)})
        write_json(directory/'config.json', config.model_dump(mode='json'), redact=True)
        path = directory/'laaj.json'
        quality = LaajReport.model_validate_json(path.read_text()) if path.exists() else None
        if quality is None or quality.item_errors or quality.overall_error:
            write_json(directory/'status.json', {'stage': 'laaj'})
            quality = evaluate_with_laaj(suite.objective, sampled, None, config, run=run,
                artifact_dir=source, trace_dir=directory/'laaj')
            quality.total_item_count = len(suite.tasks)
            write_json(path, quality.model_dump(mode='json'))
        if quality.contamination is None and not args.defer_contamination:
            write_json(directory/'status.json', {'stage': 'contamination'})
            quality.contamination = evaluate_contamination(suite.objective, sampled, config,
                artifact_dir=source, trace_dir=directory/'contamination',
                log=lambda msg: print(job, msg, flush=True))
            write_json(path, quality.model_dump(mode='json'))
        errors = {'item_errors': quality.item_errors, 'overall_error': quality.overall_error,
            'contamination_failures': [i.item_id for i in quality.contamination.items if i.status == 'failed']
                if quality.contamination else []}
        stage = 'awaiting_contamination' if quality.contamination is None else 'completed'
        status = {'stage': 'completed_with_errors' if any(errors.values()) else stage, **errors}
        write_json(directory/'status.json', status)
        return status

    summary = {}
    admission = BenchmarkConfig(memory_budget_gib=600, memory_job_gib=1, memory_headroom_gib=16)
    write_json(output/'status.json', {'stage': 'running', 'started_at': datetime.now(timezone.utc).isoformat()})
    try:
        with memory_budget(admission, output), ThreadPoolExecutor(max_workers=manifest['group_workers']) as pool:
            futures = {pool.submit(review, job): job for job in prepared}
            for future in as_completed(futures):
                job = futures[future]
                try:
                    summary[job] = future.result()
                except Exception as exc:
                    summary[job] = {'stage': 'failed', 'error': redact_secrets(str(exc))}
                    write_json(output/job/'status.json', summary[job])
                write_json(output/'summary.json', summary)
                print(job, summary[job]['stage'], flush=True)
        write_json(output/'status.json', {'stage': 'quality_finished_contamination_pending' if args.defer_contamination else 'finished',
            'groups': len(summary), 'completed': sum(s['stage'] == 'completed' for s in summary.values()),
            'awaiting_contamination': sum(s['stage'] == 'awaiting_contamination' for s in summary.values())})
    finally:
        gateway.shutdown()
        gateway.server_close()


if __name__ == '__main__':
    main()
