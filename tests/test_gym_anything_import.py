import base64
import csv
import json

import pytest

from evalclaw.sources import gym_anything as gym
from evalclaw.execution.task_runtime import task_digest
from evalclaw.protocols.tool import ToolCall
from evalclaw.quality.laaj_tools import read_task_file
from evalclaw.types import TaskSuite


@pytest.fixture
def native(tmp_path):
    local = tmp_path/'gym/local'
    generation = local/'generation'
    source = generation/'desktop'
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value))
    for name in gym.RUNTIME_FILES:
        write(local.parent/name, '# native runtime\n')
    write(generation/'batch.json', {'jobs': [[1, 'Desktop', 'desktop', 'docker']]})
    write(generation/'user-inputs.txt', 'Evaluate project continuity.\n')
    write(source/'env.json', {'id': 'desktop@1'})
    write(source/'data/shared.txt', 'Shared fixture')
    jobs, entries, rows = [], {}, []
    for index in range(1, 4):
        key = f'{index:03d}'
        task_name = 'task'+key
        root = source/'tasks'/task_name
        write(root/'task.json', {'id': task_name+'@1', 'env_id': 'desktop@1', 'description': 'Continue '+key,
                               'success': {'mode': 'program', 'spec': {'program': 'verifier.py::verify'}}})
        write(root/'verifier.py', 'def verify(): return {"score": 75, "passed": False}\n')
        hashes = {name: gym.sha256(root/name) for name in ('task.json', 'verifier.py')}
        job = local/'accepted'/key
        config = {'env': 'desktop', 'task': task_name, 'model': 'deepseek-flash', 'runner': 'docker',
                  'max_steps': 200, 'cli_timeout_sec': 1000, 'episode_timeout_sec': 2000,
                  'task_sha256': hashes['task.json'], 'verifier_sha256': hashes['verifier.py']}
        write(job/'config.json', config)
        grade = {'score': 75, 'passed': False, 'feedback': 'Partial'} if index != 3 else None
        result = {'env': 'desktop', 'task': task_name, 'verifier': grade,
                  'summary': str(job/'episode/summary.json') if index != 3 else None}
        write(job/'result.json', result)
        status = ['accepted', 'accepted_generated_setup_failure', 'accepted_framework_bug_failure'][index-1]
        entries[key] = {'env': 'desktop', 'task': task_name, 'accepted_result': str(job/'result.json'),
                        'required_attempt': str(job), 'status': status}
        jobs.append({'id': key, 'env': 'desktop', 'task': task_name, 'source': str(source), 'hashes': hashes})
        rows.append({'id': key, 'result_path': str(job/'result.json'), 'result_sha256': gym.sha256(job/'result.json')})
        if index == 3:
            continue
        write(job/'episode/summary.json', {'verifier': grade})
        write(job/'episode/trajectory.json', {'model': 'deepseek-flash', 'task': 'Continue '+key,
                                              'steps': [{'step': 1, 'command': '{"action":"screenshot"}'}]})
        write(job/'episode/cli_harness/prompt.txt', 'Use act only. Continue '+key)
        write(job/'episode/traj.jsonl', '{"event":"reset"}\n')
        image = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                            'data': base64.b64encode(b'fixture-image').decode()}}
        for attempt in (0, 1):
            stream = [{'type': 'user', 'message': {'content': [image]}},
                      {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'sk-testsecret'}]}},
                      {'type': 'result', 'result': f'Final attempt {attempt}'}]
            write(job/f'episode/cli_harness/api_attempt_{attempt}.jsonl', '\n'.join(map(json.dumps, stream))+'\n')
        write(job/'episode/cli_harness/home/private', 'PRIVATE_CONFIG')
        write(local/'newer'/key/'result.json', {**result, 'verifier': {'score': 100, 'passed': True}})
    write(local/'evaluation_results.json', {'dataset': 'local-test', 'source': str(generation), 'tasks': entries})
    write(local/'outputs/eval114_rerun_0920/config.json', {'jobs': jobs})
    write(local/'outputs/deepseek_final/summary.json', {'ledger_sha256': gym.sha256(local/'evaluation_results.json')})
    with (local/'outputs/deepseek_final/results.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    return local, tmp_path/'converted'


def test_preserves_adopted_attempts_grades_visibility_and_failures(native):
    suite, run, manifest = gym.convert_requirement(native[0], 1, native[1])
    assert [r.score for r in run.results] == [.75, .75, 0]
    assert [r.error is None for r in run.results] == [True, False, False]
    assert run.results[0].episode.metrics[1].value is False
    assert run.results[2].episode.metrics[0].status == 'error'
    assert run.results[2].episode.metrics[0].value is None
    assert run.results[0].raw_response == 'Final attempt 1'
    assert manifest['items'][0]['cli_records'] == {'api_attempt_0.jsonl': 3, 'api_attempt_1.jsonl': 3}
    task = suite.tasks[0]
    assert task.interaction.budget.tool_calls is None
    assert task.environment.service.status == 'not_provided'
    assert task.content.messages[0].content == 'Use act only. Continue 001'
    assert run.results[0].episode.task_digest == task_digest(task)
    assert all(a.visibility == ['reviewer'] for a in task.assets)
    paths = {a.id: a.path for a in task.assets}
    assert 'environment/data/shared.txt' in paths
    assert 'environment/tasks/task002/task.json' not in paths
    assert len(list((native[1]/'native'/task.id/'cli-images').iterdir())) == 1
    assert TaskSuite.model_validate_json(suite.model_dump_json()) == suite
    read = read_task_file(ToolCall(id='r', name='read_task_file', arguments={
        'item_id': task.id, 'area': 'asset', 'path': 'api_attempt_0.jsonl', 'max_chars': 10000}), suite)
    assert not read.error
    records = [json.loads(line) for line in json.loads(read.content)['content'].splitlines()]
    assert records[1]['message']['content'][0]['text'] == '[REDACTED]'
    assert records[0]['message']['content'][0]['source']['original_encoding'] == 'base64'
    assert (native[1]/records[0]['message']['content'][0]['source']['path']).read_bytes() == b'fixture-image'
    assert not any('PRIVATE_CONFIG' in p.read_text(errors='ignore') for p in native[1].rglob('*') if p.is_file())


def test_rejects_changed_accepted_result(native):
    path = native[0]/'accepted/001/result.json'
    value = gym.load(path); value['verifier']['score'] = 100; path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Accepted attempt mismatch'):
        gym.convert_requirement(native[0], 1, native[1])


def test_rejects_changed_task_definition(native):
    path = native[0]/'generation/desktop/tasks/task001/verifier.py'
    path.write_text('def verify(): return 100')
    with pytest.raises(ValueError, match='Generated task changed'):
        gym.convert_requirement(native[0], 1, native[1])


def test_fifth_software_group_uses_main_requirement_six(native):
    generation = native[0]/'generation'
    (generation/'batch.json').write_text(json.dumps({'jobs': [[5, 'Desktop', 'desktop', 'docker']]}))
    (generation/'user-inputs.txt').write_text('\n'.join(['Unrelated']*5+['Evaluate economical strategies.']))
    suite, _, _ = gym.convert_requirement(native[0], 6, native[1])
    assert suite.objective == 'Evaluate economical strategies.'
    assert {t.dimension_id for t in suite.tasks} == {'D6'}


def test_cli_image_metadata_and_message_share_one_attachment(tmp_path):
    data = base64.b64encode(b'image-bytes').decode()
    row = {'message': {'type': 'base64', 'media_type': 'image/png', 'data': data},
           'tool_use_result': {'type': 'image/png', 'base64': data, 'dimensions': {'originalWidth': 1280}}}
    converted = gym.extract_images(row, tmp_path)
    assert converted['message']['path'] == converted['tool_use_result']['path']
    assert converted['tool_use_result']['dimensions'] == {'originalWidth': 1280}
    assert len(list((tmp_path/'cli-images').iterdir())) == 1
