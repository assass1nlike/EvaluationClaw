"""Evaluate every final seed once, using a bounded queue of official single runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from local.eval_runtime import RecordedDockerSandbox, check_host, infrastructure_errors, NetworkPreflightError

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.replace(path)


def collect_result(job, returncode):
    run = Path(job["run"])
    summaries = sorted(run.glob("episodes/*/summary.json"))
    summary = json.loads(summaries[-1].read_text()) if summaries else {}
    initialization = run / "initialization/commands.jsonl"
    setup_events = [json.loads(line) for line in initialization.read_text().splitlines()] if initialization.exists() else []
    setup_issues = [e for e in setup_events if e.get("error") or e.get("returncode") not in (None, 0)]
    attempts = sorted(run.glob("episodes/*/cli_harness/api-retries.jsonl"))
    events = [json.loads(line) for path in attempts for line in path.read_text().splitlines()]
    result = dict(env=job["env"], task=job["task"], returncode=returncode,
                  steps=summary.get("steps"), verifier=summary.get("verifier"),
                  cli=events[-1] if events else None, api_retries=max(0, len(events)-1),
                  infrastructure_errors=infrastructure_errors(run), initialization_issues=setup_issues,
                  summary=str(summaries[-1]) if summaries else None, finished=time.time())
    write_json(run / "result.json", result)
    return result


def recover_setup(batch, ids):
    config = json.loads((batch / "config.json").read_text())
    jobs = [dict(job) for job in config["jobs"] if job["id"] in ids]
    if len(jobs) != len(ids):
        raise ValueError("Unknown recovery job")
    recovery = batch / "recovery"
    recovery.mkdir(exist_ok=False)
    for job in jobs:
        original = Path(job["run"])
        if list(original.glob("episodes/*/cli_harness")):
            raise ValueError("Do not reset a task whose model has already started")
        result = json.loads((original / "result.json").read_text())
        if result["returncode"] == 0:
            raise ValueError("Recovery requires a failed infrastructure attempt")
        job["run"] = str(recovery / job["id"])
    write_json(recovery / "config.json", dict(reason="inotify limit exhausted before model invocation", jobs=jobs))
    running, finished = [], []
    while jobs or running:
        original = json.loads((batch / "progress.json").read_text())
        for process, job, log in list(running):
            code = process.poll()
            if code is not None:
                log.close()
                finished.append(collect_result(job, code))
                running.remove((process, job, log))
        if jobs and original["queued"] == 0 and original["running"] + len(running) < config["parallel"]:
            job = jobs.pop(0)
            log = (recovery / f'{job["id"]}.log').open("w")
            process = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-u", str(ROOT / "local/evaluate.py"),
                                        "--source", job["source"], "--task", job["task"], "--run", job["run"]],
                                       stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
            running.append((process, job, log))
        state = dict(time=time.time(), queued=len(jobs), running=len(running), results=finished)
        write_json(recovery / "progress.json", state)
        time.sleep(5)
    write_json(recovery / "completion.json", state)


class ExistingRun:
    """Observe a worker left running by a stopped queue controller."""
    def __init__(self, pid, run):
        self.pid = pid
        self.run = Path(run)

    def poll(self):
        try:
            command = (Path('/proc') / str(self.pid) / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            command = []
        if str(self.run).encode() in command and b'--worker' not in command:
            return None
        result = self.run / 'exit.json'
        return json.loads(result.read_text())['returncode'] if result.exists() else 1


def main():
    os.umask(0o077)
    from local.eval_docker import use_dedicated_docker
    use_dedicated_docker()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--parallel", type=int, default=30)
    parser.add_argument("--recover-setup", nargs="+")
    parser.add_argument("--resume", action="store_true", help="Adopt active workers and dispatch only queued tasks")
    parser.add_argument("--retry-from", type=Path, help="Original batch whose task IDs are retained")
    parser.add_argument("--ids", nargs="+", help="Explicit task IDs to rerun in fresh directories")
    parser.add_argument("--alongside", type=Path, help="Share the parallel limit with a fully dispatched batch")
    args = parser.parse_args()
    if args.parallel < 1:
        parser.error("--parallel must be positive")
    batch = args.batch.resolve()
    if args.recover_setup:
        return recover_setup(batch, args.recover_setup)
    if args.resume:
        config = json.loads((batch / "config.json").read_text())
        if (Path('/proc') / str(config['pid']) / 'cmdline').exists():
            command = (Path('/proc') / str(config['pid']) / 'cmdline').read_bytes().split(b'\0')
            if str(batch).encode() in command:
                raise RuntimeError("The previous queue controller is still running")
        check_host()
        state = json.loads((batch / "progress.json").read_text())
        jobs = config['jobs']
        by_id = {job['id']: job for job in jobs}
        active_ids = {entry['id'] for entry in state['active']}
        next_index = len(jobs) - state['queued']
        assert len(active_ids) == state['running']
        assert state['running'] + state['finished'] == next_index
        if any(Path(job['run']).exists() for job in jobs[next_index:]):
            raise RuntimeError("A queued task already has output; refusing duplicate evaluation")
        running = {entry['id']: (ExistingRun(entry['pid'], by_id[entry['id']]['run']),
                                  by_id[entry['id']], None) for entry in state['active']}
        previous_pid = config['pid']
        config['pid'] = os.getpid()
        write_json(batch / 'config.json', config)
        with (batch / 'resumes.jsonl').open('a') as log:
            log.write(json.dumps(dict(time=time.time(), previous_pid=previous_pid, pid=os.getpid(),
                                      active=state['active'], queued=state['queued'])) + '\n')
        revision = batch / 'source' / time.strftime('resume_%Y%m%d_%H%M%S')
        revision.mkdir()
        for name in ('evaluate_batch.py', 'evaluate.py', 'eval_runtime.py', 'eval_setup.py', 'seed_batch.py'):
            shutil.copy2(ROOT / 'local' / name, revision / name)
        return run_queue(batch, jobs, config['parallel'], running, state['results'], next_index,
                         config.get('alongside'))
    if args.retry_from:
        original = json.loads((args.retry_from / 'config.json').read_text())
        if not args.ids or len(args.ids) != len(set(args.ids)):
            parser.error("--retry-from requires distinct --ids")
        by_id = {job['id']: job for job in original['jobs']}
        if set(args.ids) - by_id.keys():
            parser.error("Unknown retry task ID")
        args.source = Path(original['source'])
    elif args.ids:
        parser.error("--ids requires --retry-from")
    if args.alongside:
        args.alongside = args.alongside.resolve()
        if json.loads((args.alongside / 'progress.json').read_text())['queued']:
            parser.error("The alongside batch must have dispatched its entire queue")
    if args.source is None:
        parser.error("--source is required for a new batch")
    preflight = check_host()
    batch.mkdir(parents=True, exist_ok=False)
    (batch / "jobs").mkdir()
    (batch / "source").mkdir()
    for name in ("evaluate.py", "evaluate_batch.py", "eval_api_retry.py", "eval_runtime.py", "prepare_eval_base.py",
                 "eval_docker.py", "eval_proxy.py", "seed_batch.py", "eval_setup.py"):
        shutil.copy2(ROOT / "local" / name, batch / "source" / name)
    for name in ("env.py", "runtime/runners/qemu_ports.py", "runtime/runners/qemu_apptainer.py",
                 "runtime/runners/qemu_native.py"):
        target = batch / "source/gym_anything" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "src/gym_anything" / name, target)
    from evaluate import DeepSeekClaudeCodeAgent
    sandbox = RecordedDockerSandbox(DeepSeekClaudeCodeAgent({"model": "deepseek-flash"}).sandbox_spec(),
                                    batch / "preflight")
    sandbox.build()
    try:
        sandbox.start(9, "preflight-no-model", {})
        result = sandbox.exec("true", 30)
        if result.returncode:
            raise RuntimeError("Docker preflight command failed")
    finally:
        sandbox.stop()
    write_json(batch / "preflight.json", preflight)
    groups = []
    for manifest in sorted(args.source.resolve().glob("*_env/workspace/benchmarks/cua_world/environments/*/tasks/seed_tasks.json")):
        source = manifest.parent.parent
        if source.name != source.parents[4].name:
            continue
        tasks = json.loads(manifest.read_text())
        if len(tasks) != len(set(tasks)):
            raise ValueError(f"Duplicate tasks: {manifest}")
        group = []
        for task in tasks:
            task_dir = source / "tasks" / task
            hashes = {name: hashlib.sha256((task_dir / name).read_bytes()).hexdigest()
                      for name in ("task.json", "verifier.py")}
            group.append(dict(source=str(source), env=source.name, task=task, hashes=hashes))
        groups.append(group)
    jobs = [group[index] for index in range(max(map(len, groups))) for group in groups if index < len(group)]
    for index, job in enumerate(jobs):
        job.update(id=f"{index+1:03d}", run=str(batch / "jobs" / f"{index+1:03d}"))
    if args.retry_from:
        jobs = [dict(by_id[task_id], run=str(batch / 'jobs' / task_id)) for task_id in args.ids]
        for job in jobs:
            for name, expected in job['hashes'].items():
                path = Path(job['source']) / 'tasks' / job['task'] / name
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise RuntimeError(f"Task changed since original run: {job['id']}/{name}")
    write_json(batch / "config.json", dict(source=str(args.source.resolve()), parallel=args.parallel,
                                          model="deepseek-flash", thinking=True, effort="high", seed=42,
                                          cli_version="2.1.229", cli_timeout_sec=28800, api_retries=3, jobs=jobs,
                                          retry_from=str(args.retry_from.resolve()) if args.retry_from else None,
                                          alongside=str(args.alongside) if args.alongside else None,
                                          pid=os.getpid(), started=time.time()))
    return run_queue(batch, jobs, args.parallel, {}, [], 0, args.alongside)


def alongside_active(batch):
    if batch is None:
        return []
    batch = Path(batch)
    state = json.loads((batch / 'progress.json').read_text())
    if state['queued']:
        raise RuntimeError("Alongside queue resumed dispatching; cannot safely share capacity")
    jobs = {job['id']: job for job in json.loads((batch / 'config.json').read_text())['jobs']}
    return [entry for entry in state['active']
            if ExistingRun(entry['pid'], jobs[entry['id']]['run']).poll() is None]


def run_queue(batch, jobs, parallel, running, finished, next_index, alongside=None):
    next_start = 0
    halted = False
    network_wait = False
    while (not halted and next_index < len(jobs)) or running:
        for job_id, (process, job, log) in list(running.items()):
            code = process.poll()
            if code is not None:
                if log is not None:
                    log.close()
                result = collect_result(job, code)
                finished.append(result)
                if result["infrastructure_errors"]:
                    halted = True
                del running[job_id]
        others = alongside_active(alongside)
        blocked_tasks = {(entry['env'], entry['task']) for entry in others}
        can_start = (not halted and next_index < len(jobs)
                     and len(running) + len(others) < parallel and time.time() >= next_start
                     and (jobs[next_index]['env'], jobs[next_index]['task']) not in blocked_tasks)
        if can_start:
            try:
                check_host()
            except NetworkPreflightError as error:
                next_start = time.time() + 60
                network_wait = True
                write_json(batch / "preflight-failure.json", {"error": str(error), "time": time.time(),
                                                              "retry_at": next_start})
            except RuntimeError as error:
                write_json(batch / "preflight-failure.json", {"error": str(error), "time": time.time()})
                halted = True
            else:
                if network_wait:
                    with (batch / "network-recoveries.jsonl").open("a") as log:
                        log.write(json.dumps({"time": time.time()}) + "\n")
                network_wait = False
        if can_start and not halted and not network_wait:
            job = jobs[next_index]
            log = (batch / "jobs" / f'{job["id"]}.log').open("w")
            process = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-u", str(ROOT / "local/evaluate.py"),
                                        "--source", job["source"], "--task", job["task"], "--run", job["run"]],
                                       stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
            running[job["id"]] = (process, job, log)
            next_index += 1
            next_start = time.time() + 5
        state = dict(time=time.time(), total=len(jobs), running=len(running), finished=len(finished),
                     alongside_running=len(others), combined_running=len(running)+len(others),
                     dispatch_halted=halted, network_wait=network_wait,
                     queued=len(jobs)-next_index,
                     active=[dict(id=j["id"], env=j["env"], task=j["task"], pid=p.pid) for p,j,_ in running.values()],
                     results=finished)
        write_json(batch / "progress.json", state)
        time.sleep(2)
    write_json(batch / ("halted.json" if halted else "completion.json"), state)
    return 2 if halted else 0


if __name__ == "__main__":
    raise SystemExit(main())
