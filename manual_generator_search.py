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
        name="抽象代数难题",
        description="考察群、环、域、模等抽象代数结构中的非平凡定理与推论",
        approach="出具有一定深度的证明题、判断题和计算题，覆盖群论、环论、域论核心难点",
        needs_research=True,
    )

    print("=== 正在搜索参考资料并生成题目 ===\n")
    questions = generate_questions(dim, count=3, config=config)

    for i, q in enumerate(questions, 1):
        print(f"--- 题目 {i} [{q.task_type.value} / {q.difficulty.value}] ---")
        print(f"题干: {q.prompt}")
        if q.choices:
            for c in q.choices:
                print(f"  {c}")
        if q.answer:
            print(f"正确答案: {q.answer}")
        if q.rubric:
            print(f"评分标准: {q.rubric[:200]}{'...' if len(q.rubric) > 200 else ''}")
        if q.test_code:
            print(f"测试代码: {q.test_code[:200]}")
        if q.source.uri:
            print(f"来源: {q.source.uri}")
        print()


if __name__ == "__main__":
    main()
