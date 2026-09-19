"""Prepare per-software guest state before any model call; runs only in a VM."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml

ROOT=Path(__file__).resolve().parents[3]
JOB=Path('/home/ga/job')


def run(*args,**kwargs):
    return subprocess.run(args,check=True,**kwargs)


def main():
    config=json.loads((JOB/'config.json').read_text())
    assert not Path('/home/ga/.claude/projects').exists()
    assert not list(Path('/home/ga').glob('smoke*'))
    # Expand this private disk's filesystem after the host reserves the larger disk.
    expanded = subprocess.run(['sudo','growpart','/dev/vda','1'])
    if expanded.returncode not in (0, 1):
        raise RuntimeError('Guest partition expansion failed')
    run('sudo','resize2fs','/dev/vda1')
    fs = os.statvfs('/')
    assert fs.f_blocks * fs.f_frsize > 190 * 1024**3
    run('sudo','chown','-R','ga:ga',str(ROOT),str(JOB))
    env_dir=ROOT/'benchmarks/cua_world/environments'/config['env']
    spec=json.loads((env_dir/'env.json').read_text())
    (JOB/'original_env.json').write_text(json.dumps(spec,indent=2)+'\n')
    config['original_tasks']=sorted(p.name for p in (env_dir/'tasks').iterdir() if p.is_dir())
    spec['runner']=config['runner']
    if config['runner']=='docker':
        spec['image']='gym-anything-local/ubuntu-gnome-highres:20260915'
        spec['security']['runtime']='runc'
    for mount in spec.get('mounts',[]):
        mount['source']=str(ROOT/mount['source'])
    spec.setdefault('recording',{})['output_dir']=str(JOB/'episodes')
    (env_dir/'env.json').write_text(json.dumps(spec,indent=2)+'\n')
    (JOB/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    (ROOT/'.mcp.json').write_text(json.dumps({'mcpServers':{'visual-grounding':{
        'command':str(ROOT/'.venv/bin/python'),
        'args':[str(ROOT/'local/isolation/vm/screenshot_mcp.py')]}}},indent=2)+'\n')
    (ROOT/'.claude').mkdir(exist_ok=True)
    (ROOT/'.claude/settings.local.json').write_text(json.dumps({'enabledMcpjsonServers':['visual-grounding'],'model':'deepseek-flash'})+'\n')
    Path('/home/ga/.claude').mkdir(exist_ok=True)
    Path('/home/ga/.claude/settings.json').write_text(json.dumps({'skipDangerousModePermissionPrompt':True})+'\n')
    Path('/home/ga/.claude.json').write_text(json.dumps({'hasCompletedOnboarding':True,'lastOnboardingVersion':'2.1.229'})+'\n')
    with (ROOT/'.git/info/exclude').open('a') as f:
        f.write('\n/local/\n/.venv/\n/.claude/\n/.mcp.json\n')
    run('git','-C',str(ROOT),'config','user.name','Gym Anything')
    run('git','-C',str(ROOT),'config','user.email','gym-anything@localhost')
    # Each generation VM creates its own software-VM key. No host private key enters.
    key=Path('/home/ga/qemu-key')
    run('ssh-keygen','-q','-t','ed25519','-N','','-f',str(key))
    cache=Path('/home/ga/qemu-cache');cache.mkdir()
    image=cache/'base_ubuntu_gnome.qcow2'
    Path('/home/ga/nested-original.qcow2').rename(image)
    proxy='http://10.0.2.2:3128'
    docker=json.dumps({'proxies':{'default':{'httpProxy':proxy,'httpsProxy':proxy,'noProxy':'localhost,127.0.0.1'}}})
    cloud={'ssh_pwauth':False,'write_files':[
        {'path':'/home/ga/.ssh/authorized_keys','owner':'ga:ga','permissions':'0600','content':key.with_suffix('.pub').read_text()},
        {'path':'/etc/environment','content':f'http_proxy={proxy}\nhttps_proxy={proxy}\nHTTP_PROXY={proxy}\nHTTPS_PROXY={proxy}\nno_proxy=localhost,127.0.0.1\n'},
        {'path':'/etc/apt/apt.conf.d/90-gym-proxy','content':f'Acquire::http::Proxy "{proxy}";\nAcquire::https::Proxy "{proxy}";\n'},
        {'path':'/etc/systemd/system/docker.service.d/proxy.conf','content':f'[Service]\nEnvironment="HTTP_PROXY={proxy}" "HTTPS_PROXY={proxy}" "NO_PROXY=localhost,127.0.0.1"\n'},
        {'path':'/root/.docker/config.json','content':docker},
        {'path':'/home/ga/.docker/config.json','owner':'ga:ga','content':docker}],
        'power_state':{'mode':'poweroff','delay':'now','timeout':30,'condition':True}}
    (cache/'user-data').write_text('#cloud-config\n'+yaml.safe_dump(cloud))
    (cache/'meta-data').write_text('instance-id: '+config['env']+'-key\n')
    run('genisoimage','-output',str(cache/'seed.iso'),'-volid','cidata','-joliet','-rock',str(cache/'user-data'),str(cache/'meta-data'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    with (JOB/'nested-provision.log').open('w') as log:
        proc=subprocess.Popen(['qemu-system-x86_64','-enable-kvm','-cpu','host','-m','3072','-smp','2','-drive',f'file={image},format=qcow2,if=virtio','-cdrom',str(cache/'seed.iso'),'-nic','none','-display','none','-monitor','none','-serial','stdio'],stdout=log,stderr=subprocess.STDOUT)
        try:
            if proc.wait(timeout=300)!=0:raise RuntimeError('Nested key preparation failed')
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
    env={'PATH':f'{ROOT}/.venv/bin:/home/ga/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
         'PYTHONPATH':f'{ROOT}:{ROOT}/src','PYTHONHASHSEED':'42','DISABLE_AUTOUPDATER':'1',
         'GYM_ANYTHING_RUNNER':config['runner'],'GYM_ANYTHING_DOCKER_NETWORK':'gym-anything-local',
         'GYM_ANYTHING_QEMU_CACHE':str(cache),'GYM_ANYTHING_QEMU_WORK_DIR':'/home/ga/q',
         'GYM_ANYTHING_QEMU_SSH_KEY':str(key),'GYM_SCREENSHOT_AUDIT':str(JOB/'screenshot-api.jsonl'),
         'http_proxy':'http://10.0.2.100:3128','https_proxy':'http://10.0.2.100:3128',
         'HTTP_PROXY':'http://10.0.2.100:3128','HTTPS_PROXY':'http://10.0.2.100:3128',
         'no_proxy':'localhost,127.0.0.1','NO_PROXY':'localhost,127.0.0.1',
         'ANTHROPIC_MODEL':'deepseek-flash','CLAUDE_CODE_EFFORT_LEVEL':'high'}
    for k in ['ANTHROPIC_DEFAULT_OPUS_MODEL','ANTHROPIC_DEFAULT_SONNET_MODEL','ANTHROPIC_DEFAULT_HAIKU_MODEL','CLAUDE_CODE_SUBAGENT_MODEL']:
        env[k]='deepseek-flash'
    (JOB/'environment.json').write_text(json.dumps(env,indent=2)+'\n')
    run(sys.executable,str(ROOT/'local/isolation/vm/claude_retry.py'),'--install')
    (JOB/'prepared.json').write_text(json.dumps({'seed':42,'time':time.time(),'model_calls':0,'original_tasks':config['original_tasks']},indent=2)+'\n')


if __name__=='__main__':main()
