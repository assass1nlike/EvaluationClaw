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


def test_gateway_shares_rate_across_author_task_and_laaj(tmp_path, monkeypatch):
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
    config = settings().model_copy(update={"proxy":None, "author_base_url":base_url,
        "task_key_env":"TASK_TEST_KEY", "laaj_key_env":"REVIEW_TEST_KEY",
        "task_model":TargetModelConfig(model="task", provider="openai_compatible", base_url=base_url),
        "laaj_model":TargetModelConfig(model="review", provider="openai_responses", base_url=base_url)})
    for key in ("FRONTIER_API_KEY", "TASK_TEST_KEY", "REVIEW_TEST_KEY"):
        monkeypatch.setenv(key, key + "-value")
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
                pending = [pool.submit(request, "author-token", "/v1/responses", config.author_model),
                    pool.submit(request, bindings["task"]["api_key"], "/v1/chat/completions", "task"),
                    pool.submit(request, bindings["laaj"]["api_key"], "/v1/responses", "review")]
                assert [f.result().status_code for f in pending] == [200, 200, 200]
        entries = [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]
        assert {e["role"] for e in entries} == {"author", "task", "laaj"}
        starts = sorted(e["started"] for e in entries)
        assert all(b - a >= 2.05 for a, b in zip(starts, starts[1:]))
        assert {auth for _, auth, _ in received} == {"Bearer " + key + "-value" for key in
            ("FRONTIER_API_KEY", "TASK_TEST_KEY", "REVIEW_TEST_KEY")}
    finally:
        gateway.shutdown()
        gateway.server_close()
        upstream.shutdown()
        upstream.server_close()


def test_evaluation_keeps_unsupported_tasks_in_quality_and_counts(tmp_path, monkeypatch):
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
        assert supplied.tasks[0].content.messages[0].role == "developer"
        assert len(supplied.tasks) == config.laaj_sample_size == 51
        return SimpleNamespace(item_errors={}, overall_error=None, model_dump=lambda **kw: {})
    monkeypatch.setattr("evalclaw.execution.runner.run_eval", run)
    monkeypatch.setattr("evalclaw.quality.laaj.evaluate_with_laaj", quality)
    config = settings()
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
