"""Resume transient API failures in the same evaluation session and action budget."""
import json
import os
from pathlib import Path
import subprocess
import select
import sys
import time


def retryable(result):
    if not result or result.get("terminal_reason") != "api_error":
        return False
    status = result.get("api_error_status")
    return status is None or status in (408, 409, 429) or isinstance(status, int) and 500 <= status < 600


def run(args, prompt, logs, binary="claude", delay=5):
    args = list(args)
    session = args[args.index("--resume")+1] if "--resume" in args else None
    prefix = os.environ.get("EVAL_ATTEMPT_PREFIX", "api_attempt")
    for attempt in range(4):
        result = None
        command = [binary, *args]
        if attempt:
            if "--resume" in command:
                command[command.index("--resume")+1] = session
            else:
                command += ["--resume", session]
        with (logs / f"{prefix}_{attempt}.jsonl").open("w") as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            process.stdin.write(prompt)
            process.stdin.close()
            for line in process.stdout:
                log.write(line)
                log.flush()
                # The CLI can mark inherited pipes nonblocking; image events exceed pipe capacity.
                remaining = memoryview(line.encode())
                while remaining:
                    try:
                        remaining = remaining[os.write(sys.stdout.fileno(), remaining):]
                    except BlockingIOError:
                        select.select([], [sys.stdout.fileno()], [])
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                session = event.get("session_id", session)
                if event.get("type") == "result":
                    result = event
            code = process.wait()
            process.stdout.close()
        again = retryable(result) and bool(session) and attempt < 3
        with (logs / "api-retries.jsonl").open("a") as log:
            log.write(json.dumps(dict(attempt=attempt, session_id=session, returncode=code,
                                      terminal_reason=result.get("terminal_reason") if result else None,
                                      api_error_status=result.get("api_error_status") if result else None,
                                      is_error=result.get("is_error") if result else None,
                                      retry_scheduled=again, time=time.time())) + "\n")
        if not again:
            return code
        prompt = "Continue the same task interrupted by the API error from this saved conversation, preserving work already done."
        time.sleep(delay)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:], sys.stdin.read(), Path("/logs")))
