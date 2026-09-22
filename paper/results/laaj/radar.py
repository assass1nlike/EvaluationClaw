"""Snapshot available, demand-aligned measurements for the conventional radar."""
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent
METRICS = ['Correctness', 'Faithfulness', 'Diversity', 'Difficulty', 'Non-contamination']
DEMANDS = {
    'mmlu-pro': '16-factual-knowledge',
    'livebench-reasoning': '17-reasoning',
    'livebench-coding': '19-computer-science',
    'livebench-data': '20-data-analysis',
    'ifbench': '21-instruction-following',
    'helm-long-context': '22-long-context',
}


def collect():
    sources = {}

    def read(path):
        raw = path.read_bytes()
        sources[str(path.relative_to(REPO))] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    def quality(directory):
        rows = [read(p) for p in sorted((directory/'laaj/items').glob('*/result.json'))]
        scores = {name: {'value': 25*(mean(row[name.lower()]['score'] for row in rows)-1),
                         'items': len(rows)} for name in METRICS[:2]} if rows else {}
        path = directory/'laaj.json'
        if path.exists():
            report = read(path)
            if report.get('model') != 'gpt-5.6-luna':
                raise ValueError('Radar quality judgments must use Luna')
            if report.get('diversity'):
                scores['Diversity'] = {'value': 25*(report['diversity']['score']-1), 'demands': 1}
        return scores

    reference = REPO/'benchmark-output/reference-luna-20260922'
    generated = REPO/'benchmark-output/main-gym-luna-20260922'
    contamination = REPO/'benchmark-output/contamination-20260922/evaluation'
    for batch in (reference, generated):
        assert read(batch/'manifest.json')['model'] == 'gpt-5.6-luna'
    methods = {'EvalScientist': {}, 'Expert-curated': {}}
    for ref, job in DEMANDS.items():
        methods['Expert-curated'][ref] = quality(reference/'evaluation'/ref)
        directory = generated/'evaluation'/('evalscientist--'+job)
        values = quality(directory)
        path = directory/'run.json'
        if path.exists():
            data = read(path)
            results = data['results']
            if any(row['target_id'] != 'deepseek-flash-openclaw' for row in results):
                raise ValueError('Difficulty requires the same DeepSeek target')
            valid = [row['score'] for row in results if not row.get('error')]
            if any(not 0 <= value <= 1 for value in valid):
                raise ValueError('Expected normalized native scores')
            if valid:
                values['Difficulty'] = {'value': 100*(1-mean(valid)), 'items': len(valid),
                    'execution_errors_excluded': len(results)-len(valid)}
            del data, results
            gc.collect()
        matches = []
        outcomes = []
        for path in sorted((contamination/('evalscientist--'+job)/'contamination').glob('*/result.json')):
            result = read(path)
            outcomes.append(result['status'])
            if result['status'] == 'matched' and result.get('contamination'):
                matches.append(result['contamination']['score'])
        if matches:
            values['Non-contamination'] = {'value': 25*(mean(matches)-1), 'items': len(matches),
                'completed_searches': len(outcomes), 'failed_searches': outcomes.count('failed')}
        methods['EvalScientist'][ref] = values
    aggregate = {}
    for method, demands in methods.items():
        aggregate[method] = {}
        for metric in METRICS:
            observed = {name: scores[metric] for name, scores in demands.items() if metric in scores}
            aggregate[method][metric] = {
                'value': mean(row['value'] for row in observed.values()) if observed else None,
                'demands': list(observed),
                'items': sum(row.get('items', 0) for row in observed.values()),
            }
    snapshot = {'captured_at': datetime.now(timezone.utc).isoformat(), 'judge': 'gpt-5.6-luna',
        'seed': 42, 'metrics': METRICS, 'demand_mapping': DEMANDS,
        'aggregation': 'mean within each demand, then equal weight across demands with available values',
        'scale': '0--100; quality and conditional contamination resistance use 25*(score-1)',
        'difficulty': '100*(1-mean normalized DeepSeek Flash score); execution errors excluded',
        'missing': 'null; no imputation; no expert target runs or expert contamination reviews in this batch',
        'per_demand': methods, 'aggregate': aggregate, 'sources_sha256': sources}
    (OUTPUT/'radar-data.json').write_text(json.dumps(snapshot, indent=2)+'\n')
    return snapshot


if __name__ == '__main__':
    print(json.dumps(collect()['aggregate'], indent=2))
