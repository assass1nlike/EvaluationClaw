"""Validate isolation before making any model request, then run the original driver."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import urllib.error

job = Path(sys.argv[1])
root = Path(__file__).resolve().parents[2]
config = json.loads((job / 'config.json').read_text())
assert not Path('/tmp/nuxeo_probe').exists()
assert not Path('/tmp/taskdev').exists()
assert {p.name for p in job.parent.iterdir()} == {job.name, 'qemu_cache'}
assert not Path('/data1/zangyihe/.claude/projects').exists()
assert not (root / 'benchmarks').exists()
assert not Path('/var/run/host-docker.sock').exists()
images = subprocess.check_output(['docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}'], text=True).splitlines()
expected = ['gym-anything-local/ubuntu-gnome-highres:20260915'] if config['runner'] == 'docker' else []
assert sorted(images) == expected, images
fd = os.open('/dev/kvm', os.O_RDWR)
os.close(fd)
version = subprocess.check_output(['/home/zangyihe/.local/bin/claude', '--version'], text=True).strip()
assert version.startswith('2.1.229 '), version
subprocess.run(['qemu-system-x86_64', '--version'], check=True, stdout=subprocess.DEVNULL)
with urllib.request.urlopen('https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json', timeout=30) as response:
    assert response.status == 200
try:
    urllib.request.urlopen('https://api.deepseek.com/models', timeout=30)
except urllib.error.HTTPError as error:
    assert error.code == 401
import gym_anything
assert Path(gym_anything.__file__).is_relative_to(job / 'workspace')
(root / 'local/q/1').mkdir(parents=True, exist_ok=True)
(job / 'isolation_check.json').write_text(json.dumps({
    'passed': True, 'images': images, 'claude_version': version,
    'gym_anything_source': gym_anything.__file__,
    'historical_outputs_visible': False, 'old_tmp_visible': False,
    'old_claude_sessions_visible': False, 'kvm_accessible': True,
    'github_reachable': True, 'deepseek_reachable': True,
}, indent=2) + '\n')
while not (job / 'start').exists():
    time.sleep(1)
with (job / 'driver.log').open('w') as log:
    result = subprocess.run([sys.executable, str(root / 'local/seed_batch.py'), '--job', str(job)],
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
raise SystemExit(result.returncode)
