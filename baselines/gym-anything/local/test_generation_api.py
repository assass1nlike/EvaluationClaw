"""Exercise the official client's stream parser and the local service wiring."""

import json
import os

import anthropic
import httpx

from local import generate
from extras.research.task_generation.propose_and_amplify import method
from extras.research.task_generation.propose_and_amplify.pipeline import utils_enhanced


def test_official_stream_preserves_parameters_and_conversation(tmp_path, monkeypatch):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        message = {"id": "msg_test", "type": "message", "role": "assistant",
                   "model": "deepseek-flash", "content": [], "stop_reason": None,
                   "stop_sequence": None, "usage": {"input_tokens": 9, "output_tokens": 0}}
        events = [
            ("message_start", {"message": message}),
            ("content_block_start", {"index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
            ("content_block_delta", {"index": 0, "delta": {"type": "thinking_delta", "thinking": "reasoning"}}),
            ("content_block_stop", {"index": 0}),
            ("content_block_start", {"index": 1, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"index": 1, "delta": {"type": "text_delta", "text": "result"}}),
            ("content_block_stop", {"index": 1}),
            ("message_delta", {"delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 3}}),
            ("message_stop", {}),
        ]
        body = "".join(f"event: {name}\ndata: {json.dumps({'type': name, **data})}\n\n"
                       for name, data in events)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(utils_enhanced, "USAGE_DUMP_DIR", str(tmp_path / "usage"))
    with anthropic.Anthropic(api_key="test-key", base_url="https://example.invalid/anthropic",
                             http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        first = utils_enhanced.create_llm("deepseek-flash", verbose=False)
        first.client = client
        result = first.chat("Design a task.", retry_count=1)
        assert result["response"] == "result"
        assert result["think_text"] == "reasoning"
        second = utils_enhanced.create_llm("deepseek-flash", verbose=False)
        second.client = client
        second.set_conversation(first.get_conversation())
        second.chat("Implement that task.", retry_count=1)
    assert len(requests) == 2
    assert requests[0]["temperature"] == 1.0
    assert requests[0]["max_tokens"] == 40000
    assert requests[0]["thinking"] == {"type": "enabled", "budget_tokens": 16384}
    assert requests[0]["stream"] is True
    assert requests[1]["messages"][:-1] == first.get_conversation()


def test_deepseek_configuration_is_scoped_and_credentials_are_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=test-secret-123\nDEEPSEEK_BASE_URL=https://api.deepseek.com/\n"
        "DEEPSEEK_MODEL=deepseek-flash\n"
    )
    requirement = tmp_path / "requirement.txt"
    requirement.write_text("Evaluate consistency.")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "original-key")

    def pipeline(args):
        assert args.proposer_model == args.amplifier_model == "deepseek-flash"
        assert os.environ["ANTHROPIC_API_KEY"] == "test-secret-123"
        assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "test-secret-123"
        assert os.environ["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
        return 0

    monkeypatch.setattr(method, "run_pipeline", pipeline)
    assert generate.main(["--deepseek", "--requirement-file", str(requirement),
                          "--software", "Demo", "--env-dir", "demo_env",
                          "--output-dir", str(tmp_path / "output")]) == 0
    assert os.environ["ANTHROPIC_API_KEY"] == "original-key"
    saved = json.loads((tmp_path / "output/input_all.json").read_text())
    assert saved["proposer_model"] == saved["amplifier_model"] == "deepseek-flash"
    assert "test-secret-123" not in (tmp_path / "output/input_all.json").read_text()
