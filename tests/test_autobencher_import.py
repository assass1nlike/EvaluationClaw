import json
import subprocess
import sys
from pathlib import Path

import pytest

from evalclaw.sources.autobencher import convert_round
from evalclaw.sources.autobencher_scorer import score
from evalclaw.types import TaskSuite


@pytest.fixture
def native(tmp_path):
    def save(name, value):
        (tmp_path / name).write_text(json.dumps(value))
    save('config.json', {'theme': 'Answer factual questions', 'model': 'native-model', 'seed': 42})
    questions = [{'id': '1', 'category': cat, 'question': 'When?', 'gold_answer': 'January 21'}
                 for cat in ['Dates', 'History']]
    answers = [{**q, 'prompt': 'Output just with the final answer to the question.\nQuestion:When?\nAnswer:',
                'test_taker_response': '01/21'} for q in questions]
    grades = [{**q, 'id': str(i), 'test_taker_answer': '01/21', 'is_correct': 'true',
               'reasons': 'Equivalent date ## true'} for i, q in enumerate(questions, 1)]
    save('wiki.1.KI_questions.json', questions)
    (tmp_path / 'wiki.1.test_taker_inference.json').write_text('\n'.join(map(json.dumps, answers)))
    save('wiki.1.compare_answers.json', grades)
    (tmp_path / 'wiki_autobencher.py').write_text('def fast_compare_answers():\n    context_str = "Compare semantically.\\n"\n')
    return tmp_path


def test_preserves_native_prompt_reference_and_duplicate_source_ids(native):
    suite, run, records, manifest = convert_round(native, 1, upstream=native)
    assert len({t.id for t in suite.tasks}) == 2
    assert [t.provenance['native_id'] for t in suite.tasks] == ['1', '1']
    for task, record, result in zip(suite.tasks, records, run.results):
        assert task.content.messages[-1].content == record['answer']['prompt']
        assert task.evaluation.references[0].value == record['question']['gold_answer']
        assert task.evaluation.scorers[0].kind == 'component'
        assert result.raw_response == record['answer']['test_taker_response']
        assert result.episode.events == []  # Import does not fabricate timestamps or execution events.
        assert result.episode.native_evidence
        assert task.challenge_effort is None
    assert TaskSuite.model_validate_json(suite.model_dump_json()).tasks == suite.tasks
    assert manifest['count'] == 2


def test_refuses_misaligned_native_results(native):
    path = native / 'wiki.1.compare_answers.json'
    rows = json.loads(path.read_text())
    rows[0]['test_taker_answer'] = 'Different observed answer'
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError, match='row 1'):
        convert_round(native, 1, upstream=native)


def test_component_advertises_the_declared_version(native, tmp_path):
    suite, _, _, _ = convert_round(native, 1, upstream=native)
    spec = suite.tasks[0].evaluation.scorers[0].component
    for name, contents in spec.files.items():
        (tmp_path / name).write_text(contents)
    response = subprocess.run([sys.executable, '-u', 'score.py'], cwd=tmp_path,
        input=json.dumps({'id': 1, 'method': 'describe'}) + '\n', text=True,
        capture_output=True, check=True, timeout=10)
    description = json.loads(response.stdout)['result']
    assert description['version'] == spec.version
    assert 'score' in description['methods']


@pytest.mark.parametrize('verdict,status,value', [('true', 'valid', 1), ('false', 'valid', 0),
                                               ('uncertain', 'error', None)])
def test_native_comparator_and_invalid_verdict(native, verdict, status, value):
    suite, run, records, _ = convert_round(native, 1, upstream=native)
    task = suite.tasks[0]
    def call(role, messages):
        assert role == 'judge'
        assert messages[0] == {'role': 'system', 'content': 'You are a helpful AI agent.'}
        assert messages[1]['content'] == records[0]['judge_prompt']
        return {'content': f'Reason ## {verdict}'}
    result = score({'references': [r.model_dump() for r in task.evaluation.references],
                    'episode': run.results[0].episode.model_dump()},
                   task.evaluation.scorers[0].component.config, model_call=call)
    assert result['metrics'][0]['status'] == status
    assert result['metrics'][0]['value'] == value
