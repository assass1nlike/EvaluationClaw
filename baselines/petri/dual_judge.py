"""Score the completed audit independently against both sets of criteria."""

import asyncio
from functools import wraps

from inspect_ai.util import span
from petri.scorers.judge import alignment_judge
from petri.scorers.prompts import DIMENSIONS

from requirement_judge import DEFAULT_RUBRIC, requirement_judge


def dual_judges(requirement: str, rubric: str = DEFAULT_RUBRIC):
    judges = {
        "requirement_judge": requirement_judge(requirement, rubric),
        "alignment_judge": alignment_judge(),
    }

    async def score(state, target):
        async def evaluate(name, judge):
            async with span(name=name, type="scorer"):
                return await judge(state, target)

        results = await asyncio.gather(
            *(evaluate(name, judge) for name, judge in judges.items()),
            return_exceptions=True,
        )
        scores, errors = {}, {}
        for name, result in zip(judges, results):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                errors[name] = {"error": f"{type(result).__name__}: {result}"}
            elif name == "alignment_judge" and (
                set(result.value) != set(DIMENSIONS)
                or "score_descriptions" in (result.metadata or {})
            ):
                errors[name] = {"error": "Incomplete native judgment",
                                "response": (result.metadata or {}).get("response", "")}
            else:
                scores[name] = result
        state.scores = scores
        state.metadata["judge_errors"] = errors

    # Preserve each scorer's Inspect registration and aggregation metrics.
    @wraps(judges["requirement_judge"])
    async def primary(state, target):
        await score(state, target)
        return state.scores.get("requirement_judge")

    @wraps(judges["alignment_judge"])
    async def reference(state, target):
        return state.scores.get("alignment_judge")

    return [primary, reference]
