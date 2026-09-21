"""Check real tool continuation and the configured evaluation request settings."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from openai import OpenAI
from local.model_runtime import configured_calls, request_parameters, seed_everything
from local.run_with_usage import UsageRecorder, observe_calls, observe_sync
from utils.agent_utils import Agent
from utils.core import MetaChain


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--provider", choices=["deepseek", "qwen"], required=True)
    parser.add_argument("--tool-choice", choices=["required", "auto"], default="required")
    args = parser.parse_args()
    seed_everything(42)
    recorder = UsageRecorder(args.output)
    status = "failed"
    try:
        if args.provider == "deepseek":
            def lookup_constant():
                """Read the integer that the user wants squared."""
                return "17"
            def case_resolved(answer: str):
                """Submit the square after reading the integer from the lookup tool."""
                return answer
            agent = Agent(name="thinking_probe", model="openai/deepseek-flash", tool_choice=args.tool_choice,
                          instructions="Call lookup_constant, then square its result and call case_resolved. Do not guess the lookup result.",
                          functions=[lookup_constant, case_resolved])
            with observe_calls(recorder), configured_calls():
                result = asyncio.run(MetaChain().run_async(agent=agent,
                    messages=[{"role": "user", "content": "Read the integer and submit its square."}], max_turns=8))
            data = {"messages": result.messages}
            (recorder.directory / "response.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            assistants = [m for m in result.messages if m.get("role") == "assistant"]
            assert len(assistants) >= 2 and all("reasoning_content" in m for m in assistants)
            submissions = [tc for m in assistants for tc in (m.get("tool_calls") or [])
                           if tc["function"]["name"] == "case_resolved"]
            assert len(submissions) == 1
            assert json.loads(submissions[0]["function"]["arguments"])["answer"] == "289"
            assert any(m.get("tool_call_id") == submissions[0]["id"] and m.get("content") == "289"
                       for m in result.messages)
            print(json.dumps({"provider": "deepseek", "assistant_turns": len(assistants), "answer": "289"}), flush=True)
        else:
            with OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                        timeout=180, max_retries=0) as client:
                call = observe_sync(client.chat.completions.create, recorder, "thinking_probe.qwen")
                result = call(model="qwen3.8-27b", messages=[{"role": "user", "content": "What is 17 squared? Answer briefly."}],
                              temperature=0, seed=42, max_tokens=131072, stream=False,
                              **request_parameters("qwen3.8-27b"))
            (recorder.directory / "response.json").write_text(result.model_dump_json(indent=2) + "\n")
            assert result.choices[0].finish_reason == "stop" and result.choices[0].message.content
            assert result.usage.completion_tokens_details.reasoning_tokens > 0
            print(json.dumps({"provider": "qwen", "usage": result.usage.model_dump()}), flush=True)
        status = "completed"
    finally:
        recorder.finish(status)
        print(recorder.directory, flush=True)


if __name__ == "__main__":
    main()
