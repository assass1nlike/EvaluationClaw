import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

from evalclaw.sources.petri import archive_files, convert_requirement, resolve_attachments, sha256, target_message
from evalclaw.protocols.task_definition import TaskMessage
from evalclaw.types import TaskSuite


@pytest.fixture
def native(tmp_path):
    root, output = tmp_path/'source', tmp_path/'review'
    root.mkdir()
    goal = 'Evaluate attribution of failures.'
    primary = {'status': 'scored', 'score': 8, 'summary': 'Some success', 'reason': 'Evidence',
               'evidence': ['target quote'], 'limitations': 'One audit'}
    native = {'status': 'scored', 'scores': {f'dim{i}': 1 for i in range(23)}, 'reason': 'EXCLUDED_ALIGNMENT_REPORT'}
    config = {'seed': 42, 'models': {'target': 'deepseek/deepseek-flash'}}
    system = {'id': 's', 'role': 'system', 'content': 'You coordinate workers.', 'metadata': {'source': 'Auditor'}}
    user = {'id': 'u', 'role': 'user', 'content': 'Check which worker failed.', 'metadata': {'source': 'Auditor'}}
    response = {'id': 'a', 'role': 'assistant', 'content': 'Worker B failed.', 'metadata': {'source': 'Target'}}
    rolled = {**response, 'id': 'a0', 'content': 'Worker A failed.'}
    calls = [{'event': 'model', 'role': 'auditor', 'input': [{'role': 'system','content': 'Audit policy'}], 'tools': []}]
    for answer in (rolled, response):
        calls.append({'event': 'model', 'role': 'target', 'input': [system,user],
                      'tools': [{'name': 'inspect_worker', 'parameters': {'type':'object'}}],
                      'output': {'choices': [{'message': answer}]}})
    requirement_input = {'requirement': goal, 'rubric': 'Rubric', 'transcript': 'Original branch.\nRollback.\nNew branch.'}
    sample = {'events': calls, 'attachments': {'history': json.dumps(requirement_input)},
        'store': {'RequirementJudgeStore:messages': [
            {'role':'system','content':'Judge instructions'}, {'role':'user','content':'attachment://history'}],
            'JudgeStore:messages': [{'role':'system','content':'Native instructions'}],
            'AuditStore:target': {'messages': [system,user,response], 'tools': []}},
        'scores': {'requirement_judge': {'metadata': {'judgment': primary}}, 'alignment_judge': {'value': native['scores']}}}
    transcript = {'metadata': {'judge_output': {'response': 'EXCLUDED_ALIGNMENT_REPORT'}},
                  'events': [{'type': 'rollback', 'native': True}], 'target_messages': [system,user,response]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('samples/1.json',json.dumps(sample))
    judgment = {'judgment': primary, 'response': json.dumps(primary)}
    summary = {'scores': {'performance':8}, 'status':'success', 'tool_errors': [{'error':'recovered'}], 'judge_errors':{},
               'native_judgment': native}
    files = {'instruction.txt': goal.encode(), 'rubric.txt': b'Rubric', 'judge_prompt.txt': b'Judge instructions',
        'native_judge_prompt.txt': b'Native instructions', 'config.json':json.dumps(config).encode(),
        'judgment.json':json.dumps(judgment).encode(), 'native_judgment.json':json.dumps(native).encode(),
        'summary.json':json.dumps(summary).encode(), 'transcripts/a.json':json.dumps(transcript).encode(),
        'logs/a.eval':buf.getvalue()}

    def pack(path, contents):
        path.parent.mkdir(parents=True,exist_ok=True)
        with tarfile.open(path,'w:gz') as a:
            for name,value in contents.items():
                info=tarfile.TarInfo(name);info.size=len(value);a.addfile(info,io.BytesIO(value))

    artifact='artifacts/deepseek-flash/requirement-07-epoch-01.tar.gz'
    pack(root/artifact,files)
    source='provenance/deepseek-flash/source.tar.gz'
    pack(root/source,{n:b'# original source' for n in ['source/requirement_judge.py',
        'source/upstream/src/petri/scorers/judge.py','source/upstream/src/petri/scorers/prompts.py']})
    row={'id':'petri/deepseek-flash/requirement-07/epoch-01','requirement_line':7,'requirement':goal,
         'epoch':1,'seed':42,'artifact_path':'petri/'+artifact,'artifact_sha256':sha256(root/artifact),
         'config_json':json.dumps(config),'judgment_json':json.dumps(judgment),
         'native_judgment_json':json.dumps(native),'performance_score':8,'exit_code':1}
    (root/'data').mkdir();(root/'data/deepseek-flash.jsonl').write_text(json.dumps(row)+'\n')
    (root/'SHA256SUMS').write_text('\n'.join(f'{sha256(root/p)}  {p}' for p in [artifact,source,'data/deepseek-flash.jsonl']))
    return root, output


def test_preserves_adaptive_audit_without_inventing_replay(native):
    root, output=native
    suite,run,manifest=convert_requirement(root,7,output,revision='pinned')
    task=suite.tasks[0];result=run.results[0]
    assert [m.role for m in task.content.messages]==['system','user']
    assert task.interaction.controller.status=='not_provided'
    assert not result.episode.events
    assert len(result.episode.outputs)==2  # The rolled-back target response is retained.
    assert result.episode.final_messages[-1]['content']=='Worker B failed.'
    assert result.episode.outputs[0]['content']=='Worker A failed.'
    assert len(result.episode.metrics)==1 and result.episode.metrics[0].value==8
    assert [m.id for m in task.evaluation.metrics]==['performance']
    assert [s.id for s in task.evaluation.scorers]==['requirement-judge']
    assert result.score==pytest.approx(7/9) and result.error is None
    assert result.execution['tool_errors']==[{'error':'recovered'}]
    assert all(a.visibility==['reviewer'] for a in task.assets)
    assert TaskSuite.model_validate_json(suite.model_dump_json())==suite
    history=next(a for a in task.assets if a.id=='target-history.txt')
    assert Path(history.path).read_text()=='Original branch.\nRollback.\nNew branch.'
    assert manifest['replay_supported'] is False
    assert set(json.loads((output/'native'/task.id/'transcript.json').read_text())['metadata'])==set()
    assert not (output/'native'/task.id/'native_judgment.json').exists()
    assert not (output/'native'/task.id/'inspect-sample.json').exists()
    assert not (output/'native'/task.id/'alignment-judge.json').exists()
    assert all(b'EXCLUDED_ALIGNMENT_REPORT' not in p.read_bytes() for p in output.rglob('*') if p.is_file())


def test_supplementary_judgment_does_not_gate_requirement_review(native,monkeypatch):
    from evalclaw.sources import petri
    original=petri.read_audit
    def without_supplementary(path):
        files,transcript,sample=original(path)
        files.pop('native_judgment.json');files.pop('native_judge_prompt.txt')
        sample['store'].pop('JudgeStore:messages')
        sample['scores'].pop('alignment_judge')
        return files,transcript,sample
    monkeypatch.setattr(petri,'read_audit',without_supplementary)
    suite,run,_=convert_requirement(native[0],7,native[1],revision='pinned')
    assert run.results[0].episode.metrics[0].value==8
    assert len(suite.tasks[0].evaluation.scorers)==1


def test_checksum_prevents_silent_source_changes(native):
    root,output=native
    with (root/'data/deepseek-flash.jsonl').open('a') as f: f.write(' ')
    with pytest.raises(ValueError,match='checksum'):
        convert_requirement(root,7,output,revision='pinned')


def test_attachment_resolution_is_exact_and_missing_is_error():
    assert resolve_attachments(['attachment://a','literal attachment://a'],{'a':'evidence'})==['evidence','literal attachment://a']
    with pytest.raises(KeyError): resolve_attachments('attachment://missing',{})


def test_rejects_grade_misalignment_even_with_valid_checksums(native):
    root,output=native
    path=root/'data/deepseek-flash.jsonl'
    row=json.loads(path.read_text());row['performance_score']=10
    path.write_text(json.dumps(row)+'\n')
    sums=root/'SHA256SUMS'
    lines=sums.read_text().splitlines()
    sums.write_text('\n'.join(f'{sha256(path)}  data/deepseek-flash.jsonl' if line.endswith('  data/deepseek-flash.jsonl') else line for line in lines))
    with pytest.raises(ValueError,match='Inconsistent published audit'):
        convert_requirement(root,7,output,revision='pinned')


def test_shared_tools_can_read_full_history_and_judge(native):
    from evalclaw.diagnostics import write_json
    from evalclaw.protocols.tool import ToolCall
    from evalclaw.quality.laaj_tools import read_task_file
    from evalclaw.quality.analysis_tools import read_item_evidence
    root,output=native
    suite,run,_=convert_requirement(root,7,output,revision='pinned')
    write_json(output/'construction.json',{'suite':suite.model_dump(mode='json')})
    write_json(output/'run.json',run.model_dump(mode='json'))
    task=suite.tasks[0]
    result=read_task_file(ToolCall(id='read',name='read_task_file',arguments={
        'item_id':task.id,'area':'asset','path':'target-history.txt'}),suite)
    assert result.error is None
    result=read_item_evidence(ToolCall(id='judge',name='read_item_evidence',arguments={
        'item_id':task.id,'target_id':'deepseek-flash','kind':'judge'}),output)
    assert result.error is None
    assert json.loads(json.loads(result.content)['judge_reasoning'])['score']==8


def test_missing_replay_is_explicit_without_structural_failure_or_docker(native,tmp_path):
    from evalclaw.execution.task_runtime import ContractSession, CapabilityMismatch, contract_issues
    from evalclaw.types import BenchmarkConfig,TargetModelConfig
    suite,_,_=convert_requirement(native[0],7,native[1],revision='pinned')
    task=suite.tasks[0]
    assert contract_issues(task)==[]
    def unexpected_component(*args,**kwargs):
        pytest.fail('An unavailable imported controller must not start a container')
    session=ContractSession(task,BenchmarkConfig(),TargetModelConfig(id='test',model='test',provider='openai_compatible'),tmp_path,
                            component_factory=unexpected_component)
    with pytest.raises(CapabilityMismatch):session.prepare()


def test_seeded_and_prefill_messages_are_not_target_outputs():
    for prefill in [True,False]:
        message=target_message({'role':'assistant','content':'externally supplied', 'metadata':{'prefill':prefill}})
        parsed=TaskMessage.model_validate(message)
        assert parsed.origin==('prefill' if prefill else 'seeded_context')


def test_archive_rejects_traversal(tmp_path):
    path=tmp_path/'bad.tar.gz'
    with tarfile.open(path,'w:gz') as a:
        info=tarfile.TarInfo('../escape');info.size=1;a.addfile(info,io.BytesIO(b'x'))
    with pytest.raises(ValueError,match='Invalid archive'):
        archive_files(path)
