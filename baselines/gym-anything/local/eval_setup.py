"""Prepare guest-readable mount copies and observe official initialization."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import time
from unittest.mock import patch

CHECK_IMAGE = 'gym-anything-local/ubuntu-gnome-highres:20260915'
READ_CHECK = '''import os,pathlib,sys
for root in map(pathlib.Path,sys.argv[1:]):
    paths=[root]
    if root.is_dir():
        for directory,dirs,files in os.walk(root,onerror=lambda e: (_ for _ in ()).throw(e)):
            paths.extend(pathlib.Path(directory)/name for name in dirs+files)
    for path in paths:
        required=os.R_OK | (os.X_OK if path.is_dir() else 0)
        if not os.access(path,required):raise PermissionError(str(path))
print("All mounted inputs readable by guest ga")
'''


def prepare_environment(source, destination, episodes):
    source, destination = Path(source), Path(destination)
    spec = json.loads((source / 'env.json').read_text())
    destination.mkdir()
    mounts = spec.get('mounts', [])
    # Task definitions are copied too, keeping the source release immutable.
    for path in source.iterdir():
        if path.name in {'env.json', 'artifacts'}:
            continue
        target = destination / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
    changed = []
    for mount in mounts:
        original = Path(mount['source']).resolve()
        relative = original.relative_to(source.resolve())
        target = destination / relative
        if not original.exists():
            # Docker's directory bind mount creates a missing source directory.
            target.mkdir(parents=True, exist_ok=True)
        for path in [target, *target.rglob('*')] if target.is_dir() else [target]:
            mode = stat.S_IMODE(path.stat().st_mode)
            # Staging inputs must be readable; never invent an executable script.
            readable = mode | (0o555 if path.is_dir() else 0o444)
            if path.is_file() and mode & stat.S_IXUSR:
                readable |= 0o111
            if readable != mode:
                path.chmod(readable)
                changed.append({'path': str(path.relative_to(destination)),
                                'before': oct(mode), 'after': oct(readable)})
        mount['source'] = str(target)
    spec['recording']['output_dir'] = str(episodes)
    (destination / 'env.json').write_text(json.dumps(spec, indent=2) + '\n')
    return spec, changed


def check_mounts(spec, report):
    """Use the real desktop image's ga account, without starting its desktop."""
    command = ['docker', 'run', '--rm', '--network', 'none', '--read-only',
               '--user', 'ga', '--entrypoint', 'python3']
    targets = []
    for index, mount in enumerate(spec.get('mounts', [])):
        target = f'/inputs/{index}'
        command += ['--mount', f'type=bind,src={mount["source"]},dst={target},readonly']
        targets.append(target)
    result = subprocess.run([*command, CHECK_IMAGE, '-c', READ_CHECK, *targets],
                            capture_output=True, text=True, timeout=120)
    Path(report).write_text(json.dumps(dict(returncode=result.returncode,
        stdout=result.stdout, stderr=result.stderr, guest_user='ga'), indent=2) + '\n')
    result.check_returncode()


@contextmanager
def observe_initialization(env, run):
    """Record, but do not change, reset calls, return codes or exceptions."""
    run = Path(run)
    reset, execute = env.reset, env._runner.exec

    def observed_reset(*args, **kwargs):
        directory = run / 'initialization'
        directory.mkdir(exist_ok=True)

        def observed_exec(command, *positional, **options):
            started = time.time()
            event = dict(started=started, command_sha256=hashlib.sha256(command.encode()).hexdigest())
            try:
                result = execute(command, *positional, **options)
                event['returncode'] = result
                return result
            except Exception as error:
                event['error'] = type(error).__name__
                if hasattr(error, 'timeout'):
                    event['timeout_seconds'] = error.timeout
                raise
            finally:
                event['elapsed_seconds'] = time.time() - started
                with (directory / 'commands.jsonl').open('a') as log:
                    log.write(json.dumps(event) + '\n')
        try:
            with patch.object(env._runner, 'exec', observed_exec):
                return reset(*args, **kwargs)
        finally:
            copied = {}
            for name in ('env_setup_pre_start.log', 'env_setup_post_start.log', 'task_pre_task.log'):
                try:
                    env._runner.copy_from('/home/ga/' + name, str(directory / name))
                    copied[name] = (directory / name).exists()
                except Exception as error:
                    copied[name] = type(error).__name__
            (directory / 'logs.json').write_text(json.dumps(copied, indent=2) + '\n')

    with patch.object(env, 'reset', observed_reset):
        yield env
