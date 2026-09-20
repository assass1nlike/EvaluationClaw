"""Complete partial answer caches with the official inference function, then resume."""

import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

from api import start_api
from run import ROOT, seed_everything


def complete_answers(questions, path, pending, infer):
    answers = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(answers) <= len(questions)
    for question, answer in zip(questions, answers):
        assert all(answer[key] == value for key, value in question.items())
    for question in questions[len(answers):]:
        result = infer([question], pending)
        assert len(result) == 1 and result[0]['question'] == question['question']
        with path.open('a') as output:
            output.write(json.dumps(result[0]) + '\n')
        pending.unlink()
        answers.append(result[0])
        print(f'Recovered answers: {len(answers)}/{len(questions)}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, required=True)
    args = parser.parse_args()
    directory = args.resume.resolve()
    config = json.loads((directory / 'config.json').read_text())
    if os.getenv('PYTHONHASHSEED') != str(config['seed']):
        os.environ['PYTHONHASHSEED'] = str(config['seed'])
        os.execv(sys.executable, [sys.executable, '-u', *sys.argv])
    seed_everything(config['seed'])
    load_dotenv(ROOT / '.env')
    target = config.get('test_taker')
    if target:
        target = target | {'api_key': os.environ[target['api_key_env']]}
    url, close = start_api(config['base_url'], os.environ['AUTOBENCHER_API_KEY'],
                           config['model'], config['extra_body'], config['seed'], directory,
                           test_taker=target)
    os.environ['OPENAI_BASE_URL'] = url
    os.environ['OPENAI_API_KEY'] = 'local-proxy'
    os.environ.pop('OPENAI_ORG_ID', None)
    sys.path.insert(0, str(ROOT / 'upstream'))
    try:
        from util import process_args_for_models
        from tool_util import test_taker_inference

        alias = 'gpt-autobencher-target' if target else 'gpt-autobencher'
        model, tokenizer, _, client = process_args_for_models(alias)
        def infer(questions, path):
            return test_taker_inference((model, tokenizer, client), questions, str(path))
        for iteration in range(1, config['iterations'] + 1):
            prefix = directory / f'wiki.{iteration}'
            path = Path(f'{prefix}.test_taker_inference.json')
            if not path.exists() or Path(f'{prefix}.compare_answers.json').exists():
                continue
            questions = json.loads(Path(f'{prefix}.KI_questions.json').read_text())
            complete_answers(questions, path, directory / 'recovery/pending-answer.json', infer)
    finally:
        close()
    os.execv(sys.executable, [sys.executable, '-u', str(ROOT / 'run.py'), '--resume', str(directory)])


if __name__ == '__main__':
    main()
