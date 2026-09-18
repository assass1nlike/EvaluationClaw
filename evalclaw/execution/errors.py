"""Failures of the scoring service, distinct from defects in a task definition."""


class EvaluationExecutionError(RuntimeError):
    """Scoring could not complete; neither the task nor the target is graded."""


class JudgeResponseError(EvaluationExecutionError):
    """The judge could not return a valid assessment for this item."""
