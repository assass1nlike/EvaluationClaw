import json
from concurrent.futures import ThreadPoolExecutor

import httpx
from openai import OpenAI

from local.request_rate import RequestPacer
from local.evaluate_qwen import request_with_retry


def virtual_clock(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("local.request_rate.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("local.request_rate.time.sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    return clock


def test_threads_share_rolling_minute_limit(monkeypatch, tmp_path):
    virtual_clock(monkeypatch)
    path = tmp_path / "starts.jsonl"
    pacer = RequestPacer(45, path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(pacer, [None] * 100))
    starts = [json.loads(line)["monotonic"] for line in path.read_text().splitlines()]
    assert len(starts) == 100
    assert all(sum(start <= other < start + 60 for other in starts) <= 45 for start in starts)


def test_http_retries_are_paced_and_preserve_high_request(monkeypatch, tmp_path):
    clock = virtual_clock(monkeypatch)
    starts, payloads = [], []
    def transport(request):
        starts.append(clock[0])
        payloads.append(json.loads(request.content))
        if len(starts) == 1:
            return httpx.Response(429, headers={"retry-after": "0"},
                                  json={"error": {"message": "limited", "type": "rate_limit_error"}})
        return httpx.Response(200, json={"id": "test", "object": "chat.completion",
            "created": 1, "model": "gpt-5.6-sol", "choices": [{"index": 0,
            "finish_reason": "stop", "message": {"role": "assistant", "content": "289"}}]})
    pacer = RequestPacer(45, tmp_path / "starts.jsonl")
    with OpenAI(api_key="test", base_url="https://example.test/v1", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(transport),
                                         event_hooks={"request": [pacer]})) as client:
        payload = {"model": "gpt-5.6-sol", "reasoning_effort": "high",
                   "max_completion_tokens": 131072, "stream": False,
                   "messages": [{"role": "user", "content": "17 squared?"}]}
        response = request_with_retry(client.chat.completions.create, **payload)
    assert response.choices[0].message.content == "289"
    assert payloads == [payload, payload]
    assert starts[1] - starts[0] >= 60 / 45
