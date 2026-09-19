"""Normalize provider transcripts and structured CLI results without executing content."""
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any


def cli_result(name: str, output: str) -> dict[str, Any]:
    """Decode documented CLI envelopes; ordinary text is never interpreted as an error."""
    values = []
    decoder = json.JSONDecoder()
    for index, char in enumerate(output):
        if char != "{" or (index and output[index - 1] != "\n"):
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except ValueError:
            continue
        if isinstance(value, dict):
            values.append(value)
    structured_cli = name in {"openclaw", "claude-code", "codex"}
    result: dict[str, Any] = {"final_response": "" if structured_cli else output, "status": "unavailable"}
    for value in values:
        if name == "openclaw" and isinstance(value.get("ok"), bool):
            result.update(final_response=value.get("final", ""),
                          status="completed" if value["ok"] else "failed",
                          error=value.get("error"), session_id=value.get("sessionId"),
                          tool_call_count=(value.get("toolSummary") or {}).get("calls"))
        elif name == "openclaw" and isinstance(value.get("payloads"), list) and isinstance(value.get("meta"), dict):
            result.update(final_response="\n".join(p.get("text", "") for p in value["payloads"] if isinstance(p, dict)),
                          status="failed" if value["meta"].get("aborted") else "completed",
                          session_id=value["meta"].get("agentMeta", {}).get("sessionId"))
        elif name == "claude-code" and value.get("type") == "result":
            result.update(final_response=value.get("result", ""),
                          status="failed" if value.get("is_error") else "completed",
                          error=value.get("errors"), session_id=value.get("session_id"))
        elif name == "codex":
            if value.get("type") == "turn.failed":
                result.update(status="failed", error=value.get("error"))
            elif value.get("type") == "turn.completed":
                result["status"] = "completed"
            elif value.get("type") == "item.completed" and value.get("item", {}).get("type") == "agent_message":
                result["final_response"] = value["item"].get("text", "")
    return result


def response_messages(body: str) -> list[dict]:
    """Recover assistant content from JSON or the documented SSE event schemas."""
    try:
        values = [json.loads(body)]
    except ValueError:
        values = []
        for line in body.splitlines():
            if line.startswith("data:") and line[5:].strip() != "[DONE]":
                try:
                    values.append(json.loads(line[5:]))
                except ValueError:
                    continue
    messages = []
    chunks: dict[int, dict] = {}
    text = ""
    anthropic: dict[int, dict] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        for choice in value.get("choices", []):
            if isinstance(choice.get("message"), dict):
                messages.append(choice["message"])
            delta = choice.get("delta") or {}
            text += delta.get("content") or ""
            for fragment in delta.get("tool_calls", []):
                tool = chunks.setdefault(fragment.get("index", 0), {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                tool["id"] = fragment.get("id") or tool["id"]
                for key in ("name", "arguments"):
                    tool["function"][key] += (fragment.get("function") or {}).get(key) or ""
        if value.get("type") == "message" and value.get("role") == "assistant":
            messages.append(value)
        if value.get("type") == "content_block_start":
            anthropic[value["index"]] = dict(value["content_block"])
        elif value.get("type") == "content_block_delta":
            block = anthropic.get(value["index"], {})
            delta = value.get("delta", {})
            if delta.get("type") == "input_json_delta":
                block["partial_json"] = block.get("partial_json", "") + delta.get("partial_json", "")
            elif delta.get("type") == "text_delta":
                block["text"] = block.get("text", "") + delta.get("text", "")
        if value.get("type") == "response.output_item.done":
            messages.append(value["item"])
        elif value.get("type") == "response.completed":
            messages = value.get("response", {}).get("output", [])
        elif value.get("object") == "response":
            messages.extend(value.get("output", []))
    if text or chunks:
        messages.append({"role": "assistant", "content": text, "tool_calls": list(chunks.values())})
    if anthropic:
        for block in anthropic.values():
            if "partial_json" in block:
                try:
                    block["input"] = json.loads(block.pop("partial_json"))
                except ValueError:
                    pass
        messages.append({"role": "assistant", "content": list(anthropic.values())})
    return messages


def _assemble_responses(events: list[dict]) -> list[dict]:
    """Retain streamed bytes already observed even when the episode interrupts a response."""
    ordered = []
    responses = {}
    chunks = {}
    for event in events:
        kind = event.get("kind")
        if kind == "response_start":
            response = {**event, "kind": "response", "complete": False}
            responses[event["id"]] = response
            chunks[event["id"]] = []
            ordered.append(response)
        elif kind in {"response_chunk", "response_end"}:
            if event["id"] in responses:
                chunks[event["id"]].append(event.get("body", ""))
                if kind == "response_end":
                    responses[event["id"]]["complete"] = event["complete"]
        else:
            ordered.append(event)
    for key, response in responses.items():
        response["body"] = "".join(chunks[key])
    return ordered


def normalize_events(events: list[dict], name: str, raw: str, stderr: str = "", *, stages: Sequence[dict] = ()) -> dict:
    cli = cli_result(name, raw)
    histories = []
    calls: dict[tuple[str, str], dict] = {}
    results: dict[tuple[str, str], Any] = {}
    responses = []
    requests = []

    def call(call_id, tool, arguments):
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                pass
        if call_id:
            calls[(session, call_id)] = {"id": call_id, "name": tool, "arguments": arguments}

    for event in _assemble_responses(events):
        session = next((s["session_id"] for s in reversed(stages)
                        if event.get("time", 0) >= s.get("started_at", float("inf"))), "")
        if event.get("kind") == "response":
            messages = response_messages(event.get("body", ""))
            responses.append({**event, "messages": messages})
        else:
            requests.append(event)
            payload = event.get("payload", {})
            messages = payload.get("messages", payload.get("input", []))
            if isinstance(messages, list):
                histories = list(messages)
        if not isinstance(messages, list):
            continue
        if event.get("kind") == "response":
            histories.extend(messages)
            # Harnesses may rewrite provider call ids before execution. Preserve
            # proposals separately instead of guessing aliases or double-counting.
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            for tool in message.get("tool_calls", []):
                function = tool.get("function", {})
                call(tool.get("id"), function.get("name"), function.get("arguments"))
            if message.get("role") == "tool":
                results[(session, message.get("tool_call_id"))] = message.get("content")
            if message.get("type") == "function_call":
                call(message.get("call_id"), message.get("name"), message.get("arguments"))
            elif message.get("type") == "function_call_output":
                results[(session, message.get("call_id"))] = message.get("output")
            content = message.get("content", [])
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    call(block.get("id"), block.get("name"), block.get("input"))
                elif block.get("type") == "tool_result":
                    results[(session, block.get("tool_use_id"))] = block.get("content")
    trace = [{"step": n, "origin": "target", "phase": "target_execution",
              "session_id": key[0] or None,
              "source": "model_api_transcript", "tool_call": tool,
              "observation": results.get(key), "result_observed": key in results}
             for n, (key, tool) in enumerate(calls.items(), 1)]
    count = cli.get("tool_call_count")
    if stages:
        counts = [s.get("tool_call_count") for s in stages]
        count = sum(counts) if all(isinstance(n, int) for n in counts) else None
    return {
        "final_response": cli["final_response"], "raw_output": raw, "stderr": stderr,
        "trace": trace, "history": histories, "model_requests": requests, "model_responses": responses,
        "final_state": {}, "tool_call_count": count,
        "observed_tool_call_count": len(trace),
        "availability": {"history": "observed" if events else "unavailable",
                         "final_response": "reported" if cli["status"] != "unavailable" else "unavailable",
                         "trace": "partial" if events else "unavailable",
                         "tool_call_count": "reported" if count is not None else "unavailable"},
        "provenance": "Gateway-observed harness/provider transcript. history is the latest request context plus subsequent observed responses; model_requests preserves every context snapshot, including earlier sessions. Tool results are reported by the harness; this is not a syscall audit. Missing events do not prove absence. Setup, harness maintenance and reviewer actions are not target tool calls.",
    }
