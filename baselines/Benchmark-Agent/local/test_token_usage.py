import asyncio
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from local.run_with_usage import UsageRecorder, observe_async, observe_calls, observe_sync


def response(content="{}", usage=None):
    return SimpleNamespace(
        id="test-response", model="test-model", usage=usage,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def events(recorder):
    return [json.loads(line) for line in (recorder.directory / "calls.jsonl").read_text().splitlines()]


def test_sync_preserves_arguments_and_response(tmp_path):
    recorder = UsageRecorder(tmp_path)
    usage = {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
             "completion_tokens_details": {"reasoning_tokens": 2}, "prompt_cache_hit_tokens": 6}
    result = response(usage=usage)
    messages = [{"role": "user", "content": "private prompt"}]
    received = []

    def call(*args, **kwargs):
        received.append((args, kwargs))
        return result

    wrapped = observe_sync(call, recorder, "test")
    assert wrapped("positional", model="test-model", messages=messages, api_key="secret") is result
    assert received == [(('positional',), {"model": "test-model", "messages": messages, "api_key": "secret"})]
    assert received[0][1]["messages"] is messages
    assert events(recorder)[0]["usage"] == usage
    assert recorder.summary["reported_tokens"] == {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}
    text = (recorder.directory / "calls.jsonl").read_text()
    assert "private prompt" not in text and "secret" not in text


def test_async_and_exception_identity(tmp_path):
    recorder = UsageRecorder(tmp_path)
    result = response(usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5})
    original_error = RuntimeError("private error")
    received = []

    async def call(**kwargs):
        received.append(kwargs)
        if kwargs.get("fail"):
            raise original_error
        return result

    wrapped = observe_async(call, recorder, "async")
    assert asyncio.run(wrapped(model="test-model", stream=False)) is result
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(wrapped(model="test-model", fail=True))
    assert caught.value is original_error
    assert received == [{"model": "test-model", "stream": False}, {"model": "test-model", "fail": True}]
    assert recorder.summary["failed_calls"] == 1
    assert recorder.summary["calls_with_incomplete_usage"] == 1
    assert "private error" not in (recorder.directory / "calls.jsonl").read_text()


def test_retry_behavior_identical_and_every_response_counted(tmp_path, monkeypatch):
    from utils import core, llm_caller

    def run(observed):
        requests = []
        replies = iter([response("not json", {"prompt_tokens": 11, "completion_tokens": 1, "total_tokens": 12}),
                        response('{"answer": 42}', {"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18})])

        def fake_completion(**kwargs):
            requests.append(copy.deepcopy(kwargs))
            return next(replies)

        monkeypatch.setattr(llm_caller, "completion", fake_completion)
        payload = {"mode": "json", "model": "test-model", "user_prompt": "test"}
        if observed:
            recorder = UsageRecorder(tmp_path)
            original_sync, original_async = core.completion, core.acompletion
            with observe_calls(recorder):
                result = llm_caller.llm_call(payload)
            assert core.completion is original_sync and core.acompletion is original_async
            assert llm_caller.completion is fake_completion
            assert recorder.summary["finished_calls"] == 2
            assert recorder.summary["reported_tokens"]["total_tokens"] == 30
        else:
            result = llm_caller.llm_call(payload)
        return result, requests

    assert run(False) == run(True)


def test_concurrent_calls_and_distinct_resume_runs(tmp_path):
    recorder = UsageRecorder(tmp_path)
    result = response(usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})
    wrapped = observe_sync(lambda **kwargs: result, recorder, "tool")
    with ThreadPoolExecutor(max_workers=8) as pool:
        outputs = list(pool.map(lambda _: wrapped(model="test-model"), range(40)))
    assert all(item is result for item in outputs)
    recorder.finish("completed")
    summary = json.loads((recorder.directory / "summary.json").read_text())
    assert summary["reported_tokens"]["total_tokens"] == 200
    assert len(events(recorder)) == 40
    assert summary["calls_with_incomplete_usage"] == summary["logging_errors"] == 0
    resumed = UsageRecorder(tmp_path)
    resumed.finish("completed")
    assert resumed.directory != recorder.directory
    assert resumed.summary["finished_calls"] == 0


def test_logging_failure_preserves_result_and_original_error(tmp_path, monkeypatch):
    recorder = UsageRecorder(tmp_path)
    result = response()
    original_error = ValueError("original")

    def fail_to_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(type(tmp_path), "open", fail_to_write)
    assert observe_sync(lambda: result, recorder, "tool")() is result

    def fail():
        raise original_error

    with pytest.raises(ValueError) as caught:
        observe_sync(fail, recorder, "tool")()
    assert caught.value is original_error
    assert recorder.summary["logging_errors"] == 2


def test_stream_not_consumed_and_missing_usage_not_estimated(tmp_path):
    recorder = UsageRecorder(tmp_path)
    stream = iter(["chunk"])
    assert observe_sync(lambda **kwargs: stream, recorder, "tool")(stream=True) is stream
    assert next(stream) == "chunk"
    partial = response(usage={"prompt_tokens": 7})
    observe_sync(lambda: partial, recorder, "tool")()
    assert recorder.summary["calls_with_incomplete_usage"] == 2
    assert recorder.summary["reported_tokens"] == {"prompt_tokens": 7, "completion_tokens": 0, "total_tokens": 0}
