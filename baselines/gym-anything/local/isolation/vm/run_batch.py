"""Schedule ten isolated generation VMs, preserving the official build pipeline."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import time

import verify
from dotenv import dotenv_values

ROOT=verify.ROOT
sys.path.insert(0,str(ROOT))
from local.seed_batch import JOBS, seed_everything

IMAGE=ROOT/'local/outputs/vm_base/generator.qcow2'
GUEST_JOB='/home/ga/job'
CPU=8
RAM=24
LIMIT=28
DISK=200


def write(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)


def preflight(client,job,name):
    info=json.loads(verify.host(['docker','inspect',name]).stdout)[0]
    hc=info['HostConfig']
    assert hc['NetworkMode']=='none' and hc['ReadonlyRootfs'] and not hc['Privileged']
    assert hc['CapDrop']==['ALL'] and 'no-new-privileges=true' in hc['SecurityOpt']
    assert hc['Memory']==LIMIT*1024**3 and hc['MemorySwap']==hc['Memory']
    assert hc['PidsLimit']==512 and hc['NanoCpus']==CPU*1_000_000_000 and not hc['PortBindings']
    assert [x['PathOnHost'] for x in hc['Devices']]==['/dev/kvm']
    assert [(m['Source'],m['Destination']) for m in info['Mounts'] if m['RW']]==[(str(job/'disk.raw'),'/disk.raw')]
    write(job/'container.json',info)
    _,policy,_=verify.guest(client,'sudo sshd -T -C user=ga,host=localhost,addr=10.0.2.2')
    opts=dict(line.split(None,1) for line in policy.splitlines())
    assert opts['passwordauthentication']==opts['kbdinteractiveauthentication']=='no'
    assert opts['authenticationmethods']=='publickey'
    code='''import os,json,pathlib,socket,urllib.request,urllib.error,fcntl,subprocess
assert not pathlib.Path('/qemu').exists()
assert not pathlib.Path('/dev/nvme1n1').exists()
assert not pathlib.Path('/home/ga/.claude/projects').exists()
assert not pathlib.Path(HOST_SENTINEL).exists()
f=os.open('/dev/kvm',os.O_RDWR);assert fcntl.ioctl(f,0xAE00,0)==12;os.close(f)
proxy=urllib.request.build_opener(urllib.request.ProxyHandler({'http':'http://10.0.2.100:3128','https':'http://10.0.2.100:3128'}))
checks={}
for url in ['http://10.0.2.2:22','http://169.254.169.254','http://example.com']:
 try:proxy.open(url,timeout=10)
 except urllib.error.HTTPError as e:assert e.code==403;checks[url]='denied'
 else:raise AssertionError(url)
try:s=socket.create_connection(('10.0.2.2',80),timeout=2)
except OSError:checks['direct']='blocked'
else:s.close();raise AssertionError('direct access permitted')
try:proxy.open('https://api.deepseek.com/models',timeout=45)
except urllib.error.HTTPError as e:assert e.code==401;checks['deepseek']=401
else:raise AssertionError('Unexpected API result')
print(json.dumps(checks))
'''.replace('HOST_SENTINEL',repr(str(job/'host-canary.txt')))
    _,out,_=verify.guest(client,"python3 - <<'PY'\n"+code+'PY',timeout=90)
    assert (job/'host-canary.txt').read_text()=='Host-only safety sentinel\n'
    write(job/'preflight.json',{'passed':True,'publickey_only':True,'network':json.loads(out),'time':time.time()})


def copy_observations(client,job,key):
    with client.open_sftp() as sftp:
        for entry in sftp.listdir_attr(GUEST_JOB):
            if Path(entry.filename).name != entry.filename or entry.filename in ('.', '..'):
                raise RuntimeError('Invalid filename from guest SFTP')
            if not stat.S_ISREG(entry.st_mode) or not entry.filename.endswith(('.json','.jsonl','.stderr','.log')):
                continue
            if entry.st_size>128*1024**2:
                continue  # The complete log remains on the guest disk and in the final archive.
            with sftp.file(GUEST_JOB+'/'+entry.filename,'rb') as f:
                content=f.read(128*1024**2+1)
            if len(content)>128*1024**2:
                raise RuntimeError('Guest output exceeded the transfer limit')
            content=content.replace(key,b'[REDACTED]')
            target=job/entry.filename
            target.write_bytes(content)


def save_tasks(client,job,env):
    code=f'''import json,pathlib,tarfile
root=pathlib.Path({str(ROOT)!r})
env=root/'benchmarks/cua_world/environments'/{env!r}
tasks=env/'tasks'
manifest=tasks/'seed_tasks.json'
value=json.loads(manifest.read_text()) if manifest.exists() else None
summary={{'seed_manifest':value,'task_directories':sorted(p.name for p in tasks.iterdir() if p.is_dir())}}
pathlib.Path('/home/ga/job/tasks-summary.json').write_text(json.dumps(summary,indent=2)+'\\n')
with tarfile.open('/home/ga/tasks.tar.gz','w:gz',dereference=False) as tar:tar.add(env,arcname={env!r})
'''
    verify.guest(client,shlex.quote(str(ROOT/'.venv/bin/python'))+" - <<'PY'\n"+code+'PY',timeout=600)
    with client.open_sftp() as sftp:
        if sftp.stat('/home/ga/tasks.tar.gz').st_size>20*1024**3:
            raise RuntimeError('Task archive exceeds 20 GiB; retain it on the guest disk')
        sftp.get('/home/ga/tasks.tar.gz',str(job/'tasks.tar.gz'))


def worker(batch,index,item,barrier,api):
    goal,software,env,runner=item
    job=batch/f'{index:02d}'
    name=f'ga-seeds-{batch.name}-{index:02d}'
    config={'goal':goal,'software':software,'env':env,'runner':runner,'seed':42,'remote_seed':None,
            'count':10,'task_type':'enterprise','timeout_per_phase':36000,'model':'deepseek-flash',
            'thinking':True,'reasoning_effort':'high','cli_effort':'high','cli_version':'2.1.229',
            'cpu':CPU,'guest_memory_gib':RAM,'outer_memory_gib':LIMIT,'disk_gib':DISK,'container':name}
    write(job/'config.json',config)
    sock=job/'egress/proxy.sock'
    server=verify.Server(str(sock),audit=str(job/'egress.jsonl'));sock.chmod(0o600)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    client=None
    result={'env':env,'started':time.time(),'stage':'preparing'}
    write(job/'state.json',result)
    try:
        client=verify.launch(job,name,cpus=CPU,memory_gb=RAM,limit_gb=LIMIT,disk_gb=DISK)
        verify.guest(client,'cloud-init status --wait',timeout=240)
        verify.guest(client,'mkdir -m 700 /home/ga/job')
        with client.open_sftp() as sftp:
            sftp.put(str(ROOT/'local/runtime/tools/uv'),'/home/ga/.local/bin/uv')
            sftp.chmod('/home/ga/.local/bin/uv',0o755)
            for p in ['guest_run.py','guest_launch.py','provision_job.py','screenshot_mcp.py','claude_retry.py']:
                sftp.put(str(verify.HERE/p),str(ROOT/'local/isolation/vm'/p))
            sftp.put(str(job/'config.json'),GUEST_JOB+'/config.json')
            sftp.put(str(ROOT/f'local/requirements/goal_{goal}.txt'),GUEST_JOB+'/requirement.txt')
        preflight(client,job,name)
        verify.guest(client,shlex.quote(str(ROOT/'.venv/bin/python'))+' '+shlex.quote(str(ROOT/'local/isolation/vm/provision_job.py'))+' > /home/ga/job/preparation.log 2>&1',timeout=420)
        # Confirm a fresh session and the installed CLI before providing model credentials.
        _,cli,_=verify.guest(client,'/home/ga/.local/bin/claude --version && test ! -d /home/ga/.claude/projects')
        assert cli.strip().startswith('2.1.229 ')
        with client.open_sftp() as sftp:
            with sftp.file(str(ROOT/'local/.env'),'w') as f:
                f.chmod(0o600)
                f.write(''.join(f'{k}={v}\n' for k,v in api.items()))
        copy_observations(client,job,api['DEEPSEEK_API_KEY'].encode())
        result['stage']='ready';write(job/'state.json',result)
        print(env+': ready',flush=True)
        barrier.wait(timeout=2400)
        command=['sudo','systemd-run','--unit=gym-build','--uid=ga','--gid=ga',
                 '--property=RuntimeMaxSec=145200','--property=KillMode=control-group',
                 '--property=StandardOutput=append:/home/ga/job/service.log',
                 '--property=StandardError=append:/home/ga/job/service.log',
                 '--working-directory='+str(ROOT),str(ROOT/'.venv/bin/python'),str(ROOT/'local/isolation/vm/guest_launch.py')]
        verify.guest(client,shlex.join(command))
        result.update(stage='running',released=time.time());write(job/'state.json',result)
        print(env+': official construction started',flush=True)
        while True:
            copy_observations(client,job,api['DEEPSEEK_API_KEY'].encode())
            if (job/'exit.json').exists():
                result['official_exit']=json.loads((job/'exit.json').read_text())
                save_tasks(client,job,env)
                copy_observations(client,job,api['DEEPSEEK_API_KEY'].encode())
                result['stage']='finished';break
            _,state,_=verify.guest(client,'systemctl show gym-build -p ActiveState --value',check=False)
            if state.strip() in ('failed','inactive'):
                raise RuntimeError('Build service stopped without an exit record')
            time.sleep(30)
    except Exception as error:
        barrier.abort()
        result.update(stage='infrastructure_error',error_type=type(error).__name__,error=str(error).replace(api['DEEPSEEK_API_KEY'],'[REDACTED]'))
        print(env+': '+result['error'],flush=True)
    finally:
        if client:
            try:
                copy_observations(client,job,api['DEEPSEEK_API_KEY'].encode())
                verify.guest(client,'sudo systemctl stop gym-build; rm -f '+shlex.quote(str(ROOT/'local/.env'))+'; sudo shutdown -h now',timeout=15,check=False)
            except Exception:pass
            client.close()
        verify.host(['docker','stop','-t','30',name])
        logs=verify.host(['docker','logs',name]);(job/'serial.log').write_text(logs.stdout+logs.stderr)
        server.shutdown();server.server_close();sock.unlink(missing_ok=True)
        result.update(stopped=True,finished=time.time());write(job/'state.json',result)
    return result


def main():
    os.umask(0o077)
    seed_everything(42)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    args=parser.parse_args()
    batch=args.batch.resolve()
    if (batch/'batch.json').exists():raise RuntimeError('Use a fresh batch directory')
    assert json.loads(IMAGE.with_name('READY.json').read_text())['model_calls']==0
    batch.mkdir(mode=0o700,parents=True,exist_ok=True)
    source=batch/'source'
    source.mkdir()
    for path in verify.HERE.glob('*.py'):
        shutil.copy2(path,source/path.name)
    for filename in ['generate.py','seed_batch.py','deepseek-settings.json']:
        shutil.copy2(ROOT/'local'/filename,source/filename)
    shutil.copy2(ROOT/'local/requirements.lock',source/'requirements.lock')
    write(source/'sha256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()})
    api={k:dotenv_values(ROOT/'local/.env')[k] for k in ['DEEPSEEK_API_KEY','DEEPSEEK_BASE_URL','DEEPSEEK_MODEL']}
    assert api['DEEPSEEK_MODEL']=='deepseek-flash'
    assert os.statvfs(batch).f_bavail*os.statvfs(batch).f_frsize>2100*1024**3
    canonical=(ROOT.parent.parent/'user-inputs.txt').read_text().splitlines()
    for goal,line in enumerate([1,2,3,4,6],1):
        assert (ROOT/f'local/requirements/goal_{goal}.txt').read_text().strip()==canonical[line-1].strip()
    (batch/'user-inputs.txt').write_text('\n'.join(canonical)+'\n')
    write(batch/'batch.json',{'created':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),
          'jobs':JOBS,'parallel_jobs':10,'count_per_software':10,'stage':'propose','task_type':'enterprise',
          'seed':42,'remote_seed':None,'model':'deepseek-flash','thinking':True,'reasoning_effort':'high',
          'cli_version':'2.1.229','timeout_per_phase':36000,'cpu_per_vm':CPU,'guest_memory_gib':RAM,
          'outer_memory_gib':LIMIT,'disk_gib':DISK,'clean_image':json.loads(IMAGE.with_name('READY.json').read_text()),
          'code_commit':verify.host(['git','rev-parse','HEAD'],cwd=ROOT).stdout.strip(),
          'official_commit':'774476d752d748a69288f2ead97f75dd9df08ddb'})
    (ROOT/'local/outputs/latest_safe_batch.txt').write_text(str(batch)+'\n')
    for index,item in enumerate(JOBS,1):
        job=batch/f'{index:02d}'
        verify.prepare(job,source=IMAGE,disk_gb=DISK,instance=f'gym-build-{index:02d}')
        print(item[2]+': disk reserved',flush=True)
    barrier=threading.Barrier(10,action=lambda:write(batch/'released.json',{'time':time.time(),'jobs':10}))
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures=[pool.submit(worker,batch,i,item,barrier,api) for i,item in enumerate(JOBS,1)]
        results=[future.result() for future in as_completed(futures)]
    write(batch/'results.json',results)


if __name__=='__main__':main()
