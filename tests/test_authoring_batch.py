import json
import os
from pathlib import Path
import threading

import httpx
import pytest

from evalclaw.authoring.batch_config import Settings, evaluation_config
from evalclaw.authoring.batch_gateway import Gateway
from evalclaw.authoring.batch import verify_snapshot


def settings():
    return Settings(jobs=[{"id":"test", "goal":"Test", "count":1}], gateway_host="127.0.0.1",
        evaluation_model={"provider":"openai_compatible", "model":"test",
                          "supported_message_roles":["system", "user", "assistant", "tool"]})


def deliver(root, role="user"):
    directory = root / "test/work/package"
    (directory / "one").mkdir(parents=True)
    (directory / "benchmark.json").write_text(json.dumps({"format":"benchmark-package/v1", "objective":"Test", "tasks":["one"]}))
    (directory / "one/task.json").write_text(json.dumps({"id":"one", "messages":[{"role":role, "content":"Question"}],
        "grading":{"method":"exact", "answer":"yes"}}))
    return directory


def test_settings_require_explicit_capabilities_and_external_credentials():
    config = settings().model_dump()
    config["evaluation_model"]["supported_message_roles"] = None
    with pytest.raises(ValueError):
        Settings.model_validate(config)
    config = settings().model_dump()
    config["evaluation_model"]["api_key"] = "secret"
    with pytest.raises(ValueError):
        Settings.model_validate(config)
    model = evaluation_config(settings(), Path("output"), credentials=False)
    assert model.targets[0].api_key is None
    assert model.targets[0].supported_message_roles == settings().evaluation_model.supported_message_roles


def test_explicit_direct_routes_do_not_change_host_environment(monkeypatch, tmp_path):
    from evalclaw.authoring.batch import subprocess_env
    monkeypatch.setenv("HTTPS_PROXY", "http://example:1234")
    monkeypatch.setenv("NO_PROXY", "localhost")
    config = settings().model_copy(update={"direct_hosts":["api.example"]})
    env = subprocess_env(tmp_path, config)
    assert env["NO_PROXY"] == env["no_proxy"] == "localhost,127.0.0.1,api.example"
    assert env["HTTPS_PROXY"] == "http://example:1234"
    assert os.environ["NO_PROXY"] == "localhost"


def test_job_scoped_feedback_freezes_attempts_without_model_calls(tmp_path):
    directory = deliver(tmp_path, role="developer")
    gateway = Gateway(tmp_path, settings(), {"token":"test"})
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{gateway.server_address[1]}", trust_env=False) as client:
            assert client.post("/feedback", json={"operation":"check"}).status_code == 401
            assert client.post("/feedback", headers={"Authorization":"Bearer token"}, json=[]).status_code == 400
            bad = client.post("/feedback", headers={"Authorization":"Bearer token"}, json={"operation":"unknown"})
            assert bad.json()["status"] == "invalid"
            response = client.post("/feedback", headers={"Authorization":"Bearer token"}, json={"operation":"check"})
            assert response.json()["status"] == "unsupported_binding"
        frozen = tmp_path / "test/checks/0001/bundle/original/one/task.json"
        original = frozen.read_bytes()
        (directory / "one/task.json").write_text("{}")
        result = gateway.feedback("test", {"operation":"check"})
        assert result["status"] == "invalid"
        assert frozen.read_bytes() == original
        assert json.loads((tmp_path / "test/checks/0002/submitted/one/task.json").read_text()) == {}
    finally:
        gateway.shutdown()
        gateway.server_close()
        thread.join()


def test_snapshot_rejects_source_or_settings_changes(tmp_path):
    import hashlib
    from evalclaw.authoring.package import _hashes
    (tmp_path / "source").mkdir()
    (tmp_path / "source/example.py").write_text("pass")
    (tmp_path / "settings.json").write_text("{}")
    (tmp_path / "snapshot.json").write_text(json.dumps({"source":_hashes(tmp_path / "source"),
        "settings_sha256":hashlib.sha256(b"{}").hexdigest()}))
    verify_snapshot(tmp_path)
    (tmp_path / "source/example.py").write_text("changed")
    with pytest.raises(ValueError):
        verify_snapshot(tmp_path)


def test_independent_model_routes_and_credentials(monkeypatch, tmp_path):
    from evalclaw.types import TargetModelConfig
    config = settings().model_copy(update={
        "task_model": TargetModelConfig(model="task-model", provider="openai_compatible",
            base_url="https://task.example/v1", extra_body={"reasoning_effort":"high"}),
        "task_key_env": "TASK_TEST_KEY",
        "laaj_model": TargetModelConfig(model="review-model", provider="openai_responses",
            base_url="https://review.example/v1", extra_body={"reasoning":{"effort":"high"}}),
        "laaj_key_env": "REVIEW_TEST_KEY"})
    for key, value in (("DEEPSEEK_API_KEY", "target-key"), ("TASK_TEST_KEY", "task-key"), ("REVIEW_TEST_KEY", "review-key")):
        monkeypatch.setenv(key, value)
    bound = evaluation_config(config, tmp_path, bindings={
        "task":{"base_url":"http://gateway/v1", "api_key":"task-token"},
        "laaj":{"base_url":"http://gateway/v1", "api_key":"review-token"}})
    assert bound.targets[0].model == "test"
    assert bound.targets[0].api_key == "target-key"
    assert bound.actor_model == bound.task_models[0].model == "task-model"
    assert bound.actor_api_key == bound.task_models[0].api_key == "task-token"
    assert bound.actor_base_url == bound.task_models[0].base_url == "http://gateway/v1"
    assert bound.laaj_model == "review-model"
    assert bound.laaj_api_key == "review-token"
    assert bound.laaj_reasoning_effort == bound.actor_extra_body["reasoning_effort"] == "high"
    for field in ("evaluation_model", "task_model", "laaj_model"):
        raw = config.model_dump()
        raw[field]["api_key"] = "inline-secret"
        with pytest.raises(ValueError):
            Settings.model_validate(raw)


@pytest.mark.parametrize("pooled", [False, True])
def test_gateway_shares_per_key_rate_across_author_task_and_laaj(tmp_path, monkeypatch, pooled):
    from concurrent.futures import ThreadPoolExecutor
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from evalclaw.types import TargetModelConfig
    received = []
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers["Authorization"], payload))
            body = json.dumps({"model":payload["model"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{upstream.server_address[1]}/v1"
    config = settings().model_copy(update={"proxy":None, "author_base_url":base_url, "request_spacing_seconds": 0.08,
        "task_key_env":"TASK_TEST_KEY", "laaj_key_env":"REVIEW_TEST_KEY",
        "task_model":TargetModelConfig(model="task", provider="openai_compatible", base_url=base_url),
        "laaj_model":TargetModelConfig(model="review", provider="openai_responses", base_url=base_url)})
    for key in ("FRONTIER_API_KEY", "TASK_TEST_KEY", "REVIEW_TEST_KEY"):
        monkeypatch.setenv(key, "shared-key")
    if pooled:
        monkeypatch.setenv("SECOND_KEY", "second-key")
        config.key_pools = {name: ["FRONTIER_API_KEY", "SECOND_KEY"] for name in
                            ("FRONTIER_API_KEY", "TASK_TEST_KEY", "REVIEW_TEST_KEY")}
    gateway = Gateway(tmp_path, config, {"author-token":"test"})
    bindings = gateway.evaluation_bindings("test")
    threading.Thread(target=gateway.serve_forever, daemon=True).start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{gateway.server_address[1]}", trust_env=False, timeout=15) as client:
            def request(token, path, model):
                return client.post(path, headers={"Authorization":"Bearer " + token}, json={"model":model})
            assert request(bindings["task"]["api_key"], "/feedback", "task").status_code == 403
            assert request("author-token", "/v1/chat/completions", "task").status_code == 404
            assert request("author-token", "/v1/responses", "review").status_code == 400
            with ThreadPoolExecutor(3) as pool:
                pending = []
                for _ in range(3):
                    pending.extend([pool.submit(request, "author-token", "/v1/responses", config.author_model),
                        pool.submit(request, bindings["task"]["api_key"], "/v1/chat/completions", "task"),
                        pool.submit(request, bindings["laaj"]["api_key"], "/v1/responses", "review")])
                assert [f.result().status_code for f in pending] == [200] * 9
        entries = [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]
        assert {e["role"] for e in entries} == {"author", "task", "laaj"}
        for credential in ({e["credential_env"] for e in entries} if pooled else {None}):
            starts = sorted(e["started"] for e in entries if credential is None or e["credential_env"] == credential)
            assert all(b - a >= 0.075 for a, b in zip(starts, starts[1:]))
        assert {auth for _, auth, _ in received} == ({"Bearer shared-key", "Bearer second-key"} if pooled else {"Bearer shared-key"})
        assert "shared-key" not in (tmp_path / "requests.jsonl").read_text()
        assert "second-key" not in (tmp_path / "requests.jsonl").read_text()
    finally:
        gateway.shutdown()
        gateway.server_close()
        upstream.shutdown()
        upstream.server_close()


@pytest.mark.parametrize("wire", ["json", "chat_stream", "responses_stream"])
@pytest.mark.parametrize("recover", [True, False])
def test_gateway_retries_identity_before_delivering_content(tmp_path, monkeypatch, wire, recover):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    calls = []
    credentials = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            credentials.append(self.headers["Authorization"])
            model = "expected" if recover and len(calls) > 1 else "wrong"
            value = {"model": model, "output": "accepted" if model == "expected" else "discard-me"}
            if wire == "json":
                body = json.dumps(value).encode()
                content_type = "application/json"
            else:
                # The identity may change at completion, after a correct header.
                values = [{"model": "expected"}, value]
                if wire == "responses_stream":
                    values = [{"type": kind, "response": v} for kind, v in
                              zip(["response.created", "response.completed"], values)]
                body = ("".join("data: " + json.dumps(v) + "\r\n\r\n" for v in values)
                        + "data: [DONE]\r\n\r\n").encode()
                content_type = "text/event-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    config = settings().model_copy(update={"proxy": None, "author_model": "expected",
        "author_base_url": f"http://127.0.0.1:{upstream.server_address[1]}/v1",
        "request_spacing_seconds": 0.01,
        "key_pools": {"FRONTIER_API_KEY": ["FRONTIER_API_KEY", "SECOND_KEY"]}})
    monkeypatch.setenv("FRONTIER_API_KEY", "test")
    monkeypatch.setenv("SECOND_KEY", "second")
    gateway = Gateway(tmp_path, config, {"author": "test"})
    threading.Thread(target=gateway.serve_forever, daemon=True).start()
    try:
        with httpx.Client(trust_env=False) as client:
            result = client.post(f"http://127.0.0.1:{gateway.server_address[1]}/v1/responses",
                headers={"Authorization": "Bearer author"}, json={"model": "expected", "stream": wire != "json"})
        assert result.status_code == (200 if recover else 502)
        assert "discard-me" not in result.text
        assert len(calls) == (2 if recover else 3)
        assert credentials[:2] == ["Bearer test", "Bearer second"]
        assert all(call == calls[0] for call in calls)
        entries = [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]
        assert entries[0]["error"] == "model_identity_mismatch"
        assert "wrong" in entries[0]["reported_models"]
        for credential in {e["credential_env"] for e in entries}:
            starts = sorted(e["started"] for e in entries if e["credential_env"] == credential)
            assert all(b - a >= 0.009 for a, b in zip(starts, starts[1:]))
    finally:
        gateway.shutdown()
        gateway.server_close()
        upstream.shutdown()
        upstream.server_close()


def test_gateway_model_identity_missing_is_not_a_match():
    from io import BytesIO
    from evalclaw.authoring.batch_gateway import response_models
    assert response_models(BytesIO(b'{"output":"answer"}'), "application/json") == set()
    assert response_models(BytesIO(b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\ndata: [DONE]\n\n'),
                           "text/event-stream") == set()


def test_two_keys_allow_100_rpm_without_doubling_each_keys_quota(tmp_path, monkeypatch):
    from types import SimpleNamespace
    now = [1000.0]
    monkeypatch.setattr("evalclaw.authoring.batch_gateway.time", SimpleNamespace(
        monotonic=lambda: now[0], time=lambda: now[0], sleep=lambda delay: now.__setitem__(0, now[0] + delay)))
    monkeypatch.setenv("FIRST_KEY", "one")
    monkeypatch.setenv("SECOND_KEY", "two")
    config = settings().model_copy(update={"request_spacing_seconds": 1.21,
        "key_pools": {"FRONTIER_API_KEY": ["FIRST_KEY", "SECOND_KEY"]}})
    gateway = Gateway(tmp_path, config, {})
    try:
        starts = [gateway.acquire_key("FRONTIER_API_KEY") for _ in range(202)]
        for _, key, started in starts:
            assert sum(k == key and started - 60 < t <= started for _, k, t in starts) <= 50
            assert sum(started - 60 < t <= started for _, _, t in starts) <= 100
        assert sum(t < 1060 for _, _, t in starts) == 100
    finally:
        gateway.server_close()


@pytest.mark.parametrize("sample_size", [None, 20])
def test_evaluation_keeps_unsupported_tasks_in_quality_and_counts(tmp_path, monkeypatch, sample_size):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from evalclaw.authoring import load_package
    from evalclaw.authoring.batch import evaluate
    prototype = load_package(deliver(tmp_path))
    items = [prototype.tasks[0].model_copy(deep=True) for _ in range(51)]
    for index, item in enumerate(items):
        item.id = f"task-{index}"
    items[0].content.messages[0].role = "developer"
    suite = prototype.model_copy(update={"tasks":items})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setattr("evalclaw.authoring.batch.load_bundle", lambda directory: suite)
    monkeypatch.setattr("evalclaw.authoring.batch.prepare", lambda *a, **kw: {"images":[]})
    monkeypatch.setattr("evalclaw.execution.memory_budget.memory_budget", lambda *a, **kw: nullcontext())
    def run(supplied, accepted, *args, **kwargs):
        assert len(supplied.tasks) == 51
        assert len(accepted.passed_item_ids) == 50
        assert "task-0" not in accepted.passed_item_ids
        return SimpleNamespace(results=[SimpleNamespace(score=1, error=None) for _ in range(50)], model_dump=lambda **kw: {})
    def quality(goal, supplied, analysis, config, **kwargs):
        import random
        expected = {t.id for t in random.Random(42).sample(sorted(items, key=lambda t: t.id), sample_size or 51)}
        assert {t.id for t in supplied.tasks} == expected
        assert len(supplied.tasks) == config.laaj_sample_size == (sample_size or 51)
        sampling = json.loads((tmp_path / "test/evaluation/laaj-sampling.json").read_text())
        assert set(sampling["item_ids"]) == expected and sampling["total_items"] == 51
        return SimpleNamespace(item_errors={}, overall_error=None, model_dump=lambda **kw: {})
    monkeypatch.setattr("evalclaw.execution.runner.run_eval", run)
    monkeypatch.setattr("evalclaw.quality.laaj.evaluate_with_laaj", quality)
    config = settings()
    config.laaj_sample_size = sample_size
    result = evaluate(tmp_path, config, config.jobs[0].model_copy(update={"count":51}))
    assert result["requested"] == result["generated"] == 51
    assert result["unsupported"] == 1
    assert result["attempted"] == result["valid_scored"] == 50


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires Docker")
def test_author_gateway_executes_and_records_real_protocol_cases(tmp_path):
    directory = deliver(tmp_path)
    task_file = directory / "one/task.json"
    task = json.loads(task_file.read_text())
    task["service"] = {"image":"python:3.11-slim", "command":["python", "-u", "service.py"], "files":["service.py"]}
    task_file.write_text(json.dumps(task))
    (directory / "one/service.py").write_text('''from benchmark_io import serve
def initialize(params, config):
    return {'state':0, 'tools':[]}
def call_tool(params, config):
    return {'content':'', 'error':True if params.get('broken') else 'Not found'}
serve({'initialize':initialize, 'call_tool':call_tool})
''')
    gateway = Gateway(tmp_path, settings(), {"token":"test"})
    try:
        result = gateway.feedback("test", {"operation":"exercise", "cases":[
            {"task":"one", "component":"environment", "calls":[{"method":"initialize"}, {"method":"call_tool"}]},
            {"task":"one", "component":"environment", "calls":[{"method":"call_tool", "params":{"broken":True}}]},
        ]})
        assert [case["status"] for case in result["cases"]] == ["passed", "failed"]
        recorded = json.loads((tmp_path / "test/checks/0001/images.json").read_text())
        assert recorded["images"][0]["image_id"].startswith("sha256:")
        from evalclaw.authoring import load_bundle
        suite = load_bundle(tmp_path / "test/checks/0001/bundle")
        assert suite.tasks[0].environment.service.image == "python:3.11-slim"
    finally:
        gateway.server_close()


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires Docker")
def test_author_client_available_in_login_shell(tmp_path):
    from evalclaw.authoring.batch import docker
    from evalclaw.authoring.batch_gateway import AUTHOR_CLIENT
    script = tmp_path / "benchmark-package"
    script.write_text(AUTHOR_CLIENT)
    script.chmod(0o755)
    result = docker("run", "--rm", "--pull", "never", "-v", f"{script}:/usr/local/bin/benchmark-package:ro",
        "--entrypoint", "bash", "evalclaw-harness-runtime:latest", "-lc", "benchmark-package --help",
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
