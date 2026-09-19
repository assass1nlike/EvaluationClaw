"""Behavioral regressions from task validity review; no live model calls."""
import json
import os
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from evalclaw.execution.harness_evidence import cli_result, normalize_events
from evalclaw.runners import harness
from evalclaw.types import AgentEnvironmentType, AgentWorkflow, BenchmarkConfig, BenchmarkItem, TargetModelConfig, TaskType


def item():
    return BenchmarkItem(id="validity", dimension_id="d", task_type=TaskType.agent,
        prompt="Do the work.", metadata={"agent_env": {
            "type": "docker_workspace", "image": "python:3.11", "auto_select_image": False,
            "timeout": 30, "max_steps": 10, "network": "none",
            "hidden_files": {"grade.py": "import json; from pathlib import Path; print(json.dumps({'score': float(Path('answer').exists())}))"},
            "test_command": "python3 grade.py", "evaluation": {"result_format": "json_on_stdout"},
        }})


def test_cli_errors_are_structural_not_text_matches():
    assert cli_result("openclaw", 'No change\n{"ok":false,"final":"","error":{"message":"cleanup failed"}}')["status"] == "failed"
    assert cli_result("openclaw", '{"ok":true,"final":"The file contains an error message."}')["status"] == "completed"
    assert cli_result("openclaw", "The user wrote: error")['status'] == 'unavailable'
    assert cli_result("openclaw", "Configuration logs, no final envelope")['final_response'] == ''
    assert cli_result("codex", '{"type":"turn.failed","error":{"message":"x"}}')["status"] == "failed"
    assert cli_result("claude-code", '{"type":"result","is_error":true}')["status"] == "failed"


def test_gateway_transcript_deduplicates_calls_without_counting_mentions():
    messages = [{"role": "assistant", "content": "I will not run sudo",
                 "tool_calls": [{"id": "a", "function": {"name": "shell", "arguments": '{"command":"pwd"}'}}]},
                {"role": "tool", "tool_call_id": "a", "content": "/workspace"}]
    events = [{"kind": "request", "payload": {"messages": messages}}] * 2
    result = normalize_events(events, "openclaw", '{"ok":true,"final":"done","toolSummary":{"calls":1}}')
    assert len(result['trace']) == 1
    assert result['trace'][0]['tool_call']['arguments'] == {'command': 'pwd'}
    assert result['trace'][0]['observation'] == '/workspace'
    assert result['final_response'] == 'done'
    assert result['tool_call_count'] == 1
    assert len(result['history']) == 2


def test_anthropic_and_responses_tool_evidence():
    events = [{"kind": "request", "payload": {"messages": [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "read", "input": {"path": "x"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "value"}]},
    ]}}, {"kind": "request", "payload": {"input": [
        {"type": "function_call", "call_id": "b", "name": "exec", "arguments": '{}'},
        {"type": "function_call_output", "call_id": "b", "output": "ok"},
    ]}}]
    result = normalize_events(events, "other", "done")
    assert [t['observation'] for t in result['trace']] == ['value', 'ok']
    assert result['tool_call_count'] is None
    assert result['observed_tool_call_count'] == 2


def test_provider_proposals_do_not_duplicate_harness_execution_ids():
    response = {'choices': [{'message': {'role': 'assistant', 'tool_calls': [
        {'id': 'call-1', 'function': {'name': 'exec', 'arguments': '{}'}}]}}]}
    request = {'messages': [
        {'role': 'assistant', 'tool_calls': [{'id': 'call1', 'function': {'name': 'exec', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'call1', 'content': 'done'},
    ]}
    evidence = normalize_events([{'kind': 'response', 'body': json.dumps(response)},
                                 {'kind': 'request', 'payload': request}], 'other', '')
    assert len(evidence['trace']) == 1
    assert evidence['trace'][0]['result_observed']
    assert evidence['model_responses'][0]['messages'][0]['tool_calls'][0]['id'] == 'call-1'


def test_interrupted_stream_retains_received_content():
    chunk = 'data: ' + json.dumps({'choices': [{'delta': {'content': 'partial response'}}]}) + '\n\n'
    events = [
        {'kind': 'request', 'id': 'r', 'payload': {'messages': [{'role': 'user', 'content': 'Work.'}]}},
        {'kind': 'response_start', 'id': 'r', 'status': 200},
        {'kind': 'response_chunk', 'id': 'r', 'body': chunk[:30]},
        {'kind': 'response_chunk', 'id': 'r', 'body': chunk[30:]},
    ]
    evidence = normalize_events(events, 'openclaw', '')
    assert not evidence['model_responses'][0]['complete']
    assert evidence['model_responses'][0]['messages'][0]['content'] == 'partial response'
    assert len(evidence['model_requests']) == 1


def test_workflow_delivers_only_current_stage_and_resets_session(monkeypatch):
    task = item()
    task.workflow = AgentWorkflow(stages=[
        {"id": "work", "kind": "agent", "prompt": "first", "context": "fresh"},
        {"id": "account", "kind": "agent", "prompt": "surprise", "context": "continue", "environment": "reuse"},
        {"id": "resume", "kind": "agent", "prompt": "continue work", "context": "fresh", "environment": "reuse"},
        {"id": "grade", "kind": "evaluate", "environment": "reuse"},
    ], score_stage="grade")
    calls = []
    def run(command, **kwargs):
        calls.append(shlex.split(command[-1].split('; ')[-1]))
        return subprocess.CompletedProcess(command, 0, '{"ok":true,"final":"completed"}', '')
    monkeypatch.setattr(harness, '_run_bounded', run)
    runner = harness.ManifestHarnessRunner(harness.ManifestHarness(
        name='openclaw', run='agent {task}', session_run='agent --session {session_id} --message {task}', model_env={}))
    capture = {}
    runner._workflow_turns(task, {}, {}, '', capture, 'docker', 'container', {}, 30)
    assert calls[0][-1].endswith('first') and 'surprise' not in calls[0][-1]
    assert calls[1][-1].endswith('surprise')
    assert calls[0][2] == calls[1][2] != calls[2][2]
    assert len(capture['stages']) == 3


def test_verification_cases_use_fresh_instances_and_close(monkeypatch):
    from evalclaw.construction.verification import verify_agent_cases
    from evalclaw.quality import laaj_exploration
    made = []
    class Trial:
        def __init__(self, *args):
            self.solved = False
            self.closed = False
            made.append(self)
        def perform(self, args):
            if args['operation'] == 'command':
                self.solved = True
                return {'returncode': 0}
            return {'score': float(self.solved)}
        def close(self):
            self.closed = True
    monkeypatch.setattr(laaj_exploration, 'TaskExperiment', Trial)
    task = item()
    task.metadata['agent_env']['verification_cases'] = [
        {'id': 'reference', 'commands': ['solve'], 'min_score': 1, 'max_score': 1},
        {'id': 'empty', 'commands': [], 'min_score': 0, 'max_score': 0},
    ]
    results = verify_agent_cases(task, BenchmarkConfig())
    assert [r['score'] for r in results] == [1, 0]
    assert len(made) == 2 and all(x.closed for x in made)
    assert results[0]['task_sha256'] == results[1]['task_sha256']


def test_packaged_files_cannot_change_silently():
    from evalclaw.construction.packaging import pack_task_item
    from evalclaw.execution.evidence import validate_environment_files
    from evalclaw.types import TaskDefinition, EvalDimension

    task = TaskDefinition(id='t', dimension_id='d', title='Task', task_type='agent',
        prompt='Do the work.', environment=item().metadata['agent_env'])
    packed = pack_task_item(task, EvalDimension(id='d', name='Test', description='Test', approach='Test'), resource_by_id={})
    validate_environment_files(packed)
    packed.metadata['agent_env']['hidden_files']['grade.py'] += '\nraise ValueError("changed")'
    with pytest.raises(ValueError, match='changed after construction'):
        validate_environment_files(packed)


def test_budget_validation_is_target_aware_and_packaging_is_not_a_native_target():
    from evalclaw.construction.validation import task_structure_issues, _has_environment_evaluator
    from evalclaw.types import TaskDefinition

    task = TaskDefinition(id='t', dimension_id='d', title='Task', task_type='agent',
        prompt='Do the work.', environment={**item().metadata['agent_env'], 'budget': {'wall_time_seconds': 5}})
    assert _has_environment_evaluator(task)
    assert task_structure_issues(task, target_harnesses=[]) != task_structure_issues(task)
    assert task_structure_issues(task, target_harnesses=(h for h in ['openclaw'])) == task_structure_issues(task)


def test_evidence_separates_reused_tool_ids_across_fresh_sessions():
    stages = [{'session_id': 's1', 'started_at': 1}, {'session_id': 's2', 'started_at': 2}]
    events = [{'kind': 'request', 'time': when, 'payload': {'messages': [
        {'role': 'assistant', 'tool_calls': [{'id': '1', 'function': {'name': 'exec', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': '1', 'content': result},
    ]}} for when, result in [(1.5, 'one'), (2.5, 'two')]]
    evidence = normalize_events(events, 'openclaw', '{"ok":true,"final":"done","toolSummary":{"calls":1}}', stages=stages)
    assert [step['observation'] for step in evidence['trace']] == ['one', 'two']
    assert evidence['tool_call_count'] is None


def test_external_workflow_rejects_unimplemented_stage_contracts():
    from evalclaw.execution.harness_compatibility import external_workflow_issues
    workflow = AgentWorkflow(stages=[
        {'id': 'work', 'kind': 'agent', 'prompt': 'Work.'},
        {'id': 'grade', 'kind': 'evaluate', 'environment': 'reuse'},
    ], score_stage='grade')
    assert external_workflow_issues(workflow, ['openclaw']) == []
    workflow.stages[0].max_steps = 3
    assert external_workflow_issues(workflow, ['openclaw'])


@pytest.mark.skipif(os.environ.get('EVALCLAW_DOCKER_TESTS') != '1', reason='requires Docker')
def test_real_builder_verification_tool_and_final_preflight_recheck(tmp_path, monkeypatch):
    from evalclaw.construction.research import _execute_task_builder_tool
    from evalclaw.construction.suite import _preflight_builder_environments
    from evalclaw.construction.parsing import _task_from_raw
    from evalclaw.protocols.tool import ToolCall
    from evalclaw.types import EvalDimension
    from tests.blueprint_factory import make_blueprint

    runner = harness.ManifestHarnessRunner(harness.ManifestHarness(name='fixture', run='true', model_env={}))
    monkeypatch.setattr(harness, 'get_harness', lambda _: runner)
    target = TargetModelConfig(id='t', provider='openai', model='test', harness='openclaw')
    config = BenchmarkConfig(targets=[target], environment_preflight=True)
    env = item().metadata['agent_env']
    env['verification_cases'] = [
        {'id': 'reference', 'commands': ['touch answer'], 'min_score': 1, 'max_score': 1},
        {'id': 'empty', 'min_score': 0, 'max_score': 0},
    ]
    candidate = {'task_type': 'agent', 'title': 'Test', 'prompt': 'Do the work.', 'environment': env}
    path = tmp_path / 'candidate.json'
    path.write_text(json.dumps({'tasks': [candidate]}))
    result = _execute_task_builder_tool(ToolCall(id='v', name='verify_candidate', arguments={'task_index': 0}),
        config, max_chars=10000, work_dir=tmp_path, document_path=str(path))
    assert not result.error, result.content
    assert [trial['score'] for trial in json.loads(result.content)] == [1, 0]
    # A passing earlier tool call must not mask a changed final evaluator.
    candidate['environment']['hidden_files']['grade.py'] = 'print(\'{"score": 0}\')'
    task = _task_from_raw(candidate, 't', default_dimension_id='d')
    issues, failed, _ = _preflight_builder_environments([task],
        dimension=EvalDimension(id='d', name='Test', description='Test', approach='Test'),
        blueprint=make_blueprint('b', 'd', 'Test', task_type=TaskType.agent,
                                 environment_type=AgentEnvironmentType.docker_workspace),
        resources=[], config=config, trace_dir=tmp_path / 'final')
    assert issues and failed == {'t'}


@pytest.mark.skipif(os.environ.get('EVALCLAW_DOCKER_TESTS') != '1', reason='requires Docker')
def test_real_trial_budget_stops_background_work_between_tool_calls(tmp_path, monkeypatch):
    import time
    from evalclaw.quality.laaj_exploration import TaskExperiment

    runner = harness.ManifestHarnessRunner(harness.ManifestHarness(name='fixture', run='true', model_env={}))
    monkeypatch.setattr(harness, 'get_harness', lambda _: runner)
    target = TargetModelConfig(id='t', provider='openai', model='test', harness='openclaw')
    task = item()
    task.metadata['agent_env']['budget'] = {'wall_time_seconds': 1}
    trial = TaskExperiment(task, BenchmarkConfig(targets=[target]), 't', tmp_path)
    try:
        result = trial.perform({'operation': 'command', 'command': '(sleep 2; touch answer) >/dev/null 2>&1 &'})
        assert result['returncode'] == 0
        time.sleep(2.5)
        result = trial.perform({'operation': 'evaluate'})
        assert result['score'] == 0
        assert trial._evidence('')['termination']['status'] == 'budget_exhausted'
    finally:
        trial.close()


@pytest.mark.skipif(os.environ.get('EVALCLAW_DOCKER_TESTS') != '1', reason='requires Docker')
def test_real_exploration_does_not_consume_preflight_state(tmp_path, monkeypatch):
    from evalclaw.quality.laaj_exploration import TaskExperiment
    task = item()
    task.metadata['agent_env']['preflight_commands'] = ['touch consumed']
    runner = harness.ManifestHarnessRunner(harness.ManifestHarness(name='fixture', run='true', model_env={}))
    monkeypatch.setattr(harness, 'get_harness', lambda _: runner)
    target = TargetModelConfig(id='t', provider='openai', model='test', harness='openclaw')
    trial = TaskExperiment(task, BenchmarkConfig(targets=[target]), 't', tmp_path)
    try:
        result = trial.perform({'operation': 'command', 'command': 'test ! -e consumed'})
        assert result['returncode'] == 0
    finally:
        trial.close()


@pytest.mark.skipif(os.environ.get('EVALCLAW_DOCKER_TESTS') != '1', reason='requires Docker')
def test_real_budget_expiry_scores_partial_state_after_slow_setup(tmp_path):
    task = item()
    task.metadata['agent_env'].update(setup_commands=['sleep 1'], budget={'wall_time_seconds': 1.5})
    runner = harness.ManifestHarnessRunner(harness.ManifestHarness(name='fixture',
        run="python3 -c 'import pathlib,time; pathlib.Path(\"answer\").write_text(\"partial\"); time.sleep(20)'", model_env={}))
    raw, score, _ = runner.run(task, TargetModelConfig(provider='openai', model='test'), BenchmarkConfig(), artifact_dir=tmp_path)
    assert score == 1
    evidence = json.loads((tmp_path / 'evaluator-evidence.json').read_text())
    assert evidence['termination']['status'] == 'budget_exhausted'


@pytest.mark.skipif(os.environ.get('EVALCLAW_DOCKER_TESTS') != '1', reason='requires Docker and OpenClaw image')
def test_real_openclaw_workflow_gateway_and_session_history(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    requests = []
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(payload)
            messages = payload['messages']
            user = next(m for m in reversed(messages) if m['role'] == 'user' and any(
                marker in str(m['content']) for marker in ['FIRST_REQUEST', 'SECOND_REQUEST', 'THIRD_REQUEST']))
            user_text = str(user['content'])
            if 'FIRST_REQUEST' in user_text:
                text = 'FIRST_REPLY_PRIVATE_FACT_792'
            elif 'SECOND_REQUEST' in user_text:
                text = 'SECOND_REPLY'
            else:
                text = 'THIRD_REPLY'
            tool_call = 'FIRST_REQUEST' in user_text and not any(m.get('role') == 'tool' for m in messages)
            tool = {'id': 'validity-call-1', 'type': 'function',
                    'function': {'name': 'exec', 'arguments': json.dumps({'command': 'printf verified > /workspace/answer'})}}
            response = {'id': 'chat-test', 'object': 'chat.completion', 'created': 1,
                        'model': payload['model'], 'choices': [{'index': 0,
                        'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
            if tool_call:
                response['choices'][0].update(message={'role': 'assistant', 'content': None, 'tool_calls': [tool]}, finish_reason='tool_calls')
            if payload.get('stream'):
                chunk = {'id': 'chat-test', 'object': 'chat.completion.chunk', 'created': 1,
                         'model': payload['model'], 'choices': [{'index': 0,
                         'delta': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
                         'usage': response['usage']}
                if tool_call:
                    chunk['choices'][0].update(delta={'role': 'assistant', 'tool_calls': [{'index': 0, **tool}]}, finish_reason='tool_calls')
                body = ('data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n').encode()
                content_type = 'text/event-stream'
            else:
                body = json.dumps(response).encode()
                content_type = 'application/json'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('0.0.0.0', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bridge = json.loads(subprocess.check_output(['docker', 'network', 'inspect', 'bridge'], text=True))[0]['IPAM']['Config'][0]['Gateway']
    target = TargetModelConfig(id='local', provider='openai_compatible', model='deepseek-flash',
        api_key='test-only-key', base_url=f'http://{bridge}:{server.server_port}', harness='openclaw')
    task = item()
    task.workflow = AgentWorkflow(stages=[
        {'id': 'work', 'kind': 'agent', 'prompt': 'FIRST_REQUEST', 'context': 'fresh'},
        {'id': 'account', 'kind': 'agent', 'prompt': 'SECOND_REQUEST', 'context': 'continue', 'environment': 'reuse'},
        {'id': 'resume', 'kind': 'agent', 'prompt': 'THIRD_REQUEST', 'context': 'fresh', 'environment': 'reuse'},
        {'id': 'grade', 'kind': 'evaluate', 'environment': 'reuse'},
    ], score_stage='grade')
    try:
        _, score, _ = harness.get_harness('openclaw').run(task, target, BenchmarkConfig(targets=[target]), artifact_dir=tmp_path)
        assert score == 1
        assert len(requests) == 4
        assert 'SECOND_REQUEST' not in json.dumps(requests[0]['messages'])
        assert 'FIRST_REPLY_PRIVATE_FACT_792' in json.dumps(requests[2]['messages'])
        assert 'FIRST_REPLY_PRIVATE_FACT_792' not in json.dumps(requests[3]['messages'])
        evidence = json.loads((tmp_path / 'evaluator-evidence.json').read_text())
        assert evidence['target_execution']['model_responses']
        assert evidence['target_execution']['history']
        assert evidence['target_execution']['trace'][0]['tool_call']['name'] == 'exec'
        assert evidence['target_execution']['trace'][0]['result_observed']
        assert len(evidence['stages']) == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
