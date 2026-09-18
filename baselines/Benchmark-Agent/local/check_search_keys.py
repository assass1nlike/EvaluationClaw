"""Small, interleaved single-key / four-key test; no retries to hide throttling."""

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from openai import OpenAI

from local.run_with_usage import UsageRecorder
from utils.model_config import get_tool_model, load_model_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    api = load_model_config()["web_search_api"]
    keys = [os.environ[name] for name in api["api_key_envs"]]
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
    manifest = {"started_utc": datetime.now(timezone.utc).isoformat(), "base_url": api["base_url"],
                "request": payload, "concurrency": 4, "attempts_per_request": 1,
                "round_order": ["single", "pool", "pool", "single"], "rounds": []}

    def run(index, slot):
        key = keys[slot]
        started = time.monotonic()
        row = {"index": index, "key_slot": slot + 1,
               "credential_id": hashlib.sha256(key.encode()).hexdigest()[:12]}
        try:
            with OpenAI(api_key=key, base_url=api["base_url"], timeout=180, max_retries=0) as client:
                raw = client.responses.with_raw_response.create(**payload)
                result = raw.parse()
            recorder.record("probe.request_response", model, response=result, api_key=key)
            row.update(http_status=raw.status_code, response_status=result.status,
                       incomplete_details=result.incomplete_details.model_dump() if result.incomplete_details else None,
                       usage=result.usage.model_dump() if result.usage else None,
                       tool_usage=getattr(result, "tool_usage", None),
                       search_calls=[item.model_dump() for item in result.output if item.type == "web_search_call"],
                       answer=result.output_text)
            headers = raw.headers
        except Exception as exc:
            recorder.record("probe.request_response", model, error=exc, api_key=key)
            http = getattr(exc, "response", None)
            headers = http.headers if http is not None else {}
            row.update(http_status=getattr(exc, "status_code", None), error_type=type(exc).__name__,
                       error_code=getattr(exc, "code", None))
            body = getattr(exc, "body", None)
            if isinstance(body, dict):
                message = body.get("message", "")
                for secret in keys:
                    message = message.replace(secret, "[REDACTED]")
                row["error_message"] = message[:3000]
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        row["rate_limit_headers"] = {k: v for k, v in headers.items() if k.lower().startswith(
            ("retry-after", "x-ratelimit-", "x-ms-ratelimit-", "x-ms-retry-after"))}
        return row

    for mode in manifest["round_order"]:
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: run(i, i if mode == "pool" else 0), range(4)))
        entry = {"mode": mode, "elapsed_seconds": round(time.monotonic() - started, 3), "results": results}
        manifest["rounds"].append(entry)
        (recorder.directory / "comparison.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(mode, [(r["key_slot"], r["http_status"], r.get("response_status")) for r in results], flush=True)
        if any(r["http_status"] == 429 for r in results):
            # Do not escalate load or immediately run another group inside a rate-limit window.
            manifest["stopped_after_throttling"] = True
            break
    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (recorder.directory / "comparison.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    recorder.finish("completed")
    print(recorder.directory, flush=True)


if __name__ == "__main__":
    main()
