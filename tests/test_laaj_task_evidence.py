import json

import pytest

from evalclaw.diagnostics import write_json
from evalclaw.execution.task_runtime import task_digest
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.quality import laaj
from evalclaw.quality.laaj_tools import inspect_agent_environment, read_task_file
from evalclaw.quality.task_evidence import TaskEvidence, task_data
from evalclaw.types import (AnalysisReport, BenchmarkConfig, EpisodeRecord, EvalRun,
                           ItemResult, QcReport, TaskBlueprint, TaskDesign, TaskType)
from tests.test_laaj import _response, _suite


@pytest.fixture
def evidence(tmp_path):
    suite = _suite()
    suite.spec.constraints = ['PLANNER_CONCLUSION']
    suite.dimensions[0].description = 'PLANNER_DESIGN'
    suite.tasks[0].metadata = {'qc': 'QC_CONCLUSION', 'task_design': 'BUILDER_DESIGN'}
    qc = QcReport(summary='QC_CONCLUSION')
    run = EvalRun(suite=suite, qc_report=qc, results=[ItemResult(
        item_id=item.id, target_id='target', raw_response='TARGET_RESPONSE',
        judge_reasoning='SCORER_REASON', score=0.5,
        episode=EpisodeRecord(task_id=item.id, task_digest=task_digest(item),
                              native_evidence=[f'native/{item.id}/screen.png']),
    ) for item in suite.tasks])
    write_json(tmp_path/'construction.json', {'suite': suite.model_dump(mode='json'), 'qc_report': qc.model_dump()})
    write_json(tmp_path/'run.json', run.model_dump(mode='json'))
    write_json(tmp_path/'qc_report.json', qc.model_dump())
    write_json(tmp_path/'analysis/report.json', {'analysis': 'ANALYSER_CONCLUSION'})
    for item in suite.tasks:
        directory = tmp_path/'runner/target'/item.id
        write_json(directory/'item.json', item.model_dump(mode='json'))
        write_json(directory/'judge.json', {'request': {'body': {'messages': [
            {'role': 'user', 'content': json.dumps({'item': item.model_dump(mode='json'), 'model_response': 'TARGET_RESPONSE'})}
        ]}}, 'response': 'SCORER_REASON'})
        screen = tmp_path/f'native/{item.id}/screen.png'
        screen.parent.mkdir(parents=True)
        screen.write_bytes(b'image')
    return suite, run, tmp_path


def call(view, name, **args):
    return view.dispatch(ToolCall(id='read', name=name, arguments=args))


def read(view, path):
    result = call(view, 'read_run_artifact', path=path)
    assert not result.error, result.content
    return json.loads(json.loads(result.content)['content'])


def test_task_view_excludes_control_plane_and_other_tasks(evidence):
    suite, run, root = evidence
    selected = suite.model_copy(update={'tasks': suite.tasks[:1]})
    view = TaskEvidence(selected, root, run, goal='USER_GOAL')
    construction = read(view, 'construction.json')
    assert construction == {'suite': {'objective': 'USER_GOAL', 'tasks': [task_data(suite.tasks[0])]}}
    result = read(view, 'run.json')
    assert set(result) == {'results'}
    assert [r['item_id'] for r in result['results']] == ['item_1']
    assert result['results'][0]['raw_response'] == 'TARGET_RESPONSE'
    assert result['results'][0]['judge_reasoning'] == 'SCORER_REASON'
    assert read(view, 'runner/target/item_1/item.json') == task_data(suite.tasks[0])
    judge = read(view, 'runner/target/item_1/judge.json')
    request = json.loads(judge['request']['body']['messages'][0]['content'])
    assert request == {'item': task_data(suite.tasks[0]), 'model_response': 'TARGET_RESPONSE'}
    assert judge['response'] == 'SCORER_REASON'
    for path in ('qc_report.json', 'analysis/report.json', 'runner/target/item_2/item.json', '../outside.json'):
        assert call(view, 'read_run_artifact', path=path).error
    assert call(view, 'read_item_evidence', item_id='item_1', target_id='target', kind='qc').error
    assert call(view, 'read_item_evidence', item_id='item_1', target_id='target', scope='probe').error
    item = call(view, 'read_item_evidence', item_id='item_1', target_id='target', kind='all')
    payload = json.loads(item.content)
    assert json.loads(payload['task']) == {'task': task_data(suite.tasks[0])}
    assert payload['judge_reasoning'] == 'SCORER_REASON'
    assert payload['raw_response'] == 'TARGET_RESPONSE'
    files = json.loads(call(view, 'list_run_artifacts').content)['files']
    assert {f['path'] for f in files} == set(view.files) | set(view.virtual)
    assert view.image_allowed('native/item_1/screen.png')
    assert not view.image_allowed('native/item_2/screen.png')
    # Saved evidence remains intact; the restriction is a review view only.
    assert json.loads((root/'construction.json').read_text())['qc_report']['summary'] == 'QC_CONCLUSION'
    assert json.loads((root/'runner/target/item_1/item.json').read_text())['metadata'] == suite.tasks[0].metadata


def test_evidence_symlinks_cannot_expose_control_plane(evidence):
    suite, run, root = evidence
    (root/'runner/target/item_1/alias.json').symlink_to(root/'qc_report.json')
    (root/'native/item_1/alias.json').symlink_to(root/'qc_report.json')
    run.results[0].episode.native_evidence.append('native/item_1/alias.json')
    view = TaskEvidence(suite, root, run)
    for path in ('runner/target/item_1/alias.json', 'native/item_1/alias.json'):
        assert call(view, 'read_run_artifact', path=path).error
        assert not view.image_allowed(path)
    other = root/'run/target'
    other.mkdir(parents=True)
    (other/'item_1').symlink_to(root/'analysis', target_is_directory=True)
    view = TaskEvidence(suite, root, run)
    assert call(view, 'read_run_artifact', path='run/target/item_1/report.json').error


def test_environment_inspection_preserves_scorer_without_task_design(evidence):
    suite, _, _ = evidence
    item = suite.tasks[0]
    item.task_type = TaskType.agent
    item.metadata.update(task_design_id='design', agent_env={
        'type': 'docker_workspace', 'hidden_files': {'score.py': 'assert True'},
        'test_command': 'python score.py'})
    suite.blueprints = [TaskBlueprint(id='builder', title='Builder', task_designs=[
        TaskDesign(id='design', task_type=TaskType.agent, task_count=1,
                   content_design={'description': 'PLANNER_DESIGN'})])]
    result = inspect_agent_environment(ToolCall(id='inspect', name='inspect_agent_environment',
        arguments={'item_ids': [item.id]}), suite)
    contract = json.loads(json.loads(result.content)['content'])[0]
    assert 'task_design' not in contract
    assert contract['environment']['test_command'] == 'python score.py'
    result = read_task_file(ToolCall(id='read', name='read_task_file', arguments={
        'item_id': item.id, 'area': 'hidden', 'path': 'score.py'}), suite)
    assert json.loads(result.content)['content'] == 'assert True'


@pytest.mark.parametrize('field', ['messages', 'input'])
def test_serialized_judge_requests_project_task_without_changing_response(evidence, field):
    suite, run, root = evidence
    view = TaskEvidence(suite, root, run)
    content = json.dumps({'item': suite.tasks[0].model_dump(mode='json')})
    data = {'request': {'body': {field: [{'role': 'user', 'content': [{'type': 'text', 'text': content}]}]}},
            'response': {'content': content}}
    cleaned = view.trace_data(data)
    assert json.loads(cleaned['request']['body'][field][0]['content'][0]['text']) == {'item': task_data(suite.tasks[0])}
    assert cleaned['response'] == data['response']


def test_analysis_metrics_use_a_separate_conversation(evidence, monkeypatch):
    suite, run, root = evidence
    requests = []

    def judge(messages, **kwargs):
        request = json.loads(messages[0]['content'])
        requests.append(request)
        result = json.loads(_response(analyser=True))
        if 'analyser_output' in request:
            result['diversity']['score'] = 1  # Must not replace the task-only verdict.
        text = json.dumps(result)
        return TargetToolModelResponse(adapter='litellm', content=text, tool_calls=[],
            assistant_message={'role': 'assistant', 'content': text}, raw_response={})

    monkeypatch.setattr(laaj, 'call_orchestrator_with_tools', judge)
    result = laaj.evaluate_with_laaj('USER_GOAL', suite, AnalysisReport(analysis='ANALYSER_CONCLUSION'),
        BenchmarkConfig(laaj_model='judge', laaj_api_key='test', laaj_evaluate_analyser=True),
        run=run, qc_report=run.qc_report, artifact_dir=root)
    assert len(requests) == 5
    for request in requests[:-1]:
        assert request['goal'] == 'USER_GOAL'
        assert 'analyser_output' not in request
        text = json.dumps(request)
        for marker in ('PLANNER_CONCLUSION', 'PLANNER_DESIGN', 'QC_CONCLUSION', 'BUILDER_DESIGN', 'ANALYSER_CONCLUSION'):
            assert marker not in text
    assert requests[-1]['analyser_output']['final_analysis'] == 'ANALYSER_CONCLUSION'
    assert requests[-1]['analyser_output']['main_qc']['summary'] == 'QC_CONCLUSION'
    assert result.diversity.score == 3
    assert result.systematicness.score == 4


def test_tool_loop_restricts_artifact_and_image_reads(evidence, monkeypatch):
    suite, run, root = evidence
    calls = [ToolCall(id='qc', name='read_run_artifact', arguments={'path': 'qc_report.json'}),
             ToolCall(id='image', name='view_benchmark_image', arguments={'source': 'run_artifact', 'path': 'analysis/screen.png'}),
             ToolCall(id='task', name='read_item_evidence', arguments={'item_id': 'item_1', 'target_id': 'target', 'kind': 'task'})]
    results = []
    def judge(messages, **kwargs):
        tools = calls if len(messages) == 1 else []
        text = '' if tools else _response()
        return TargetToolModelResponse(adapter='litellm', content=text, tool_calls=tools,
            assistant_message={'role': 'assistant', 'content': text}, raw_response={})
    monkeypatch.setattr(laaj, 'call_orchestrator_with_tools', judge)
    laaj._run_laaj_tool_loop({'goal': 'USER_GOAL'}, suite,
        BenchmarkConfig(laaj_model='judge', laaj_api_key='test'), artifact_dir=root,
        trace_dir=None, trace_name='test', include_agent_tools=True, run=run,
        on_tool_result=lambda call, result: results.append(result))
    assert results[0].error and results[1].error
    assert not results[2].error
    assert json.loads(json.loads(results[2].content)['task']) == {'task': task_data(suite.tasks[0])}
