"""Review completed Petri audits through the shared quality and contamination pipeline."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import random
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import numpy as np
from dotenv import load_dotenv
from evalclaw.diagnostics import write_json
from evalclaw.quality.contamination import evaluate_contamination
from evalclaw.quality.laaj import evaluate_with_laaj
from evalclaw.sources.petri import convert_requirement
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
    parser.add_argument('--target-model', default='deepseek-flash')
    parser.add_argument('--sample-size', type=int, default=2)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--convert-only', action='store_true')
    parser.add_argument('--no-contamination', action='store_true')
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error('sample-size must be positive')
    seed_everything(args.seed)
    load_dotenv(REPO / 'benchmark-output/setup-20260917/private/api.env')
    key = os.environ['DEEPSEEK_API_KEY']
    model = TargetModelConfig(id=args.target_model, model=args.target_model,
                              provider='openai_compatible', base_url='https://api.deepseek.com', api_key=key)
    config = BenchmarkConfig(seed=args.seed, laaj_model='deepseek-flash', laaj_provider='openai_compatible',
        laaj_base_url='https://api.deepseek.com', laaj_api_key=key, laaj_reasoning_effort='high',
        laaj_extra_body={'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high', 'seed': args.seed},
        laaj_sample_size=args.sample_size, laaj_evaluate_analyser=False, targets=[model],
        contamination_enabled=not args.no_contamination, contamination_sample_size=args.sample_size,
        search_backend='gemini', memory_budget_gib=None,
        output_dir=str(args.output.resolve()))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/'config.json', config.model_dump(mode='json'), redact=True)
    write_json(output/'experiment.json', {'repo': 'assassinlike/b635', 'revision': args.revision,
        'source': str(args.source.resolve()), 'target_group': args.target_model, 'sample_size': args.sample_size,
        'seed': args.seed, 'target_rerun': False, 'unit': 'complete audit, all branches',
        'scoring_scope': 'requirement-performance-only',
        'code_sha256': {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__), REPO/'evalclaw/sources/petri.py',
                      *list((REPO/'evalclaw/quality').glob('*.py'))]}})
    prepared = {}
    for number in (7, 8, 9, 13):
        name = f'requirement-{number:02d}'
        directory = output/name
        suite, run, manifest = convert_requirement(args.source, number, directory,
            target_model=args.target_model, revision=args.revision)
        write_json(directory/'suite.json', suite.model_dump(mode='json'))
        write_json(directory/'construction.json', {'suite': suite.model_dump(mode='json')})
        write_json(directory/'run.json', run.model_dump(mode='json'))
        write_json(directory/'conversion.json', manifest)
        selected = random.Random(args.seed).sample(sorted(suite.tasks, key=lambda t: t.id), min(args.sample_size,len(suite.tasks)))
        ids = {t.id for t in selected}
        sampled = suite.model_copy(update={'tasks': [t for t in suite.tasks if t.id in ids]})
        write_json(directory/'sample.json', {'seed': args.seed, 'strategy': 'uniform_without_replacement',
                   'population': len(suite.tasks), 'item_ids': [t.id for t in sampled.tasks]})
        prepared[name] = suite, sampled, run
        print(name, 'converted', len(suite.tasks), 'sampled', len(sampled.tasks), flush=True)
    if args.convert_only:
        return

    def review(name):
        suite, sampled, run = prepared[name]
        directory = output/name
        write_json(directory/'status.json', {'stage': 'laaj'})
        quality = evaluate_with_laaj(suite.objective, sampled, None, config, run=run,
                                     artifact_dir=directory, trace_dir=directory/'laaj')
        quality.total_item_count = len(suite.tasks)
        write_json(directory/'laaj.json', quality.model_dump(mode='json'))
        if config.contamination_enabled:
            write_json(directory/'status.json', {'stage': 'contamination'})
            quality.contamination = evaluate_contamination(suite.objective, sampled, config,
                artifact_dir=directory, trace_dir=directory/'contamination', log=lambda msg: print(name,msg,flush=True))
            write_json(directory/'laaj.json', quality.model_dump(mode='json'))
        write_json(directory/'status.json', {'stage': 'completed', 'item_errors': quality.item_errors,
            'overall_error': quality.overall_error, 'contamination_failures': [i.item_id for i in quality.contamination.items if i.status=='failed'] if quality.contamination else []})
        return {'converted': len(suite.tasks), 'sampled': len(sampled.tasks), 'quality': quality.model_dump(mode='json')}

    summary = {}
    with ThreadPoolExecutor(max_workers=len(prepared)) as pool:
        futures = {pool.submit(review, name): name for name in prepared}
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
