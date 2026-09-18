"""Evaluate the eight published benchmarks with the existing scoring rules."""

import argparse
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from openai import OpenAI, APIConnectionError, APIStatusError

from local.self_evaluate import (ANSWER_SYSTEM, CHOICE_SYSTEM, JUDGE_SYSTEM, answer_messages,
                                 choice_label, is_choice, save_json, _build_messages, _safe_json_loads)
from local.run_with_usage import UsageRecorder, observe_sync
from local.upload_hf_questions import RUNS, COUNTS
from utils.model_config import get_api_key, get_api_base_url, get_max_tokens, get_request_timeout


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)


class EmptyAnswerError(RuntimeError):
    pass


def empty_answer(response):
    if not response.choices:
        return True
    choice = response.choices[0]
    message = choice.message
    return (choice.finish_reason == "stop" and not (message.content or "").strip()
            and not message.refusal and not message.tool_calls)


def request_with_retry(call, **kwargs):
    # Retry the unchanged request; failed transport attempts remain in the usage log.
    limits = {"rate": 20, "transport": 6, "empty": 6}
    failures = Counter()
    while True:
        try:
            return call(**kwargs)
        except (APIConnectionError, APIStatusError, EmptyAnswerError) as exc:
            status = getattr(exc, "status_code", None)
            if status is not None and status != 429 and status < 500:
                raise
            kind = "empty" if isinstance(exc, EmptyAnswerError) else "rate" if status == 429 else "transport"
            failures[kind] += 1
            if failures[kind] >= limits[kind]:
                raise
            headers = getattr(getattr(exc, "response", None), "headers", {})
            try:
                delay = float(headers["retry-after"])
            except (KeyError, ValueError):
                delay = min(60, 2 ** failures[kind])
            print(f"[retry] {kwargs['model']} {type(exc).__name__} {failures[kind]}/{limits[kind]}", flush=True)
            time.sleep(max(0, delay) + random.random())


def score(item, subtask, result, judge):
    if not result["prediction"] or result["finish_reason"] != "stop":
        result["status"] = "incomplete_response"
    elif is_choice(subtask, item["sample"]["output"]):
        result.update(status="scored", method="exact_choice", correct=(
            choice_label(result["prediction"]) == choice_label(item["sample"]["output"]["answer"])))
    else:
        payload = {"task_input": item["sample"]["input"],
                   "reference_output": item["sample"]["output"],
                   "candidate_response": result["prediction"]}
        response = judge(messages=_build_messages(JUDGE_SYSTEM, json.dumps(payload, ensure_ascii=False), None, None))
        raw = response.choices[0].message.content or ""
        result.update(judge_raw=raw, judge_response=response.model_dump(mode="json"))
        parsed = _safe_json_loads(raw)
        if response.choices[0].finish_reason != "stop" or not isinstance(parsed, dict) or type(parsed.get("correct")) is not bool:
            result["status"] = "invalid_judgment"
        else:
            result.update(status="scored", method="model_judge", correct=parsed["correct"],
                          judge_reason=parsed.get("reason", ""))
    return result


def main(profile="qwen"):
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=8 if profile == "sol" else 128)
    args = parser.parse_args()
    seed_everything(42)
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    if (out / "config.json").exists():
        raise ValueError("Use a fresh output directory")
    key = os.environ["RIGHTAPI_API_KEY" if profile == "sol" else "QWEN_API_KEY"]
    jobs, sources = [], {}
    for (topic, batch), count in zip(RUNS.items(), COUNTS):
        run = ROOT / "cache" / batch / "user_queries" / f"{topic}_200"
        raw = (run / "evaluation.json").read_bytes()
        items = json.loads(raw)
        original = json.loads((run / "selftest/config.json").read_text())
        digest = hashlib.sha256(raw).hexdigest()
        assert digest == original["evaluation_sha256"] and len(items) == count
        subs = json.loads((run / "agents/grounding_agent.json").read_text())["context_variables"]["subtasks"]
        subs = {s["id"]: s for s in subs}
        (out / topic / "items").mkdir(parents=True)
        save_json(out / topic / "evaluation.json", items)
        save_json(out / topic / "subtasks.json", [{k: s[k] for k in ("id", "name", "answer_type")} for s in subs.values()])
        sources[topic] = {"batch": batch, "count": count, "evaluation_sha256": digest}
        jobs.extend((topic, i, item, subs[item["subtask_id"]]) for i, item in enumerate(items))
    answer_config = {"model": "qwen3.8-27b", "temperature": 0, "seed": 42,
                     "max_tokens": 131072, "stream": False, "extra_body": {"enable_thinking": True}}
    answer_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if profile == "sol":
        answer_config = {"model": "gpt-5.6-sol", "max_completion_tokens": 131072, "stream": False}
        answer_base_url = "https://www.rightapi.ai/v1"
    judge_config = {"model": "deepseek-flash", "temperature": 0.0,
                    "max_tokens": get_max_tokens("openai/deepseek-flash"), "stream": False}
    config = {"sources": sources, "workers_global": args.workers, "seed": 42,
              "hash_seed": os.environ.get("PYTHONHASHSEED"),
              "answer": answer_config, "answer_base_url": answer_base_url,
              "judge": judge_config, "judge_base_url": get_api_base_url(),
              "timeout_seconds": 7200, "answer_system": ANSWER_SYSTEM, "choice_system": CHOICE_SYSTEM,
              "judge_system": JUDGE_SYSTEM, "rate_limit_attempts": 20, "transport_attempts": 6,
              "judge_thinking": "provider default", "qwen_thinking_budget": "provider default",
              "scoring": "strict choice letter match; separate DeepSeek judge for other answer types"}
    if profile == "sol":
        config.pop("qwen_thinking_budget")
        config.update(answer_reasoning="provider default", answer_temperature="provider default",
                      answer_api_seed="omitted", empty_answer_attempts=6)
    save_json(out / "config.json", config)
    usage_a, usage_j = UsageRecorder(out / "answering"), UsageRecorder(out / "judging")
    client_a = OpenAI(api_key=key, base_url=config["answer_base_url"], timeout=7200, max_retries=0)
    client_j = OpenAI(api_key=get_api_key(), base_url=get_api_base_url(),
                      timeout=get_request_timeout("openai/deepseek-flash"), max_retries=0)
    answer = observe_sync(client_a.chat.completions.create, usage_a, f"{profile}_evaluation.answer")
    judge_call = observe_sync(client_j.chat.completions.create, usage_j, f"{profile}_evaluation.judge")

    def judge(**kwargs):
        return request_with_retry(judge_call, **judge_config, **kwargs)

    def evaluate(job):
        topic, index, item, subtask = job
        checkpoint = out / topic / "items" / f"{index:04d}.json"
        result = {"topic": topic, "index": index, "subtask_id": item["subtask_id"],
                  "dataset_id": item["dataset_id"], "source_idx": item["idx"],
                  "reference": item["sample"]["output"]}

        def checked_answer(**kwargs):
            response = answer(**kwargs)
            if profile == "sol" and empty_answer(response):
                result.setdefault("empty_answer_responses", []).append(response.model_dump(mode="json"))
                result["status"] = "retrying_empty_answer"
                save_json(checkpoint, result)
                raise EmptyAnswerError("The gateway returned no answer")
            return response

        try:
            response = request_with_retry(checked_answer, **answer_config, messages=answer_messages(item, subtask))
            result.update(prediction=response.choices[0].message.content or "",
                          finish_reason=response.choices[0].finish_reason,
                          answer_response=response.model_dump(mode="json"), status="answered")
            save_json(checkpoint, result)
            score(item, subtask, result, judge)
        except Exception as exc:
            result.update(status="error", error_type=type(exc).__name__, http_status=getattr(exc, "status_code", None))
        save_json(checkpoint, result)
        return result

    state = {"started_utc": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
             "status": "running", "total": len(jobs), "finished": 0, "by_topic": {}}
    results = []

    def summarize():
        state["finished"] = len(results)
        state["statuses"] = dict(Counter(r["status"] for r in results))
        for topic in RUNS:
            selected = [r for r in results if r["topic"] == topic]
            scored = [r for r in selected if r["status"] == "scored"]
            correct = sum(r["correct"] for r in scored)
            state["by_topic"][topic] = {"total": sources[topic]["count"], "finished": len(selected),
                                       "scored": len(scored), "correct": correct,
                                       "accuracy_on_scored": correct / len(scored) if scored else None}
        save_json(out / "status.json", state)

    summarize()
    try:
        # Interleave requirements while sharing one bounded worker pool.
        jobs.sort(key=lambda j: j[1])
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(evaluate, job) for job in jobs]):
                results.append(future.result())
                summarize()
                print(f"Evaluated {len(results)}/{len(jobs)} {state['statuses']}", flush=True)
        state["status"] = "completed" if all(r["status"] == "scored" for r in results) else "completed_with_unscored"
        save_json(out / "results.json", sorted(results, key=lambda r: (r["topic"], r["index"])))
    except BaseException:
        state["status"] = "failed"
        raise
    finally:
        state["finished_utc"] = datetime.now(timezone.utc).isoformat()
        summarize()
        usage_a.finish(state["status"])
        usage_j.finish(state["status"])
        client_a.close()
        client_j.close()


if __name__ == "__main__":
    main()
