"""Live check of reasoning, tool-result continuation, and prefix completion."""

import asyncio
import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from inspect_ai.model import (
    ChatMessageAssistant, ChatMessageTool, ChatMessageUser, ContentReasoning,
    GenerateConfig, get_model,
)
from inspect_ai.tool import ToolInfo, ToolParams

import deepseek_api  # Register provider.
from run import seed_everything


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefill', action='store_true', help='Also test prefix with tools (currently rejected by DeepSeek)')
    args = parser.parse_args()
    load_dotenv('.env', override=True)
    seed_everything(42)
    config = GenerateConfig(max_tokens=300000, reasoning_effort="high", seed=42,
                            max_retries=2, timeout=600, max_connections=1,
                            extra_body={"thinking": {"type": "enabled"}})
    model = get_model("deepseek/deepseek-flash", base_url="https://api.deepseek.com/beta",
                      config=config, memoize=False)
    tool = ToolInfo(name="read_ledger", description="Read the current count from the ledger.",
                    parameters=ToolParams(type="object", properties={}, required=[]))
    messages = [ChatMessageUser(content="Call read_ledger to get the count, then tell me the count.")]
    first = await model.generate(messages, tools=[tool])
    assert first.message.tool_calls
    messages.append(first.message)
    for call in first.message.tool_calls:
        messages.append(ChatMessageTool(content='{"count":7}', tool_call_id=call.id))
    second = await model.generate(messages, tools=[tool])
    assert second.message.text.strip()
    outputs = [first, second]
    if args.prefill:
        messages.extend([second.message, ChatMessageUser(content="Repeat the count in one sentence."),
                         ChatMessageAssistant(content="The count is", metadata={"prefill": True})])
        third = await model.generate(messages, tools=[tool])
        assert third.message.text.strip()
        outputs.append(third)
    Path('results/tests/deepseek-probe.json').write_text(json.dumps({
        "model": "deepseek-flash", "base_url": "https://api.deepseek.com/beta",
        "config": config.model_dump(exclude_none=True),
        "outputs": [output.model_dump(mode="json") for output in outputs],
    }, indent=2) + '\n')
    print(json.dumps({"status": "success", "steps": [
        {"stop": out.choices[0].stop_reason, "text_chars": len(out.message.text),
         "has_reasoning": isinstance(out.message.content, list) and any(
             isinstance(c, ContentReasoning) and bool(c.reasoning) for c in out.message.content)}
        for out in outputs
    ]}))


if __name__ == '__main__':
    asyncio.run(main())
