"""Retry transient Claude API failures inside the original phase's process group."""
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import threading
import sys
import time

MAX_RETRIES = 3
CONTINUE = (
    'Continue the request interrupted by the API error from this saved conversation. '
    'Complete the same request, preserving work already done; do not start a new batch.'
)


def retryable(result):
    if not result or result.get('terminal_reason') != 'api_error':
        return False
    status = result.get('api_error_status')
    return status is None or status in (408, 409, 429) or (
        isinstance(status, int) and 500 <= status < 600
    )


def resume_args(args, session):
    result = list(args)
    if '--session-id' in result:
        index = result.index('--session-id')
        result[index:index+2] = ['--resume', session]
    else:
        result[result.index('--resume')+1] = session
    result[result.index('-p')+1] = CONTINUE
    return result


def run(binary, args, job, *, delay=5):
    source = Path(__file__).resolve().parents[3] / 'extras/research/task_generation/propose_and_amplify/pipeline/propose_cc.py'
    # Load the official cleanup helper without initializing the package's model SDKs.
    _kill_process_group = runpy.run_path(str(source))['_kill_process_group']

    status = json.loads((job/'status.json').read_text())
    phase = status['phase']
    session_flag = '--session-id' if '--session-id' in args else '--resume'
    session = args[args.index(session_flag)+1]
    process = None

    def terminate(signum, frame):
        # The outer official timeout must also stop the isolated attempt group.
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        raise SystemExit(128+signum)

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        for attempt in range(MAX_RETRIES+1):
            result = None
            with (job/f'phase_{phase}_attempt_{attempt}.jsonl').open('x') as log:
                process = subprocess.Popen([str(binary), *args], stdout=subprocess.PIPE,
                                           text=True, bufsize=1, start_new_session=True)

                def forward():
                    nonlocal result
                    for line in process.stdout:
                        log.write(line)
                        log.flush()
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(event, dict) and event.get('type') == 'result':
                            result = event

                reader = threading.Thread(target=forward, daemon=True)
                reader.start()
                try:
                    returncode = process.wait()
                finally:
                    _kill_process_group(process.pid)
                    process.wait()
                    reader.join()
                    process.stdout.close()
            again = retryable(result) and attempt < MAX_RETRIES
            with (job/'api-retries.jsonl').open('a') as log:
                log.write(json.dumps({
                    'time': time.time(), 'phase': phase, 'attempt': attempt,
                    'session_id': session, 'returncode': returncode,
                    'terminal_reason': result.get('terminal_reason') if result else None,
                    'api_error_status': result.get('api_error_status') if result else None,
                    'retry_scheduled': again,
                    'retries_exhausted': retryable(result) and not again,
                })+'\n')
            if not again:
                return returncode
            args = resume_args(args, session)
            time.sleep(delay)
    finally:
        signal.signal(signal.SIGTERM, previous)


def main():
    if sys.argv[1:] == ['--install']:
        install()
        return 0
    binary = Path('/home/ga/.local/bin/claude-original')
    args = sys.argv[1:]
    # Other invocations (version/help, interactive CLI) retain their normal behavior.
    if ('-p' not in args or '--output-format' not in args or
            args[args.index('--output-format')+1] != 'stream-json' or
            not any(flag in args for flag in ('--session-id', '--resume'))):
        os.execv(str(binary), [str(binary), *args])
    return run(binary, args, Path('/home/ga/job'))


def install():
    root = Path(__file__).resolve().parents[3]
    binary = Path('/home/ga/.local/bin/claude')
    original = binary.with_name('claude-original')
    if not original.exists():
        os.link(binary, original)
    version = subprocess.check_output([str(original), '--version'], text=True).strip()
    if not version.startswith('2.1.229 '):
        raise RuntimeError('Unexpected Claude Code version')
    temporary = binary.with_name('claude.new')
    temporary.write_text(
        f'#!{root}/.venv/bin/python\nimport sys\nsys.path.insert(0,{str(root)!r})\n'
        'from local.isolation.vm.claude_retry import main\nraise SystemExit(main())\n'
    )
    temporary.chmod(0o755)
    temporary.replace(binary)
    job = Path('/home/ga/job')
    state = json.loads((job/'status.json').read_text()) if (job/'status.json').exists() else None
    (job/'retry-policy.json').write_text(json.dumps({
        'installed': time.time(), 'max_retries': MAX_RETRIES, 'delay_seconds': 5,
        'scope': 'New CLI invocations; active invocation remains unchanged',
        'status_at_install': state, 'cli_version': version,
    }, indent=2)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
