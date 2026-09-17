"""Failures of the scoring service, distinct from defects in a task definition."""


class EvaluationExecutionError(RuntimeError):
    """Scoring could not complete; neither the task nor the target is graded."""
