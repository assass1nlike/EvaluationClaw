"""Preserve Benchmark-Agent's exported self-test scoring contract."""
import json


def score(params, config, model_call=None):
    from native import choice_label, _safe_json_loads
    answer = params['episode']['outputs'][-1]
    reference = next(r['value'] for r in params['references'] if r['id'] == 'answer')
    if config['method'] == 'exact_choice':
        correct = choice_label(answer) == choice_label(reference['answer'])
        return {'metrics': [{'metric': 'accuracy', 'value': int(correct), 'status': 'valid',
                             'reason': 'Native strict uppercase option-letter comparison.'}]}
    if model_call is None:
        from benchmark_io import model as model_call
    judge_input = {'task_input': config['task_input'], 'reference_output': reference,
                   'candidate_response': answer}
    response = model_call('judge', [
        {'role': 'system', 'content': config['judge_system']},
        {'role': 'user', 'content': json.dumps(judge_input, ensure_ascii=False)},
    ])
    raw = response['content']
    judgment = _safe_json_loads(raw)
    choices = response.get('raw', {}).get('choices', [])
    complete = bool(choices) and choices[0].get('finish_reason') == 'stop'
    valid = complete and isinstance(judgment, dict) and type(judgment.get('correct')) is bool
    return {'metrics': [{'metric': 'accuracy', 'value': int(judgment['correct']) if valid else None,
                         'status': 'valid' if valid else 'error',
                         'reason': str(judgment.get('reason', '')) if valid else 'Invalid native judge response.',
                         'raw': {'judge_raw': raw}}]}


if __name__ == '__main__':
    from benchmark_io import serve
    serve({'score': score}, version='benchmark-agent-selftest-1')
