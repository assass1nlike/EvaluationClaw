from __future__ import annotations

import queue

from evalclaw.live.bus import _SENTINEL, RunBus
from evalclaw.live.streamers import _stream_group


def test_snapshot_compacts_tokens_and_reports_cursor() -> None:
    bus = RunBus("run-1")
    bus.publish({"type": "llm_start", "call_id": "call-1", "t": 1})
    bus.publish({"type": "token", "call_id": "call-1", "text": "hello ", "t": 2})
    bus.publish({"type": "token", "call_id": "call-1", "text": "world", "t": 3})
    bus.publish({"type": "llm_end", "call_id": "call-1", "t": 4})

    snapshot = bus.snapshot()

    assert snapshot["last_seq"] == 4
    assert [event["seq"] for event in snapshot["events"]] == [1, 3, 4]
    assert snapshot["events"][1]["text"] == "hello world"


def test_subscription_replays_only_events_after_cursor() -> None:
    bus = RunBus("run-1")
    bus.publish({"type": "llm_start", "call_id": "call-1", "t": 1})
    bus.publish({"type": "token", "call_id": "call-1", "text": "before", "t": 2})
    bus.publish({"type": "token", "call_id": "call-1", "text": "after", "t": 3})
    bus.publish({"type": "log", "message": "done", "t": 4})
    bus.end()

    subscriber = bus.subscribe(after=2)

    token = subscriber.get_nowait()
    log = subscriber.get_nowait()
    assert token["seq"] == 3
    assert token["text"] == "after"
    assert log["seq"] == 4
    assert subscriber.get_nowait() is _SENTINEL
    try:
        subscriber.get_nowait()
    except queue.Empty:
        pass
    else:
        raise AssertionError("subscription replayed an event more than once")


def test_task_builder_stream_group_uses_builder_job_directory(tmp_path) -> None:
    trace_dir = tmp_path / "task-builder" / "dimension_1__job" / "invocation" / "tool-trace" / "llm"

    group_id, label = _stream_group(trace_dir, "construction", "task-builder-003")

    assert group_id == "construction:task-builder:dimension_1__job"
    assert label == "TaskBuilder dimension_1__job"


def test_other_stream_groups_remain_per_trace_name(tmp_path) -> None:
    group = _stream_group(tmp_path / "planner" / "invocation" / "llm", "planner", "planner-attempt-01")

    assert group is None
