"""Implement the upstream API interface with an OpenAI-compatible endpoint."""

import itertools
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

_requests = itertools.count(int(os.environ.get("BENCHMAKER_REQUEST_OFFSET", "0")))
_log_lock = threading.Lock()


class Get:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["BENCHMAKER_API_KEY"],
            base_url=os.environ["BENCHMAKER_BASE_URL"],
            timeout=180,
            max_retries=2,
        )

    def calc(self, query, temp=1, n=1, model="4omini"):
        actual_model = (
            os.environ["BENCHMAKER_CALIBRATION_MODEL"] if model == "4omini" else model
        )

        def complete(request_id):
            seed = int(os.environ["BENCHMAKER_SEED"]) + request_id
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
                "finish_reason": choice.finish_reason,
                "usage": response.usage.model_dump(),
            }
            with _log_lock, open("requests.jsonl", "a") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            return choice.message.content, response.usage

        ids = [next(_requests) for _ in range(n)]
        with ThreadPoolExecutor(max_workers=int(os.environ["BENCHMAKER_CONCURRENCY"])) as pool:
            results = list(pool.map(complete, ids))
        # Upstream ignores this field; record token counts, not an estimated price.
        return [r[0] for r in results], {
            "prompt": sum(r[1].prompt_tokens for r in results),
            "completion": sum(r[1].completion_tokens for r in results),
        }
