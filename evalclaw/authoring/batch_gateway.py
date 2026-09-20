"""Job-scoped author API access and immutable interface-feedback attempts."""
import json
import os
import secrets
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from .batch_config import evaluation_config
from .package import _hashes, pack
from .readiness import exercise, prepare
from ..execution.contract_capabilities import binding_issues


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


class Gateway(ThreadingHTTPServer):
    def __init__(self, root, settings, tokens):
        self.root, self.settings, self.tokens = root, settings, tokens
        self.runtime_tokens = {}
        self.rate_lock = threading.Lock()
        self.log_lock = threading.Lock()
        self.job_locks = {job: threading.Lock() for job in tokens.values()}
        self.last = 0.
        super().__init__((settings.gateway_host, 0), Handler)

    def evaluation_bindings(self, job):
        bindings = {}
        for role, model, key_env in (
            ("task", self.settings.task_model, self.settings.task_key_env),
            ("laaj", self.settings.laaj_model, self.settings.laaj_key_env),
        ):
            if model is None:
                model, key_env = self.settings.evaluation_model, self.settings.evaluation_key_env
            if model.provider not in {"openai_responses", "openai_compatible"}:
                raise ValueError(f"Gateway does not support {model.provider}")
            token = secrets.token_urlsafe(32)
            self.runtime_tokens[token] = (job, role, model, key_env)
            bindings[role] = {"base_url": f"http://{self.settings.gateway_host}:{self.server_address[1]}/v1",
                              "api_key": token}
        return bindings

    def log(self, entry):
        with self.log_lock, (self.root / "requests.jsonl").open("a") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def feedback(self, job, request):
        operation = request.get("operation")
        if operation not in {"check", "prepare", "exercise"}:
            raise ValueError("Choose check, prepare or exercise")
        with self.job_locks[job]:
            directory = self.root / job
            checks = directory / "checks"
            checks.mkdir(exist_ok=True)
            attempt = checks / f"{len(list(checks.iterdir())) + 1:04d}"
            attempt.mkdir()
            try:
                work = directory / "work/package"
                # Record even structurally invalid attempts for reproducibility.
                import shutil
                _hashes(work)
                shutil.copytree(work, attempt / "submitted")
                suite = pack(attempt / "submitted", attempt / "bundle")
                config = evaluation_config(self.settings, attempt, credentials=False)
                issues = {task.id: binding_issues(task, config, config.targets[0]) for task in suite.tasks}
                if operation == "check":
                    result = {"status": "unsupported_binding" if any(issues.values()) else "valid",
                              "task_ids": [t.id for t in suite.tasks], "binding_issues": issues}
                else:
                    images = prepare(attempt / "bundle", suite, bind=True)
                    save(attempt / "images.json", images)
                    if operation == "prepare":
                        result = images
                    else:
                        cases = request.get("cases")
                        if not isinstance(cases, list):
                            raise ValueError("exercise requires a JSON list of calls in cases")
                        result = exercise(suite, cases)
            except Exception as exc:
                result = {"status": "invalid", "error": f"{type(exc).__name__}: {exc}"}
            save(attempt / "request.json", request)
            save(attempt / "result.json", result)
            return {"attempt": attempt.name, **result}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        job = self.server.tokens.get(token)
        runtime = self.server.runtime_tokens.get(token)
        if job is None and runtime is None:
            self.send_error(401)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Request must be a JSON object")
        except (ValueError, UnicodeDecodeError):
            self.send_error(400, "Request must be a JSON object")
            return
        if self.path == "/feedback":
            if runtime is not None:
                self.send_error(403)
                return
            try:
                result = self.server.feedback(job, payload)
            except ValueError as exc:
                result = {"status": "invalid", "error": str(exc)}
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            self.server.log({"job": job, "operation": "feedback", "status": result["status"]})
            return
        settings = self.server.settings
        if runtime:
            job, role, model, key_env = runtime
            model_name, base_url = model.model, model.base_url
            suffix = "/responses" if model.provider == "openai_responses" else "/chat/completions"
        else:
            role, model_name, base_url, key_env = "author", settings.author_model, settings.author_base_url, settings.author_key_env
            suffix = "/responses"
        if self.path != "/v1" + suffix:
            self.send_error(404)
            return
        if payload.get("model") != model_name:
            self.send_error(400, "Model differs from frozen experiment configuration")
            return
        with self.server.rate_lock:
            time.sleep(max(0, self.server.last + settings.request_spacing_seconds - time.monotonic()))
            self.server.last = time.monotonic()
            started = time.time()
        entry = {"job": job, "role": role, "started": started, "model": payload.get("model"),
                 "reasoning": payload.get("reasoning", {"effort": payload.get("reasoning_effort")}),
                 "request_bytes": len(body)}
        headers_sent = False
        try:
            with httpx.Client(timeout=600, proxy=settings.proxy, trust_env=False) as client:
                with client.stream("POST", base_url.rstrip("/") + suffix, content=body,
                    headers={"Authorization": "Bearer " + os.environ[key_env],
                             "Content-Type": "application/json"}) as response:
                    entry["status"] = response.status_code
                    self.send_response(response.status_code)
                    self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    headers_sent = True
                    for chunk in response.iter_bytes():
                        self.wfile.write(chunk)
                        self.wfile.flush()
        except Exception as exc:
            entry["error"] = type(exc).__name__ + ": " + str(exc)
            if not headers_sent:
                self.send_error(502, "Upstream connection failed")
        finally:
            entry["seconds"] = time.time() - started
            self.server.log(entry)


# Installed inside the author container; never expose Docker sockets or real keys.
AUTHOR_CLIENT = '''#!/usr/bin/python3
import json, os, pathlib, sys, urllib.request
if len(sys.argv) == 2 and sys.argv[1] in ('--help', '-h'):
    print('Usage: benchmark-package check|prepare|exercise /work/package [CASES.json]')
    raise SystemExit(0)
operation = sys.argv[1] if len(sys.argv) > 1 else 'check'
if len(sys.argv) < 3 or pathlib.Path(sys.argv[2]).resolve() != pathlib.Path('/work/package'):
    raise SystemExit('Usage: benchmark-package check|prepare|exercise /work/package [CASES.json]')
data = {'operation': operation}
if operation == 'exercise':
    data['cases'] = json.loads(pathlib.Path(sys.argv[3]).read_text())
request = urllib.request.Request(os.environ['AUTHOR_GATEWAY'] + '/feedback',
    data=json.dumps(data).encode(), headers={'Authorization': 'Bearer ' + os.environ['AUTHOR_TOKEN']})
result = json.loads(urllib.request.urlopen(request, timeout=7500).read())
print(json.dumps(result))
raise SystemExit(0 if result['status'] in ('valid', 'passed', 'prepared') else 1)
'''
