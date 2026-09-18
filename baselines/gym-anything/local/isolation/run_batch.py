"""Run the existing seed driver with a private filesystem and Docker per software."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'local'))
import seed_batch

IMAGE = 'gym-anything-local/seed-isolation:20260918'


def mount(source, target=None, readonly=False):
    return ['--mount', f'type=bind,src={source},dst={target or source}' + (',readonly' if readonly else '')]


def launch(job):
    config = json.loads((job / 'config.json').read_text())
    name = f'ga-seed-{job.parent.name}-{job.name}'
    home = job / 'home'
    home.mkdir()
    claude_config = job / 'claude-config'
    claude_config.mkdir()
    original = json.loads(Path('/data1/zangyihe/.claude/settings.json').read_text())
    settings = {k: original[k] for k in ['effortLevel', 'skipDangerousModePermissionPrompt'] if k in original}
    settings['env'] = {k: v for k, v in original.get('env', {}).items() if k == 'CLAUDE_CODE_EFFORT_LEVEL'}
    seed_batch.write_json(claude_config / 'settings.json', settings)
    seed_batch.write_json(job / 'claude-state.json', {'hasCompletedOnboarding': True, 'lastOnboardingVersion': '2.1.229'})
    cache = job / 'qemu_cache'
    cache.mkdir()
    base = ROOT / 'local/runtime/qemu/cache/base_ubuntu_gnome.qcow2'
    (cache / base.name).symlink_to(base)
    command = ['docker', 'run', '--name', name, '--privileged', '--init',
               '--label', f'gym.seed_batch={job.parent.name}', '--network', 'gym-seed-isolated',
               '--workdir', str(job / 'workspace'),
               '--mount', f'type=volume,src={name}-docker,dst=/var/lib/docker']
    command += mount(job) + mount(home, '/home/zangyihe')
    command += mount(claude_config, '/data1/zangyihe/.claude')
    command += mount(job / 'claude-state.json', '/data1/zangyihe/.claude.json')
    command += mount(cache, job.parent / 'qemu_cache')
    for rel in ['.venv', 'local/.env', 'local/seed_batch.py', 'local/isolation/check.py',
                'local/runtime/qemu/bin', 'local/runtime/qemu/rootfs',
                'local/runtime/qemu/cache/base_ubuntu_gnome.qcow2']:
        command += mount(ROOT / rel, readonly=True)
    interpreter = (ROOT / '.venv/bin/python').resolve().parent.parent
    command += mount(interpreter, readonly=True)
    command += mount(interpreter, Path(os.readlink(ROOT / '.venv/bin/python')).parent.parent, True)
    command += mount(Path('/home/zangyihe/.local/bin/claude').resolve(), '/home/zangyihe/.local/bin/claude', True)
    for parent in [ROOT, *ROOT.parents]:
        for filename in ['AGENTS.md', 'CLAUDE.md']:
            if (parent / filename).is_file():
                command += mount(parent / filename, readonly=True)
    if config['runner'] == 'docker':
        command += mount(ROOT / 'local/outputs/isolation_assets/desktop.tar', '/opt/desktop.tar', True)
    env = {
        'HOME': '/home/zangyihe', 'CLAUDE_CONFIG_DIR': '/data1/zangyihe/.claude',
        'DISABLE_AUTOUPDATER': '1', 'PYTHONUNBUFFERED': '1', 'PYTHONHASHSEED': '42',
        'PATH': f"{ROOT / 'local/runtime/qemu/bin'}:{ROOT / '.venv/bin'}:/home/zangyihe/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        'PYTHONPATH': f"{job / 'workspace/src'}:{job / 'workspace'}",
        'GYM_ANYTHING_RUNNER': config['runner'],
        'GYM_ANYTHING_DOCKER_NETWORK': 'gym-anything-local',
        'GYM_ANYTHING_QEMU_CACHE': str(job.parent / 'qemu_cache'),
        'GYM_ANYTHING_QEMU_WORK_DIR': str(ROOT / 'local/q/1'),
        'SEED_JOB': str(job),
        'http_proxy': 'http://10.250.0.1:17890',
        'https_proxy': 'http://10.250.0.1:17890',
        'all_proxy': 'socks5://10.250.0.1:17890',
        'NO_PROXY': os.environ.get('NO_PROXY', 'localhost,127.0.0.1'),
    }
    for key, value in env.items():
        command += ['--env', f'{key}={value}']
    command += [IMAGE, str(seed_batch.PYTHON), str(ROOT / 'local/isolation/check.py'), str(job)]
    seed_batch.write_json(job / 'container.json', {'name': name, 'command': command})
    with (job / 'container.log').open('w') as out:
        result = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT)
    seed_batch.write_json(job / 'exit.json', {'returncode': result.returncode,
                          'finished': datetime.now(timezone.utc).isoformat()})
    return {'env': job.name, 'returncode': result.returncode}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=Path, required=True)
    args = parser.parse_args()
    batch = args.batch.resolve()
    if list(batch.glob('*/container.json')):
        raise RuntimeError('Batch already launched; preserve its sessions')
    jobs = [seed_batch.prepare(batch, item) for item in seed_batch.JOBS]
    seed_batch.write_json(batch / 'batch.json', {
        'upstream_commit': seed_batch.UPSTREAM_COMMIT, 'jobs': seed_batch.JOBS,
        'seed': 42, 'remote_seed': None, 'parallel_jobs': 10, 'stage': 'propose',
        'count_per_software': 10, 'timeout_per_phase': 36000,
        'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com',
        'image': seed_batch.IMAGE, 'isolation_image': IMAGE, 'cli_version': '2.1.229',
        'proposer_sampling': 'CLI/provider defaults; original effort settings preserved',
        'isolation': 'Private filesystem, tmp, home, Claude sessions, Docker daemon and QEMU software cache per job; no host Docker socket or historical output mounts',
    })
    for name in ['seed_batch.py', 'generate.py', 'requirements.lock']:
        shutil.copy2(ROOT / 'local' / name, batch / name)
    shutil.copytree(ROOT / 'local/isolation', batch / 'isolation', ignore=shutil.ignore_patterns('desktop.tar', '__pycache__'))
    (ROOT / 'local/outputs/latest_seed_batch.txt').write_text(str(batch) + '\n')
    print(f'Starting 10 isolated jobs: {batch}', flush=True)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(launch, jobs))
    seed_batch.write_json(batch / 'exits.json', results)
    return int(any(row['returncode'] for row in results))


if __name__ == '__main__':
    raise SystemExit(
        'Disabled: privileged generation containers do not protect the host. '
        'See local/isolation/security.md before running another batch.'
    )
