import fcntl
import json
import multiprocessing
import time
from contextlib import contextmanager

import pytest

from local.test_search_retries import call, limited, clock
from local.test_native_responses import response
from utils import native_responses as native
from utils.search_queue import search_slot, infrastructure_wait, progress_clock, SearchInfrastructureError


def occupy(directory, start, acquired=None):
    start.wait()
    with search_slot(directory, 4):
        if acquired is not None:
            acquired.set()
            time.sleep(30)
        else:
            time.sleep(0.15)


def test_eight_processes_share_four_slots(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    jobs = [ctx.Process(target=occupy, args=(str(tmp_path), start)) for _ in range(8)]
    for job in jobs:
        job.start()
    start.set()
    for job in jobs:
        job.join(15)
        assert job.exitcode == 0
    rows = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    active, peak = set(), 0
    for row in rows:
        if row["event"] == "acquired":
            active.add(row["id"])
            peak = max(peak, len(active))
        else:
            active.remove(row["id"])
    assert not active and peak == 4


def test_process_death_releases_slot(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    start, acquired = ctx.Event(), ctx.Event()
    job = ctx.Process(target=occupy, args=(str(tmp_path), start, acquired))
    job.start()
    start.set()
    try:
        assert acquired.wait(10)
        with (tmp_path / "slot_0.lock").open("a") as slot:
            with pytest.raises(BlockingIOError):
                fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
            job.kill()
            job.join(5)
            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if job.is_alive():
            job.kill()
            job.join()


def test_queue_time_excluded_and_slot_released_before_retry(monkeypatch, clock):
    occupied = []
    requests = []

    @contextmanager
    def slot(*args):
        clock["now"] += 1000
        occupied.append(True)
        try:
            yield 1000
        finally:
            occupied.pop()

    def request(**kwargs):
        assert occupied
        requests.append(kwargs)
        if len(requests) == 1:
            raise limited()
        return response()

    def sleep(seconds):
        assert not occupied
        clock["now"] += seconds

    monkeypatch.setattr(native, "search_slot", slot)
    monkeypatch.setattr(native, "request_response", request)
    monkeypatch.setattr(native.time, "sleep", sleep)
    assert call(retry_config={"global_concurrency": 4, "queue_dir": "unused"}).status == "completed"
    assert requests[0]["timeout"] == 180
    assert requests[1]["timeout"] == 177.75
    assert requests[0]["input"] == requests[1]["input"]


def test_infrastructure_failure_bypasses_framework_error_handling(monkeypatch, clock):
    def request(**kwargs):
        raise limited()
    monkeypatch.setattr(native, "request_response", request)
    with pytest.raises(SearchInfrastructureError):
        native.responses_completion(**dict(
            model="openai/responses/test", messages=[], api_key="test", base_url="https://example.org",
            timeout=180, max_tokens=12000, tools=[], tool_choice="required", temperature=0.3,
            retry_config={"rate_limit_attempts": 1, "stop_on_api_error": True}))
    assert not issubclass(SearchInfrastructureError, Exception)


def test_watchdog_clock_excludes_waiting():
    before = progress_clock()
    with infrastructure_wait():
        time.sleep(0.1)
        assert progress_clock() - before < 0.05
    assert progress_clock() - before < 0.05
