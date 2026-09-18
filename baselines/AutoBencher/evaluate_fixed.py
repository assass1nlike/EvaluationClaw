"""Evaluate frozen AutoBencher questions with concurrent API calls."""

import argparse
import ast
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

from dotenv import load_dotenv
import httpx

from run import ROOT, seed_everything


def dump(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def read_records(path):
    if not path.exists():
        return {}
    return {r["id"]: r for r in map(json.loads, path.read_text().splitlines())}


def judge_prefix():
    tree = ast.parse((ROOT / "upstream/wiki_autobencher.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "fast_compare_answers")
    assignment = next(n for n in function.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "context_str"
                              for t in n.targets))
    return ast.literal_eval(assignment.value)


def judge_prompt(prefix, index, question, answer):
    return (prefix + f"Question {index}: {question['question']}\n"
            f"pred={answer.strip()} || gold={question['gold_answer'].strip()}\nreason:")


def request_body(role, prompt, seed):
    return {"model": role["model"], "messages": [
        {"role": "system", "content": "You are a helpful AI agent."},
        {"role": "user", "content": prompt}],
        "temperature": role["temperature"], "max_tokens": role["max_tokens"],
        "n": 1, "seed": seed, **role["extra_body"]}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    config = json.loads(args.config.read_text())
    if os.environ.get("PYTHONHASHSEED") != str(config["seed"]):
        import sys
        os.environ["PYTHONHASHSEED"] = str(config["seed"])
        os.execv(sys.executable, [sys.executable, "-u", *sys.argv])
    seed_everything(config["seed"])
    keys = {role: os.environ[config[role]["api_key_env"]] for role in ["target", "judge"]}
    source = ROOT / config["source_batch"]
    source_config = json.loads((source / "config.json").read_text())
    out = args.resume.resolve() if args.resume else ROOT / "runs" / (
        "eval-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    out.mkdir(exist_ok=bool(args.resume), parents=True)
    hashes = {}
    items = []
    iteration = config["iteration"]
    for task in source_config["tasks"]:
        name = task["name"]
        question_file = source / name / f"wiki.{iteration}.KI_questions.json"
        questions = json.loads(question_file.read_text())
        answers = [json.loads(line) for line in
                   (source / name / f"wiki.{iteration}.test_taker_inference.json").read_text().splitlines()]
        assert len(questions) == len(answers)
        hashes[str(question_file.relative_to(source))] = hashlib.sha256(question_file.read_bytes()).hexdigest()
        (out / name).mkdir(exist_ok=True)
        if not args.resume:
            shutil.copy2(question_file, out / name / question_file.name)
        for index, (question, answer) in enumerate(zip(questions, answers), 1):
            assert question["question"] == answer["question"]
            items.append({"id": f"{name}/{iteration}/{index}", "task": name,
                          "index": index, "question": question, "prompt": answer["prompt"]})
    if args.resume:
        assert json.loads((out / "config.json").read_text()) == config
        assert json.loads((out / "source-sha256.json").read_text()) == hashes
    else:
        dump(out / "config.json", config)
        dump(out / "source-sha256.json", hashes)
    prefix = judge_prefix()
    (out / "judge-prompt.txt").write_text(prefix)
    answers = read_records(out / "answers.jsonl")
    grades = read_records(out / "grades.jsonl")
    status = {"status": "running", "started": datetime.now(timezone.utc).isoformat(),
              "questions": len(items), "output_dir": str(out)}

    def save_status():
        status.update(answers=len(answers), grades=len(grades))
        status["tasks"] = {t["name"]: {
            "questions": sum(i["task"] == t["name"] for i in items),
            "answers": sum(r["task"] == t["name"] for r in answers.values()),
            "grades": sum(r["task"] == t["name"] for r in grades.values())}
            for t in source_config["tasks"]}
        dump(out / "status.json", status)

    save_status()
    print(f"Evaluation directory: {out}; questions: {len(items)}", flush=True)
    semaphores = {r: asyncio.Semaphore(config[r]["concurrency"]) for r in keys}
    with (out / "requests.jsonl").open("a", buffering=1) as request_log, \
            (out / "answers.jsonl").open("a", buffering=1) as answer_log, \
            (out / "grades.jsonl").open("a", buffering=1) as grade_log:
        async with httpx.AsyncClient(timeout=300, limits=httpx.Limits(
                max_connections=136, max_keepalive_connections=136)) as client:
            async def call(role, item, prompt):
                settings = config[role]
                body = request_body(settings, prompt, config["seed"])
                async with semaphores[role]:
                    for attempt in range(3):
                        started = time.time()
                        try:
                            response = await client.post(settings["base_url"].rstrip("/") + "/chat/completions",
                                headers={"Authorization": "Bearer " + keys[role]}, json=body)
                            code = response.status_code
                            try:
                                payload = response.json()
                            except ValueError:
                                payload = response.text
                        except httpx.TransportError as error:
                            code, payload = 0, {"error": type(error).__name__}
                        record = {"id": item["id"], "role": role, "attempt": attempt + 1,
                                  "started": started, "seconds": time.time() - started,
                                  "request": body, "status": code, "response": payload}
                        request_log.write(json.dumps(record, ensure_ascii=False) + "\n")
                        if code == 200:
                            content = payload["choices"][0]["message"]["content"]
                            if not isinstance(content, str) or not content.strip():
                                raise RuntimeError(f"{role} {item['id']}: empty response; see requests.jsonl")
                            return content.strip()
                        if code not in [0, 408, 409, 429] and code < 500:
                            break
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                    raise RuntimeError(f"{role} {item['id']}: HTTP {code}; see requests.jsonl")

            async def evaluate(item):
                identity = {k: item[k] for k in ["id", "task", "index"]}
                if item["id"] not in answers:
                    response = await call("target", item, item["prompt"])
                    record = identity | {"prompt": item["prompt"], "test_taker_response": response}
                    answer_log.write(json.dumps(record, ensure_ascii=False) + "\n")
                    answers[item["id"]] = record
                if item["id"] not in grades:
                    answer = answers[item["id"]]["test_taker_response"]
                    response = await call("judge", item, judge_prompt(prefix, item["index"], item["question"], answer))
                    record = identity | {"reasons": response, "is_correct": response.split("##")[-1].strip()}
                    grade_log.write(json.dumps(record, ensure_ascii=False) + "\n")
                    grades[item["id"]] = record
                if len(grades) % 50 == 0 or len(grades) == 1:
                    save_status()
                    print(f"Answered {len(answers)}/{len(items)}; graded {len(grades)}/{len(items)}", flush=True)

            pending = []
            try:
                # Validate one real question end to end before filling the request queues.
                await evaluate(items[0])
                pending = [asyncio.create_task(evaluate(item)) for item in items[1:]]
                await asyncio.gather(*pending)
            except Exception as error:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                status.update(status="failed", error=str(error))
                save_status()
                raise

    summary = {"source_batch": config["source_batch"], "iteration": iteration,
               "target_model": config["target"]["model"], "judge_model": config["judge"]["model"], "tasks": {}}
    for task in source_config["tasks"]:
        name = task["name"]
        task_answers, task_grades = [], []
        for item in (i for i in items if i["task"] == name):
            answer, grade = answers[item["id"]], grades[item["id"]]
            task_answers.append(item["question"] | {"prompt": item["prompt"],
                                "test_taker_response": answer["test_taker_response"]})
            task_grades.append(item["question"] | {"id": str(item["index"]),
                "test_taker_answer": answer["test_taker_response"],
                "reasons": grade["reasons"], "is_correct": grade["is_correct"]})
        (out / name / f"wiki.{iteration}.test_taker_inference.json").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in task_answers))
        dump(out / name / f"wiki.{iteration}.compare_answers.json", task_grades)
        correct = sum(g["is_correct"] == "true" for g in task_grades)
        baseline = json.loads((source / name / f"wiki.{iteration}.compare_answers.json").read_text())
        summary["tasks"][name] = {"questions": len(task_grades), "correct": correct,
            "accuracy": correct / len(task_grades), "invalid_judgments": [g for g in task_grades
                if g["is_correct"] not in ["true", "false"]],
            "deepseek_correct": sum(g["is_correct"] == "true" for g in baseline)}
    usage = {role: Counter() for role in keys}
    for line in (out / "requests.jsonl").read_text().splitlines():
        record = json.loads(line)
        if record["status"] == 200:
            usage[record["role"]].update({k: record["response"].get("usage", {}).get(k, 0)
                for k in ["prompt_tokens", "completion_tokens", "total_tokens"]})
    summary["usage"] = {k: dict(v) for k, v in usage.items()}
    dump(out / "summary.json", summary)
    status.update(status="complete", ended=datetime.now(timezone.utc).isoformat())
    save_status()
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
