"""Measure four-key native-search bursts without request retries."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from openai import AsyncOpenAI
from local.run_with_usage import UsageRecorder
from utils.model_config import get_tool_model, load_model_config


async def measure(args):
    load_dotenv(ROOT / ".env")
    api = load_model_config()["web_search_api"]
    keys = [os.environ[name] for name in api["api_key_envs"]]
    if len(set(keys)) != 4:
        raise ValueError("This probe requires four distinct configured keys")
    model = get_tool_model("web_search")
    recorder = UsageRecorder(args.output)
    payload = {
        "model": model.removeprefix("openai/responses/"),
        "input": "Search official NASA sources: is Venus or Mercury the hottest planet, and why? "
                 "Answer briefly in your own words with the source URL.",
        "tools": [{"type": "web_search", "search_context_size": "medium"}],
        "tool_choice": "required", "max_output_tokens": 12000,
        "include": ["web_search_call.action.sources"],
    }
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "base_url": api["base_url"],
              "request": payload, "levels": args.levels, "rounds_per_level": args.rounds,
              "cooldown_seconds": args.cooldown, "initial_cooldown_seconds": args.initial_cooldown,
              "timeout_seconds": 180,
              "attempts_per_request": 1, "assignment": "index modulo four",
              "requests_per_round": args.requests,
              "measurement": "closed-loop concurrency" if args.requests else "one simultaneous burst per round",
              "rounds": []}
    report_path = recorder.directory / "concurrency.json"

    def save():
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(report_path)

    clients = [AsyncOpenAI(api_key=key, base_url=api["base_url"], timeout=180, max_retries=0)
               for key in keys]
    status = "failed"
    try:
        save()
        print(f"Report: {report_path}", flush=True)
        if args.initial_cooldown:
            print(f"Initial cooldown {args.initial_cooldown}s", flush=True)
            await asyncio.sleep(args.initial_cooldown)
        for concurrency in args.levels:
            limited = False
            for repeat in range(args.rounds):
                if report["rounds"]:
                    print(f"Cooldown {args.cooldown}s", flush=True)
                    await asyncio.sleep(args.cooldown)
                active, peak = 0, 0
                started = time.monotonic()

                async def request(index):
                    nonlocal active, peak
                    slot = index % 4
                    key = keys[slot]
                    row = {"index": index, "key_slot": slot + 1,
                           "credential_id": hashlib.sha256(key.encode()).hexdigest()[:12],
                           "started_utc": datetime.now(timezone.utc).isoformat(),
                           "start_offset_seconds": time.monotonic() - started}
                    active += 1
                    peak = max(peak, active)
                    result, error, headers = None, None, {}
                    try:
                        raw = await clients[slot].responses.with_raw_response.create(**payload)
                        result = raw.parse()
                        headers = raw.headers
                        searches = [x for x in result.output if x.type == "web_search_call"]
                        row.update(http_status=raw.status_code, response_status=result.status,
                                   incomplete_details=result.incomplete_details.model_dump() if result.incomplete_details else None,
                                   completed_searches=sum(x.status == "completed" for x in searches),
                                   usage=result.usage.model_dump() if result.usage else None,
                                   tool_usage=getattr(result, "tool_usage", None))
                    except Exception as exc:
                        error = exc
                        http = getattr(exc, "response", None)
                        headers = http.headers if http is not None else {}
                        message = str(getattr(exc, "body", None) or type(exc).__name__)
                        for secret in keys:
                            message = message.replace(secret, "[REDACTED]")
                        row.update(http_status=getattr(exc, "status_code", None),
                                   error_type=type(exc).__name__, error_code=getattr(exc, "code", None),
                                   error_message=message[:3000])
                    finally:
                        active -= 1
                        row["end_offset_seconds"] = time.monotonic() - started
                        row["elapsed_seconds"] = row["end_offset_seconds"] - row["start_offset_seconds"]
                    row["rate_limit_headers"] = {k: v for k, v in headers.items() if k.lower().startswith(
                        ("retry-after", "x-ratelimit-", "x-ms-ratelimit-", "x-ms-retry-after"))}
                    recorder.record("concurrency.request_response", model, response=result, error=error, api_key=key)
                    with (recorder.directory / "requests.jsonl").open("a") as handle:
                        handle.write(json.dumps({"concurrency": concurrency, "repeat": repeat + 1, **row}) + "\n")
                    return row

                gate = asyncio.Semaphore(concurrency)

                async def scheduled(index):
                    async with gate:
                        return await request(index)

                rows = await asyncio.gather(*(scheduled(index) for index in range(args.requests or concurrency)))
                entry = {"concurrency": concurrency, "repeat": repeat + 1, "peak_client_inflight": peak,
                         "elapsed_seconds": time.monotonic() - started,
                         "http_status_counts": dict(Counter(str(x["http_status"]) for x in rows)),
                         "completed_with_search": sum(x.get("response_status") == "completed" and
                                                      x.get("completed_searches", 0) > 0 for x in rows),
                         "results": rows}
                report["rounds"].append(entry)
                save()
                print(json.dumps({k: v for k, v in entry.items() if k != "results"}), flush=True)
                limited |= any(x["http_status"] == 429 for x in rows)
            if limited:
                report["stopped_at_first_throttled_level"] = concurrency
                break
        status = "completed"
    finally:
        await asyncio.gather(*(client.close() for client in clients))
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        report["status"] = status
        save()
        recorder.finish(status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--levels", type=int, nargs="+", default=[4, 8, 16, 32, 64, 128, 256])
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--cooldown", type=float, default=65)
    parser.add_argument("--initial-cooldown", type=float, default=65)
    parser.add_argument("--requests", type=int, help="Total requests per round; refill each freed worker immediately")
    args = parser.parse_args()
    if min(args.levels) < 1 or args.rounds < 1 or min(args.cooldown, args.initial_cooldown) < 0:
        parser.error("levels and rounds must be positive; cooldown must be nonnegative")
    if args.requests is not None and args.requests < max(args.levels):
        parser.error("requests must be at least the largest concurrency level")
    asyncio.run(measure(args))
