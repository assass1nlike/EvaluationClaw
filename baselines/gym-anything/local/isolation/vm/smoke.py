"""Exercise framework runners and a bounded DeepSeek tool call inside the VM."""
import json
from pathlib import Path
import shlex

from dotenv import dotenv_values


def run(client, root, out, guest, record, docker_only=False):
    print('Copying pinned framework and dependencies into VM', flush=True)
    if guest(client, 'test -f ' + shlex.quote(str(root/'.venv/bin/python')), check=False)[0]:
        with client.open_sftp() as sftp:
            sftp.put(str(out/'framework.tar'), '/home/ga/framework.tar')
        guest(client, 'sudo tar -xf /home/ga/framework.tar -C / && rm /home/ga/framework.tar', timeout=180)
    py=str(root/'.venv/bin/python')
    guest(client, f"sudo chown -R ga:ga {shlex.quote(str(root))} /home/ga/.local && "
          "sudo usermod -aG docker,kvm ga && mkdir -p /home/ga/smoke /home/ga/qemu-cache")
    prefix = f'cd {shlex.quote(str(root))} && PYTHONPATH={shlex.quote(str(root))}:{shlex.quote(str(root/"src"))} '
    record('framework_import', guest(client,prefix+shlex.quote(py)+" -c 'import gym_anything; print(gym_anything.__file__)'")[1].strip())
    guest(client, 'sudo chmod 666 /var/run/docker.sock')  # Guest-only daemon; model already has guest sudo.
    proxy_config = json.dumps({'proxies': {'default': {
        'httpProxy': 'http://10.0.2.100:3128', 'httpsProxy': 'http://10.0.2.100:3128',
        'noProxy': 'localhost,127.0.0.1'}}})
    configure = ('from pathlib import Path; content=' + repr(proxy_config) + '; '
                 "[(p.parent.mkdir(parents=True,exist_ok=True),p.write_text(content)) for p in "
                 "[Path('/root/.docker/config.json'),Path('/home/ga/.docker/config.json')]]")
    guest(client, 'sudo python3 -c ' + shlex.quote(configure) + ' && sudo chown -R ga:ga /home/ga/.docker')
    fetch = "import urllib.request; print(urllib.request.urlopen('https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json',timeout=30).status)"
    _, status, _ = guest(client, "docker run --rm gym-anything-local/ubuntu-gnome-highres:20260915 python3 -c " + shlex.quote(fetch), timeout=60)
    assert status.strip() == '200', status
    record('docker_egress', {'github_status': 200, 'proxy': 'http://10.0.2.100:3128'})
    docker_smoke = '''from pathlib import Path
from gym_anything.runtime.runners.docker import DockerRunner
from gym_anything.specs import EnvSpec
r=DockerRunner(EnvSpec.from_dict({'id':'vm_boundary_smoke','image':'gym-anything-local/ubuntu-gnome-highres:20260915','resources':{'cpu':2,'mem_gb':3,'net':True},'security':{'user':'root','privileged':True,'use_systemd':True,'mount_cgroups':True,'cgroupns_host':True,'tmpfs_run':True,'runtime':'runc'},'vnc':{'password':'password'},'recording':{'enable':False,'output_dir':'/home/ga/smoke/docker'}}))
try:
 r.start(seed=42)
 assert r.exec_capture('printf framework-docker-ok').strip()=='framework-docker-ok'
 r._wait_for_xserver()
 assert r.capture_screenshot(Path('/home/ga/smoke/docker/desktop.png'))
 print('Docker runner commands and desktop screenshot passed')
finally:r.stop()
'''
    rc, text, err = guest(client, prefix+shlex.quote(py)+" - <<'INNER'\n"+docker_smoke+'INNER',timeout=300,check=False)
    record('framework_docker',{'passed':rc==0,'output':text[-2000:],'error':err[-2000:]})
    if docker_only:
        if rc == 0:
            with client.open_sftp() as sftp:
                sftp.get('/home/ga/smoke/docker/desktop.png', str(out/'docker-desktop.png'))
        return
    # Create a separate nested-VM key in the guest. Host management key stays outside.
    guest(client,"test -f /home/ga/qemu-key || ssh-keygen -q -t ed25519 -N '' -f /home/ga/qemu-key")
    provision = '''from pathlib import Path
import subprocess,yaml
p=Path('/home/ga/qemu-cache')
pub=Path('/home/ga/qemu-key.pub').read_text().strip()
c={'ssh_pwauth':False,'write_files':[{'path':'/home/ga/.ssh/authorized_keys','owner':'ga:ga','permissions':'0600','content':pub+'\\n'}],'power_state':{'mode':'poweroff','delay':'now','timeout':30,'condition':True}}
(p/'user-data').write_text('#cloud-config\\n'+yaml.safe_dump(c))
(p/'meta-data').write_text('instance-id: nested-key-provision\\n')
subprocess.run(['genisoimage','-output',str(p/'seed.iso'),'-volid','cidata','-joliet','-rock',str(p/'user-data'),str(p/'meta-data')],check=True,capture_output=True)
with open(p/'key-provision.log','w') as log:
 proc=subprocess.Popen(['qemu-system-x86_64','-enable-kvm','-cpu','host','-m','3072','-smp','2','-drive','file=/home/ga/nested.qcow2,format=qcow2,if=virtio','-cdrom',str(p/'seed.iso'),'-nic','none','-display','none','-monitor','none','-serial','stdio'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
 try: assert proc.wait(timeout=240)==0
 finally:
  if proc.poll() is None:proc.kill();proc.wait()
Path('/home/ga/nested.qcow2').rename(p/'base_ubuntu_gnome.qcow2')
'''
    guest(client, 'sudo apt-get install -y -qq genisoimage',timeout=180)
    guest(client,prefix+shlex.quote(py)+" - <<'INNER'\n"+provision+'INNER',timeout=270)
    qemu_smoke = '''from pathlib import Path
from gym_anything.runtime.runners.qemu_native import QemuNativeRunner
from gym_anything.specs import EnvSpec
r=QemuNativeRunner(EnvSpec.from_dict({'id':'nested_framework_check','resources':{'cpu':2,'mem_gb':3,'net':False},'vnc':{'password':'password'},'recording':{'enable':False}}))
try:
 r.start(seed=42)
 assert r._test_ssh_auth()
 assert r.exec_capture('printf framework-qemu-ok').strip()=='framework-qemu-ok'
 assert r.capture_screenshot(Path('/home/ga/smoke/qemu.png'))
 print('Nested QEMU runner public-key commands and desktop screenshot passed')
finally:r.stop()
'''
    _,text,_=guest(client,prefix+'GYM_ANYTHING_QEMU_CACHE=/home/ga/qemu-cache GYM_ANYTHING_QEMU_SSH_KEY=/home/ga/qemu-key '+shlex.quote(py)+" - <<'INNER'\n"+qemu_smoke+'INNER',timeout=300)
    record('framework_nested_qemu',text.strip())
    guest(client, "mkdir -p /home/ga/.claude && printf '%s' '{\"skipDangerousModePermissionPrompt\":true}' > /home/ga/.claude/settings.json")
    config=dotenv_values(root/'local/.env')
    api={k:config[k] for k in ['DEEPSEEK_MODEL','DEEPSEEK_API_KEY','DEEPSEEK_BASE_URL']}
    with client.open_sftp() as sftp:
        with sftp.file('/home/ga/smoke/api.json','w') as f:
            f.chmod(0o600)
            f.write(json.dumps(api))
    model_smoke = '''import json,os,shlex
from pathlib import Path
from extras.research.task_generation.propose_and_amplify.pipeline.propose_cc import run_claude
from local.generate import ROOT as LOCAL_ROOT
cfg=json.loads(Path('/home/ga/smoke/api.json').read_text())
os.environ.update(ANTHROPIC_API_KEY=cfg['DEEPSEEK_API_KEY'],ANTHROPIC_AUTH_TOKEN=cfg['DEEPSEEK_API_KEY'],ANTHROPIC_BASE_URL=cfg['DEEPSEEK_BASE_URL'].rstrip('/')+'/anthropic',ANTHROPIC_MODEL=cfg['DEEPSEEK_MODEL'],DISABLE_AUTOUPDATER='1')
for k in ['ANTHROPIC_DEFAULT_OPUS_MODEL','ANTHROPIC_DEFAULT_SONNET_MODEL','ANTHROPIC_DEFAULT_HAIKU_MODEL','CLAUDE_CODE_SUBAGENT_MODEL']:os.environ[k]=cfg['DEEPSEEK_MODEL']
code="import json,socket; from pathlib import Path; Path('/home/ga/smoke/model-tool.json').write_text(json.dumps({'hostname':socket.gethostname(),'marker':42}))"
prompt="This is an infrastructure smoke test, not benchmark generation. Use Bash once to execute: " + shlex.join(['python3','-c',code]) + ". Then stop. Do not inspect credentials, change services, install packages or access the network with tools."
settings=LOCAL_ROOT/'deepseek-settings.json'
run_claude(Path('/home/ga/.local/bin/claude'),['-p',prompt,'--model',cfg['DEEPSEEK_MODEL'],'--settings',str(settings),'--effort','high','--dangerously-skip-permissions','--max-turns','3','--output-format','json'],cwd=Path('/home/ga/smoke'),timeout=180)
'''
    try:
        rc,text,err=guest(client,prefix+shlex.quote(py)+" - <<'INNER' > /home/ga/smoke/model-response.json 2>/home/ga/smoke/model-error.log\n"+model_smoke+'INNER',timeout=210)
        _,artifact,_=guest(client,'cat /home/ga/smoke/model-tool.json')
        value=json.loads(artifact)
        assert value == {'hostname':'gym-isolation','marker':42},value
        record('model_tool_inside_guest',{'model':api['DEEPSEEK_MODEL'],'artifact':value,'max_turns':3,'timeout':180})
    finally:
        guest(client,'rm -f /home/ga/smoke/api.json',check=False)
    with client.open_sftp() as sftp:
        for name in ['docker/desktop.png','qemu.png','model-tool.json']:
            try:
                sftp.get('/home/ga/smoke/'+name,str(out/name.replace('/', '-')))
            except FileNotFoundError:
                pass
        for name in ['model-response.json','model-error.log']:
            with sftp.file('/home/ga/smoke/'+name) as f:
                content=f.read().decode().replace(api['DEEPSEEK_API_KEY'],'[REDACTED]')
            p=out/name
            p.touch(mode=0o600)
            p.write_text(content)
