"""Apply experiment API settings without changing the official agent workflow."""

from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
import json
import random

from utils.model_config import load_model_config


def seed_everything(seed=42):
    import numpy as np
    random.seed(seed)
    np.random.seed(seed)


def request_parameters(model):
    name = model.removeprefix("openai/responses/").removeprefix("openai/")
    return deepcopy(load_model_config().get("request_parameters", {}).get(name, {}))


def prepare_request(kwargs):
    settings = request_parameters(kwargs["model"])
    if "extra_body" in settings:
        settings["extra_body"] = {**(kwargs.get("extra_body") or {}), **settings["extra_body"]}
    return {**kwargs, **settings}


def reasoning_capture(kwargs):
    """Retain the raw reasoning field that LiteLLM 1.55 discards when parsing."""
    captured = {}
    previous = kwargs.get("logger_fn")

    def log(details):
        if details.get("log_event_type") == "post_api_call":
            raw = details["original_response"]
            raw = json.loads(raw) if isinstance(raw, str) else raw
            for choice in raw.get("choices", []):
                captured[choice["index"]] = choice["message"].get("reasoning_content")
        if previous:
            previous(details)

    kwargs["logger_fn"] = log

    def restore(response):
        for choice in response.choices:
            reasoning = captured.get(choice.index)
            if choice.message.tool_calls and reasoning is None:
                raise RuntimeError("DeepSeek tool response is missing reasoning_content")
            if reasoning is not None:
                choice.message.reasoning_content = reasoning
        return response

    return restore


def configure(call, asynchronous=False):
    def prepare(kwargs):
        kwargs = prepare_request(kwargs)
        preserve = (kwargs["model"].removeprefix("openai/") == "deepseek-flash"
                    and kwargs.get("tools") and not kwargs.get("stream"))
        restore = reasoning_capture(kwargs) if preserve else lambda response: response
        return kwargs, restore

    @wraps(call)
    def sync(**kwargs):
        kwargs, restore = prepare(kwargs)
        return restore(call(**kwargs))

    @wraps(call)
    async def async_call(**kwargs):
        kwargs, restore = prepare(kwargs)
        return restore(await call(**kwargs))

    return async_call if asynchronous else sync


@contextmanager
def configured_calls():
    from utils import core, llm_caller, native_responses
    targets = [(core, "completion", False), (core, "acompletion", True),
               (llm_caller, "completion", False), (native_responses, "request_response", False)]
    originals = [(module, name, getattr(module, name)) for module, name, _ in targets]
    try:
        for module, name, asynchronous in targets:
            setattr(module, name, configure(getattr(module, name), asynchronous))
        yield
    finally:
        for module, name, original in originals:
            setattr(module, name, original)
