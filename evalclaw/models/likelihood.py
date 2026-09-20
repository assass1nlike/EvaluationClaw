"""Exact continuation scoring for endpoints exposing completion log probabilities."""
from __future__ import annotations

import math
import os

import httpx


def continuation_likelihood(messages, continuations, target, *, timeout_s=300):
    # A chat template is part of the original protocol, not something this
    # adapter is permitted to guess. Callers provide its exact rendered prompt.
    if len(messages) != 1 or messages[0]["role"] != "user" or not isinstance(messages[0]["content"], str):
        raise ValueError("Completion likelihood requires one explicitly rendered text prompt")
    prefix = messages[0]["content"]
    url = (target.base_url or "https://api.openai.com/v1").rstrip("/") + "/completions"
    key = target.api_key or os.environ.get("OPENAI_API_KEY", "")
    results = []
    with httpx.Client(timeout=timeout_s) as client:
        for continuation in continuations:
            try:
                response = client.post(url, headers={"Authorization": f"Bearer {key}"}, json={
                    **target.extra_body, "model": target.model, "prompt": prefix + continuation,
                    "max_tokens": 0, "echo": True, "logprobs": 1,
                })
            except httpx.TimeoutException as exc:
                raise TimeoutError("Continuation likelihood request timed out") from exc
            response.raise_for_status()
            raw = response.json()
            choice = raw["choices"][0]
            if choice["text"] != prefix + continuation:
                raise ValueError("Likelihood endpoint did not echo the exact prompt and continuation")
            probabilities = choice["logprobs"]
            offsets = probabilities["text_offset"]
            values = probabilities["token_logprobs"]
            if len(offsets) != len(values):
                raise ValueError("Likelihood token offsets and probabilities do not align")
            if continuation and len(prefix) not in offsets:
                raise ValueError("Continuation starts inside a token; cannot attribute its exact likelihood")
            selected = [value for offset, value in zip(offsets, values) if offset >= len(prefix)]
            if any(value is None or not math.isfinite(value) for value in selected):
                raise ValueError("Endpoint omitted continuation log probabilities")
            results.append({"continuation": continuation, "log_likelihood": sum(selected),
                            "tokens": len(selected), "raw": raw})
    return results
