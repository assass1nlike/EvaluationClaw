"""Manual smoke: generator + Gemini web search, no full pipeline."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from evalclaw.generator import generate_questions
from evalclaw.types import BenchmarkConfig, TargetModelConfig, TestDimension

# Gemini as orchestrator using its OpenAI-compatible base URL.
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def main() -> None:
    if not GEMINI_KEY:
        raise SystemExit("Set GEMINI_API_KEY to run this manual generator search smoke.")

    config = BenchmarkConfig(
        orchestrator_model="gemini-2.5-flash-lite",
        orchestrator_api_key=GEMINI_KEY,
        orchestrator_base_url=GEMINI_BASE,
        targets=[TargetModelConfig(id="claude-opus-4-6", provider="anthropic", model="claude-opus-4-6")],
        questions_per_dimension=3,
    )

    dim = TestDimension(
        id="abstract_algebra_hard",
        name="Hard abstract algebra",
        description="Evaluate non-trivial theorems and consequences in groups, rings, fields, and modules.",
        approach="Generate deep proof, judgment, and calculation tasks covering core difficult points in group theory, ring theory, and field theory.",
        needs_research=True,
    )

    print("=== Searching references and generating items ===\n")
    questions = generate_questions(dim, count=3, config=config)

    for i, q in enumerate(questions, 1):
        print(f"--- Item {i} [{q.task_type.value} / {q.difficulty.value}] ---")
        print(f"Prompt: {q.prompt}")
        if q.choices:
            for c in q.choices:
                print(f"  {c}")
        if q.answer:
            print(f"Answer: {q.answer}")
        if q.rubric:
            print(f"Rubric: {q.rubric[:200]}{'...' if len(q.rubric) > 200 else ''}")
        if q.test_code:
            print(f"Test code: {q.test_code[:200]}")
        if q.source.uri:
            print(f"Source: {q.source.uri}")
        print()


if __name__ == "__main__":
    main()
