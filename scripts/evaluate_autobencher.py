"""Convert saved AutoBencher rounds and review a seeded sample with the shared LaaJ."""
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
from evalclaw.sources.autobencher import convert_round
from evalclaw.types import BenchmarkConfig, TargetModelConfig


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    if os.environ.get('PYTHONHASHSEED') != str(seed):
        raise ValueError(f'Launch with PYTHONHASHSEED={seed}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--iteration', type=int, default=1)
    parser.add_argument('--sample-size', type=int, default=2)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--contamination', action='store_true')
    args = parser.parse_args()
    if args.sample_size < 1 or args.iteration < 1:
        parser.error('Sample size and iteration must be positive')
    seed_everything(args.seed)
    load_dotenv(REPO / 'benchmark-output/setup-20260917/private/api.env')
    key = os.environ['DEEPSEEK_API_KEY']
    model = TargetModelConfig(id='deepseek-flash', model='deepseek-flash', provider='openai_compatible',
        base_url='https://api.deepseek.com', api_key=key,
        extra_body={'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'})
    config = BenchmarkConfig(seed=args.seed, laaj_model=model.model, laaj_provider=model.provider,
        laaj_base_url=model.base_url, laaj_api_key=key, laaj_reasoning_effort='high',
        laaj_extra_body=model.extra_body, laaj_sample_size=args.sample_size, laaj_evaluate_analyser=False,
        contamination_enabled=args.contamination, contamination_sample_size=args.sample_size,
        search_backend='gemini', targets=[model],
        task_models=[model.model_copy(update={'id': 'native-judge', 'extra_body': {
            **model.extra_body, 'temperature': 0.0, 'seed': args.seed, 'max_tokens': 300000}})],
        memory_budget_gib=600, memory_job_gib=1, memory_headroom_gib=16,
        output_dir=str(args.output.resolve()), runner_max_workers=0)
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    batch = args.batch.resolve()
    native_config = json.loads((batch / 'config.json').read_text())
    upstream = REPO / 'baselines/AutoBencher/upstream'
    write_json(output / 'config.json', config.model_dump(mode='json'), redact=True)
    write_json(output / 'experiment.json', {
        'source_batch': str(batch), 'iteration': args.iteration, 'sample_size_per_goal': args.sample_size,
        'seed': args.seed, 'contamination': args.contamination, 'target_rerun': False,
        'source_code_sha256': {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__), *list((REPO / 'evalclaw/sources').glob('autobencher*.py')),
                      *list((REPO / 'evalclaw/quality').glob('*.py'))]},
    })
    prepared = {}
    for entry in native_config['tasks']:
        name = entry['name']
        suite, run, records, manifest = convert_round(batch / name, args.iteration, upstream=upstream)
        directory = output / name
        write_json(directory / 'suite.json', suite.model_dump(mode='json'))
        write_json(directory / 'construction.json', {'suite': suite.model_dump(mode='json')})
        write_json(directory / 'run.json', run.model_dump(mode='json'))
        write_json(directory / 'conversion.json', manifest)
        for record in records:
            write_json(directory / 'native' / f"{record['task_id']}.json", record)
        # Keep byte-identical source artifacts and the original comparator for audit.
        for key_name, path in manifest['source_files'].items():
            shutil.copy2(path, directory / 'native' / Path(path).name)
        shutil.copy2(upstream / 'wiki_autobencher.py', directory / 'native/wiki_autobencher.py')
        selected = random.Random(args.seed).sample(sorted(suite.tasks, key=lambda t: t.id),
                                                  min(args.sample_size, len(suite.tasks)))
        selected_ids = {t.id for t in selected}
        sampled = suite.model_copy(update={'tasks': [t for t in suite.tasks if t.id in selected_ids]})
        write_json(directory / 'sample.json', {'strategy': 'uniform_without_replacement', 'seed': args.seed,
            'population': len(suite.tasks), 'item_ids': [t.id for t in sampled.tasks]})
        prepared[name] = (suite, sampled, run)
        print(f'{name}: converted {len(suite.tasks)}, sampled {len(sampled.tasks)}', flush=True)

    def review(name):
        suite, sampled, run = prepared[name]
        directory = output / name
        write_json(directory / 'status.json', {'stage': 'laaj'})
        quality = evaluate_with_laaj(suite.objective, sampled, None, config, run=run,
            artifact_dir=directory, trace_dir=directory / 'laaj')
        quality.total_item_count = len(suite.tasks)
        write_json(directory / 'laaj.json', quality.model_dump(mode='json'))
        if args.contamination:
            write_json(directory / 'status.json', {'stage': 'contamination'})
            quality.contamination = evaluate_contamination(suite.objective, sampled, config,
                artifact_dir=directory, trace_dir=directory / 'contamination',
                log=lambda text: print(f'[{name}] {text}', flush=True))
            write_json(directory / 'laaj.json', quality.model_dump(mode='json'))
        write_json(directory / 'status.json', {'stage': 'completed', 'item_errors': quality.item_errors,
                                             'overall_error': quality.overall_error})
        return {'converted': len(suite.tasks), 'sampled': len(sampled.tasks),
                'quality': quality.model_dump(mode='json')}

    summary = {}
    with memory_budget(config, output), ThreadPoolExecutor(max_workers=len(prepared)) as pool:
        futures = {pool.submit(review, name): name for name in prepared}
        for future in as_completed(futures):
            name = futures[future]
            try:
                summary[name] = future.result()
            except Exception as exc:
                summary[name] = {'error': str(exc)}
                write_json(output / name / 'status.json', {'stage': 'failed', 'error': str(exc)}, redact=True)
            write_json(output / 'summary.json', summary, redact=True)
            print(f'{name}: review finished', flush=True)


if __name__ == '__main__':
    main()
