"""Responses transport for the repository's pinned pre-Responses LiteLLM version."""

import itertools
import math
import os
import random
import threading
import time
from email.utils import parsedate_to_datetime
from contextlib import nullcontext

from openai import OpenAI, RateLimitError, APITimeoutError, APIError
from utils.search_queue import search_slot, infrastructure_wait, SearchInfrastructureError


_key_lock = threading.Lock()
_key_sequence = itertools.count(os.getpid())


def request_response(*, model, api_key, base_url, timeout, **payload):
    """One provider request; observed separately so every attempt is accounted for."""
    with OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0) as client:
        return client.responses.create(model=model.removeprefix("openai/responses/"), **payload)


def retry_delay(error, attempt, base, maximum):
    headers = error.response.headers
    delays = []
    for name, scale in (("retry-after-ms", 0.001), ("x-ms-retry-after-ms", 0.001), ("retry-after", 1)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            delay = float(value) * scale
        except ValueError:
            if name != "retry-after":
                continue
            try:
                delay = parsedate_to_datetime(value).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(delay) and delay >= 0:
            delays.append(delay)
    minimum = max(delays) if delays else min(maximum, base * 2 ** attempt)
    return minimum + random.uniform(0, min(base, 1))


def responses_completion(*, model, messages, api_key, base_url, max_tokens,
                         timeout, tools, tool_choice, temperature, request_timeout=None,
                         api_keys=None, retry_config=None, fallback=None):
    inputs = []
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            parts = []
            for part in content:
                if part["type"] == "text":
                    parts.append({"type": "input_text", "text": part["text"]})
                elif part["type"] == "image_url":
                    image = part["image_url"]
                    parts.append({"type": "input_image", "image_url": image["url"],
                                  "detail": image.get("detail", "auto")})
                else:
                    raise ValueError(f"Unsupported Responses content type: {part['type']}")
            content = parts
        inputs.append({"role": message["role"], "content": content})
    config = retry_config or {}
    attempts = config.get("rate_limit_attempts", 6)
    timeout_attempts = config.get("timeout_attempts", 1)
    base = config.get("retry_base_seconds", 2)
    maximum = config.get("retry_max_seconds", 60)
    budget = config.get("retry_budget_seconds", timeout)
    if (type(attempts) is not int or attempts < 1 or
            type(timeout_attempts) is not int or timeout_attempts < 1 or
            min(base, maximum, budget) <= 0):
        raise ValueError("Invalid native search retry configuration")
    endpoints = [(base_url, list(dict.fromkeys(api_keys or [api_key])), config)]
    if fallback:
        fallback_config = fallback.get("retry_config") or config
        endpoints.append((fallback["base_url"], [fallback["api_key"]], fallback_config))

    for endpoint_index, (endpoint_url, endpoint_keys, endpoint_config) in enumerate(endpoints):
        endpoint_attempts = endpoint_config.get("rate_limit_attempts", attempts)
        endpoint_timeout_attempts = endpoint_config.get("timeout_attempts", timeout_attempts)
        endpoint_base = endpoint_config.get("retry_base_seconds", base)
        endpoint_maximum = endpoint_config.get("retry_max_seconds", maximum)
        endpoint_budget = endpoint_config.get("retry_budget_seconds", budget)
        endpoint_deadline = time.monotonic() + endpoint_budget
        timeout_failures = 0
        for attempt in range(endpoint_attempts):
            try:
                slot = (search_slot(endpoint_config["queue_dir"], endpoint_config["global_concurrency"])
                        if endpoint_config.get("global_concurrency") else nullcontext(0))
                with slot as waited:
                    endpoint_deadline += waited  # Admission waiting never consumes retry budget.
                    with _key_lock:
                        key = endpoint_keys[next(_key_sequence) % len(endpoint_keys)]
                    per_request_timeout = timeout if timeout_failures else min(
                        timeout, max(0.001, endpoint_deadline - time.monotonic())
                    )
                    return request_response(
                        model=model, api_key=key, base_url=endpoint_url,
                        # Timeout retries are count-based and each gets the full request timeout.
                        timeout=per_request_timeout, input=inputs,
                        tools=tools, tool_choice=tool_choice,
                        max_output_tokens=max_tokens, include=["web_search_call.action.sources"],
                    )
            except APITimeoutError as exc:
                timeout_failures += 1
                if timeout_failures < endpoint_timeout_attempts:
                    print(f"[web search] timeout; retry {timeout_failures + 1}/{endpoint_timeout_attempts}.", flush=True)
                    continue
                if endpoint_index + 1 < len(endpoints):
                    print("[web search] timeout retries exhausted; switching search endpoint.", flush=True)
                    break
                if endpoint_config.get("stop_on_api_error"):
                    raise SearchInfrastructureError("Search API stopped: timeout retries exhausted") from exc
                raise
            except RateLimitError as exc:
                if exc.code in {"insufficient_quota", "billing_hard_limit_reached"} or attempt + 1 == endpoint_attempts:
                    if endpoint_config.get("stop_on_api_error"):
                        raise SearchInfrastructureError(f"Search API stopped: HTTP 429, code={exc.code}") from exc
                    raise
                delay = retry_delay(exc, attempt, endpoint_base, endpoint_maximum)
                if delay >= endpoint_deadline - time.monotonic():
                    if endpoint_config.get("stop_on_api_error"):
                        raise SearchInfrastructureError("Search API stopped: HTTP 429 retry budget exhausted") from exc
                    raise
                print(f"[web search] HTTP 429; retry {attempt + 2}/{endpoint_attempts} after {delay:.1f}s.", flush=True)
                with infrastructure_wait():
                    time.sleep(delay)
                if time.monotonic() >= endpoint_deadline:
                    if endpoint_config.get("stop_on_api_error"):
                        raise SearchInfrastructureError("Search API stopped: HTTP 429 retry budget exhausted") from exc
                    raise
            except APIError as exc:
                if endpoint_config.get("stop_on_api_error"):
                    raise SearchInfrastructureError(f"Search API stopped: {type(exc).__name__}") from exc
                raise
