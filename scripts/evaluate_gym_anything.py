"""Convert audited local Gym-Anything tasks and run the shared LaaJ pipeline."""
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
from evalclaw.quality.contamination import evaluate_contamination
from evalclaw.quality.laaj import evaluate_with_laaj
from evalclaw.sources.gym_anything import REQUIREMENTS, convert_requirement
from evalclaw.types import BenchmarkConfig, EvalRun, QcReport, TargetModelConfig, TaskSuite


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    if os.environ.get('PYTHONHASHSEED') != str(seed):
        raise ValueError(f'Launch with PYTHONHASHSEED={seed}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--sample-size', type=int, default=2)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--convert-only', action='store_true')
    parser.add_argument('--review-converted', action='store_true')
    args = parser.parse_args()
    if args.sample_size < 1 or (args.convert_only and args.review_converted):
        parser.error('Use a positive sample size and one conversion/review mode')
    seed_everything(args.seed)
    load_dotenv(REPO/'benchmark-output/setup-20260917/private/api.env')
    key = os.environ['DEEPSEEK_API_KEY']
    model = TargetModelConfig(id='deepseek-flash', model='deepseek-flash',
        provider='openai_compatible', base_url='https://api.deepseek.com', api_key=key)
    output = args.output.resolve()
    config = BenchmarkConfig(seed=args.seed, laaj_model='deepseek-flash', laaj_provider='openai_compatible',
        laaj_base_url='https://api.deepseek.com', laaj_api_key=key, laaj_reasoning_effort='high',
        laaj_extra_body={'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high', 'seed': args.seed},
        laaj_sample_size=args.sample_size, laaj_evaluate_analyser=False, targets=[model],
        contamination_enabled=True, contamination_sample_size=args.sample_size,
        search_backend='gemini', memory_budget_gib=None, output_dir=str(output))
    code_paths = [Path(__file__), REPO/'evalclaw/sources/gym_anything.py',
                  *list((REPO/'evalclaw/quality').glob('*.py'))]
    record = {'source': str(args.source.resolve()), 'target_group': 'deepseek-flash', 'sample_size': args.sample_size,
        'seed': args.seed, 'target_rerun': False, 'unit': 'one generated desktop task and its accepted native attempt',
        'requirements': list(REQUIREMENTS), 'scoring_scope': 'native-program-verifier-score-and-pass',
        'code_sha256': {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}}
    output.mkdir(parents=True, exist_ok=args.review_converted)
    if args.review_converted:
        previous = json.loads((output/'experiment.json').read_text())
        adapter = 'evalclaw/sources/gym_anything.py'
        if ({k: v for k, v in previous.items() if k != 'code_sha256'} !=
                {k: v for k, v in record.items() if k != 'code_sha256'}
                or previous['code_sha256'][adapter] != record['code_sha256'][adapter]):
            raise ValueError('Review settings or adapter differ from converted experiment')
        write_json(output/'review-implementation.json', record['code_sha256'])
    else:
        write_json(output/'config.json', config.model_dump(mode='json'), redact=True)
        write_json(output/'experiment.json', record)
    def prepare(number):
        name = f'requirement-{number:02d}'
        directory = output/name
        if args.review_converted:
            suite = TaskSuite.model_validate_json((directory/'suite.json').read_text())
            run = EvalRun.model_validate({**json.loads((directory/'run.json').read_text()),
                                         'suite': suite, 'qc_report': QcReport()})
        else:
            suite, run, manifest = convert_requirement(args.source, number, directory)
            write_json(directory/'suite.json', suite.model_dump(mode='json'))
            write_json(directory/'construction.json', {'suite': suite.model_dump(mode='json')})
            write_json(directory/'run.json', run.model_dump(mode='json'))
            write_json(directory/'conversion.json', manifest)
        selected = random.Random(args.seed).sample(sorted(suite.tasks, key=lambda t: t.id), min(args.sample_size, len(suite.tasks)))
        ids = {t.id for t in selected}
        sampled = suite.model_copy(update={'tasks': [t for t in suite.tasks if t.id in ids]})
        sampled_run = run.model_copy(update={'suite': sampled, 'results': [r for r in run.results if r.item_id in ids]})
        evidence = directory/'sampled-review'
        evidence.mkdir(exist_ok=True)
        if not args.review_converted:
            for task in sampled.tasks:
                shutil.copytree(directory/'native'/task.id, evidence/'native'/task.id, copy_function=os.link)
        write_json(evidence/'construction.json', {'suite': sampled.model_dump(mode='json')})
        write_json(evidence/'run.json', sampled_run.model_dump(mode='json'))
        write_json(directory/'sample.json', {'seed': args.seed, 'strategy': 'uniform_without_replacement',
                   'population': len(suite.tasks), 'item_ids': [t.id for t in sampled.tasks]})
        print(name, 'converted', len(suite.tasks), 'sampled', len(sampled.tasks), flush=True)
        return name, (suite, sampled, sampled_run)
    with ThreadPoolExecutor(max_workers=len(REQUIREMENTS)) as pool:
        prepared = dict(pool.map(prepare, REQUIREMENTS))
    if args.convert_only:
        return

    def review(name):
        suite, sampled, run = prepared[name]
        directory = output/name
        evidence = directory/'sampled-review'
        write_json(directory/'status.json', {'stage': 'laaj'})
        quality = evaluate_with_laaj(suite.objective, sampled, None, config, run=run,
                                     artifact_dir=evidence, trace_dir=directory/'laaj')
        quality.total_item_count = len(suite.tasks)
        write_json(directory/'laaj.json', quality.model_dump(mode='json'))
        write_json(directory/'status.json', {'stage': 'contamination'})
        quality.contamination = evaluate_contamination(suite.objective, sampled, config,
            artifact_dir=evidence, trace_dir=directory/'contamination', log=lambda msg: print(name, msg, flush=True))
        write_json(directory/'laaj.json', quality.model_dump(mode='json'))
        write_json(directory/'status.json', {'stage': 'completed', 'item_errors': quality.item_errors,
            'overall_error': quality.overall_error, 'contamination_failures': [
                i.item_id for i in quality.contamination.items if i.status == 'failed']})
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
