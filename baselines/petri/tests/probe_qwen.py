"""Live DashScope checks for tools and assistant partial completion."""

import asyncio
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import APIStatusError, AsyncOpenAI

from run import seed_everything


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.8-27b"
TOOL = {"type": "function", "function": {
    "name": "read_ledger", "description": "Read the current integer count from the ledger.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}}
PREFIX = '{"count":'


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-start", action="store_true", help="Test tool invocation from a prefilled turn")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=True)
    seed_everything(42)
    records = []
    output = ROOT / "results" / "tests" / ("qwen-prefill-tool-start.json" if args.tool_start else "qwen-prefill-probe.json")
    async with AsyncOpenAI(base_url=BASE_URL, api_key=os.environ["QWEN_API_KEY"],
                          max_retries=0, timeout=90) as client:
        async def request(name, thinking, messages, tools=False):
            payload = {
                "model": MODEL, "messages": messages, "max_tokens": 4096, "seed": 42,
                "extra_body": {"enable_thinking": thinking},
            }
            if tools:
                payload.update(tools=[TOOL], tool_choice="auto")
            record = {"name": name, "thinking": thinking, "request": payload,
                      "timestamp": datetime.now(timezone.utc).isoformat()}
            records.append(record)
            try:
                result = await client.chat.completions.create(**payload)
                record.update(status="success", response=result.model_dump())
                message = result.choices[0].message
                if messages[-1].get("partial"):
                    try:
                        record["prefix_plus_completion"] = json.loads(messages[-1]["content"] + (message.content or ""))
                    except ValueError:
                        record["prefix_plus_completion"] = None
                print(json.dumps({"name": name, "thinking": thinking, "status": "success",
                                  "content": message.content, "tool_calls": len(message.tool_calls or []),
                                  "reasoning_chars": len(getattr(message, "reasoning_content", "") or ""),
                                  "prefix_plus_completion": record.get("prefix_plus_completion")}), flush=True)
                return message.model_dump(exclude_none=True)
            except APIStatusError as error:
                record.update(status="api_error", http_status=error.status_code, error=error.body)
                print(json.dumps({"name": name, "thinking": thinking, "status": error.status_code,
                                  "error": error.body}), flush=True)
                return None
            finally:
                output.write_text(json.dumps({"base_url": BASE_URL, "model": MODEL,
                                              "timeout": 90, "max_retries": 0, "records": records},
                                             ensure_ascii=False, indent=2) + "\n")

        async def probe(thinking):
            if args.tool_start:
                messages = [{"role": "user", "content": "Read the ledger using read_ledger, then report its count. Do not guess the count."},
                            {"role": "assistant", "content": "I will read the ledger now.", "partial": True}]
                first = await request("prefill_before_tool_call", thinking, messages, tools=True)
                if first and first.get("tool_calls"):
                    first["content"] = messages.pop()["content"] + (first.get("content") or "")
                    messages.append(first)
                    for call in first["tool_calls"]:
                        messages.append({"role": "tool", "tool_call_id": call["id"], "content": '{"count":7}'})
                    await request("tool_result_after_prefilled_tool_call", thinking, messages, tools=True)
                return
            simple = [{"role": "user", "content": "Return one JSON object with only the integer field count set to 7. No Markdown."}]
            await request("prefill_without_tools", thinking,
                          [*simple, {"role": "assistant", "content": PREFIX, "partial": True}])
            messages = [{"role": "user", "content": "Call read_ledger exactly once to learn the count, then return one JSON object with only the integer field count from the ledger. No Markdown."}]
            first = await request("tool_call", thinking, messages, tools=True)
            if not first or not first.get("tool_calls"):
                return
            messages.append(first)
            for call in first["tool_calls"]:
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": '{"count":7}'})
            await request("tool_result_without_prefill", thinking, messages, tools=True)
            await request("tool_result_with_prefill", thinking,
                          [*messages, {"role": "assistant", "content": PREFIX, "partial": True}], tools=True)

        await asyncio.gather(probe(False), probe(True))


if __name__ == "__main__":
    asyncio.run(main())
