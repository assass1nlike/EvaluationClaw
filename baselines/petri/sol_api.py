"""External streaming Responses adapter for the Sol relay."""

import asyncio
import json
import os
from functools import wraps
from uuid import uuid4
from pathlib import Path
from time import monotonic, time

from inspect_ai.model import ContentReasoning, ModelCall, ModelOutput, ModelUsage, modelapi
from inspect_ai.model._openai_responses import (
    openai_responses_chat_choices, openai_responses_inputs,
    openai_responses_tool_choice, openai_responses_tools,
)
from inspect_ai.model._providers.openai import OpenAIAPI

from request_rate import wait_for_slot


@modelapi(name="sol")
class SolAPI(OpenAIAPI):
    def __init__(self, model_name, *, rate_limit_file, rpm=50, call_log=None, **kwargs):
        if not 0 < rpm <= 50:
            raise ValueError("Sol RPM must be in (0, 50]")
        kwargs["api_key"] = kwargs.get("api_key") or os.environ.get("SOL_API_KEY")
        if not kwargs["api_key"]:
            raise ValueError("SOL_API_KEY is required")
        super().__init__(model_name, responses_api=True, max_retries=0, **kwargs)
        self.call_log = Path(call_log) if call_log else None
        self.model_mismatch_error = None

        async def limit(request):
            started = await asyncio.to_thread(wait_for_slot, rate_limit_file, rpm)
            self.record({"event": "request_start", "monotonic": started,
                         "time": time(), "pid": os.getpid()})

        # HTTP hook counts every attempt, including any future SDK-level retry.
        self.client._client.event_hooks["request"].append(limit)

    def record(self, value):
        if self.call_log:
            with self.call_log.open("a") as handle:
                handle.write(json.dumps(value, ensure_ascii=False) + "\n")

    def force_reasoning_history(self):
        return "all"

    def guard_tool(self, tool):
        @wraps(tool)
        async def guarded(*args, **kwargs):
            try:
                return await tool(*args, **kwargs)
            finally:
                # Petri converts provider exceptions to recoverable ToolError.
                # Raise outside that conversion to fail this epoch on exhaustion.
                if self.model_mismatch_error:
                    raise RuntimeError(self.model_mismatch_error)
        return guarded

    async def generate(self, input, tools, tool_choice, config):
        if self.model_mismatch_error:
            raise RuntimeError(self.model_mismatch_error)
        if any((m.metadata or {}).get("prefill") for m in input):
            raise ValueError("Sol Responses adapter requires no-prefill")
        inputs = await openai_responses_inputs([m for m in input if m.role != "system"], self)
        encrypted = {part.signature: part.internal["encrypted_content"]
                     for message in input if isinstance(message.content, list)
                     for part in message.content if isinstance(part, ContentReasoning)
                     and isinstance(part.internal, dict) and part.internal.get("encrypted_content")}
        for item in inputs:
            if item["type"] == "reasoning" and item.get("id") in encrypted:
                item["encrypted_content"] = encrypted[item["id"]]
        request = dict(
            model=self.model_name,
            instructions="\n\n".join(m.text for m in input if m.role == "system"),
            input=inputs,
            reasoning={"effort": config.reasoning_effort, "summary": "auto"},
            max_output_tokens=config.max_tokens, store=False, stream=True,
            include=["reasoning.encrypted_content"],
        )
        if tools:
            request["tools"] = openai_responses_tools(tools, self.model_name, config)
            request["tool_choice"] = openai_responses_tool_choice(tool_choice, request["tools"])
        started = monotonic()
        request_id = uuid4().hex
        attempts = (config.max_retries or 0) + 1
        for attempt in range(1, attempts + 1):
            response = None
            stream = await self.client.responses.create(**request, timeout=config.timeout)
            async with stream:
                async for event in stream:
                    if event.type in ("response.completed", "response.incomplete", "response.failed"):
                        response = event.response
                    elif event.type == "error":
                        raise RuntimeError(str(event))
            if response is None:
                raise RuntimeError("Responses stream ended without a final response")
            error = None
            if response.model != self.model_name:
                error = f"Requested {self.model_name}, received {response.model}"
            elif response.status == "failed" or response.error:
                error = f"Responses failed: {response.error}"
            elif response.instructions != request["instructions"]:
                error = "Relay did not preserve system instructions"
            elif not response.reasoning or response.reasoning.effort != config.reasoning_effort:
                error = "Relay did not confirm requested reasoning effort"
            self.record({"event": "response", "time": time(), "model": response.model,
                         "request_id": request_id, "attempt": attempt,
                         "status": response.status, "reasoning": response.reasoning.model_dump() if response.reasoning else None,
                         "requested_max_output_tokens": config.max_tokens,
                         "returned_max_output_tokens": response.max_output_tokens,
                         "usage": response.usage.model_dump() if response.usage else None,
                         "error": error, **({"request": request, "rejected_response": response.model_dump()} if error else {})})
            if response.model != self.model_name:
                if attempt < attempts:
                    continue
                self.model_mismatch_error = f"{error}; model mismatch retries exhausted after {attempts} attempts"
                raise RuntimeError(self.model_mismatch_error)
            if error:
                raise RuntimeError(error)
            break
        usage = response.usage
        choices = openai_responses_chat_choices(self.model_name, response, tools)
        encrypted = {item.id: item.encrypted_content for item in response.output
                     if item.type == "reasoning" and item.encrypted_content}
        for choice in choices:
            for part in choice.message.content:
                if isinstance(part, ContentReasoning) and part.signature in encrypted:
                    part.internal = {"encrypted_content": encrypted[part.signature]}
        return ModelOutput(
            model=response.model,
            choices=choices,
            usage=ModelUsage(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                             input_tokens_cache_read=usage.input_tokens_details.cached_tokens,
                             reasoning_tokens=usage.output_tokens_details.reasoning_tokens,
                             total_tokens=usage.total_tokens) if usage else None,
        ), ModelCall.create(request=request, response=response.model_dump(), time=monotonic() - started)
