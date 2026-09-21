"""Import a pinned HF Benchmark-Agent snapshot and evaluate a seeded sample with shared LaaJ."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import numpy as np
from dotenv import load_dotenv
from evalclaw.diagnostics import write_json
from evalclaw.execution.memory_budget import memory_budget
from evalclaw.quality.contamination import evaluate_contamination
from evalclaw.quality.laaj import evaluate_with_laaj
from evalclaw.sources.benchmark_agent import convert_requirement
from evalclaw.types import BenchmarkConfig, TargetModelConfig


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    if os.environ.get('PYTHONHASHSEED') != str(seed):
        raise ValueError(f'Launch with PYTHONHASHSEED={seed}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--sample-size', type=int, default=2)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--no-contamination', action='store_true')
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error('Sample size must be positive')
    seed_everything(args.seed)
    load_dotenv(REPO / 'benchmark-output/setup-20260917/private/api.env')
    key = os.environ['DEEPSEEK_API_KEY']
    config = BenchmarkConfig(seed=args.seed, laaj_model='deepseek-flash', laaj_provider='openai_compatible',
        laaj_base_url='https://api.deepseek.com', laaj_api_key=key, laaj_reasoning_effort='high',
        laaj_extra_body={'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high', 'seed': args.seed},
        laaj_sample_size=args.sample_size, laaj_evaluate_analyser=False,
        contamination_enabled=not args.no_contamination, contamination_sample_size=args.sample_size,
        search_backend='gemini', memory_budget_gib=600, memory_job_gib=1, memory_headroom_gib=16,
        output_dir=str(args.output.resolve()), runner_max_workers=0)
    args.output.mkdir(parents=True, exist_ok=False)
    output, source = args.output.resolve(), args.source.resolve()
    upstream = REPO / 'baselines/Benchmark-Agent'
    write_json(output / 'config.json', config.model_dump(mode='json'), redact=True)
    write_json(output / 'experiment.json', {'repo': 'assassinlike/b635', 'revision': args.revision,
        'source': str(source), 'sample_size_per_goal': args.sample_size, 'seed': args.seed,
        'target_rerun': False, 'contamination': not args.no_contamination,
        'code_sha256': {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__), *list((REPO/'evalclaw/sources').glob('benchmark_agent*.py')),
                      *list((REPO/'evalclaw/quality').glob('*.py'))]}})
    prepared = {}
    for path in sorted((source/'data').glob('*.jsonl')):
        name = path.stem
        suite, run, records, manifest = convert_requirement(source, name, upstream=upstream, revision=args.revision)
        directory = output/name
        write_json(directory/'suite.json', suite.model_dump(mode='json'))
        write_json(directory/'construction.json', {'suite': suite.model_dump(mode='json')})
        write_json(directory/'run.json', run.model_dump(mode='json'))
        write_json(directory/'conversion.json', manifest)
        for record in records:
            write_json(directory/'native'/f"{record['task_id']}.json", record)
        for raw in [path, source/'provenance'/f'{name}.json', upstream/'local/self_evaluate.py', upstream/'utils/llm_caller.py']:
            shutil.copy2(raw, directory/'native'/raw.name)
        selected = random.Random(args.seed).sample(sorted(suite.tasks, key=lambda t: t.id), min(args.sample_size,len(suite.tasks)))
        selected_ids = {t.id for t in selected}
        sampled = suite.model_copy(update={'tasks': [t for t in suite.tasks if t.id in selected_ids]})
        write_json(directory/'sample.json', {'seed': args.seed, 'strategy': 'uniform_without_replacement',
                   'population': len(suite.tasks), 'item_ids': [t.id for t in sampled.tasks]})
        native = manifest['selftest_config']
        parameters = {**native.get('request_parameters', {}), 'temperature': native['temperature'], 'max_tokens': native['max_tokens']}
        if native.get('seed') is not None:
            parameters['seed'] = native['seed']
        model = TargetModelConfig(id='deepseek-flash', model='deepseek-flash', provider='openai_compatible',
                                  base_url=config.laaj_base_url, api_key=key, extra_body=parameters)
        group_config = config.model_copy(update={'targets': [model], 'task_models': [model.model_copy(update={'id': 'native-judge'})]})
        write_json(directory/'config.json', group_config.model_dump(mode='json'), redact=True)
        prepared[name] = suite, sampled, run, group_config
        print(name, 'converted', len(suite.tasks), 'sampled', len(sampled.tasks), flush=True)

    def review(name):
        suite, sampled, run, group_config = prepared[name]
        directory = output/name
        write_json(directory/'status.json', {'stage': 'laaj'})
        quality = evaluate_with_laaj(suite.objective, sampled, None, group_config, run=run,
                                     artifact_dir=directory, trace_dir=directory/'laaj')
        quality.total_item_count = len(suite.tasks)
        write_json(directory/'laaj.json', quality.model_dump(mode='json'))
        if config.contamination_enabled:
            write_json(directory/'status.json', {'stage': 'contamination'})
            quality.contamination = evaluate_contamination(suite.objective, sampled, group_config,
                artifact_dir=directory, trace_dir=directory/'contamination', log=lambda msg: print(name,msg,flush=True))
            write_json(directory/'laaj.json', quality.model_dump(mode='json'))
        write_json(directory/'status.json', {'stage': 'completed', 'item_errors': quality.item_errors,
            'overall_error': quality.overall_error, 'contamination_failures': [i.item_id for i in quality.contamination.items if i.status=='failed'] if quality.contamination else []})
        return {'converted': len(suite.tasks), 'sampled': len(sampled.tasks), 'quality': quality.model_dump(mode='json')}

    summary = {}
    with memory_budget(config, output), ThreadPoolExecutor(max_workers=len(prepared)) as pool:
        futures = {pool.submit(review,name): name for name in prepared}
        for future in as_completed(futures):
            name = futures[future]
            try:
                summary[name] = future.result()
            except Exception as exc:
                summary[name] = {'error': str(exc)}
                write_json(output/name/'status.json', {'stage': 'failed', 'error': str(exc)}, redact=True)
            write_json(output/'summary.json', summary, redact=True)
            print(name, 'review finished', flush=True)


if __name__ == '__main__':
    main()
