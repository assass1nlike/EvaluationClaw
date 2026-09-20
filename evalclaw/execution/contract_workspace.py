"""Execute compatible explicit workspaces through the established CLI lifecycle."""
from __future__ import annotations

import json
import time

from .contract_capabilities import binding_issues, workspace_projection
from .task_runtime import ContractSession, contract_issues, scalar_score


def evaluate_workspace(session, backend, image, workdir, evidence, container):
    execution = evidence.get("target_execution", {})
    final = execution.get("final_response", execution.get("raw_output", ""))
    stages = evidence.get("stages", [])
    session.episode.outputs = [s["output"] for s in stages if "output" in s] or [final]
    if stages:
        session.episode.final_messages = []
        for stage in stages:
            if stage.get("context") == "fresh":
                session.episode.final_messages = []
            session.session = stage.get("session_id", session.session)
            for role, key in (("user", "prompt"), ("assistant", "output")):
                if key in stage:
                    session.episode.final_messages.append({"role": role, "content": stage[key]})
            session.emit("dialogue_stage", "runtime", stage)
    else:
        session.episode.final_messages = [{"role": "assistant", "content": final}]
    session.episode.final_state = execution.get("final_state")
    session.episode.termination = evidence.get("termination", {}).get("status", "completed")
    session.episode.artifacts["native_evaluator_evidence"] = evidence
    if execution.get("tool_call_count") is not None:
        session.episode.usage["tool_calls"] = execution["tool_call_count"]
    session.emit("native_execution", "target", execution)
    session.workspace = (session.config.docker_executable, container, session.item.environment.workdir)
    session.environment_scorer = lambda: backend.evaluate(image, workdir, evidence=evidence, container_name=container)
    session.target_ended = True
    session.evaluate()
    session.require_valid_scoring()
    return scalar_score(session.item, session.episode) or 0.0, "\n".join(m.reason for m in session.episode.metrics)


def run_workspace_contract(item, config, target, *, trace_dir=None, preflight=False):
    from ..runners.harness import ManifestHarnessRunner, get_harness
    from ..types import ItemResult

    started = time.monotonic()
    session = ContractSession(item, config, target, trace_dir)
    error, raw, stage = None, "", "preflight"
    try:
        issues = contract_issues(item) + binding_issues(item, config, target)
        if issues:
            raise ValueError("; ".join(issues))
        runner = get_harness(target.harness)
        if not isinstance(runner, ManifestHarnessRunner):
            raise ValueError("This custom harness does not expose the workspace evaluation lifecycle")
        projected = workspace_projection(item)
        session.prepare_scorers()

        def evaluate(backend, image, workdir, evidence, container):
            nonlocal stage
            stage = "evaluation"
            return evaluate_workspace(session, backend, image, workdir, evidence, container)

        stage = "target" if not preflight else "preflight"
        raw, _, _ = runner.run(projected, target, config, artifact_dir=trace_dir,
                               preflight_only=preflight, evaluation_callback=evaluate)
        if preflight and item.environment.verification_cases:
            from ..construction.verification import verify_agent_cases
            verify_agent_cases(item, config)
    except Exception as exc:
        from .errors import EvaluationExecutionError
        if preflight and isinstance(exc, EvaluationExecutionError):
            raise
        error = f"{type(exc).__name__}: {exc}"
        session.episode.termination = "error"
        session.emit("execution_error", "runtime", {"stage": stage, "error": error})
        evidence = getattr(exc, "execution_evidence", None)
        if evidence:
            session.episode.artifacts["native_evaluator_evidence"] = evidence
            raw = evidence.get("target_execution", {}).get("raw_output", raw)
    finally:
        if trace_dir and (trace_dir / "native-episode.json").is_file():
            session.episode.artifacts["native_episode"] = str(trace_dir / "native-episode.json")
        try:
            session.close()
        except Exception as exc:
            error = error or f"Cleanup error: {type(exc).__name__}: {exc}"
            session.emit("cleanup_error", "runtime", {"error": str(exc)})
    try:
        score = scalar_score(item, session.episode)
    except (ValueError, TypeError) as exc:
        score = None
        error = error or f"Scalar selection error: {exc}"
    return ItemResult(item_id=item.id, target_id=target.id, score=score or 0.0, error=error,
                      raw_response=raw, episode=session.episode,
                      execution={"stage": stage, "scalar_available": score is not None},
                      latency_ms=round((time.monotonic() - started) * 1000),
                      judge_reasoning=json.dumps([m.model_dump(mode="json") for m in session.episode.metrics]))
