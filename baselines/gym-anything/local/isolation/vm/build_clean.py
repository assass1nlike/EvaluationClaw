"""Prepare a model-free generation image from the original secure base."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import threading

import verify

ROOT = verify.ROOT
OUT = ROOT/'local/outputs/vm_base'
NAME = 'ga-generator-preparation'
COMMIT = '774476d752d748a69288f2ead97f75dd9df08ddb'
ADAPTERS = [
    'src/gym_anything/runtime/runners/docker.py',
    'src/gym_anything/runtime/runners/qemu_apptainer.py',
    'src/gym_anything/runtime/runners/qemu_native.py',
    'src/gym_anything/runtime/runners/qemu_ssh.py',
    'src/gym_anything/runtime/runners/build_base_qcow2_nodocker.py',
    'extras/research/task_generation/propose_and_amplify/pipeline/propose_cc.py',
    'local/generate.py', 'local/deepseek-settings.json', 'local/seed_batch.py',
    'local/isolation/vm/guest_proxy.py',
]


def bundle():
    target=OUT/'code.tar'
    upstream=ROOT/'local/outputs/upstream'
    verify.host(['git','-C',str(upstream),'archive',COMMIT,
                 '--prefix='+str(ROOT).lstrip('/')+'/', '-o',str(target)])
    with tarfile.open(target,'a') as tar:
        tar.add(upstream/'.git',arcname=str(ROOT/'.git').lstrip('/'))
        for rel in [*ADAPTERS,'.venv','local/runtime/tools/python']:
            tar.add(ROOT/rel,arcname=str(ROOT/rel).lstrip('/'))
        tar.add(ROOT/'local/runtime/tools/claude',arcname='home/ga/.local/bin/claude')
        instructions=ROOT/'local/outputs/migration_20260918/records/instructions'
        for row in json.loads((instructions/'index.json').read_text()):
            tar.add(instructions/row['snapshot'],arcname=row['original_path'].lstrip('/'))
    (OUT/'source.json').write_text(json.dumps({'official_commit':COMMIT,'adapters':{
        p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ADAPTERS}},indent=2)+'\n')
    return target


def main():
    OUT.mkdir(mode=0o700,parents=True,exist_ok=True)
    if (OUT/'READY.json').exists():
        print('Clean image already prepared'); return
    if (OUT/'disk.raw').exists():
        raise RuntimeError('Incomplete preparation exists; inspect it before resuming')
    verify.prepare(OUT,instance='gym-generator-preparation')
    sock=OUT/'egress/proxy.sock'
    server=verify.Server(str(sock)); sock.chmod(0o600)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    client=None
    success=False
    try:
        client=verify.launch(OUT,NAME,cpus=8,memory_gb=16,limit_gb=20)
        print('Installing guest dependencies',flush=True)
        verify.guest(client,'cloud-init status --wait',timeout=240)
        verify.guest(client,'sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io docker-compose-v2 qemu-system-x86 qemu-utils genisoimage git curl jq cloud-guest-utils',timeout=1200)
        print('Packing and copying original framework and pinned tools',flush=True)
        package=bundle()
        with client.open_sftp() as sftp:
            sftp.put(str(package),'/home/ga/code.tar')
            sftp.put(str(ROOT/'local/outputs/isolation_assets/desktop.tar'),'/home/ga/desktop.tar')
            sftp.put(str(verify.QEMU/'secure-cache/base_ubuntu_gnome.qcow2'),'/home/ga/nested-original.qcow2')
        verify.guest(client,'sudo tar -xf /home/ga/code.tar -C / && rm /home/ga/code.tar',timeout=300)
        verify.guest(client,'sudo systemctl daemon-reload && sudo systemctl restart docker && sudo docker load -i /home/ga/desktop.tar && rm /home/ga/desktop.tar',timeout=300)
        module=next(m for m in ['kvm_amd','kvm_intel'] if Path('/sys/module',m).exists())
        command=f'''sudo chown -R ga:ga {shlex.quote(str(ROOT))} /home/ga/.local
sudo usermod -aG docker,kvm ga
sudo modprobe {module}
echo {module} | sudo tee /etc/modules-load.d/gym-kvm.conf >/dev/null
sudo mkdir -p /etc/systemd/system/gym-egress.service.d
sudo tee /etc/systemd/system/gym-egress.service >/dev/null <<'UNIT'
[Unit]
Description=Restricted egress relay inside the generation VM
[Service]
ExecStart=/usr/bin/python3 {ROOT}/local/isolation/vm/guest_proxy.py
User=ga
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now gym-egress
mkdir -p /home/ga/.docker
cat > /home/ga/.docker/config.json <<'JSON'
{{"proxies":{{"default":{{"httpProxy":"http://10.0.2.100:3128","httpsProxy":"http://10.0.2.100:3128","noProxy":"localhost,127.0.0.1"}}}}}}
JSON
sudo mkdir -p /root/.docker
sudo cp /home/ga/.docker/config.json /root/.docker/config.json
sudo docker network create gym-anything-local
sudo rm -f /home/ga/.bash_history
sudo cloud-init clean --logs
sync
'''
        verify.guest(client,command,timeout=180)
        rc,out,err=verify.guest(client,f'{ROOT}/.venv/bin/python --version && /home/ga/.local/bin/claude --version && sudo docker version --format "{{{{.Server.Version}}}}" && qemu-system-x86_64 --version',timeout=30)
        (OUT/'versions.txt').write_text(out+err)
        assert '2.1.229' in out
        verify.guest(client,'test ! -d /home/ga/.claude/projects && test ! -f '+str(ROOT/'local/.env'))
        success=True
    finally:
        if client:
            try:verify.guest(client,'sudo shutdown -h now',timeout=5,check=False)
            except Exception:pass
            client.close()
        verify.host(['docker','stop','-t','30',NAME])
        logs=verify.host(['docker','logs',NAME]);(OUT/'serial.log').write_text(logs.stdout+logs.stderr)
        server.shutdown();server.server_close();sock.unlink(missing_ok=True)
    if success:
        print('Converting clean generation image',flush=True)
        target=OUT/'generator.qcow2'
        verify.host([str(verify.QEMU/'bin/qemu-img'),'convert','-O','qcow2',str(OUT/'disk.raw'),str(target)])
        with target.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        (OUT/'READY.json').write_text(json.dumps({'sha256':digest,'path':str(target),'model_calls':0,'source_base_sha256':'399ae62720c46a6af2727796e33c9fa040d7760a09f4c4b1e1acffba1ef2e2ff'},indent=2)+'\n')
        print('Clean image ready: '+str(target),flush=True)


if __name__=='__main__':main()
