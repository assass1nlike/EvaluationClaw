"""Probe the evaluation gateway without retries or benchmark scoring."""

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from openai import AsyncOpenAI
from local.run_with_usage import UsageRecorder


def seed_everything(seed):
    random.seed(seed)
    import numpy as np
    np.random.seed(seed)


async def main(args):
    seed_everything(42)
    load_dotenv(ROOT / ".env")
    key = os.environ["RIGHTAPI_API_KEY"]
    args.output.mkdir(parents=True, exist_ok=False)
    recorder = UsageRecorder(args.output)
    payload = {"model": "gpt-5.6-sol", "stream": False, "max_completion_tokens": 2048,
               "messages": [{"role": "user", "content":
                   "A fair six-sided die is rolled twice. Given that the sum is at least 9, "
                   "what is the probability that at least one roll is 6? "
                   "Explain by enumerating the relevant ordered pairs, then give the reduced fraction."}]}
    report = {"started_utc": datetime.now(timezone.utc).isoformat(),
              "base_url": "https://www.rightapi.ai/v1", "request": payload,
              "levels": args.levels, "requests_per_level": args.requests,
              "timeout_seconds": args.timeout, "attempts_per_request": 1,
              "seed": 42, "hash_seed": os.environ.get("PYTHONHASHSEED"),
              "api_seed_temperature_reasoning": "provider defaults (omitted)",
              "cooldown_seconds": 15, "rounds": [], "status": "running"}

    def save():
        temporary = args.output / "report.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(args.output / "report.json")

    save()
    async with AsyncOpenAI(api_key=key, base_url=report["base_url"], timeout=args.timeout,
                           max_retries=0) as client:
        for concurrency in args.levels:
            if report["rounds"]:
                await asyncio.sleep(15)
            gate = asyncio.Semaphore(concurrency)
            active, peak = 0, 0
            started = time.monotonic()

            async def request(index):
                nonlocal active, peak
                async with gate:
                    active += 1
                    peak = max(peak, active)
                    before = time.monotonic()
                    row = {"concurrency": concurrency, "index": index,
                           "start_offset_seconds": before - started,
                           "started_utc": datetime.now(timezone.utc).isoformat()}
                    response, error, headers = None, None, {}
                    try:
                        raw = await client.chat.completions.with_raw_response.create(**payload)
                        headers = raw.headers
                        row["http_status"] = raw.status_code
                        response = raw.parse()
                        row["response"] = response.model_dump(mode="json")
                        choice = response.choices[0]
                        row["completed"] = choice.finish_reason == "stop" and bool(choice.message.content)
                        row["finish_reason"] = choice.finish_reason
                    except Exception as exc:
                        error = exc
                        http = getattr(exc, "response", None)
                        headers = http.headers if http is not None else headers
                        row.update(completed=False, error_type=type(exc).__name__,
                                   http_status=getattr(exc, "status_code", row.get("http_status")),
                                   error_code=getattr(exc, "code", None),
                                   error_message=str(getattr(exc, "body", None) or exc).replace(key, "[REDACTED]")[:3000])
                    finally:
                        active -= 1
                    row["elapsed_seconds"] = time.monotonic() - before
                    row["end_offset_seconds"] = time.monotonic() - started
                    row["rate_limit_headers"] = {k: v for k, v in headers.items()
                                                if k.lower().startswith(("retry-after", "x-ratelimit-", "x-ms-ratelimit-"))}
                    recorder.record("sol_probe.request_response", payload["model"],
                                    response=response, error=error, api_key=key)
                    with (args.output / "requests.jsonl").open("a") as handle:
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    print(json.dumps({k: v for k, v in row.items() if k != "response"}), flush=True)
                    return row

            rows = await asyncio.gather(*(request(i) for i in range(args.requests or concurrency)))
            latencies = sorted(r["elapsed_seconds"] for r in rows)
            entry = {"concurrency": concurrency, "requests": len(rows), "peak_client_inflight": peak,
                     "completed": sum(r["completed"] for r in rows),
                     "http_status_counts": dict(Counter(str(r["http_status"]) for r in rows)),
                     "elapsed_seconds": time.monotonic() - started,
                     "latency_min": latencies[0], "latency_median": latencies[len(rows) // 2],
                     "latency_max": latencies[-1]}
            report["rounds"].append(entry)
            save()
            print("ROUND " + json.dumps(entry), flush=True)
            if entry["completed"] != len(rows):
                report["stopped_at_failure_level"] = concurrency
                break
    report.update(status="completed", finished_utc=datetime.now(timezone.utc).isoformat())
    save()
    recorder.finish("completed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--levels", type=int, nargs="+", default=[1, 2, 4, 8, 16, 32])
    parser.add_argument("--requests", type=int)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if min(args.levels) < 1 or (args.requests is not None and args.requests < max(args.levels)):
        parser.error("positive levels required; requests must cover the largest level")
    asyncio.run(main(args))
