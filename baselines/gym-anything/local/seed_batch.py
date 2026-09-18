"""Run ten isolated ten-seed proposer jobs and retain their evidence."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import shutil
import shlex
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'
IMAGE = 'gym-anything-local/ubuntu-gnome-highres:20260915'
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
        '--claude-bin', '/home/zangyihe/.local/bin/claude', *resume_args,
    ])


def prepare(batch, item):
    goal, software, env_name, runner = item
    job = batch / env_name
    job.mkdir(exist_ok=True)
    workspace = job / 'workspace'
    if not workspace.exists():
        reference = batch / JOBS[0][2] / 'workspace/.git'
        clone_args = ['--reference', str(reference), '--dissociate'] if reference.exists() else []
        subprocess.run(['git', 'clone', '--quiet', *clone_args, UPSTREAM_URL, str(workspace)], check=True)
        subprocess.run(['git', 'checkout', '--quiet', '-b', 'seed-generation', UPSTREAM_COMMIT], cwd=workspace, check=True)
    for rel in ['src/gym_anything/runtime/runners/docker.py', 'local/generate.py',
                'extras/research/task_generation/propose_and_amplify/pipeline/propose_cc.py']:
        destination = workspace / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, destination)
    if not (workspace / 'local/.env').exists():
        (workspace / 'local/.env').symlink_to(ROOT / 'local/.env')
    if not (workspace / '.venv').exists():
        (workspace / '.venv').symlink_to(ROOT / '.venv', target_is_directory=True)
    with (workspace / '.git/info/exclude').open('a') as exclusions:
        exclusions.write('\n/local/.env\n/.claude/settings.local.json\n/.venv\n')
    shutil.copy2(ROOT / f'local/requirements/goal_{goal}.txt', job / 'requirement.txt')
    env_dir = workspace / 'benchmarks/cua_world/environments' / env_name
    config = {'goal': goal, 'software': software, 'env': env_name, 'runner': runner,
              'seed': 42, 'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com',
              'count': 10, 'timeout_per_phase': 36000, 'task_type': 'enterprise',
              'original_tasks': sorted(p.name for p in (env_dir / 'tasks').iterdir() if p.is_dir())}
    write_json(job / 'config.json', config)
    shutil.copy2(ROOT / 'benchmarks/cua_world/environments' / env_name / 'env.json', job / 'original_env.json')
    spec = json.loads((job / 'original_env.json').read_text())
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
        'command': str(PYTHON), 'args': [str(workspace / 'extras/research/software_as_env/creation_audit/mcp/screenshot_query_mcp.py')]
    }}})
    (workspace / '.claude').mkdir(exist_ok=True)
    from dotenv import dotenv_values
    api = dotenv_values(ROOT / 'local/.env')
    settings = workspace / '.claude/settings.local.json'
    settings.touch(mode=0o600)
    settings.chmod(0o600)
    write_json(settings, {
        'enabledMcpjsonServers': ['visual-grounding'], 'model': api['DEEPSEEK_MODEL'],
        'env': {
            'ANTHROPIC_BASE_URL': api['DEEPSEEK_BASE_URL'].rstrip('/') + '/anthropic',
            'ANTHROPIC_AUTH_TOKEN': api['DEEPSEEK_API_KEY'],
            'ANTHROPIC_API_KEY': api['DEEPSEEK_API_KEY'],
            **{key: api['DEEPSEEK_MODEL'] for key in [
                'ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
                'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
                'CLAUDE_CODE_SUBAGENT_MODEL',
            ]},
        },
    })
    return job


def launch(job, resume_phase=0, kvm=None):
    config = json.loads((job / 'config.json').read_text())
    workspace = job / 'workspace'
    environ = dict(os.environ)
    environ.update(
        PATH=f"{ROOT / 'local/runtime/qemu/bin'}:{ROOT / '.venv/bin'}:" + environ['PATH'],
        PYTHONPATH=f"{workspace / 'src'}:{workspace}", PYTHONHASHSEED='42',
        PYTHONUNBUFFERED='1',
        GYM_ANYTHING_RUNNER=config['runner'], GYM_ANYTHING_DOCKER_NETWORK='gym-anything-local',
        GYM_ANYTHING_QEMU_CACHE=str(job.parent / 'qemu_cache'),
        GYM_ANYTHING_QEMU_WORK_DIR=str(ROOT / 'local/q' / str([x[2] for x in JOBS if x[3] == 'qemu'].index(config['env']) + 1) if config['runner'] == 'qemu' else 'desktop'),
    )
    command = [str(PYTHON), str(Path(__file__).resolve()), '--job', str(job),
               '--resume-phase', str(resume_phase)]
    if kvm is None:
        kvm = config['runner'] == 'qemu'
    if kvm:
        command = ['sg', 'kvm', '-c', shlex.join(command)]
    with (job / 'driver.log').open('a') as log:
        proc = subprocess.Popen(command,
                                cwd=workspace, env=environ, stdout=log, stderr=subprocess.STDOUT)
        rc = proc.wait()
    write_json(job / 'exit.json', {'returncode': rc, 'finished': datetime.now(timezone.utc).isoformat()})
    return {'env': config['env'], 'returncode': rc}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', type=Path)
    parser.add_argument('--resume-phase', type=int, default=0)
    parser.add_argument('--batch', type=Path, help='Resume preparation before any jobs have launched')
    args = parser.parse_args()
    if args.job:
        return job_main(args.job.resolve(), args.resume_phase)
    batch = args.batch or ROOT / 'local/outputs' / ('seeds_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    batch = batch.resolve()
    batch.mkdir(exist_ok=True)
    if any(batch.glob("*/driver.log")):
        raise RuntimeError("Batch already launched; preserve its sessions")
    cache = batch / 'qemu_cache'
    cache.mkdir(exist_ok=True)
    base = ROOT / 'local/runtime/qemu/cache/base_ubuntu_gnome.qcow2'
    if not base.exists():
        raise FileNotFoundError(base)
    if not (cache / base.name).exists():
        (cache / base.name).symlink_to(base)
    write_json(batch / 'batch.json', {
        'upstream_commit': UPSTREAM_COMMIT,
        'jobs': JOBS, 'seed': 42, 'parallel_jobs': 10, 'stage': 'propose',
        'remote_seed': None, 'image': IMAGE, 'cli_version': '2.1.229',
        'count_per_software': 10, 'timeout_per_phase': 36000,
        'proposer_sampling': 'CLI/provider defaults; no sampling override',
        'execution_policy': 'upstream run_claude; normal CLI and MCP discovery; observation only',
    })
    jobs = [prepare(batch, item) for item in JOBS]
    shutil.copy2(Path(__file__), batch / 'seed_batch.py')
    shutil.copy2(ROOT / 'local/generate.py', batch / 'generate.py')
    (ROOT / 'local/outputs/latest_seed_batch.txt').write_text(str(batch) + '\n')
    print(f'Starting 10 parallel jobs: {batch}', flush=True)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(launch, jobs))
    write_json(batch / 'exits.json', results)
    return int(any(result['returncode'] for result in results))


if __name__ == '__main__':
    raise SystemExit(
        'Disabled: this entry runs model-issued commands without a verified host boundary. '
        'See local/isolation/security.md before running another batch.'
    )
