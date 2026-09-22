"""Reproduce the baseline quality values in the two main results tables."""
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
BATCH = REPO/'benchmark-output/formal-baseline-laaj-20260922'
sys.path.insert(0, str(BATCH/'code'))
from evalclaw.diagnostics import write_json
from evalclaw.models.llm import extract_json
from evalclaw.types import LaajItemResult, LaajReport

OUTPUT = Path(__file__).resolve().parent
EXCLUDED = 'autocontrol-user_input_15_12'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def available_d15():
    directory = BATCH/'evaluation/autocontrol--requirement-15'
    sample = json.loads((directory/'sample.json').read_text())
    items, evidence = {}, {}
    for path in sorted((directory/'laaj/items').glob('*/llm/*.json')):
        trace = json.loads(path.read_text())
        if trace.get('status') != 'completed' or trace.get('finish_reason') != 'stop':
            continue
        response = trace.get('response', {})
        if response.get('model') != 'gpt-6-astra':
            continue
        message = response.get('choices', [{}])[0].get('message', {})
        if not isinstance(message.get('content'), str) or message.get('tool_calls'):
            continue
        request = json.loads(trace['request']['body']['messages'][1]['content'])
        item_id = request['item']['id']
        result = LaajItemResult.model_validate({**extract_json(message['content']), 'item_id': item_id})
        if item_id in items:
            raise ValueError(f'Multiple final scores require inspection: {item_id}')
        items[item_id] = result
        evidence[item_id] = {'path': str(path.relative_to(REPO)), 'sha256': digest(path)}
    if set(sample['item_ids']) - set(items) != {EXCLUDED} or len(items) != 19:
        raise ValueError('The observed missing judgment differs from the approved exclusion')
    write_json(OUTPUT/'autocontrol-d15.json', {
        'model': 'gpt-6-astra', 'item_results': [items[k].model_dump(mode='json') for k in sorted(items)],
        'evidence': evidence, 'excluded_item_ids': [EXCLUDED],
        'exclusion_reason': 'User confirmed bio_policy blocking and authorized aggregation of available judgments.',
        'diversity': None, 'contamination': None})
    return list(items.values())


def mean(values):
    return sum(Decimal(str(v)) for v in values)/len(values)


def scale(value):
    return str(((value-1)*25).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def main():
    summary = {'model': 'gpt-6-astra', 'reasoning_effort': 'high', 'seed': 42,
        'transformation': '25 * (mean_raw_score - 1)',
        'item_weighting': 'equal weight per available task judgment',
        'diversity_weighting': 'equal weight per scored demand; AutoControl uses five available demands by user instruction',
        'contamination': 'pending', 'baselines': {}}
    for baseline, expected in [('autobencher', 400), ('benchmark-agent', 400), ('petri', 80), ('autocontrol', 119)]:
        items, diversity, sources = [], [], {}
        groups = sorted((BATCH/'evaluation').glob(baseline+'--*'))
        for group in groups:
            path = group/'laaj.json'
            if not path.exists():
                if group.name != 'autocontrol--requirement-15':
                    raise ValueError(f'Unexpected missing group: {group.name}')
                items.extend(available_d15())
                continue
            report = LaajReport.model_validate_json(path.read_text())
            if report.item_errors or report.overall_error:
                raise ValueError(f'Inspect errors before aggregation: {group.name}')
            items.extend(report.item_results)
            if report.diversity is not None:
                diversity.append(report.diversity.score)
            sources[group.name] = {'path': str(path.relative_to(REPO)), 'sha256': digest(path)}
        assert len(items) == expected
        scores = {metric: mean([getattr(item, metric).score for item in items])
                  for metric in ['correctness', 'faithfulness']}
        expected_diversity = 5 if baseline == 'autocontrol' else len(groups)
        if len(diversity) != expected_diversity:
            raise ValueError(f'Unexpected number of diversity judgments: {baseline}')
        scores['diversity'] = mean(diversity)
        summary['baselines'][baseline] = {
            'item_count': len(items), 'demand_count': len(groups), 'diversity_demand_count': len(diversity),
            'raw_1_to_5': {k: str(v) for k, v in scores.items()},
            'table_0_to_100': {k: scale(v) for k, v in scores.items()},
            'report_sources': sources,
            'excluded_item_ids': [EXCLUDED] if baseline == 'autocontrol' else []}
        print(baseline, summary['baselines'][baseline]['table_0_to_100'])
    write_json(OUTPUT/'baseline-quality.json', summary)


if __name__ == '__main__':
    main()
