"""Run ten ten-seed proposer jobs on the host and retain their evidence."""
import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'
IMAGE = 'gym-anything-local/ubuntu-gnome-highres:20260915'
RUNTIME_IMAGE = 'gym-anything-local/host-generation:20260919'
UPSTREAM_COMMIT = '774476d752d748a69288f2ead97f75dd9df08ddb'
UPSTREAM_URL = 'https://github.com/cmu-l3/gym-anything'
JOBS = [
    (1, 'ERPNext', 'erpnext_env', 'qemu'),
    (1, 'Moodle', 'moodle_env', 'qemu'),
    (2, 'Redmine', 'redmine_env', 'qemu'),
    (2, 'Nuxeo Platform', 'nuxeo_platform_env', 'qemu'),
    (3, 'Visual Studio Code', 'vscode_env', 'docker'),
    (3, 'LibreOffice Writer', 'libreoffice_writer_env', 'docker'),
    (4, 'WordPress', 'wordpress_env', 'qemu'),
    (4, 'Rancher', 'rancher_env', 'qemu'),
    (5, 'QGIS', 'qgis_env', 'docker'),
    (5, 'RStudio', 'rstudio_env', 'docker'),
]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def seed_everything(seed):
    random.seed(seed)
    import numpy as np
    np.random.seed(seed)


def record_claude(official, binary, args, *, cwd, timeout, job, phase):
    """Observe the upstream call without changing its failure or cleanup policy."""
    prefix = job / f'phase_{phase}'
    args = [*args, '--output-format', 'stream-json', '--verbose']
    write_json(prefix.with_suffix('.input.json'), {'argv': [str(binary), *args], 'timeout': timeout})
    status = {'phase': phase, 'started': datetime.now(timezone.utc).isoformat()}
    write_json(job / 'status.json', status)
    processes = []
    with prefix.with_suffix('.jsonl').open('w') as out, prefix.with_suffix('.stderr').open('w') as err:
        class RecordedProcess(subprocess.Popen):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, stdout=out, stderr=err, **kwargs)
                processes.append(self)

            def wait(self, *args, **kwargs):
                try:
                    return super().wait(*args, **kwargs)
                except subprocess.TimeoutExpired:
                    status['timeout'] = True
                    raise

        try:
            with patch.object(subprocess, 'Popen', RecordedProcess):
                official(binary, args, cwd=cwd, timeout=timeout)
        finally:
            status['returncode'] = processes[0].poll() if processes else None
            status['finished'] = datetime.now(timezone.utc).isoformat()
            out.flush()
            result = None
            for line in prefix.with_suffix('.jsonl').read_text().splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get('type') == 'result':
                    result = event
            status['result'] = result
            write_json(prefix.with_suffix('.result.json'), status)
            write_json(job / 'status.json', status)


def job_main(job, resume_phase=0):
    config = json.loads((job / 'config.json').read_text())
    workspace = job / 'workspace'
    sys.path[:0] = [str(workspace / 'src'), str(workspace)]
    from extras.research.task_generation.propose_and_amplify.pipeline import propose_cc
    from local import generate
    from dotenv import dotenv_values
    api = dotenv_values(ROOT / 'local/.env')
    os.environ.update(
        SCREENSHOT_QUERY_PROVIDER='openai', SCREENSHOT_QUERY_MODEL=api['DEEPSEEK_MODEL'],
        SCREENSHOT_QUERY_BASE_URL=api['DEEPSEEK_BASE_URL'],
        SCREENSHOT_QUERY_API_KEY=api['DEEPSEEK_API_KEY'],
    )
    seed_everything(config['seed'])
    phase = resume_phase
    official_claude = propose_cc.run_claude

    def run_claude(binary, args, *, cwd, timeout):
        nonlocal phase
        phase += 1
        return record_claude(official_claude, binary, args, cwd=cwd, timeout=timeout,
                             job=job, phase=phase)

    propose_cc.run_claude = run_claude
    resume_args = []
    if resume_phase:
        first = json.loads((job / 'phase_1.input.json').read_text())['argv']
        session = first[first.index('--session-id') + 1]
        resume_args = ['--session-id', session, '--propose-start-idx', str(resume_phase)]
    return generate.main([
        '--deepseek', '--requirement-file', str(job / 'requirement.txt'),
        '--software', config['software'], '--env-dir', config['env'],
        '--workspace', str(workspace), '--stage', 'propose',
        '--output-dir', str(job / 'generation'),
        '--timeout-sec', str(config['timeout_per_phase']),
        '--claude-bin', str(job / 'claude'), *resume_args,
    ])


def prepare(batch, item):
    goal, software, env_name, runner = item
    job = batch / env_name
    job.mkdir(exist_ok=True)
    workspace = job / 'workspace'
    if not workspace.exists():
        subprocess.run(['git', 'clone', '--quiet', '--no-checkout',
                        str(ROOT / 'local/outputs/upstream'), str(workspace)], check=True)
        subprocess.run(['git', 'checkout', '--quiet', '-B', 'main', UPSTREAM_COMMIT], cwd=workspace, check=True)
    for rel in ['src/gym_anything/runtime/runners/docker.py', 'local/generate.py',
                'local/deepseek-settings.json',
                'src/gym_anything/runtime/runners/qemu_apptainer.py',
                'src/gym_anything/runtime/runners/qemu_native.py',
                'src/gym_anything/runtime/runners/qemu_ssh.py',
                'src/gym_anything/runtime/runners/build_base_qcow2_nodocker.py',
                'local/isolation/vm/screenshot_mcp.py',
                'extras/research/task_generation/propose_and_amplify/pipeline/propose_cc.py']:
        destination = workspace / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, destination)
    if not (workspace / 'local/.env').exists():
        (workspace / 'local/.env').symlink_to(ROOT / 'local/.env')
    if not (workspace / '.venv').exists():
        (workspace / '.venv').symlink_to(ROOT / '.venv', target_is_directory=True)
    with (workspace / '.git/info/exclude').open('a') as exclusions:
        exclusions.write('\n/local/\n/.claude/\n/.mcp.json\n/.venv\n')
    shutil.copy2(ROOT / f'local/requirements/goal_{goal}.txt', job / 'requirement.txt')
    env_dir = workspace / 'benchmarks/cua_world/environments' / env_name
    config = {'goal': goal, 'software': software, 'env': env_name, 'runner': runner,
              'seed': 42, 'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com',
              'count': 10, 'timeout_per_phase': 36000, 'task_type': 'enterprise',
              'thinking': True, 'reasoning_effort': 'high', 'cli_effort': 'high',
              'max_api_retries': 3, 'retry_delay_seconds': 5,
              'original_tasks': sorted(p.name for p in (env_dir / 'tasks').iterdir() if p.is_dir())}
    write_json(job / 'config.json', config)
    original = subprocess.check_output([
        'git', '-C', str(workspace), 'show',
        f'{UPSTREAM_COMMIT}:benchmarks/cua_world/environments/{env_name}/env.json',
    ], text=True)
    (job / 'original_env.json').write_text(original)
    spec = json.loads(original)
    spec['runner'] = runner
    if runner == 'docker':
        spec['image'] = IMAGE
        spec['security']['runtime'] = 'runc'
    for mount in spec.get('mounts', []):
        mount['source'] = str(workspace / mount['source'])
    spec.setdefault('recording', {})['output_dir'] = str(job / 'episodes')
    spec['version'] = spec.get('version', '1.0') + '-' + batch.name
    write_json(env_dir / 'env.json', spec)
    write_json(workspace / '.mcp.json', {'mcpServers': {'visual-grounding': {
        'command': str(PYTHON), 'args': [str(workspace / 'local/isolation/vm/screenshot_mcp.py')]
    }}})
    (workspace / '.claude').mkdir(exist_ok=True)
    settings = workspace / '.claude/settings.local.json'
    settings.touch(mode=0o600)
    settings.chmod(0o600)
    write_json(settings, {
        'enabledMcpjsonServers': ['visual-grounding'], 'model': 'deepseek-flash',
    })
    cli_config = job / 'claude-config'
    cli_config.mkdir(exist_ok=True)
    write_json(cli_config / 'settings.json', {'skipDangerousModePermissionPrompt': True})
    write_json(cli_config / '.claude.json', {'hasCompletedOnboarding': True,
                                          'lastOnboardingVersion': '2.1.229'})
    wrapper = job / 'claude'
    wrapper.write_text(
        f'#!{PYTHON}\nimport sys\nfrom pathlib import Path\nsys.path.insert(0,{str(ROOT)!r})\n'
        'from local.isolation.vm.claude_retry import run\n'
        f'raise SystemExit(run(Path({str(ROOT / "local/runtime/tools/claude")!r}),'
        f'sys.argv[1:],Path({str(job)!r})))\n'
    )
    wrapper.chmod(0o700)
    cache = job / 'qemu_cache'
    cache.mkdir(exist_ok=True)
    base = ROOT / 'local/runtime/qemu/secure-cache/base_ubuntu_gnome.qcow2'
    if not (cache / base.name).exists():
        (cache / base.name).symlink_to(base)
    return job


def runtime_command(job, command, environ):
    """Use the host network and daemon, with standard Docker KVM device access."""
    config = json.loads((job / 'config.json').read_text())
    name = f'ga-build-{job.parent.name}-{config["env"]}'
    docker = ['docker', 'run', '--rm', '--init', '--name', name, '--network', 'host',
              '--device', '/dev/kvm', '--group-add', str(os.stat('/dev/kvm').st_gid),
              '--group-add', str(os.stat('/var/run/docker.sock').st_gid),
              '--mount', f'type=bind,src={ROOT},dst={ROOT}',
              '--mount', 'type=bind,src=/tmp,dst=/tmp',
              '--mount', 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock',
              '--workdir', str(job / 'workspace')]
    keys = ['PATH', 'PYTHONPATH', 'PYTHONHASHSEED', 'PYTHONUNBUFFERED',
            'GYM_ANYTHING_RUNNER', 'GYM_ANYTHING_QEMU_CACHE', 'GYM_ANYTHING_QEMU_WORK_DIR',
            'GYM_ANYTHING_QEMU_SSH_KEY', 'GYM_SCREENSHOT_AUDIT', 'CLAUDE_CONFIG_DIR',
            'CLAUDE_CODE_EFFORT_LEVEL', 'DISABLE_AUTOUPDATER',
            'ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
            'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
            'CLAUDE_CODE_SUBAGENT_MODEL',
            'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY']
    for key in keys:
        if key in environ:
            docker += ['--env', key]
    return [*docker, RUNTIME_IMAGE, *command]


def launch(job, resume_phase=0, runtime='host'):
    config = json.loads((job / 'config.json').read_text())
    workspace = job / 'workspace'
    environ = dict(os.environ)
    environ.update(
        PATH=f"{ROOT / 'local/runtime/qemu/bin'}:{ROOT / '.venv/bin'}:{ROOT / 'local/runtime/tools'}:" + environ['PATH'],
        PYTHONPATH=f"{workspace / 'src'}:{workspace}", PYTHONHASHSEED='42',
        PYTHONUNBUFFERED='1',
        GYM_ANYTHING_RUNNER=config['runner'],
        GYM_ANYTHING_QEMU_CACHE=str(job / 'qemu_cache'),
        GYM_ANYTHING_QEMU_WORK_DIR=str(ROOT / 'local/q' / job.parent.name / str([x[2] for x in JOBS].index(config['env']) + 1)),
        GYM_ANYTHING_QEMU_SSH_KEY=str(ROOT / 'local/runtime/qemu/ssh/key'),
        GYM_SCREENSHOT_AUDIT=str(job / 'screenshot-api.jsonl'),
        CLAUDE_CONFIG_DIR=str(job / 'claude-config'),
        CLAUDE_CODE_EFFORT_LEVEL='high', DISABLE_AUTOUPDATER='1',
    )
    environ.pop('GYM_ANYTHING_DOCKER_NETWORK', None)
    for key in ['ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
                'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
                'CLAUDE_CODE_SUBAGENT_MODEL']:
        environ[key] = 'deepseek-flash'
    command = [str(PYTHON), str(Path(__file__).resolve()), '--job', str(job),
               '--resume-phase', str(resume_phase)]
    if runtime == 'docker':
        command = runtime_command(job, command, environ)
    with (job / 'driver.log').open('a') as log:
        proc = subprocess.Popen(command,
                                cwd=workspace, env=environ, stdout=log, stderr=subprocess.STDOUT)
        write_json(job / 'process.json', {'pid': proc.pid, 'started': time.time(),
                                         'workspace': str(workspace)})
        rc = proc.wait()
    write_json(job / 'exit.json', {'returncode': rc, 'finished': datetime.now(timezone.utc).isoformat()})
    return {'env': config['env'], 'returncode': rc}


def main():
    os.umask(0o077)
    seed_everything(42)
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', type=Path)
    parser.add_argument('--resume-phase', type=int, default=0)
    parser.add_argument('--batch', type=Path, help='Resume preparation before any jobs have launched')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--runtime', choices=['host', 'docker'], default='host')
    args = parser.parse_args()
    if args.job:
        return job_main(args.job.resolve(), args.resume_phase)
    batch = args.batch or ROOT / 'local/outputs' / ('seeds_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    batch = batch.resolve()
    batch.mkdir(exist_ok=True)
    if any(batch.glob("*/driver.log")):
        raise RuntimeError("Batch already launched; preserve its sessions")
    base = ROOT / 'local/runtime/qemu/secure-cache/base_ubuntu_gnome.qcow2'
    if not base.exists():
        raise FileNotFoundError(base)
    canonical = (ROOT.parent.parent / 'user-inputs.txt').read_text().splitlines()
    for goal, line in enumerate([1, 2, 3, 4, 6], 1):
        assert (ROOT / f'local/requirements/goal_{goal}.txt').read_text().strip() == canonical[line-1].strip()
    (batch / 'user-inputs.txt').write_text('\n'.join(canonical) + '\n')
    write_json(batch / 'batch.json', {
        'upstream_commit': UPSTREAM_COMMIT,
        'jobs': JOBS, 'seed': 42, 'parallel_jobs': 10, 'stage': 'propose',
        'remote_seed': None, 'image': IMAGE, 'cli_version': '2.1.229',
        'count_per_software': 10, 'timeout_per_phase': 36000,
        'proposer_sampling': 'CLI/provider defaults; no sampling override',
        'thinking': True, 'reasoning_effort': 'high', 'task_type': 'enterprise',
        'max_api_retries': 3, 'retry_delay_seconds': 5,
        'runtime': args.runtime,
        'execution_policy': 'official network defaults; public-key-only Linux SSH; same-session API retry',
    })
    jobs = [prepare(batch, item) for item in JOBS]
    shutil.copy2(Path(__file__), batch / 'seed_batch.py')
    shutil.copy2(ROOT / 'local/generate.py', batch / 'generate.py')
    shutil.copy2(ROOT / 'local/isolation/vm/claude_retry.py', batch / 'claude_retry.py')
    shutil.copy2(ROOT / 'local/requirements.lock', batch / 'requirements.lock')
    write_json(batch / 'source.json', {
        'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'sha256': {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in [
            'local/seed_batch.py', 'local/generate.py', 'local/deepseek-settings.json',
            'local/isolation/vm/claude_retry.py', 'local/isolation/vm/screenshot_mcp.py',
            'src/gym_anything/runtime/runners/qemu_apptainer.py',
            'src/gym_anything/runtime/runners/qemu_native.py',
            'src/gym_anything/runtime/runners/qemu_ssh.py',
            'src/gym_anything/runtime/runners/docker.py',
            'extras/research/task_generation/propose_and_amplify/pipeline/propose_cc.py',
        ]},
    })
    if args.prepare_only:
        print(f'Prepared 10 jobs without model calls: {batch}', flush=True)
        return 0
    check = [str(PYTHON), '-c', 'import os,fcntl; f=os.open("/dev/kvm",os.O_RDWR); assert fcntl.ioctl(f,0xAE00,0)==12; os.close(f)']
    if args.runtime == 'docker':
        check = runtime_command(jobs[0], check, dict(os.environ))
    subprocess.run(check, check=True)
    version = subprocess.check_output([str(ROOT / 'local/runtime/tools/claude'), '--version'], text=True)
    assert version.strip() == '2.1.229 (Claude Code)'
    (ROOT / 'local/outputs/latest_seed_batch.txt').write_text(str(batch) + '\n')
    print(f'Starting 10 parallel jobs: {batch}', flush=True)
    with ThreadPoolExecutor(max_workers=10) as pool:
        pending = {pool.submit(launch, job, runtime=args.runtime) for job in jobs}
        results = []
        while pending:
            done, pending = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
            results.extend(future.result() for future in done)
            states = {}
            for job in jobs:
                path = job / 'status.json'
                if path.exists():
                    try:
                        status = json.loads(path.read_text())
                    except json.JSONDecodeError:
                        continue  # A phase recorder is currently replacing the status.
                    states[job.name] = {k: status[k] for k in ['phase', 'started', 'finished', 'returncode', 'timeout'] if k in status}
            with (batch / 'monitor.jsonl').open('a') as log:
                log.write(json.dumps({'time': time.time(), 'jobs': states,
                                     'disk_free_bytes': shutil.disk_usage(batch).free}) + '\n')
    write_json(batch / 'exits.json', results)
    return int(any(result['returncode'] for result in results))


if __name__ == '__main__':
    raise SystemExit(main())
