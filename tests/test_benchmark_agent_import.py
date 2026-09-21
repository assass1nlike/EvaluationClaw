import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

from evalclaw.sources.benchmark_agent import convert_requirement, native_helpers
from evalclaw.sources.benchmark_agent_scorer import score
from evalclaw.types import TaskSuite

UPSTREAM = Path(__file__).resolve().parents[1] / 'baselines/Benchmark-Agent'


@pytest.fixture
def native(tmp_path, monkeypatch):
    constants = {n.targets[0].id: ast.literal_eval(n.value)
                 for n in ast.parse((UPSTREAM/'local/self_evaluate.py').read_text()).body
                 if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                 and n.targets[0].id in {'ANSWER_SYSTEM', 'CHOICE_SYSTEM', 'JUDGE_SYSTEM'}}
    tasks = []
    for index, (answer_type, answer, prediction, method) in enumerate([
        ('choice', 'A', ' A ', 'exact_choice'),
        ('choice', 'yes', 'Yes', 'model_judge'),
        ('span', '2', 'two', 'model_judge'),
    ]):
        inputs = {'context': ['Keep structured content', {'number': 2}], 'question': f'Question {index}? A) first B) second'}
        reference = {'answer': answer}
        original = {'subtask_id': str(index), 'dataset_id': 'source', 'idx': 11+index,
                    'sample': {'input': inputs, 'output': reference}}
        result = {'index': index, 'subtask_id': str(index), 'dataset_id': 'source', 'source_idx': 11+index,
                  'reference': reference, 'prediction': prediction, 'correct': True, 'status': 'scored',
                  'finish_reason': 'stop', 'method': method}
        if method == 'model_judge':
            result.update(judge_raw='```json\n{"correct": true, "reason": "Equivalent"}\n```', judge_reason='Equivalent')
        tasks.append({'id': f'benchmark-agent/test/{index:04d}', 'task': 'test', 'question_index': index,
            'requirement': 'Test the original task', 'subtask_id': str(index), 'subtask_name': f'Task {index}',
            'answer_type': answer_type, 'dataset_id': 'source', 'input_json': json.dumps(inputs,ensure_ascii=False),
            'reference_output_json': json.dumps(reference), 'original_question_json': json.dumps(original),
            'model_answer': prediction, 'correct': True, 'scoring_method': method,
            'original_selftest_json': json.dumps(result)})
    provenance = {'requirement': 'Test the original task',
        'selftest_config': {'model': 'openai/deepseek-flash', 'seed': 42,
            'answer_system': constants['ANSWER_SYSTEM'], 'choice_system': constants['CHOICE_SYSTEM'],
            'judge_system': constants['JUDGE_SYSTEM']},
        'subtasks': [{'id': t['subtask_id'], 'name': t['subtask_name'], 'description': 'Original subtask',
                      'answer_type': t['answer_type']} for t in tasks],
        'summary': {'exported_items': 3, 'correct': 3}}
    (tmp_path/'data').mkdir(); (tmp_path/'provenance').mkdir()
    (tmp_path/'data/test.jsonl').write_text('\n'.join(map(json.dumps,tasks)))
    (tmp_path/'provenance/test.json').write_text(json.dumps(provenance))
    def refresh_manifest():
        files = {f'benchmark-agent/{p.relative_to(tmp_path)}': hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in [tmp_path/'data/test.jsonl', tmp_path/'provenance/test.json']}
        (tmp_path/'provenance/manifest.json').write_text(json.dumps({'files_sha256': files}))
    refresh_manifest()
    module = types.ModuleType('native')
    exec(native_helpers(UPSTREAM), module.__dict__)
    monkeypatch.setitem(sys.modules,'native',module)
    return tmp_path, refresh_manifest


def convert(native):
    return convert_requirement(native[0], 'test', upstream=UPSTREAM, revision='fixed-revision')


def test_preserves_inputs_fallback_grading_and_evidence(native):
    suite, run, records, manifest = convert(native)
    for task, result, record in zip(suite.tasks,run.results,records):
        assert task.content.messages[1].content == record['exported']['input_json']
        assert result.raw_response == record['selftest']['prediction']
        assert task.evaluation.references[0].value == record['question']['sample']['output']
        assert task.challenge_effort is None and not result.episode.events
        assert result.episode.native_evidence
    assert suite.tasks[0].evaluation.scorers[0].component.config['method']=='exact_choice'
    assert suite.tasks[1].task_type.value=='choice'
    assert suite.tasks[1].evaluation.scorers[0].component.config['method']=='model_judge'
    assert TaskSuite.model_validate_json(suite.model_dump_json()) == suite
    assert manifest['revision']=='fixed-revision'
    assert [t.value for t in suite.spec.task_types]==['choice','generation']


@pytest.mark.parametrize('tamper', ['checksum', 'alignment', 'score'])
def test_refuses_corrupted_or_misaligned_records(native, tamper):
    path=native[0]/'data/test.jsonl';rows=[json.loads(s) for s in path.read_text().splitlines()]
    if tamper=='score':
        r=json.loads(rows[0]['original_selftest_json']);r['correct']=False
        rows[0]['correct']=False;rows[0]['original_selftest_json']=json.dumps(r)
    else:
        rows[0]['model_answer']='B'
    path.write_text('\n'.join(map(json.dumps,rows)))
    if tamper!='checksum': native[1]()
    with pytest.raises(ValueError): convert(native)


@pytest.mark.parametrize('answer,value',[('A',1),(' A\n',1),('a',0),('A because ...',0),('',0),('B',0)])
def test_choice_contract_is_not_silently_relaxed(native, answer, value):
    suite,run,_,_=convert(native);task=suite.tasks[0]
    episode=run.results[0].episode.model_dump();episode['outputs']=[answer]
    result=score({'episode':episode,'references':[r.model_dump() for r in task.evaluation.references]},task.evaluation.scorers[0].component.config)
    assert result['metrics'][0]['value']==value


@pytest.mark.parametrize('raw,finish,status,value',[
    ('{"correct": true,"reason":"same"}', 'stop','valid',1),
    ('```json\n{"correct": false,"reason":"wrong"}\n```','stop','valid',0),
    ('{"correct":"true"}','stop','error',None),
    ('{"correct":true}','length','error',None),
    ('not JSON','stop','error',None),
])
def test_native_model_judge_protocol(native,raw,finish,status,value):
    suite,run,records,_=convert(native);task=suite.tasks[1]
    def call(role,messages):
        assert role=='judge'
        assert json.loads(messages[1]['content']) == {
            'task_input':records[1]['question']['sample']['input'],
            'reference_output':records[1]['question']['sample']['output'], 'candidate_response':'Yes'}
        return {'content':raw,'raw':{'choices':[{'finish_reason':finish}]}}
    result=score({'episode':run.results[1].episode.model_dump(),
                  'references':[r.model_dump() for r in task.evaluation.references]},
                 task.evaluation.scorers[0].component.config,call)
    assert result['metrics'][0]['value']==value and result['metrics'][0]['status']==status


def test_component_protocol_version(native,tmp_path):
    suite,_,_,_=convert(native)
    spec=suite.tasks[0].evaluation.scorers[0].component
    for path,content in spec.files.items(): (tmp_path/path).write_text(content)
    result=subprocess.run([sys.executable,'score.py'],cwd=tmp_path,text=True,capture_output=True,
        input=json.dumps({'id':1,'method':'describe'})+'\n',check=True,timeout=10)
    assert json.loads(result.stdout)['result']=={'version':spec.version,'methods':['score']}
