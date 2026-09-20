"""Exercise packaged tasks through the same isolated runtime used by reviewers."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from ..types import AgentVerificationCase, BenchmarkConfig, BenchmarkItem


def verify_agent_cases(item: BenchmarkItem, config: BenchmarkConfig, *, directory: Path | None = None) -> list[dict]:
    from ..quality.laaj_exploration import _experiment

    cases = [AgentVerificationCase.model_validate(case)
             for case in (item.environment.verification_cases if item.content is not None else
                          item.metadata.get("agent_env", {}).get("verification_cases", []))]
    if not cases:
        return []
    if item.workflow is not None:
        raise ValueError("Verification command cases currently require a single-stage task.")
    fingerprint = hashlib.sha256(item.model_dump_json().encode()).hexdigest()
    if directory is not None:
        directory = directory / uuid.uuid4().hex
    outcomes = []
    targets = config.targets or [None]
    for target in targets:
        for case in cases:
            name = f"{target.id if target else 'native'}-{case.id}"
            experiment = _experiment(item, config, target.id if target else "",
                                     directory / name if directory else None)
            try:
                for command in case.commands:
                    result = experiment.perform({"operation": "command", "command": command})
                    if result.get("status") == "budget_exhausted":
                        break
                    if result.get("returncode", 0) != 0 or result.get("error"):
                        raise ValueError(f"Verification case {name}: command failed: {result}")
                result = experiment.perform({"operation": "evaluate", "final_answer": case.final_answer})
                if case.required_interventions:
                    runtime = getattr(experiment, "workspace_trial", None) or experiment
                    controller = (experiment.runtime.interventions if item.content is not None and runtime is experiment
                                  else runtime.controller)
                    completed = {event["id"] for event in controller.records
                                 if event["status"] == "completed"} if controller else set()
                    missing = set(case.required_interventions) - completed
                    if missing:
                        raise ValueError(f"Verification case {name}: interventions not triggered successfully: {sorted(missing)}")
                if result["score"] is None:
                    raise ValueError("Command verification cases require evaluation.scalar")
                passed = case.min_score <= result["score"] <= case.max_score
                outcomes.append({"case": name, "task_sha256": fingerprint, "passed": passed, **result})
                if not passed:
                    raise ValueError(f"Verification case {name}: expected [{case.min_score}, {case.max_score}], got {json.dumps(result)}")
            finally:
                experiment.close()
    return outcomes
