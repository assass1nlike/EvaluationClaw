"""Validate one full generation VM boundary; never launch a benchmark batch."""
import argparse
import json
import os
from pathlib import Path
import random
import shlex
import subprocess
import threading
import time

import paramiko
import yaml

from proxy import Server

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'local/outputs/vm_isolation_check'
QEMU = ROOT / 'local/runtime/qemu'
NAME = 'ga-vm-isolation-check'
IMAGE = 'gym-anything-local/seed-isolation:20260918'
KEY = QEMU / 'ssh/key'
report = {'seed': 42, 'model': None, 'benchmark_generation': False, 'checks': {}}


def host(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def record(name, value):
    report['checks'][name] = value
    if name == 'model_tool_inside_guest':
        report['model'] = value['model']
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(name + ': ' + ('saved' if name == 'guest_boundary' else json.dumps(value)), flush=True)


def connect():
    transport = paramiko.ProxyCommand(shlex.join(['docker', 'exec', '-i', NAME, 'python3', '/relay.py', 'ssh']))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect('vm-verification', username='ga', key_filename=str(KEY), sock=transport,
                       timeout=15, banner_timeout=15, auth_timeout=15, allow_agent=False, look_for_keys=False)
    except Exception:
        transport.close()
        raise
    return client


def guest(client, command, timeout=120, check=True):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    stdin.close()
    out, err = stdout.read().decode(), stderr.read().decode()
    rc = stdout.channel.recv_exit_status()
    if check and rc:
        raise RuntimeError(f'Guest command failed ({rc}): {command}\n{out[-2000:]}\n{err[-2000:]}')
    return rc, out, err


def prepare():
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    (OUT / 'egress').mkdir(mode=0o700, exist_ok=True)
    (OUT / 'host-canary.txt').write_text('Host-only safety sentinel\n')
    if not (OUT / 'disk.raw').exists():
        print('Preparing fixed-size 50 GiB guest disk', flush=True)
        host([str(QEMU / 'bin/qemu-img'), 'convert', '-O', 'raw',
              str(QEMU / 'secure-cache/base_ubuntu_gnome.qcow2'), str(OUT / 'disk.raw')])
        host(['fallocate', '-l', str(50 * 1024**3), str(OUT / 'disk.raw')])
    from gym_anything.runtime.runners.qemu_ssh import SSHD_CONFIG
    config = {
        'ssh_pwauth': False,
        'write_files': [
            {'path': '/etc/ssh/sshd_config.d/00-gym-anything.conf', 'permissions': '0600', 'content': SSHD_CONFIG},
            {'path': '/etc/apt/apt.conf.d/90-gym-proxy', 'content': 'Acquire::http::Proxy "http://10.0.2.100:3128";\nAcquire::https::Proxy "http://10.0.2.100:3128";\n'},
            {'path': '/etc/environment', 'content': 'http_proxy=http://10.0.2.100:3128\nhttps_proxy=http://10.0.2.100:3128\nHTTP_PROXY=http://10.0.2.100:3128\nHTTPS_PROXY=http://10.0.2.100:3128\nno_proxy=localhost,127.0.0.1\n'},
            {'path': '/etc/systemd/system/docker.service.d/proxy.conf', 'content': '[Service]\nEnvironment="HTTP_PROXY=http://10.0.2.100:3128" "HTTPS_PROXY=http://10.0.2.100:3128" "NO_PROXY=localhost,127.0.0.1"\n'},
        ],
        'runcmd': [['systemctl', 'restart', 'ssh']],
    }
    (OUT / 'user-data').write_text('#cloud-config\n' + yaml.safe_dump(config))
    (OUT / 'meta-data').write_text('instance-id: gym-isolation-verify\nlocal-hostname: gym-isolation\n')
    host(['genisoimage', '-output', str(OUT / 'seed.iso'), '-volid', 'cidata', '-joliet', '-rock',
          str(OUT / 'user-data'), str(OUT / 'meta-data')])


def launch():
    cmd = ['docker', 'run', '-d', '--init', '--name', NAME, '--network', 'none', '--read-only',
           '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges=true',
           '--user', f'{os.getuid()}:{os.stat("/dev/kvm").st_gid}', '--device', '/dev/kvm',
           '--cpus', '4', '--memory', '10g', '--memory-swap', '10g', '--pids-limit', '512',
           '--ulimit', 'nofile=1024:1024', '--ulimit', 'core=0:0',
           '--ulimit', f'fsize={50 * 1024**3}:{50 * 1024**3}',
           '--log-opt', 'max-size=5m', '--log-opt', 'max-file=2',
           '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=64m',
           '--mount', f'type=bind,src={OUT / "disk.raw"},dst=/disk.raw',
           '--mount', f'type=bind,src={OUT / "seed.iso"},dst=/seed.iso,readonly',
           '--mount', f'type=bind,src={QEMU / "rootfs"},dst=/qemu,readonly',
           '--mount', f'type=bind,src={OUT / "egress"},dst=/egress,readonly',
           '--mount', f'type=bind,src={HERE / "relay.py"},dst=/relay.py,readonly',
           '--entrypoint', '/qemu/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2', IMAGE,
           '--library-path', '/qemu/lib/x86_64-linux-gnu:/qemu/usr/lib/x86_64-linux-gnu',
           '/qemu/usr/bin/qemu-system-x86_64', '-L', '/qemu/usr/share/qemu',
           '-enable-kvm', '-cpu', 'host', '-m', '8192', '-smp', '4',
           '-drive', 'file=/disk.raw,format=raw,if=virtio', '-cdrom', '/seed.iso',
           '-display', 'none', '-monitor', 'none', '-serial', 'stdio',
           '-device', 'virtio-net-pci,netdev=net0', '-netdev',
           'user,id=net0,restrict=on,hostfwd=tcp:127.0.0.1:2222-:22,guestfwd=tcp:10.0.2.100:3128-cmd:python3 /relay.py proxy']
    (OUT / 'launch.json').write_text(json.dumps(cmd, indent=2) + '\n')
    host(cmd)
    for _ in range(90):
        try:
            return connect()
        except (OSError, paramiko.SSHException):
            time.sleep(2)
    raise RuntimeError('SSH did not become ready')


def verify(client):
    config = json.loads(host(['docker', 'inspect', NAME]).stdout)[0]
    hc = config['HostConfig']
    assert not hc['Privileged'] and hc['NetworkMode'] == 'none' and hc['ReadonlyRootfs']
    assert hc['CapDrop'] == ['ALL'] and 'no-new-privileges=true' in hc['SecurityOpt']
    assert hc['PidsLimit'] == 512 and hc['Memory'] == 10 * 1024**3 and hc['NanoCpus'] == 4_000_000_000
    assert hc['MemorySwap'] == hc['Memory'] and not hc['PortBindings']
    assert [d['PathOnHost'] for d in hc['Devices']] == ['/dev/kvm']
    assert [m['Destination'] for m in config['Mounts'] if m['RW']] == ['/disk.raw']
    (OUT / 'container-inspect.json').write_text(json.dumps(config, indent=2) + '\n')
    resources = host(['docker', 'exec', NAME, 'python3', '-c',
        "import json,pathlib; print(json.dumps({p:pathlib.Path('/sys/fs/cgroup/'+p).read_text().strip() for p in ['memory.max','memory.swap.max','pids.max','cpu.max']}))"]).stdout
    resource_values = json.loads(resources)
    assert resource_values['memory.max'] == str(10 * 1024**3)
    assert resource_values['memory.swap.max'] == '0' and resource_values['pids.max'] == '512'
    quota, period = map(int, resource_values['cpu.max'].split())
    assert quota / period == 4
    record('outer_limits', resource_values)
    record('outer_guardrails', json.loads(host(['docker', 'exec', NAME, 'python3', '-c',
                                             (HERE / 'outer_checks.py').read_text()]).stdout))
    _, state, _ = guest(client, 'cloud-init status --wait', timeout=180)
    record('cloud_init', state.strip())
    _, policy, _ = guest(client, 'sudo sshd -T -C user=ga,host=localhost,addr=10.0.2.2')
    opts = dict(line.split(None, 1) for line in policy.splitlines())
    assert opts['passwordauthentication'] == opts['kbdinteractiveauthentication'] == 'no'
    assert opts['authenticationmethods'] == 'publickey'
    record('ssh_publickey_only', True)
    _, isolation, _ = guest(client, "sudo python3 - <<'INNER'\nimport json, pathlib, os\np=" + repr(str(OUT/'host-canary.txt')) + "\nassert not pathlib.Path(p).exists()\nassert not pathlib.Path('/qemu').exists()\nassert not pathlib.Path('/var/run/docker.sock').exists()\nassert not pathlib.Path('/dev/nvme0n1').exists()\nprint(json.dumps({'host_canary_absent':True,'host_devices_absent':True,'host_docker_absent':True,'mounts':pathlib.Path('/proc/mounts').read_text()}))\nINNER")
    record('guest_boundary', json.loads(isolation))
    original = Path('/proc/sys/kernel/printk').read_text()
    guest(client, "sudo sysctl -w kernel.printk='3 4 1 7'")
    assert Path('/proc/sys/kernel/printk').read_text() == original
    record('guest_kernel_write_does_not_change_host', True)
    network = r'''import socket, urllib.request, urllib.error, json, os
os.environ['no_proxy']=''
os.environ['NO_PROXY']=''
p=urllib.request.build_opener(urllib.request.ProxyHandler({'http':'http://10.0.2.100:3128','https':'http://10.0.2.100:3128'}))
r={}
for url in ['http://127.0.0.1:22','http://10.0.2.2:22','http://192.168.1.1','http://169.254.169.254','http://example.com']:
    try: p.open(url,timeout=10)
    except urllib.error.HTTPError as e: assert e.code == 403; r[url]='denied'
    else: raise AssertionError(url)
for addr in ['10.0.2.2','198.51.100.1']:
    try: s=socket.create_connection((addr,80),timeout=2)
    except OSError: r[addr]='direct blocked'
    else: s.close(); raise AssertionError(addr)
for url in ['https://api.deepseek.com/models','https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json']:
    try:
        with p.open(url,timeout=30) as response: r[url]=response.status
    except urllib.error.HTTPError as e:
        assert e.code == 401; r[url]=401
print(json.dumps(r))
'''
    _, net, _ = guest(client, 'python3 - <<\'INNER\'\n' + network + 'INNER', timeout=120)
    record('network', json.loads(net))
    print('Installing guest Docker and nested QEMU through restricted proxy', flush=True)
    guest(client, 'sudo DEBIAN_FRONTEND=noninteractive dpkg --configure -a', timeout=300)
    guest(client, 'sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io qemu-system-x86 qemu-utils', timeout=900)
    guest(client, 'sudo systemctl daemon-reload && sudo systemctl restart docker')
    record('docker_server', guest(client, 'sudo docker version --format "{{.Server.Version}}"')[1].strip())
    modules = [name for name in ('kvm_amd', 'kvm_intel') if Path('/sys/module', name).exists()]
    if len(modules) != 1:
        raise RuntimeError(f'Expected one host KVM CPU module, found {modules}')
    guest(client, f"sudo modprobe {modules[0]} && sudo chmod 666 /dev/kvm")
    record('nested_kvm', guest(client, "python3 -c \"import os,fcntl; f=os.open('/dev/kvm',os.O_RDWR); assert fcntl.ioctl(f,0xAE00,0)==12; print('KVM API 12')\"")[1].strip())
    print('Transferring original desktop Docker image into guest', flush=True)
    with client.open_sftp() as sftp:
        sftp.put(str(ROOT/'local/outputs/isolation_assets/desktop.tar'), '/home/ga/desktop.tar')
    guest(client, 'sudo docker load -i /home/ga/desktop.tar && rm /home/ga/desktop.tar', timeout=300)
    _, docker_test, _ = guest(client, 'sudo docker run --rm --privileged --network none gym-anything-local/ubuntu-gnome-highres:20260915 bash -lc "id; test -d /sys/fs/cgroup; command -v Xvnc"', timeout=120)
    record('guest_privileged_docker', docker_test.strip())
    print('Transferring secure base for nested VM boot', flush=True)
    with client.open_sftp() as sftp:
        sftp.put(str(QEMU/'secure-cache/base_ubuntu_gnome.qcow2'), '/home/ga/nested.qcow2')
    # Check genuine nested KVM boot, with no network or host mounts.
    nested = r'''import subprocess,time
from pathlib import Path
with open('/home/ga/nested.log','w') as log:
    p=subprocess.Popen(['qemu-system-x86_64','-enable-kvm','-cpu','host','-m','3072','-smp','2','-drive','file=/home/ga/nested.qcow2,format=qcow2,if=virtio','-nic','none','-display','none','-monitor','none','-serial','stdio'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
    try:
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            text=Path('/home/ga/nested.log').read_text(errors='replace')
            if 'login:' in text: print('Nested KVM reached guest login'); break
            if p.poll() is not None: raise RuntimeError(text[-2000:])
            time.sleep(2)
        else: raise RuntimeError('Nested guest boot timed out')
    finally:
        p.terminate()
        try: p.wait(timeout=15)
        except subprocess.TimeoutExpired: p.kill(); p.wait()
'''
    record('nested_vm_boot', guest(client, "python3 - <<'INNER'\n" + nested + 'INNER', timeout=210)[1].strip())
    record('disk_capacity_bytes', (OUT/'disk.raw').stat().st_size)
    assert (OUT/'disk.raw').stat().st_size == 50 * 1024**3
    record('host_canary_unchanged', (OUT/'host-canary.txt').read_text() == 'Host-only safety sentinel\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', action='store_true', help='Exercise framework/model after boundary verification')
    parser.add_argument('--docker-smoke', action='store_true', help='Repeat only the Docker runner check')
    args = parser.parse_args()
    random.seed(42)
    if args.smoke or args.docker_smoke:
        saved = json.loads((OUT / 'verification.json').read_text())
        if not saved['checks'].get('boundary_passed'):
            raise SystemExit('Boundary verification must pass first')
        report.update(saved)
    prepare()
    sock = OUT/'egress/proxy.sock'
    if sock.exists():
        sock.unlink()
    server = Server(str(sock))
    sock.chmod(0o600)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = None
    try:
        client = launch()
        record('stopped', False)
        if args.smoke or args.docker_smoke:
            record('framework_smoke_passed', False)
            from smoke import run
            run(client, ROOT, OUT, guest, record, docker_only=args.docker_smoke)
            checks = report['checks']
            record('framework_smoke_passed', bool(checks['framework_docker']['passed'] and
                   checks.get('framework_nested_qemu') and checks.get('model_tool_inside_guest') and
                   checks.get('docker_egress')))
        else:
            verify(client)
            record('boundary_passed', True)
    finally:
        if client:
            try:
                guest(client, 'sudo shutdown -h now', timeout=5, check=False)
            except (OSError, paramiko.SSHException):
                pass
            client.close()
        exists = subprocess.run(['docker','inspect',NAME],capture_output=True).returncode == 0
        if exists:
            log=host(['docker','logs',NAME])
            (OUT/'serial.log').write_text(log.stdout + log.stderr)
            subprocess.run(['docker','stop','-t','20',NAME],check=True,stdout=subprocess.DEVNULL)
            state=json.loads(host(['docker','inspect',NAME]).stdout)[0]['State']
            record('stopped', not state['Running'])
        server.shutdown()
        server.server_close()
        sock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
