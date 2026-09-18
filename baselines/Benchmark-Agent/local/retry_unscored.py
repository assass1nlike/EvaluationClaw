"""Retry unscored exported items using the saved evaluation configuration."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

from evaluate_qwen import (ROOT, OpenAI, EmptyAnswerError, empty_answer, request_with_retry,
                           score, answer_messages, seed_everything, save_json,
                           UsageRecorder, observe_sync, get_api_key)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--key-env", default="RIGHTAPI_API_KEY")
    args = parser.parse_args()
    run = args.run
    config = json.loads((run / "config.json").read_text())
    state = json.loads((run / "status.json").read_text())
    if state["status"] == "running":
        raise ValueError("The original evaluation is still running")
    results = json.loads((run / "results.json").read_text())
    pending = [r for r in results if r["status"] != "scored"]
    if not pending:
        print("All items are already scored")
        return
    seed_everything(config["seed"])
    recovery = run / "recovery" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovery.mkdir(parents=True)
    for name in ("status.json", "results.json", "config.json"):
        shutil.copy2(run / name, recovery / name)
    protected = {str(run / r["topic"] / "items" / f"{r['index']:04d}.json"):
                 hashlib.sha256((run / r["topic"] / "items" / f"{r['index']:04d}.json").read_bytes()).hexdigest()
                 for r in results if r["status"] == "scored"}
    save_json(recovery / "preserved_items.json", protected)
    info = {"started_utc": datetime.now(timezone.utc).isoformat(), "workers": 1,
            "seed": config["seed"], "hash_seed": os.environ.get("PYTHONHASHSEED"),
            "items": [{"topic": r["topic"], "index": r["index"]} for r in pending]}
    save_json(recovery / "recovery.json", info)
    key, judge_key = os.environ[args.key_env], get_api_key()
    usage_a, usage_j = UsageRecorder(recovery / "answering"), UsageRecorder(recovery / "judging")
    with OpenAI(api_key=key, base_url=config["answer_base_url"], timeout=config["timeout_seconds"],
                max_retries=0) as client_a, OpenAI(api_key=judge_key, base_url=config["judge_base_url"],
                timeout=config["timeout_seconds"], max_retries=0) as client_j:
        answer = observe_sync(client_a.chat.completions.create, usage_a, "recovery.answer")
        judge_call = observe_sync(client_j.chat.completions.create, usage_j, "recovery.judge")

        def judge(**kwargs):
            return request_with_retry(judge_call, **config["judge"], **kwargs)

        for previous in pending:
            topic, index = previous["topic"], previous["index"]
            source = config["sources"][topic]
            original = ROOT / "cache" / source["batch"] / "user_queries" / f"{topic}_200" / "evaluation.json"
            assert hashlib.sha256(original.read_bytes()).hexdigest() == source["evaluation_sha256"]
            items = json.loads((run / topic / "evaluation.json").read_text())
            assert items == json.loads(original.read_text())
            item = items[index]
            assert previous["reference"] == item["sample"]["output"]
            assert previous["subtask_id"] == item["subtask_id"]
            subtask = next(s for s in json.loads((run / topic / "subtasks.json").read_text())
                           if s["id"] == item["subtask_id"])
            checkpoint = run / topic / "items" / f"{index:04d}.json"
            prefix = recovery / f"{topic}_{index:04d}"
            shutil.copy2(checkpoint, prefix.with_suffix(".before.json"))
            result = {k: v for k, v in previous.items() if k not in ("error_type", "http_status", "status")}

            def checked_answer(**kwargs):
                response = answer(**kwargs)
                if empty_answer(response):
                    result.setdefault("empty_answer_responses", []).append(response.model_dump(mode="json"))
                    save_json(prefix.with_suffix(".result.json"), result)
                    raise EmptyAnswerError("The gateway returned no answer")
                return response

            try:
                if not result.get("prediction") or result.get("finish_reason") != "stop":
                    response = request_with_retry(checked_answer, **config["answer"],
                                                  messages=answer_messages(item, subtask))
                    result.update(prediction=response.choices[0].message.content or "",
                                  finish_reason=response.choices[0].finish_reason,
                                  answer_response=response.model_dump(mode="json"), status="answered")
                    save_json(prefix.with_suffix(".result.json"), result)
                score(item, subtask, result, judge)
            except Exception as exc:
                message = str(getattr(exc, "body", None) or exc)
                for secret in (key, judge_key):
                    message = message.replace(secret, "[REDACTED]")
                result.update(status="error", error_type=type(exc).__name__,
                              http_status=getattr(exc, "status_code", None), error_message=message[:6000])
            save_json(prefix.with_suffix(".result.json"), result)
            print(json.dumps({k: result.get(k) for k in ("topic", "index", "status", "correct", "error_message")}), flush=True)
            if result["status"] == "scored":
                save_json(checkpoint, result)
                results[results.index(previous)] = result

    for path, digest in protected.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    state["statuses"] = dict(Counter(r["status"] for r in results))
    state["status"] = "completed" if all(r["status"] == "scored" for r in results) else "completed_with_unscored"
    for topic, entry in state["by_topic"].items():
        scored = [r for r in results if r["topic"] == topic and r["status"] == "scored"]
        correct = sum(r["correct"] for r in scored)
        entry.update(scored=len(scored), correct=correct, accuracy_on_scored=correct / len(scored) if scored else None)
    state["finished_utc"] = datetime.now(timezone.utc).isoformat()
    state.setdefault("recoveries", []).append(str(recovery.relative_to(run)))
    save_json(run / "results.json", results)
    save_json(run / "status.json", state)
    info.update(finished_utc=state["finished_utc"], status=state["status"], preserved_items=len(protected))
    save_json(recovery / "recovery.json", info)
    usage_a.finish(state["status"])
    usage_j.finish(state["status"])


if __name__ == "__main__":
    main()
