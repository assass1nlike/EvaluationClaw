"""AutoBencher's native answer comparison through the component protocol."""


def judge_prompt(config, question, answer, gold):
    return (config['judge_prefix'] + f"Question {config['row']}: {question}\n"
            f"pred={answer.strip()} || gold={gold.strip()}\nreason:")


def score(params, config, model_call=None):
    if model_call is None:
        from benchmark_io import model as model_call
    reference = next(r['value'] for r in params['references'] if r['id'] == 'answer')
    answer = params['episode']['outputs'][-1]
    response = model_call('judge', [
        {'role': 'system', 'content': config['system_prompt']},
        {'role': 'user', 'content': judge_prompt(config, config['question'], answer, reference)},
    ])
    reason = response['content'].strip()
    verdict = reason.split('##')[-1].strip()
    return {'metrics': [{'metric': 'accuracy',
        'value': int(verdict == 'true') if verdict in {'true', 'false'} else None,
        'status': 'valid' if verdict in {'true', 'false'} else 'error',
        'reason': reason, 'raw': {'native_verdict': verdict}}]}


if __name__ == '__main__':
    from benchmark_io import serve
    serve({'score': score}, version='autobencher-wiki-1')
