"""Verify transient API recovery without rerunning tasks or hiding framework errors."""
import json
from pathlib import Path
import sys

import pytest

from local.isolation.vm import claude_retry


@pytest.mark.parametrize('result,expected', [
    ({'terminal_reason':'api_error','api_error_status':None},True),
    ({'terminal_reason':'api_error','api_error_status':429},True),
    ({'terminal_reason':'api_error','api_error_status':503},True),
    ({'terminal_reason':'api_error','api_error_status':401},False),
    ({'terminal_reason':'api_error','api_error_status':400},False),
    ({'terminal_reason':'completed','is_error':True},False),
    ({'terminal_reason':'max_turns'},False),
    (None,False),
])
def test_retry_classification_uses_structured_terminal_reason(result,expected):
    assert claude_retry.retryable(result) is expected


@pytest.mark.parametrize('failures,expected_calls,last_code',[(1,2,0),(3,4,0),(8,4,1),(0,1,0)])
def test_same_session_recovery_has_three_extra_attempts(tmp_path,failures,expected_calls,last_code,capsys):
    calls=tmp_path/'calls.jsonl'
    fake=tmp_path/'fake.py'
    fake.write_text('''import json,sys
from pathlib import Path
p=Path(CALLS)
old=p.read_text().splitlines() if p.exists() else []
with p.open('a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
fail=len(old)<FAILURES
print(json.dumps({'type':'result','terminal_reason':'api_error' if fail else 'completed',
                  'api_error_status':None,'is_error':fail,'session_id':'same-session'}))
sys.exit(1 if fail else 0)
'''.replace('CALLS',repr(str(calls))).replace('FAILURES',str(failures)))
    (tmp_path/'status.json').write_text('{"phase":2}')
    args=[str(fake),'-p','Create ten tasks','--session-id','same-session',
          '--output-format','stream-json','--effort','high','--append-system-prompt','requirement']
    assert claude_retry.run(Path(sys.executable),args,tmp_path,delay=0)==last_code
    observed=[json.loads(x) for x in calls.read_text().splitlines()]
    assert len(observed)==expected_calls
    assert observed[0]==args[1:]
    for retry in observed[1:]:
        assert '--session-id' not in retry
        assert retry[retry.index('--resume')+1]=='same-session'
        assert retry[retry.index('-p')+1]==claude_retry.CONTINUE
        assert retry[retry.index('--effort')+1]=='high'
        assert retry[retry.index('--append-system-prompt')+1]=='requirement'
    assert len(list(tmp_path.glob('phase_2_attempt_*.jsonl')))==expected_calls
    audit=[json.loads(x) for x in (tmp_path/'api-retries.jsonl').read_text().splitlines()]
    assert not audit[-1]['retry_scheduled']
    assert audit[-1]['retries_exhausted']==(failures>3)
    assert len(capsys.readouterr().out.splitlines())==expected_calls


def test_resumption_keeps_existing_session_and_only_changes_recovery_prompt():
    args=['-p','original request','--resume','session-1','--settings','settings.json','--effort','high']
    assert claude_retry.resume_args(args,'session-1')==[
        '-p',claude_retry.CONTINUE,'--resume','session-1','--settings','settings.json','--effort','high']
    assert args[1]=='original request'


def test_outer_timeout_kills_attempt_and_its_children(tmp_path):
    import subprocess
    import time
    from extras.research.task_generation.propose_and_amplify.pipeline.propose_cc import run_claude
    fake=tmp_path/'fake.py'
    child_pid=tmp_path/'child.pid'
    fake.write_text('import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])\n'+f'Path({str(child_pid)!r}).write_text(str(p.pid))\n'+'time.sleep(60)\n')
    (tmp_path/'status.json').write_text('{"phase":1}')
    wrapper=tmp_path/'wrapper.py'
    wrapper.write_text('from pathlib import Path\nimport sys\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[3]))+')\nfrom local.isolation.vm.claude_retry import run\n'+f'run(Path(sys.executable),[{str(fake)!r},"-p","request","--session-id","s"],Path({str(tmp_path)!r}),delay=0)\n')
    run_claude(Path(sys.executable),[str(wrapper)],cwd=tmp_path,timeout=3)
    assert child_pid.exists()
    state=Path('/proc')/child_pid.read_text()/'stat'
    assert not state.exists() or state.read_text().split()[2]=='Z'
