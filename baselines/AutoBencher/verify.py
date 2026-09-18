"""Check complete question, answer and grading artifacts for every iteration."""

import json
from pathlib import Path
import sys


def verify(run_dir):
    run_dir = Path(run_dir)
    config = json.loads((run_dir / "config.json").read_text())
    iterations = []
    for iteration in range(1, config["iterations"] + 1):
        prefix = run_dir / f"wiki.{iteration}"
        questions = json.loads(Path(f"{prefix}.KI_questions.json").read_text())
        answers = [json.loads(line) for line in
                   Path(f"{prefix}.test_taker_inference.json").read_text().splitlines()]
        grades = json.loads(Path(f"{prefix}.compare_answers.json").read_text())
        assert len(questions) == len(answers) == len(grades) > 0
        for question, answer, grade in zip(questions, answers, grades):
            assert question["question"] == answer["question"] == grade["question"]
            assert all(question[k] for k in ["question", "gold_answer", "wiki_entity"])
            assert answer["test_taker_response"].strip()
            assert grade["test_taker_answer"] == answer["test_taker_response"]
            assert grade["is_correct"] in {"true", "false"}
        iterations.append({
            "iteration": iteration, "questions": len(questions),
            "categories": sorted({q["category"] for q in questions}),
            "correct": sum(g["is_correct"] == "true" for g in grades),
            "accuracy": sum(g["is_correct"] == "true" for g in grades) / len(grades),
        })
    requests = [json.loads(line) for line in (run_dir / "requests.jsonl").read_text().splitlines()]
    usage = {k: sum(r["response"].get("usage", {}).get(k, 0) for r in requests
                    if isinstance(r["response"], dict))
             for k in ["prompt_tokens", "completion_tokens", "total_tokens"]}
    result = {"iterations": iterations, "requests": len(requests), "usage": usage,
              "finish_reasons": {reason: sum(c.get("finish_reason") == reason
                  for r in requests if r["status"] == 200
                  for c in r["response"].get("choices", []))
                  for reason in ["stop", "length"]}}
    (run_dir / "verification.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1]), indent=2))
