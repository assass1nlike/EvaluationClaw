"""Job-scoped author API access and immutable interface-feedback attempts."""
import json
import os
import secrets
import shutil
import tempfile
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


def response_models(stream, content_type):
    """Read provider identity fields without inspecting generated content."""
    models = set()

    def observe(value):
        if not isinstance(value, dict):
            return
        for obj in (value, value.get("response")):
            if isinstance(obj, dict) and isinstance(obj.get("model"), str):
                models.add(obj["model"])

    stream.seek(0)
    if "text/event-stream" in content_type:
        data = []
        def event():
            raw = b"\n".join(data).strip()
            if raw and raw != b"[DONE]":
                observe(json.loads(raw))
            data.clear()
        for line in stream:
            line = line.rstrip(b"\r\n")
            if not line:
                event()
            elif line.startswith(b"data:"):
                data.append(line[5:].lstrip(b" "))
        event()
    else:
        observe(json.load(stream))
    stream.seek(0)
    return models


class Gateway(ThreadingHTTPServer):
    def __init__(self, root, settings, tokens):
        self.root, self.settings, self.tokens = root, settings, tokens
        self.runtime_tokens = {}
        self.rate_lock = threading.Lock()
        self.log_lock = threading.Lock()
        self.job_locks = {job: threading.Lock() for job in tokens.values()}
        self.last_by_key = {}
        super().__init__((settings.gateway_host, 0), Handler)

    def acquire_key(self, key_env):
        candidates = [(name, os.environ[name]) for name in self.settings.key_pools.get(key_env, [key_env])]
        while True:
            with self.rate_lock:
                name, key = min(candidates, key=lambda candidate: self.last_by_key.get(candidate[1], float("-inf")))
                now = time.monotonic()
                delay = self.last_by_key.get(key, float("-inf")) + self.settings.request_spacing_seconds - now
                if delay <= 0:
                    self.last_by_key[key] = now
                    return name, key, time.time()
            time.sleep(delay)

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
                        result = exercise(suite, cases, config=config)
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
        for attempt in range(1, settings.model_identity_attempts + 1):
            selected_env, api_key, started = self.server.acquire_key(key_env)
            entry = {"job": job, "role": role, "started": started, "model": model_name,
                     "attempt": attempt, "credential_env": selected_env,
                     "reasoning": payload.get("reasoning", {"effort": payload.get("reasoning_effort")}),
                     "request_bytes": len(body)}
            headers_sent = False
            try:
                with httpx.Client(timeout=600, proxy=settings.proxy, trust_env=False) as client:
                    with client.stream("POST", base_url.rstrip("/") + suffix, content=body,
                        headers={"Authorization": "Bearer " + api_key,
                                 "Content-Type": "application/json"}) as response, tempfile.TemporaryFile() as buffered:
                        entry["status"] = response.status_code
                        content_type = response.headers.get("content-type", "application/json")
                        # Validate the entire stream before exposing any content or
                        # tool calls: a later event can contradict an earlier model.
                        for chunk in response.iter_bytes():
                            buffered.write(chunk)
                        buffered.seek(0)
                        if response.is_success:
                            models = response_models(buffered, content_type)
                            entry["reported_models"] = sorted(models)
                            if models != {model_name}:
                                entry["error"] = "model_identity_mismatch"
                                continue
                        self.send_response(response.status_code)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Connection", "close")
                        self.end_headers()
                        headers_sent = True
                        shutil.copyfileobj(buffered, self.wfile)
                        self.wfile.flush()
                        return
            except Exception as exc:
                entry["error"] = type(exc).__name__ + ": " + str(exc)
                if not headers_sent:
                    self.send_error(502, "Upstream connection failed")
                return
            finally:
                entry["seconds"] = time.time() - started
                self.server.log(entry)
        self.send_error(502, "Upstream model identity mismatch after retry limit")


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
