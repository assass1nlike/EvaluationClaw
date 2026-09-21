"""Small live checks; keep complete requests and responses outside main results."""

import asyncio
import json
import os
from pathlib import Path
import random
import sys

import numpy as np
from dotenv import load_dotenv
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from request_rate import wait_for_slot


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)


async def main():
    seed_everything(42)
    load_dotenv(ROOT / ".env")
    output = ROOT / "results" / "sol-probe"
    output.mkdir(exist_ok=True)
    client = AsyncOpenAI(api_key=os.environ["SOL_API_KEY"],
                         base_url="https://api.sudorelay.com/v1", timeout=120, max_retries=0)
    tools = [{"type": "function", "function": {"name": "echo", "description": "Echo text",
              "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}}]
    async def probe(name, request, responses=False):
        await asyncio.to_thread(wait_for_slot, ROOT / ".local/state/sol-rate-limit", 50)
        record = {"seed": 42, "request": request}
        try:
            if responses:
                async with await client.responses.create(**request) as stream:
                    async for event in stream:
                        if event.type in ("response.completed", "response.incomplete", "response.failed"):
                            record["response"] = event.response.model_dump()
                        elif event.type == "error":
                            record["error"] = event.model_dump()
            else:
                record["response"] = (await client.chat.completions.create(**request)).model_dump()
        except Exception as error:
            record["error"] = str(error).replace(os.environ["SOL_API_KEY"], "[REDACTED]")
        (output / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        response = record.get("response", {})
        print(json.dumps({"probe": name, "error": record.get("error"), "model": response.get("model"),
                          "reasoning": response.get("reasoning"), "choices": response.get("choices"),
                          "output": response.get("output")}, ensure_ascii=False), flush=True)

    base = [{"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": 'Return exactly the JSON object {"count":7}, without a code fence.'}]
    for name, fields in [("prefix-true", {"prefix": True}), ("prefix-false", {"prefix": False}),
                         ("prefix-invalid", {"prefix": {"invalid": True}}),
                         ("partial-true", {"partial": True}), ("assistant-history", {})]:
        await probe(name, dict(model="gpt-5.6-sol", messages=base + [
            {"role": "assistant", "content": '{"count":', **fields}], tools=tools,
            reasoning_effort="high", max_completion_tokens=300000))
    await probe("responses-in-progress", dict(model="gpt-5.6-sol",
        instructions=base[0]["content"], input=[base[1], {"type": "message", "role": "assistant",
        "status": "in_progress", "content": [{"type": "output_text", "text": '{"count":', "annotations": []}]}],
        tools=[{"type": "function", **tools[0]["function"]}],
        reasoning={"effort": "high", "summary": "auto"}, max_output_tokens=300000, store=False, stream=True), True)
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
