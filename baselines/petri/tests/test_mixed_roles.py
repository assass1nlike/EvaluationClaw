import json

import httpx
import pytest
from inspect_ai.model import get_model

import run
from test_dual_judge import NATIVE_PROMPT, NATIVE_RESPONSE
from test_scoring import JUDGMENT
from requirement_judge import SYSTEM_PROMPT
from test_sol import response_event


@pytest.mark.parametrize("target_provider,mismatches", [("qwen", 0), ("sol", 0), ("sol", 1), ("sol", 3)])
def test_deepseek_auditor_and_judges_route_target(tmp_path, monkeypatch, target_provider, mismatches):
    requests = []
    slots = []
    monkeypatch.setattr(run.sol_api, "wait_for_slot", lambda path, rpm: slots.append(rpm) or 1)
    actions = iter([
        ("send_message", {"message": "Return count=7 as JSON.",
                          **({"prefill": '{"count":'} if target_provider == "qwen" else {})}),
        ("end_conversation", {}),
    ])
    monkeypatch.setattr(run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENAI_API_KEY", "deepseek-test")
    monkeypatch.setenv("QWEN_API_KEY", "qwen-test")
    monkeypatch.setenv("SOL_API_KEY", "sol-test")

    def respond(request):
        body = json.loads(request.content)
        host = request.url.host
        requests.append((host, body))
        if host == "sol.invalid":
            assert request.headers["authorization"] == "Bearer sol-test"
            assert body["model"] == "gpt-5.6-sol"
            assert body["reasoning"]["effort"] == "high"
            assert body["max_output_tokens"] == 300000
            assert "seed" not in body and "thinking" not in body
            response = response_event(body)
            if sum(host == "sol.invalid" for host, _ in requests) <= mismatches:
                event = json.loads(response.text.split("data: ", 1)[1])
                event["response"]["model"] = "gpt-6-sol"
                return httpx.Response(200, text="data: " + json.dumps(event) + "\n\n",
                                      headers={"content-type": "text/event-stream"})
            return response
        finish = "stop"
        if host == "qwen.invalid":
            assert request.headers["authorization"] == "Bearer qwen-test"
            assert body["model"] == "qwen3.8-27b"
            assert body["messages"][-1]["partial"] is True
            assert body["messages"][-1]["content"] == '{"count":'
            assert body["enable_thinking"] is True
            assert body["max_completion_tokens"] == 300000
            message = {"role": "assistant", "content": "7}"}
        else:
            assert host == "deepseek.invalid"
            assert request.headers["authorization"] == "Bearer deepseek-test"
            assert body["model"] == "deepseek-flash"
            assert body["thinking"] == {"type": "enabled"}
            assert body["max_tokens"] == 300000
            assert all("partial" not in m and "prefix" not in m for m in body["messages"])
            system = body["messages"][0]["content"]
            if system in (SYSTEM_PROMPT, NATIVE_PROMPT):
                message = {"role": "assistant", "content": json.dumps(JUDGMENT)
                           if system == SYSTEM_PROMPT else NATIVE_RESPONSE}
            else:
                name, arguments = next(actions)
                message = {"role": "assistant", "content": "", "reasoning_content": "Proceed with the audit.",
                           "tool_calls": [{"id": name, "type": "function", "function": {
                               "name": name, "arguments": json.dumps(arguments)}}]}
                finish = "tool_calls"
        assert body["seed"] == 61
        assert body["reasoning_effort"] == "high"
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    def model(name, **kwargs):
        return get_model(name, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)), **kwargs)

    monkeypatch.setattr(run, "get_model", model)
    directory = tmp_path / "run"
    monkeypatch.setattr("sys.argv", [
        "run.py", "--auditor", "deepseek/deepseek-flash", "--target",
        "qwen/qwen3.8-27b" if target_provider == "qwen" else "sol/gpt-5.6-sol",
        "--judge", "deepseek/deepseek-flash", "--base-url", "https://deepseek.invalid/v1",
        "--target-base-url", f"https://{target_provider}.invalid/v1", "--thinking", "enabled",
        "--reasoning-effort", "high", "--max-tokens", "300000", "--prefill-mode",
        "prefill" if target_provider == "qwen" else "no-prefill",
        "--sol-rate-limit-file", str(tmp_path / "rate"),
        "--seed", "61", "--output-dir", str(directory),
    ])
    if mismatches == 3:
        with pytest.raises(RuntimeError):
            run.main()
        assert len(requests) == 4  # One auditor call, three rejected target attempts, no judging.
        assert not (directory / "judgment.json").exists()
        assert not (directory / "native_judgment.json").exists()
    else:
        run.main()
        assert len(requests) == 5 + mismatches
    if target_provider == "sol":
        target_requests = [body for host, body in requests if host == "sol.invalid"]
        assert target_requests == [target_requests[0]] * len(target_requests)
        assert len(slots) == len(target_requests)
        events = [json.loads(line) for line in (directory / "sol-calls.jsonl").read_text().splitlines()]
        rejected = [event for event in events if event.get("error")]
        assert len(rejected) == mismatches
        assert all(event["rejected_response"]["model"] == "gpt-6-sol" for event in rejected)
    if mismatches == 3:
        return
    config = json.loads((directory / "config.json").read_text())
    assert config["base_urls"] == {"auditor": "https://deepseek.invalid/v1",
                                   "target": f"https://{target_provider}.invalid/v1", "judge": "https://deepseek.invalid/v1"}
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["scores"]["performance"] == JUDGMENT["score"]
    assert len(summary["native_reference"]["scores"]) == 23
    assert summary["status"] == "success"
