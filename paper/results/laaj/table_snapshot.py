"""Collect available measurements for the provisional main-result tables."""
import gc
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCES = {}


def read(path):
    raw = path.read_bytes()
    SOURCES[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def quality(directories):
    rows, diversity = [], []
    for directory in directories:
        rows.extend(read(p) for p in sorted((directory / 'laaj/items').glob('*/result.json')))
        p = directory / 'laaj.json'
        if p.exists():
            report = read(p)
            if report.get('diversity'):
                diversity.append(report['diversity']['score'])
    result = {name: {'value': 25 * (mean(row[name]['score'] for row in rows) - 1),
                     'items': len(rows)} for name in ('correctness', 'faithfulness')} if rows else {}
    if diversity:
        result['diversity'] = {'value': 25 * (mean(diversity) - 1), 'demands': len(diversity)}
    return result


def contamination(paths, reports=False):
    items = []
    for path in paths:
        data = read(path)
        items.extend((data.get('contamination') or {}).get('items', []) if reports else [data])
    scores = [x['contamination']['score'] for x in items
              if x.get('status') == 'matched' and x.get('contamination')]
    return {'value': 25 * (mean(scores) - 1) if scores else None,
            'scored_matches': len(scores), 'searched_items': len(items)}


def main():
    batch = ROOT / 'benchmark-output'
    runs = read(batch / 'batch-23-20260921/resume.json')['runs']
    luna = batch / 'main-gym-luna-20260922/evaluation'
    rows = {
        'EvalScientist conventional': quality([Path(p) for name, p in runs.items() if int(name[:2]) > 15]),
        'EvalScientist frontier': quality(sorted(luna.glob('evalscientist--0*')) + sorted(luna.glob('evalscientist--1[0-5]-*'))),
        'Gym-Anything': quality(sorted(luna.glob('gym-anything--*'))),
    }
    for category, numbers in [('conventional', range(16, 24)), ('frontier', range(1, 16))]:
        built, requested, scores, errors = 0, 0, [], 0
        for name, path in runs.items():
            if int(name[:2]) not in numbers:
                continue
            suite = read(Path(path) / 'construction.json')['suite']
            built += len(suite['tasks'])
            requested += 200 if category == 'conventional' else 20
            sampled = read(luna / ('evalscientist--' + name) / 'run.json')
            scores.extend(x['score'] for x in sampled['results'] if not x.get('error'))
            errors += sum(bool(x.get('error')) for x in sampled['results'])
            del sampled, suite
            gc.collect()
        row = rows['EvalScientist ' + category]
        row['yield'] = {'value': 100 * built / requested, 'built': built, 'requested': requested}
        row['sample_difficulty'] = {'value': 100 * (1 - mean(scores)), 'items': len(scores), 'errors_excluded': errors}
        row['non_contamination'] = contamination(p for name in runs if int(name[:2]) in numbers
            for p in sorted((batch / 'contamination-20260922/evaluation' / ('evalscientist--' + name) / 'contamination').glob('*/result.json')))
    rows['AutoBencher'] = {'non_contamination': contamination(sorted(
        (batch / 'contamination-20260922/evaluation').glob('autobencher--*/contamination/*/result.json')))}
    for method, directory, pattern in [
        ('Benchmark-Agent', 'benchmark-agent-laaj-20260921', 'review/*/laaj.json'),
        ('Petri', 'petri-laaj-20260922', 'review/*/laaj.json'),
        ('AutoControl Arena', 'autocontrol-laaj-20260922', 'evaluation/*/laaj.json'),
        ('Gym-Anything', 'gym-laaj-20260922', 'evaluation/*/laaj.json'),
    ]:
        rows.setdefault(method, {})['non_contamination'] = contamination(sorted((batch / directory).glob(pattern)), reports=True)
    snapshot = {'captured_at': datetime.now(timezone.utc).isoformat(), 'purpose': 'provisional table demo',
        'notes': [
            'Available-item means are provisional estimates, not completed population measurements.',
            'Conventional EvalScientist quality uses earlier Astra reviews; frontier and Gym quality use current Luna reviews.',
            'AutoBencher contamination uses current Luna results; other baseline contamination uses DeepSeek adapter pilots.',
            'Do not infer full coverage or judge equivalence from this demo. Missing values remain null.',
            'Existing finalized table cells are retained; sample_difficulty is used only where the table is empty.',
        ], 'rows': rows, 'sources_sha256': SOURCES}
    (OUT / 'table-snapshot.json').write_text(json.dumps(snapshot, indent=2) + '\n')
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
