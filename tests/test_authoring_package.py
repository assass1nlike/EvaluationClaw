import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from evalclaw.authoring import benchmark_io, load_bundle, load_package, pack
from evalclaw.execution.contract_capabilities import binding_issues
from evalclaw.execution.task_runtime import render_messages, run_contract
from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.protocols.tool import ToolCall
from evalclaw.quality.laaj_tools import read_task_file
from evalclaw.types import BenchmarkConfig, TargetModelConfig

TARGET = TargetModelConfig(id="test", model="test", provider="openai_compatible")


def package(tmp_path, task=None, files=None):
    root = tmp_path / "input"
    (root / "one").mkdir(parents=True)
    (root / "benchmark.json").write_text(json.dumps({
        "format": "benchmark-package/v1", "objective": "Test input fidelity", "tasks": ["one"]}))
    (root / "one/task.json").write_text(json.dumps(task or {
        "id": "one", "prompt": "prompt.txt", "grading": {"method": "exact", "answer_file": "answer.txt"}}))
    for name, value in {"prompt.txt": "Give the answer.\r\n", "answer.txt": " 42\r\n", **(files or {})}.items():
        path = root / "one" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else value.encode())
    return root


def response(text, calls=()):
    return TargetToolModelResponse(adapter="openai", content=text, tool_calls=list(calls),
        assistant_message={"role": "assistant", "content": text}, raw_response={})


def test_plain_task_preserves_bytes_scoring_review_and_portability(tmp_path, monkeypatch):
    root = package(tmp_path)
    bundle = tmp_path / "bundle"
    suite = pack(root, bundle)
    assert render_messages(suite.tasks[0]) == [{"role": "user", "content": "Give the answer.\r\n"}]
    assert suite.tasks[0].challenge_effort is None
    assert not suite.dimensions
    assert suite.tasks[0].evaluation.references[0].value == " 42\r\n"
    assert all(a.visibility == ["judge"] for a in suite.tasks[0].assets)
    calls = []
    def model(messages, *args, **kwargs):
        calls.append(copy.deepcopy(messages))
        return response(" 42\r\n")
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    result = run_contract(suite.tasks[0], BenchmarkConfig(), TARGET)
    assert result.error is None and result.score == 1
    assert "42" not in json.dumps(calls[0])
    reviewed = read_task_file(ToolCall(id="read", name="read_task_file",
        arguments={"item_id": "one", "area": "asset", "path": "package:answer.txt"}), suite)
    assert reviewed.error is None
    assert "42" in reviewed.content
    moved = tmp_path / "moved"
    shutil.move(bundle, moved)
    shutil.rmtree(root)
    loaded = load_bundle(moved)
    assert render_messages(loaded.tasks[0]) == render_messages(suite.tasks[0])
    assert all(Path(a.path).is_file() for a in loaded.tasks[0].assets)
    with pytest.raises(ValueError):
        pack(moved / "original", moved)
    (moved / "original/one/answer.txt").write_text("different")
    with pytest.raises(ValueError, match="checksum"):
        load_bundle(moved)


def test_multimodal_and_seeded_history_not_reinterpreted(tmp_path):
    task = {"id": "one", "messages": [
        {"role": "system", "content": "System text"},
        {"role": "assistant", "content": "Earlier response", "origin": "seeded_context"},
        {"role": "user", "content": [
            {"type": "asset", "asset_id": "data", "presentation": "json"},
            {"type": "asset", "asset_id": "image", "presentation": "image"}]}],
        "files": [{"id": "data", "path": "data.json", "audience": ["target"]},
                  {"id": "image", "path": "image.png", "audience": ["target"], "media_type": "image/png"}],
        "grading": {"method": "json", "answer": [1, 2]}}
    root = package(tmp_path, task, {"data.json": '{ "value": 1 }\n', "image.png": b"binary image bytes"})
    item = load_package(root).tasks[0]
    messages = render_messages(item)
    assert [m["role"] for m in messages] == ["system", "assistant", "user"]
    assert messages[-1]["content"][0]["text"] == '{ "value": 1 }\n'
    assert messages[-1]["content"][1]["type"] == "image_url"
    assert item.content.messages[1].origin == "seeded_context"
    assert item.evaluation.references[0].value == [1, 2]


@pytest.mark.parametrize("reset", [False, True])
def test_dialogue_preserves_followups_and_scoring(tmp_path, monkeypatch, reset):
    task = {"id": "one", "prompt": "prompt.txt", "grading": {"method": "exact", "answer": "final"},
            "interaction": {"turns": [{"role": "user", "file": "followup.txt"}], "reset_between_turns": reset}}
    item = load_package(package(tmp_path, task, {"followup.txt": "Continue."})).tasks[0]
    seen = []
    def model(messages, *a, **kw):
        seen.append(copy.deepcopy(messages))
        return response("first" if len(seen) == 1 else "final")
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    result = run_contract(item, BenchmarkConfig(), TARGET)
    assert not result.error and result.score == 1
    assert result.episode.outputs == ["first", "final"]
    assert seen[1][-1] == {"role": "user", "content": "Continue."}
    assert any(m.get("content") == "first" for m in seen[1]) is not reset


def test_multiple_metrics_require_explicit_composition(tmp_path, monkeypatch):
    task = {"id": "one", "prompt": "prompt.txt", "grading": [
        {"method": "exact", "name": "a", "answer": "yes"},
        {"method": "exact", "name": "b", "answer": "no"},
        {"method": "aggregate", "name": "total", "depends_on": ["a", "b"], "weights": {"a": .25, "b": .75}}],
        "primary": {"metric": "total", "minimum": 0, "maximum": 1}}
    item = load_package(package(tmp_path, task)).tasks[0]
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: response("yes"))
    result = run_contract(item, BenchmarkConfig(), TARGET)
    assert not result.error and result.score == .25
    assert [(m.metric, m.value) for m in result.episode.metrics] == [("a", 1), ("b", 0), ("total", .25)]


def test_suite_aggregation_preserves_group_labels(tmp_path, monkeypatch):
    from evalclaw.execution.suite_metrics import aggregate_metrics

    root = package(tmp_path, {"id": "one", "prompt": "prompt.txt", "labels": {"language": "test"},
                             "grading": {"method": "exact", "answer": "42"}})
    manifest = json.loads((root / "benchmark.json").read_text())
    manifest["aggregation"] = [{"id": "per-language", "metric": "score", "aggregation": "mean", "group_by": ["language"]}]
    (root / "benchmark.json").write_text(json.dumps(manifest))
    suite = load_package(root)
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: response("42"))
    result = run_contract(suite.tasks[0], BenchmarkConfig(), TARGET)
    aggregated = aggregate_metrics(suite, [result])[0]
    assert aggregated["group"] == {"language": "test"}
    assert aggregated["value"] == 1 and aggregated["valid"] == aggregated["total"] == 1


def test_duplicate_public_paths_and_private_collisions_rejected(tmp_path):
    task = {"id": "one", "prompt": "prompt.txt", "workspace": {
        "image": "python:3.11-slim", "private_files": ["answer.txt"]},
        "files": [{"id": "answer", "path": "answer.txt", "audience": ["target"]}],
        "grading": {"method": "exact", "answer": "42"}}
    root = package(tmp_path, task)
    with pytest.raises(ValueError, match="private scoring file"):
        load_package(root)
    task["workspace"]["private_files"] = []
    task["files"].append({"id": "other", "path": "prompt.txt", "audience": ["target"], "mount": "answer.txt"})
    (root / "one/task.json").write_text(json.dumps(task))
    with pytest.raises(ValueError, match="destinations"):
        load_package(root)


@pytest.mark.parametrize("mutation", [
    {"prompt": "../outside.txt"}, {"prompt": "/etc/passwd"}, {"unexpected": "ignored?"},
    {"grading": {"method": "exact"}}, {"id": "../escape"},
    {"grading": {"method": "judge", "answer": "42"}},
    {"grading": {"method": "exact", "answer": [1, 2]}},
    {"grading": {"method": "exact", "answer": "42", "reference_is": "criterion"}},
])
def test_invalid_packages_are_not_repaired_or_partially_imported(tmp_path, mutation):
    task = {"id": "one", "prompt": "prompt.txt", "grading": {"method": "exact", "answer": "42"}, **mutation}
    root = package(tmp_path, task)
    with pytest.raises(ValueError):
        pack(root, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_duplicate_json_and_symlink_escape_rejected(tmp_path):
    root = package(tmp_path)
    manifest = root / "benchmark.json"
    original = manifest.read_text()
    manifest.write_text('{"format":"benchmark-package/v1","tasks":[],"tasks":["one"],"objective":"x"}')
    with pytest.raises(ValueError, match="Duplicate JSON"):
        load_package(root)
    manifest.write_text(original)
    (root / "one/leak").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="symlink"):
        load_package(root)


def test_cli_validation_and_author_kit(tmp_path):
    root = package(tmp_path)
    args = [sys.executable, "-m", "evalclaw.authoring"]
    run = subprocess.run([*args, "check", str(root)], capture_output=True, text=True, check=True)
    assert json.loads(run.stdout)["task_ids"] == ["one"]
    run = subprocess.run([*args, "kit", str(tmp_path / "kit")], capture_output=True, text=True, check=True)
    assert json.loads(run.stdout)["status"] == "copied"
    assert {p.name for p in (tmp_path / "kit").iterdir()} == {"DELIVERY.md", "INTERFACES.md", "benchmark_io.py"}
    (root / "one/task.json").write_text('{"id":"one"}')
    run = subprocess.run([*args, "check", str(root)], capture_output=True, text=True)
    assert run.returncode == 1
    error = json.loads(run.stdout)
    assert error["status"] == "invalid" and "one/task.json" in error["error"]


def test_workspace_paths_visibility_and_budget_binding(tmp_path):
    root = package(tmp_path, {"id": "one", "prompt": "prompt.txt",
        "workspace": {"dockerfile": "build/Dockerfile", "context": "build", "score_command": "python grader.py",
                      "private_files": ["grader.py"]},
        "files": [{"id": "data", "path": "data.bin", "audience": ["target"], "mount": "inputs/data.bin"}],
        "interaction": {"budget": {"wall_time_seconds": 30}}, "grading": {"method": "environment"}},
        {"build/Dockerfile": "FROM python:3.11-slim\n", "grader.py": 'print(\'{"score":1}\')', "data.bin": b"\x00\xff"})
    bundle = tmp_path / "bundle"
    item = pack(root, bundle).tasks[0]
    assert item.environment.hidden_files == {"grader.py": 'print(\'{"score":1}\')'}
    assert Path(item.environment.image_build["context_dir"]) == bundle / "original/one/build"
    assert not binding_issues(item, BenchmarkConfig(), TARGET.model_copy(update={"harness": "openclaw"}))
    item.interaction.budget.target_calls = 2
    assert binding_issues(item, BenchmarkConfig(), TARGET.model_copy(update={"harness": "openclaw"}))


def test_transport_model_callback_and_error_are_not_scores():
    script = """from evalclaw.authoring.benchmark_io import serve, model, event
def score(params, config):
    event('observed', params)
    reply = model('judge', [{'role':'user','content':'Review'}])
    if reply['content'] == 'fail': raise ValueError('grader failed')
    return {'metrics':[{'metric':'score','value':1}]}
serve({'score':score})
"""
    messages = [
        {"id": 1, "method": "describe"},
        {"id": 2, "method": "score", "params": {"candidate": "x"}},
        {"id": "model-1", "model_result": {"content": "fail"}},
    ]
    run = subprocess.run([sys.executable, "-c", script], input="\n".join(map(json.dumps, messages))+"\n",
                         text=True, capture_output=True, check=True)
    output = [json.loads(line) for line in run.stdout.splitlines()]
    assert output[0]["result"] == {"version": "1", "methods": ["score"]}
    assert output[1]["event"]["data"] == {"candidate": "x"}
    assert output[2]["model_request"]["role"] == "judge"
    assert output[3] == {"id": 2, "error": "ValueError: grader failed"}


DRIVER = '''from benchmark_io import serve
def next_step(params, config):
    if params['state'] is None:
        return {'state':1,'actions':[{'action':'checkpoint','id':'start'}, {'action':'target'}]}
    if params['state'] == 1:
        return {'state':2,'actions':[{'action':'branch','id':'start','branch':'second'},
            {'action':'reset_session','session':'new','messages':[{'role':'user','content':'Second input'}]},
            {'action':'target'}]}
    return {'state':3,'actions':[{'action':'end'}]}
serve({'next':next_step})
'''

GRADER = '''from benchmark_io import serve
def score(params, config):
    episode = params['episode']
    assert len(episode['outputs']) == 2
    assert any(e['kind']=='model_response' and e['origin']=='target' for e in episode['events'])
    assert any(e['branch']=='second' for e in episode['events'])
    return {'metrics':[{'metric':'score','value':int(episode['outputs'][-1]=='final')}]}
serve({'score':score})
'''


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires Docker")
def test_real_driver_branch_and_program_grading(tmp_path, monkeypatch):
    task = {"id": "one", "prompt": "prompt.txt", "interaction": {
        "driver": {"image": "python:3.11-slim", "files": ["driver.py"], "command": ["python", "-u", "driver.py"]},
        "actions": ["checkpoint", "branch", "reset_session", "target", "end"], "budget": {"target_calls": 2}},
        "grading": {"method": "program", "program": {
            "image": "python:3.11-slim", "files": ["grader.py"], "command": ["python", "-u", "grader.py"]}}}
    item = load_package(package(tmp_path, task, {"driver.py": DRIVER, "grader.py": GRADER})).tasks[0]
    seen = []
    def model(messages, *a, **kw):
        seen.append(copy.deepcopy(messages))
        return response("first" if len(seen) == 1 else "final")
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", model)
    result = run_contract(item, BenchmarkConfig(), TARGET, trace_dir=tmp_path / "run")
    assert not result.error and result.score == 1
    assert seen[1] == [{"role": "user", "content": "Second input"}]
    assert result.episode.usage["target_calls"] == 2


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires Docker")
def test_real_suite_program_aggregation(tmp_path, monkeypatch):
    from evalclaw.execution.suite_metrics import aggregate_metrics

    root = package(tmp_path)
    (root / "aggregate.py").write_text('''from benchmark_io import serve
def aggregate(params, config):
    return {'value':sum(row['score'] for row in params['results']), 'count':len(params['tasks'])}
serve({'aggregate':aggregate})
''')
    manifest = json.loads((root / "benchmark.json").read_text())
    manifest["aggregation"] = [{"id": "custom", "metric": "score", "aggregation": "program", "program": {
        "image": "python:3.11-slim", "command": ["python", "-u", "aggregate.py"], "files": ["aggregate.py"]}}]
    (root / "benchmark.json").write_text(json.dumps(manifest))
    suite = pack(root, tmp_path / "bundle")
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: response(" 42\r\n"))
    result = run_contract(suite.tasks[0], BenchmarkConfig(), TARGET)
    aggregated = aggregate_metrics(suite, [result])[0]
    assert aggregated["status"] == "valid"
    assert aggregated["raw"] == {"value": 1, "count": 1}


SERVICE = '''from pathlib import Path
from benchmark_io import serve, event
n = 0
def initialize(params, config):
    assert Path('/component/assets/secret').read_text() == 'private'
    return {'state':0, 'tools':[{'name':'increment','description':'Add one',
             'parameters':{'type':'object','properties':{},'additionalProperties':False}}]}
def call_tool(params, config):
    global n
    n += 1
    event('incremented', {'n':n})
    return {'content':str(n)}
def finalize(params, config):
    Path('/component/result.txt').write_text(str(n))
    return {'state':n,'artifact_files':{'count.txt':'/component/result.txt'}}
def score(params, config):
    assert Path('/component/outputs/count.txt').read_text() == str(params['episode']['final_state'])
    return {'metrics':[{'metric':'score','value':int(params['episode']['final_state']==1)}]}
def inspect(params, config):
    return {'observed':params.get('state',n)}
serve({'initialize':initialize,'call_tool':call_tool,'finalize':finalize,'score':score,'inspect':inspect})
'''


def service_package(tmp_path):
    return package(tmp_path, {"id": "one", "prompt": "prompt.txt",
        "service": {"image": "python:3.11-slim", "files": ["service.py"],
                    "command": ["python", "-u", "service.py"], "assets": ["secret"]},
        "service_capabilities": ["inspect"],
        "files": [{"id": "secret", "path": "secret.txt"}],
        "grading": {"method": "environment"}}, {"service.py": SERVICE, "secret.txt": "private"})


def test_service_is_preserved_and_shell_binding_is_explicitly_rejected(tmp_path):
    item = load_package(service_package(tmp_path)).tasks[0]
    assert item.environment.service.files["service.py"] == SERVICE
    assert item.environment.service.files["benchmark_io.py"] == Path(benchmark_io.__file__).read_text()
    assert not binding_issues(item, BenchmarkConfig(), TARGET)
    assert binding_issues(item, BenchmarkConfig(), TARGET.model_copy(update={"harness": "codex"}))


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires Docker")
def test_real_imported_service_executes_scores_exports_and_supports_review(tmp_path, monkeypatch):
    from evalclaw.quality.laaj_exploration import ContractExperiment
    item = pack(service_package(tmp_path), tmp_path / "bundle").tasks[0]
    replies = iter([response("", [ToolCall(id="c1", name="increment", arguments={})]), response("Done")])
    monkeypatch.setattr("evalclaw.execution.task_runtime.call_target_model_with_tools", lambda *a, **kw: next(replies))
    config = BenchmarkConfig(targets=[TARGET])
    result = run_contract(item, config, TARGET, trace_dir=tmp_path / "run")
    assert not result.error and result.score == 1
    assert result.episode.final_state == 1 and result.episode.usage["tool_calls"] == 1
    assert result.episode.artifacts["count.txt"]["kind"] == "file"
    assert any(e.kind == "component_event" and e.origin == "environment" for e in result.episode.events)
    trial = ContractExperiment(item, config, TARGET.id, tmp_path / "review")
    try:
        outcome = trial.perform({"operation": "trial", "responses": [
            {"content": "", "tool_calls": [{"id": "c1", "name": "increment", "arguments": {}}]},
            {"content": "Done"}]})
        assert outcome["metrics"][0]["value"] == 1
    finally:
        trial.close()


def test_role_binding_preserves_input_and_rejects_before_request(tmp_path, monkeypatch):
    from evalclaw.models.llm import call_target_model_with_tools
    root = package(tmp_path, {"id": "one", "messages": [
        {"role": "developer", "content": "Apply this rule."},
        {"role": "user", "content": "Question"}], "grading": {"method": "exact", "answer": "42"}})
    item = load_package(root).tasks[0]
    target = TARGET.model_copy(update={"supported_message_roles": ["system", "user", "assistant", "tool"]})
    assert binding_issues(item, BenchmarkConfig(), target)
    assert item.content.messages[0].role == "developer"
    def forbidden(*a, **kw):
        pytest.fail("Incompatible messages reached the network")
    monkeypatch.setattr("evalclaw.models.llm._with_endpoint_failover", forbidden)
    # Also protects messages introduced later by a controller or auxiliary program.
    with pytest.raises(ValueError):
        call_target_model_with_tools([{"role": "developer", "content": "New rule"}], target, [])
    compatible = target.model_copy(update={"supported_message_roles": [*target.supported_message_roles, "developer"]})
    assert not binding_issues(item, BenchmarkConfig(), compatible)


@pytest.mark.parametrize("value,accepted", [
    (1.0000000000000002, True), (1.0, True), (0.0, True),
    (1.0000001, False), (-1e-15, False), (float("inf"), False), (float("nan"), False),
])
def test_score_boundary_roundoff_preserves_raw(tmp_path, value, accepted):
    from evalclaw.execution.component_contract import validate_metrics
    item = load_package(package(tmp_path)).tasks[0]
    raw = {"metrics": [{"metric": "score", "value": value, "raw": {"details": "kept"}}]}
    if not accepted:
        with pytest.raises(ValueError):
            validate_metrics(item.evaluation.scorers[0], raw, item.evaluation.metrics)
        return
    result = validate_metrics(item.evaluation.scorers[0], raw, item.evaluation.metrics)[0]
    assert 0 <= result.value <= 1
    assert raw["metrics"][0]["value"] == value
    if value > 1:
        assert result.raw["reported_metric"] == raw["metrics"][0]


def test_image_declarations_are_portable_and_local(tmp_path):
    root = service_package(tmp_path)
    manifest = json.loads((root / "benchmark.json").read_text())
    manifest["images"] = [{"image": "python:3.11-slim", "source": "registry.example/python@sha256:abc"}]
    (root / "benchmark.json").write_text(json.dumps(manifest))
    suite = pack(root, tmp_path / "bundle")
    assert not suite.tasks[0].environment.service.pull_image
    # Import declares dependencies; it never invokes Docker or rewrites source files.
    assert (tmp_path / "bundle/original/benchmark.json").read_bytes() == (root / "benchmark.json").read_bytes()
    manifest["images"] = [{"image": "local:test", "dockerfile": "../Dockerfile"}]
    (root / "benchmark.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_package(root)


def test_cli_distinguishes_unverified_and_incompatible_roles(tmp_path):
    root = package(tmp_path, {"id":"one", "messages":[
        {"role":"developer", "content":"Rule"}, {"role":"user", "content":"Question"}],
        "grading":{"method":"exact", "answer":"42"}})
    config = tmp_path / "config.json"
    for roles, expected in [(None, "unverified_binding"), (["user"], "unsupported_binding"),
                            (["developer", "user", "assistant"], "valid")]:
        config.write_text(BenchmarkConfig(targets=[TARGET.model_copy(update={"supported_message_roles": roles})]).model_dump_json())
        run = subprocess.run([sys.executable, "-m", "evalclaw.authoring", "check", str(root), "--config", str(config)],
                             capture_output=True, text=True)
        assert json.loads(run.stdout)["status"] == expected
        assert run.returncode == (0 if expected == "valid" else 1)


CONFORMANCE_SERVICE = '''from benchmark_io import serve
def initialize(params, config):
    return {'state': 0, 'tools': [{'name':'read', 'parameters': {'type':'object'}}]}
def call_tool(params, config):
    if params.get('bad_type'):
        return {'content':'not found', 'error':True}
    return {'content':'', 'error':'Record not found'} if params.get('missing') else {'content':'record'}
def score(params, config):
    return {'metrics':[{'metric':'score', 'value':1.0000000000000002,
        'evidence': [{}] if params.get('bad_type') else ['event-1']}]}
serve({'initialize':initialize, 'call_tool':call_tool, 'score':score})
'''


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires Docker")
def test_real_conformance_checks_success_error_and_grading_paths(tmp_path):
    from evalclaw.authoring.readiness import exercise
    root = package(tmp_path, {"id":"one", "prompt":"prompt.txt", "service": {
        "image":"python:3.11-slim", "files":["service.py"], "command":["python", "-u", "service.py"]},
        "grading":{"method":"environment"}}, {"service.py":CONFORMANCE_SERVICE})
    suite = load_package(root)
    result = exercise(suite, [
        {"task":"one", "component":"environment", "calls":[
            {"method":"initialize"}, {"method":"call_tool"},
            {"method":"call_tool", "params":{"missing":True}}, {"method":"score"}]},
        {"task":"one", "component":"environment", "calls":[{"method":"call_tool", "params":{"bad_type":True}}]},
        {"task":"one", "component":"environment", "calls":[{"method":"score", "params":{"bad_type":True}}]},
    ])
    assert [case["status"] for case in result["cases"]] == ["passed", "failed", "failed"]
    assert result["cases"][0]["calls"][2]["result"]["error"] == "Record not found"
    assert result["cases"][0]["calls"][3]["result"]["metrics"][0]["value"] > 1


@pytest.mark.skipif(os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires Docker")
@pytest.mark.parametrize("build", [False, True])
def test_real_dependency_preparation_uses_declared_source(tmp_path, build):
    import uuid
    from evalclaw.authoring.readiness import prepare
    from evalclaw.execution.docker import docker_subprocess_env, resolve_docker_executable
    alias = "evalclaw-authoring-test:" + uuid.uuid4().hex
    root = package(tmp_path)
    manifest = json.loads((root / "benchmark.json").read_text())
    if build:
        (root / "Dockerfile").write_text("FROM python:3.11-slim\nLABEL evalclaw.test=authoring\n")
    manifest["images"] = [{"image":alias, **({"dockerfile":"Dockerfile"} if build else {"source":"python:3.11-slim"})}]
    (root / "benchmark.json").write_text(json.dumps(manifest))
    try:
        report = prepare(root, load_package(root))
        assert report["images"][0]["dependency"]["image"] == alias
        assert report["images"][0]["image_id"].startswith("sha256:")
    finally:
        subprocess.run([resolve_docker_executable("docker"), "image", "rm", alias],
                       capture_output=True, timeout=30, env=docker_subprocess_env("docker"))
