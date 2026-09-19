"""Check API parameter transport and the batch VM's host boundary."""
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import openai

from local.isolation.vm import screenshot_mcp
import verify


def test_screenshot_adapter_preserves_official_messages_and_result(tmp_path,monkeypatch):
    seen=[]
    def reply(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'test','object':'chat.completion','created':1,
            'model':'deepseek-flash','choices':[{'index':0,'finish_reason':'stop',
            'message':{'role':'assistant','content':'A red square.','reasoning_content':'reasoning'}}],
            'usage':{'prompt_tokens':10,'completion_tokens':8,'total_tokens':18}})
    client=openai.OpenAI(api_key='test',base_url='https://example.invalid',
                        http_client=httpx.Client(transport=httpx.MockTransport(reply)))
    monkeypatch.setattr(screenshot_mcp,'OriginalClient',lambda *a,**k:client)
    monkeypatch.setenv('GYM_SCREENSHOT_AUDIT',str(tmp_path/'audit.jsonl'))
    messages=[{'role':'user','content':[{'type':'text','text':'Describe this image'},
               {'type':'image_url','image_url':{'url':'data:image/png;base64,AA=='}}]}]
    with patch.object(screenshot_mcp.official.openai,'OpenAI',screenshot_mcp.configured_client):
        result=screenshot_mcp.official._query_openai(messages,'deepseek-flash')
    assert result=='A red square.'
    assert seen==[{'model':'deepseek-flash','messages':messages,'max_tokens':4096,
                  'reasoning_effort':'high','thinking':{'type':'enabled'}}]
    row=json.loads((tmp_path/'audit.jsonl').read_text())
    assert row['success'] and row['reasoning_characters']==9
    assert 'messages' not in row and 'reasoning_content' not in row
    client.close()


def test_batch_launch_keeps_only_disk_writable_and_no_host_network(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(verify,'host',lambda cmd:calls.append(cmd))
    monkeypatch.setattr(verify,'connect',lambda name:name)
    assert verify.launch(tmp_path,'isolated',cpus=8,memory_gb=24,limit_gb=28,disk_gb=200)=='isolated'
    cmd=calls[0]
    assert cmd[cmd.index('--network')+1]=='none'
    assert '--privileged' not in cmd and '--read-only' in cmd
    assert cmd[cmd.index('--cap-drop')+1]=='ALL'
    assert cmd[cmd.index('--security-opt')+1]=='no-new-privileges=true'
    assert cmd[cmd.index('--memory')+1]==cmd[cmd.index('--memory-swap')+1]=='28g'
    assert cmd[cmd.index('-m')+1]=='24576'
    mounts=[cmd[i+1] for i,arg in enumerate(cmd) if arg=='--mount']
    assert [m for m in mounts if 'readonly' not in m]==[f'type=bind,src={tmp_path / "disk.raw"},dst=/disk.raw']
    assert [cmd[i+1] for i,arg in enumerate(cmd) if arg=='--device']==['/dev/kvm']
    assert not any(arg in ('-p','--publish','--pid=host','--ipc=host') for arg in cmd)


def test_guest_output_cannot_write_outside_its_job(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import pytest
    from local.isolation.vm.run_batch import copy_observations
    client=MagicMock()
    sftp=client.open_sftp.return_value.__enter__.return_value
    sftp.listdir_attr.return_value=[SimpleNamespace(filename='../outside.json')]
    with pytest.raises(RuntimeError,match='Invalid filename'):
        copy_observations(client,tmp_path/'job',b'test-key')
    sftp.file.assert_not_called()
    assert not (tmp_path/'outside.json').exists()
