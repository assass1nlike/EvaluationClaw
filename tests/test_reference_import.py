import base64
import copy
import json
import os
import pickle
import zlib
from pathlib import Path

import pytest

from evalclaw.quality.task_evidence import TaskEvidence
from evalclaw.sources.reference_common import NativeSource, digest, read_rows
from evalclaw.sources.reference_helm import helm_requests
from evalclaw.sources.reference_livebench import decode_tests, livebench, select_release
from evalclaw.sources.reference_text import ifbench, mmlu_pro
from evalclaw.types import TaskSuite


@pytest.fixture
def source(tmp_path):
    root = tmp_path/'upstream'
    root.mkdir()
    (root/'native.py').write_text('def score(answer): return answer == "gold"\n')
    return NativeSource(root, tmp_path/'converted', repo='test/source', revision='test-revision', dataset={'split': 'test'})


def test_review_assets_and_reference_do_not_become_target_context(source):
    task = source.task('sample', 'g', [{'role': 'user', 'content': 'Solve this'}],
        references=[{'id': 'answer', 'kind': 'answer', 'value': 'gold'}],
        source_files=['native.py'], config={})
    suite = source.save([task], 'goal', selection={'seed': 42})
    loaded = TaskSuite.model_validate_json((source.output/'suite.json').read_text())
    assert loaded == suite
    assert task.content.messages[0].content == 'Solve this'
    assert task.evaluation.references[0].value == 'gold'
    assert task.assets[0].visibility == ['reviewer']
    assert task.assets[0].sha256 == digest(source.root/'native.py')
    view = TaskEvidence(suite, source.output)
    assert view.results == []
    assert view.files['native/source/native.py'].read_text() == (source.root/'native.py').read_text()
    assert task.evaluation.scalar is None
    assert task.evaluation.scorers[0].component.status == 'not_provided'


def test_native_asset_hash_mismatch_fails(source):
    source.assets(['native.py'])
    (source.output/'native/source/native.py').write_text('modified')
    second = NativeSource(source.root, source.output, **{
        'repo': 'test/source', 'revision': 'test-revision', 'dataset': {'split': 'test'}})
    with pytest.raises(ValueError, match='changed'):
        second.assets(['native.py'])


def test_encoded_tests_are_decoded_without_executing_pickle_objects():
    tests = [{'input': '1', 'output': '2', 'testtype': 'stdin'}]
    encoded = base64.b64encode(zlib.compress(pickle.dumps(json.dumps(tests)))).decode()
    assert decode_tests(encoded) == tests
    assert decode_tests(json.dumps(tests)) == tests
    malicious = base64.b64encode(zlib.compress(b'cbuiltins\neval\n.')).decode()
    with pytest.raises(ValueError, match='Executable'):
        decode_tests(malicious)


def test_livebench_release_and_removal_boundary(source):
    (source.root/'livebench').mkdir()
    (source.root/'livebench/common.py').write_text("LIVE_BENCH_RELEASES = {'2024-06-24', '2024-11-25'}\n")
    rows = [{'question_id': i, 'livebench_release_date': added, 'livebench_removal_date': removed}
            for i, added, removed in [('keep', '2024-06-24', ''), ('new', '2024-11-25', ''),
                                      ('removed', '2024-06-24', '2024-11-25')]]
    assert [r['question_id'] for r in select_release(rows, source, '2024-11-25')] == ['keep', 'new']
    assert [r['question_id'] for r in select_release(rows, source, '2024-06-24')] == ['keep', 'removed']
    with pytest.raises(ValueError, match='Unknown'):
        select_release(rows, source, '2099-01-01')


@pytest.fixture
def helm_state():
    spec = {'name': 'mrcr', 'adapter_spec': {'method': 'chat'},
            'scenario_spec': {'class_name': 'helm.benchmark.scenarios.openai_mrcr_scenario.OpenAIMRCRScenario'},
            'metric_specs': [{'class_name': 'helm.benchmark.metrics.openai_mrcr_metrics.OpenAIMRCRMetric'}]}
    row = {'instance': {'id': 'needle', 'references': [{'output': {'text': 'gold'}, 'tags': ['correct']}],
                        'extra_data': {'random_string_to_prepend': 'prefix'}},
           'train_trial_index': 0, 'prompt_truncated': False, 'num_train_instances': 0,
           'request': {'messages': [{'role': 'user', 'content': 'Remember'},
                                     {'role': 'assistant', 'content': 'seeded answer'},
                                     {'role': 'user', 'content': 'Recall'}], 'prompt': ''},
           'result': {'completion': 'ACTUAL_PUBLIC_MODEL_RESULT'}}
    return spec, {'adapter_spec': spec['adapter_spec'], 'request_states': [row]}


def test_helm_history_is_input_and_public_model_result_is_not_imported(source, helm_state):
    spec, state = helm_state
    source.assets = lambda paths: []
    task = helm_requests(state, spec, source)[0]
    assert [m.origin for m in task.content.messages] == ['task', 'seeded_context', 'task']
    assert task.evaluation.references[0].value == ['gold']
    assert task.evaluation.scorers[0].component.config['extra_data'] == {'random_string_to_prepend': 'prefix'}
    assert 'ACTUAL_PUBLIC_MODEL_RESULT' not in task.model_dump_json()


@pytest.mark.parametrize('change', ['truncated', 'calibration', 'duplicate', 'likelihood', 'adapter_mismatch'])
def test_helm_rejects_ambiguous_or_incomplete_import(source, helm_state, change):
    spec, state = copy.deepcopy(helm_state)
    source.assets = lambda paths: []
    row = state['request_states'][0]
    if change == 'truncated':
        row['prompt_truncated'] = True
    elif change == 'calibration':
        row['request_mode'] = 'calibration'
    elif change == 'duplicate':
        state['request_states'].append(copy.deepcopy(row))
    elif change == 'likelihood':
        spec['adapter_spec']['method'] = 'multiple_choice_separate'
    else:
        state['adapter_spec'] = {'method': 'generation'}
    with pytest.raises(ValueError):
        helm_requests(state, spec, source)


@pytest.fixture
def official():
    value = os.environ.get('REFERENCE_VALIDATION_ROOT')
    if not value:
        pytest.skip('Set REFERENCE_VALIDATION_ROOT to the frozen official-data validation directory')
    return Path(value).resolve()


def test_official_mmlu_fewshot_and_option_alignment(official, tmp_path):
    root = official/'upstream/mmlu-pro'
    source = NativeSource(root, tmp_path, repo='TIGER-AI-Lab/MMLU-Pro', revision='integration', dataset={'split': 'test'})
    rows = read_rows(official/'data/mmlu-pro/test-00000-of-00001.parquet')[:2]
    examples = read_rows(official/'data/mmlu-pro/validation-00000-of-00001.parquet')
    tasks = mmlu_pro(rows, examples, source)
    for row, task in zip(rows, tasks, strict=True):
        assert task.evaluation.references[0].value == row['answer']
        prompt = task.content.messages[0].content
        assert row['question'] in prompt
        for example in examples:
            if example['category'] == row['category']:
                assert example['question'] in prompt
        for i, option in enumerate(o for o in row['options'] if o != 'N/A'):
            assert f'{chr(65+i)}. {option}' in prompt


def test_official_ifbench_retains_native_order_and_all_constraints(official, tmp_path):
    source = NativeSource(official/'upstream/ifbench', tmp_path, repo='allenai/IFBench', revision='integration', dataset={'split': 'test'})
    rows = read_rows(source.root/'data/IFBench_test.jsonl')[:2]
    tasks = ifbench(rows, source)
    for row, task in zip(rows, tasks, strict=True):
        assert task.content.messages[0].content == row['prompt']
        assert task.evaluation.references[0].value == {'instruction_id_list': row['instruction_id_list'], 'kwargs': row['kwargs']}
        assert len(task.evaluation.metrics) == 4
        assert task.evaluation.scorers[0].component.config['entrypoint'] == 'run_eval.main'
        assert 'run_eval.py' in {a.id for a in task.assets}


@pytest.mark.parametrize('category', ['reasoning', 'coding', 'data'])
def test_official_livebench_prompt_and_grading_evidence(official, tmp_path, category):
    source = NativeSource(official/'upstream/livebench', tmp_path, repo='LiveBench/LiveBench', revision='integration', dataset={'split': 'test'})
    rows = read_rows(official/f'data/livebench-{category}/test-00000-of-00001.parquet')[:2]
    tasks = livebench(rows, source, release='2024-11-25')
    assert len(tasks) == 2
    for row, task in zip(rows, tasks, strict=True):
        assert task.content.messages[-1].content == row['turns'][0]
        if category == 'coding':
            assert task.evaluation.references[0].kind == 'tests'
            assert task.evaluation.references[0].value['private'] == decode_tests(row['private_test_cases'])
        else:
            assert task.evaluation.references[0].value == row['ground_truth']
        assert all(Path(a.path).is_file() and a.sha256 == digest(a.path) for a in task.assets)


def test_agentic_schema_preserves_repository_scaffold_and_hidden_tests(official, tmp_path):
    source = NativeSource(official/'upstream/livebench', tmp_path, repo='LiveBench/LiveBench', revision='integration', dataset={'kind': 'synthetic contract test'})
    row = {'question_id': 'schema-test', 'category': 'agentic_coding', 'task': 'python',
           'livebench_release_date': '2025-04-25', 'livebench_removal_date': '',
           'turns': ['Repair the repository'], 'org': 'example', 'repo': 'project', 'number': 1,
           'state': 'closed', 'title': 'Repair', 'body': 'Repair the repository',
           'base': {'label': 'main', 'ref': 'main', 'sha': 'pinned-base-revision'},
           'resolved_issues': [], 'fix_patch': 'PRIVATE_REFERENCE_PATCH', 'test_patch': 'PRIVATE_TEST_PATCH'}
    scaffold = 'livebench/agentic_code_runner/minisweagent/config/livebench.yaml'
    task = livebench([row], source, release='2025-04-25', scaffold=scaffold)[0]
    assert task.task_type.value == 'agent'
    assert task.interaction.protocol == 'program'
    assert task.environment.type == 'tool_service'
    assert task.interaction.controller.status == 'not_provided'
    assert task.evaluation.references[0].value['base']['sha'] == row['base']['sha']
    assert task.evaluation.references[0].value['test_patch'] == 'PRIVATE_TEST_PATCH'
    assert 'PRIVATE_TEST_PATCH' not in task.content.model_dump_json()
    assert 'PRIVATE_REFERENCE_PATCH' not in task.content.model_dump_json()
    assert task.content.messages[0].role == 'system'
    assert row['turns'][0] in task.content.messages[1].content
    incomplete = {k: v for k, v in row.items() if k != 'test_patch'}
    with pytest.raises(ValueError, match='full native'):
        livebench([incomplete], source, release='2025-04-25', scaffold=scaffold)
    with pytest.raises(ValueError, match='explicit native scaffold'):
        livebench([row], source, release='2025-04-25')


@pytest.mark.parametrize('family', ['ruler_squad', 'infinite_bench_en_mc', 'openai_mrcr'])
def test_official_helm_preserves_entire_rendered_request(official, tmp_path, family):
    folder = official/f'data/helm-{family}'
    source = NativeSource(official/'upstream/helm', tmp_path, repo='stanford-crfm/helm', revision='integration', dataset={'family': family})
    state = json.loads((folder/'scenario_state.json').read_text())
    spec = json.loads((folder/'run_spec.json').read_text())
    tasks = helm_requests(state, spec, source)
    for row, task in zip(state['request_states'], tasks, strict=True):
        expected = row['request'].get('messages') or [{'role': 'user', 'content': row['request']['prompt']}]
        assert [{'role': m.role, 'content': m.content} for m in task.content.messages] == expected
        assert task.evaluation.scorers[0].component.config['output_mapping'] == row.get('output_mapping')
        assert 'result' not in task.evaluation.scorers[0].component.config
    suite = source.save(tasks, 'long context', selection={'seed': 42})
    assert TaskEvidence(suite, tmp_path).results == []
