"""Container integration checks without model inference; EVALCLAW_DOCKER_TESTS=1."""

import json
import os
from dataclasses import replace

import pytest

from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.runners import environment_actors
from evalclaw.runners.harness import ManifestHarness, ManifestHarnessRunner, get_harness
from evalclaw.types import BenchmarkConfig, BenchmarkItem, TargetModelConfig, TaskType

pytestmark = pytest.mark.skipif(
    os.environ.get("EVALCLAW_DOCKER_TESTS") != "1", reason="requires local Docker images",
)


def _task():
    return BenchmarkItem(
        id="portable", dimension_id="tools", task_type=TaskType.agent,
        prompt="Contact Alice and save the reply.",
        metadata={"agent_env": {
            "type": "docker_workspace", "image": "python:3.11", "auto_select_image": False,
            "timeout": 60, "max_steps": 10,
            "actors": [{"id": "alice", "description": "colleague", "system_prompt": "You are Alice."}],
            "visible_files": {
                "sealed.txt": "private fixture",
                "solve.py": """import json, os, subprocess
from pathlib import Path
assert os.getuid() != 0
assert Path('/tmp/setup-ready').read_text() == 'ready'
assert not Path('eval.py').exists()
assert not Path('/evalclaw-evidence').exists()
try:
    Path('sealed.txt').read_text()
except PermissionError:
    pass
else:
    raise AssertionError('target can read protected file')
subprocess.run(['git', 'status', '--porcelain'], check=True, capture_output=True)
client = ['python3', '/run/evalclaw-contacts/contacts.py']
assert json.loads(subprocess.check_output(client + ['list'])) == [{'id': 'alice', 'description': 'colleague'}]
for message in ['first', 'second']:
    reply = subprocess.check_output(client + ['send', 'alice', message], text=True)
    assert reply.strip() == 'ack:' + message
Path('answer.txt').write_text(reply.strip())
print('done')
""",
            },
            "setup_commands": [
                "git init -q && git config user.name tester && git config user.email tester@example.org",
                'chown -R "$EVALCLAW_TARGET_UID:$EVALCLAW_TARGET_GID" /workspace/.git',
                "chmod 000 sealed.txt && printf ready > /tmp/setup-ready",
            ],
            "hidden_files": {"eval.py": """import json
from pathlib import Path
assert Path('/tmp/setup-ready').read_text() == 'ready'
assert Path('sealed.txt').read_text() == 'private fixture'
evidence = json.loads(Path('/evalclaw-evidence/episode.json').read_text())
assert evidence['schema_version'] == 'evalclaw.evaluator_evidence.v1'
score = int(Path('answer.txt').exists() and Path('answer.txt').read_text() == 'ack:second')
print(json.dumps({'score': score, 'passed': bool(score)}))
"""},
            "test_command": "python3 eval.py", "evaluation": {"result_format": "json_on_stdout"},
        }},
    )


@pytest.mark.parametrize("name", ["openclaw", "openhands", "codex", "claude-code"])
def test_real_harness_images_share_preflight_actor_and_scoring_lifecycle(monkeypatch, tmp_path, name):
    calls = []

    def actor_reply(messages, _target, _tools, **kwargs):
        calls.append(json.loads(json.dumps(messages)))
        reply = "ack:" + messages[-1]["content"]
        return TargetToolModelResponse(
            adapter="openai", content=reply, tool_calls=[],
            assistant_message={"role": "assistant", "content": reply}, raw_response={},
        )

    monkeypatch.setattr(environment_actors, "call_target_model_with_tools", actor_reply)
    # Keep real harness images and their runtime checks. A deterministic terminal
    # driver replaces inference; no provider credentials or model calls are used.
    runner = ManifestHarnessRunner(replace(
        get_harness(name)._manifest, gateway=False, model_env={}, run="python3 solve.py {task}",
    ))
    target = TargetModelConfig(
        provider="anthropic" if name == "claude-code" else "openai", model="test", harness=name,
    )
    config = BenchmarkConfig(actor_model="test", actor_provider="openai", targets=[target])
    outcome = runner.preflight(_task(), target, config, artifact_dir=tmp_path / "preflight")
    assert outcome["baseline_score"] == 0
    assert calls == []
    assert json.loads((tmp_path / "preflight/episode.json").read_text())["status"] == "preflight"
    raw, score, _ = runner.run(_task(), target, config, artifact_dir=tmp_path / "run")
    assert score == 1 and raw.strip() == "done"
    assert len(calls) == 2
    assert len(calls[0]) == 1 and len(calls[1]) == 3
    evidence = json.loads((tmp_path / "run/evaluator-evidence.json").read_text())
    assert len(evidence["actors"]["interactions"]) == 2


@pytest.mark.parametrize("failure", ["setup", "runtime", "scorer", "score_format", "actor_client"])
def test_real_preflight_rejects_broken_runtime_or_evaluator(tmp_path, failure):
    item = _task()
    env = item.metadata["agent_env"]
    env["actors"] = []
    manifest = ManifestHarness(name="fixture", run="python3 solve.py", model_env={}, preflight=("python3 --version",))
    if failure == "setup":
        env["setup_commands"] = ["exit 7"]
    elif failure == "runtime":
        manifest = replace(manifest, preflight=("missing-harness --version",))
    elif failure == "scorer":
        env["test_command"] = "python3 missing-evaluator.py"
    elif failure == "score_format":
        env["test_command"] = "printf 'not a score'"
    else:
        env["actors"] = _task().metadata["agent_env"]["actors"]
        env["setup_commands"].append(
            'for path in /usr/local/bin/python3 /usr/bin/python3 /bin/python3; do '
            'if [ -e "$path" ]; then mv "$path" "$path-disabled"; fi; done'
        )
        manifest = replace(manifest, preflight=())
    with pytest.raises(RuntimeError):
        ManifestHarnessRunner(manifest).preflight(
            item, TargetModelConfig(provider="openai", model="test"),
            BenchmarkConfig(actor_model="test", actor_provider="openai"), artifact_dir=tmp_path,
        )
    episode = json.loads((tmp_path / "episode.json").read_text())
    assert episode["status"] == "failed"
    assert episode["target_started"] is False
