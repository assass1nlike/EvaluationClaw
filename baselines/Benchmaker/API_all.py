"""Implement the upstream API interface with an OpenAI-compatible endpoint."""

import itertools
import json
import os
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

_requests = itertools.count(int(os.environ.get("BENCHMAKER_REQUEST_OFFSET", "0")))
_log_lock = threading.Lock()
_usage_path = Path("usage.json")
_usage = {
    "recorded_requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
}
if Path("requests.jsonl").exists():
    with open("requests.jsonl") as records:
        for line in records:
            usage = json.loads(line)["usage"]
            _usage["recorded_requests"] += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                _usage[key] += usage[key]


class Get:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["BENCHMAKER_API_KEY"],
            base_url=os.environ["BENCHMAKER_BASE_URL"],
            timeout=float(os.environ.get("BENCHMAKER_TIMEOUT", "180")),
            max_retries=2,
        )

    def calc(self, query, temp=1, n=1, model="4omini"):
        actual_model = (
            os.environ["BENCHMAKER_CALIBRATION_MODEL"] if model == "4omini" else model
        )

        def complete(request_id):
            seed = int(os.environ["BENCHMAKER_SEED"]) + request_id
            started = time.time()
            response = self.client.chat.completions.create(
                model=actual_model,
                messages=[{"role": "user", "content": query}],
                temperature=temp,
                max_tokens=int(os.environ["BENCHMAKER_MAX_TOKENS"]),
                seed=seed,
                extra_body=json.loads(os.environ["BENCHMAKER_EXTRA_BODY"]),
            )
            choice = response.choices[0]
            record = {
                "request_id": request_id, "model": actual_model,
                "temperature": temp, "seed": seed, "prompt": query,
                "response": choice.message.content,
                "reasoning_content": getattr(choice.message, "reasoning_content", None),
                "response_model": response.model,
                "max_tokens": int(os.environ["BENCHMAKER_MAX_TOKENS"]),
                "extra_body": json.loads(os.environ["BENCHMAKER_EXTRA_BODY"]),
                "stage": os.environ.get("BENCHMAKER_STAGE", "preflight"),
                "started_at": started, "elapsed_seconds": time.time() - started,
                "finish_reason": choice.finish_reason,
                "usage": response.usage.model_dump(),
            }
            with _log_lock, open("requests.jsonl", "a") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                _usage["recorded_requests"] += 1
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    _usage[key] += getattr(response.usage, key)
                temporary = _usage_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(_usage, indent=2) + "\n")
                temporary.replace(_usage_path)
            return choice.message.content, response.usage

        ids = [next(_requests) for _ in range(n)]
        with ThreadPoolExecutor(max_workers=int(os.environ["BENCHMAKER_CONCURRENCY"])) as pool:
            results = list(pool.map(complete, ids))
        # Upstream ignores this field; record token counts, not an estimated price.
        return [r[0] for r in results], {
            "prompt": sum(r[1].prompt_tokens for r in results),
            "completion": sum(r[1].completion_tokens for r in results),
        }
