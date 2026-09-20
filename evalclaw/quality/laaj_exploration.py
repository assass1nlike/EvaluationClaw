"""Isolated task experiments for benchmark-quality judges."""
from __future__ import annotations

import copy
import json
import subprocess
import threading
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..diagnostics import redact_secrets, write_json
from ..execution.agent_envs import build_agent_environment
from ..execution.docker import docker_subprocess_env
from ..execution.evidence import EVALUATOR_EVIDENCE_SCHEMA, execution_failure
from ..execution.interventions import InterventionController
from ..protocols.tool import ToolCall, ToolResult, ToolSpec
from ..runners import harness
from ..runners.environment_actors import CONTACT_INSTRUCTIONS, ActorSession, actor_configuration
from ..types import AnalysisReport, BenchmarkConfig, BenchmarkItem, TaskSuite, TaskType

LAAJ_EXPLORE_TOOL = ToolSpec(
    name="explore_agent_environment",
    description=(
        "Run an isolated experiment on an agent task, never on the original target run. "
        "open requires item_id; scope/iteration select main or probe tasks, target_id selects "
        "the configured runtime (default first target). Reuse the returned session_id for "
        "command, action, evaluate, trial, reset, or close. trial replays scripted responses "
        "through the complete native interaction protocol and scoring. command executes a shell command; "
        "action invokes a native tool returned by open. Target perspective uses actual target "
        "permissions; reviewer perspective is privileged inspection and cannot prove target "
        "feasibility. evaluate runs the original scorer on your trial submission and ends the "
        "experiment; reset creates a fresh environment and actor histories for another trial. "
        "Reviewer mutations are recorded. Results are judge experiments, not model scores."
    ),
    parameters={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["open", "command", "action", "evaluate", "trial", "reset", "close"]},
            "responses": {"type": "array", "items": {"type": "object"}, "description": "For trial: scripted target responses with content, tool_calls and optional usage; runs the complete declared protocol."},
            "item_id": {"type": "string"},
            "scope": {"type": "string", "enum": ["main", "probe"]},
            "iteration": {"type": "integer", "minimum": 1},
            "target_id": {"type": "string"},
            "session_id": {"type": "string"},
            "perspective": {"type": "string", "enum": ["target", "reviewer"]},
            "command": {"type": "string"},
            "action": {"type": "object", "description": "Native tool call: {action: tool_name, args: {...}}."},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
            "final_answer": {"type": "string"},
        },
        "required": ["operation"],
        "additionalProperties": False,
    },
)


class TaskExperiment:
    def __init__(self, item: BenchmarkItem, config: BenchmarkConfig, target_id: str, directory: Path | None):
        self.item = item.model_copy(deep=True)
        self.config = config
        self.directory = directory
        self.target = next((t for t in config.targets if t.id == target_id), None)
        if target_id and self.target is None:
            raise ValueError(f"Unknown configured target: {target_id}")
        if self.target is None and config.targets:
            self.target = config.targets[0]
        self.capture: dict[str, Any] = {}
        self.actors: ActorSession | None = None
        self.environment = None
        self.backend = None
        self.evaluation_callback = None
        self.workdir = None
        self.controller = None
        self.trace: list[dict[str, Any]] = []
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.started = time.monotonic()
        self.ended = False
        self.episode_started: float | None = None
        self.budget_exhausted = False
        self.budget_timer = None
        self.budget_error = None
        self.reviewer_access = False
        self.record: dict[str, Any] = {
            "purpose": "laaj_exploration", "item_id": item.id,
            "configured_target_id": self.target.id if self.target else None,
            "started_at": self.started_at, "operations": [],
        }
        try:
            env = harness.agent_env(self.item)
            if self.target and self.target.harness:
                runner = harness.get_harness(self.target.harness)
                if not isinstance(runner, harness.ManifestHarnessRunner):
                    raise ValueError("This custom harness does not support isolated task exploration.")
                harness.reject_tool_constraints(self.item, self.target.harness)
                runner._validate_target(self.target)
                self.backend = harness.environment_backend(self.item, config)
                self.image, self.workdir = self.backend.prepare()
                if env.get("actors"):
                    actors, toolsets = actor_configuration(env)
                    self.actors = ActorSession(
                        actors=actors, toolsets=toolsets, workdir=self.workdir, image=self.image,
                        environment=env, config=config, artifact_dir=directory,
                    )
                # Same setup, runtime mounts and target identity, without target inference.
                runner._launch(
                    self.item, self.target, config, self.image, self.workdir,
                    actor_session=self.actors, capture=self.capture, prepare_only=True,
                )
            else:
                if env.get("actors"):
                    raise ValueError("Actor tasks require a configured external shell harness.")
                if self.item.workflow is not None:
                    raise ValueError("Multi-stage workflows require stage-aware execution; use saved evidence.")
                if env.get("type") == "vm":
                    if not env.get("vm"):
                        raise ValueError("Exploration requires a VM creation specification, not a shared desktop.")
                    # Always create a private VM; never attach to a target's materialized VM.
                    env.pop("bridge_url", None)
                    env.pop("vm_id", None)
                    env["requires_vm"] = True
                    env["destroy_vm_on_cleanup"] = True
                self.environment = build_agent_environment(self.item, config)
            if env.get("interventions"):
                self.controller = InterventionController(env["interventions"], self._control)
            self.record["status"] = "ready"
            self.save()
        except BaseException as exc:
            self.record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            self.close()
            raise

    def save(self):
        if self.directory is not None:
            write_json(self.directory / "experiment.json", self.record, redact=True)

    def describe(self):
        data = {"item_id": self.item.id, "purpose": "laaj_exploration", "status": "ready"}
        if self.environment is not None:
            data.update(observation=self.environment.observation(), tools=[
                tool.model_dump(mode="json") for tool in self.environment.tool_specs()
            ])
        else:
            data.update(harness=self.target.harness, target_user=harness._target_container_user())
        if self.actors:
            data["contacts"] = CONTACT_INSTRUCTIONS
        data["interventions"] = "Begin on the first target-perspective action."
        if self.item.workflow is not None:
            data["workflow"] = "This trial explores the initial environment only. It cannot simulate staged conversations or grade a workflow; use stage-aware target execution for that."
        return data

    def _expire_budget(self):
        self.budget_exhausted = True
        try:
            harness.ManifestHarnessRunner._stop_episode(self.capture["docker"], self.capture["container_name"])
            if self.controller:
                self.controller.stop()
        except Exception as exc:
            self.budget_error = exc

    def _finish_budget_timer(self):
        if self.budget_timer is not None:
            self.budget_timer.cancel()
            self.budget_timer.join()
            self.budget_timer = None
        budget = harness.agent_env(self.item).get("budget") or {}
        if budget and self.episode_started is not None and not self.budget_exhausted and not self.ended:
            if time.monotonic() - self.episode_started >= float(budget["wall_time_seconds"]):
                self._expire_budget()
        if self.budget_error:
            raise RuntimeError("Could not stop the expired trial episode.") from self.budget_error

    def _exec(self, command: str, timeout: int, *, reviewer: bool):
        prefix = "" if reviewer else self.capture.get("runtime_prefix", "")
        if not reviewer:
            import shlex
            prefix += f"export EVALCLAW_EPISODE_ID={shlex.quote(self.capture['container_name'])}; "
        return harness._run_bounded(
            harness._container_exec_command(
                self.capture["docker"], self.capture["container_name"], prefix + command,
                user="0:0" if reviewer else harness._target_container_user(),
            ), timeout=timeout, env=docker_subprocess_env(self.config.docker_executable),
        )

    def _control(self, command: str, timeout: int):
        if self.environment is not None:
            run = getattr(self.environment, "run_external_command", None)
            if not callable(run):
                raise ValueError("This environment has no reviewer shell; use its native tools.")
            return run(command, timeout)
        return self._exec(command, timeout, reviewer=True)

    def _evidence(self, final_answer: str):
        from ..protocols.submission import submission_contract
        return {
            "schema_version": EVALUATOR_EVIDENCE_SCHEMA,
            "submission_contract": submission_contract(self.item),
            "purpose": "laaj_exploration", "item_id": self.item.id,
            "reviewer_access": self.reviewer_access,
            "target": {
                "id": "laaj-experiment", "model": self.config.laaj_model,
                "provider": self.config.laaj_provider,
                "harness": self.target.harness if self.target and self.target.harness else "native",
            },
            "target_execution": {
                "final_response": final_answer, "raw_output": final_answer,
                "trace": copy.deepcopy(self.trace), "history": [], "model_responses": [],
                "tool_call_count": len(self.trace), "stderr": "",
                "final_state": self.environment.state() if self.environment is not None else {},
            },
            "actors": self.actors.runtime.evidence() if self.actors else {"interactions": [], "summary": {}},
            "interventions": list(self.controller.records) if self.controller else [],
            "timing": {
                "started_at": self.started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - self.started) * 1000),
            },
            "termination": {"status": "budget_exhausted" if self.budget_exhausted else "completed", "done": True, "steps": len(self.trace)},
        }

    def perform(self, args: dict[str, Any]):
        operation = args["operation"]
        reviewer = args.get("perspective", "target") == "reviewer"
        if self.ended and not (operation == "command" and reviewer):
            raise ValueError("The experiment has ended; reset for another target trial.")
        entry = {"request": args, "started_at": datetime.now(timezone.utc).isoformat()}
        self.record["operations"].append(entry)
        try:
            if operation in {"command", "action"}:
                if reviewer:
                    self.reviewer_access = True
                else:
                    if self.budget_exhausted:
                        raise ValueError("Episode budget exhausted; evaluate the saved state or reset.")
                    if self.episode_started is None:
                        self.episode_started = time.monotonic()
                        if self.controller:
                            self.controller.start()
                        budget = harness.agent_env(self.item).get("budget") or {}
                        if budget:
                            self.budget_timer = threading.Timer(float(budget["wall_time_seconds"]), self._expire_budget)
                            self.budget_timer.daemon = True
                            self.budget_timer.start()
                timeout = max(1, min(600, int(args.get("timeout_seconds", 120))))
                budget = harness.agent_env(self.item).get("budget") or {}
                if budget and not reviewer:
                    remaining = float(budget["wall_time_seconds"]) - (time.monotonic() - self.episode_started)
                    if remaining <= 0:
                        self._finish_budget_timer()
                        return {"status": "budget_exhausted", "returncode": 124}
                    timeout = min(timeout, remaining)
                if operation == "command":
                    command = str(args.get("command") or "").strip()
                    if not command:
                        raise ValueError("command is required")
                    if self.environment is None or reviewer:
                        proc = self._control(command, timeout) if reviewer else self._exec(command, timeout, reviewer=False)
                        result = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
                        action = {"action": "run_command", "args": {"command": command}}
                    else:
                        action = {"action": "run_command", "args": {"command": command, "timeout": timeout}}
                        outcome = self.environment.step(action)
                        result = vars(outcome)
                else:
                    if self.environment is None or reviewer:
                        raise ValueError("action is for native target tools; use command for external harnesses")
                    action = args.get("action")
                    if not isinstance(action, dict):
                        raise ValueError("action must contain a native tool name and args")
                    if action.get("action") in {"final", "evaluate", "run_tests", "run_test"}:
                        raise ValueError("Use the evaluate operation to submit a final trial")
                    if action.get("action") not in {t.name for t in self.environment.tool_specs()}:
                        raise ValueError("Unavailable native tool")
                    result = vars(self.environment.step(action))
                if not reviewer:
                    self.trace.append({
                        "step": len(self.trace) + 1, "parsed_action": action,
                        "tool_call": {"id": f"explore-{len(self.trace) + 1}", "name": action["action"], "arguments": action.get("args", {})},
                        "observation": json.dumps(result, ensure_ascii=False),
                    })
                if self.controller:
                    self.controller.raise_if_failed()
                if self.actors:
                    self.actors.raise_if_failed()
                if self.budget_exhausted:
                    self._finish_budget_timer()
                    result["status"] = "budget_exhausted"
            elif operation == "evaluate":
                if self.item.workflow is not None:
                    raise ValueError("Workflow scoring requires stage-aware execution; this trial explores the initial environment only.")
                self._finish_budget_timer()
                self.ended = True
                if self.controller:
                    if self.environment is None and any(s["trigger"]["type"] == "episode_end" for s in self.controller.specs):
                        harness.ManifestHarnessRunner._stop_episode(self.capture["docker"], self.capture["container_name"])
                    self.controller.finish()
                if self.actors:
                    self.actors.close()
                    self.actors.raise_if_failed()
                final_answer = str(args.get("final_answer") or "")
                if self.budget_exhausted:
                    final_answer = ""
                write_answer = getattr(self.environment, "_write_final_answer", None)
                if callable(write_answer):
                    self.environment.final_answer = final_answer
                    self.environment.done = True
                    write_answer(final_answer)
                evidence = self._evidence(final_answer)
                if self.directory:
                    write_json(self.directory / "evaluator-evidence.json", evidence, redact=True)
                if self.evaluation_callback is not None:
                    score, details = self.evaluation_callback(evidence)
                elif self.environment is None:
                    score, details = self.backend.evaluate(
                        self.image, self.workdir, evidence, container_name=self.capture["container_name"],
                        **({"artifact_dir": self.directory / "judge" if self.directory else None}
                           if harness.agent_env(self.item).get("judge") else {}),
                    )
                elif hasattr(self.environment, "evaluate_with_evidence"):
                    if getattr(self.environment, "judge_evaluator", None) is not None and self.directory:
                        self.environment.judge_artifact_dir = self.directory / "judge"
                    details = self.environment.evaluate_with_evidence(evidence)
                    score = self.environment.score()
                else:
                    details = self.environment._evaluate(final_answer=str(args.get("final_answer") or "")).observation
                    score = self.environment.score()
                result = {"score": score, "details": details, "purpose": "laaj_exploration",
                          "reviewer_access": self.reviewer_access}
            else:
                raise ValueError(f"Unknown experiment operation: {operation}")
            entry["result"] = result
            return result
        except Exception as exc:
            entry["error"] = execution_failure(exc)
            if isinstance(exc, subprocess.TimeoutExpired):
                budget = harness.agent_env(self.item).get("budget") or {}
                if budget and not reviewer and self.episode_started is not None and time.monotonic() - self.episode_started >= float(budget["wall_time_seconds"]):
                    self._finish_budget_timer()
                    return {"status": "budget_exhausted", "returncode": 124, "stdout": entry["error"]["stdout"], "stderr": entry["error"]["stderr"]}
                # docker exec timeout alone leaves the command running inside the container.
                self.close()
                self.ended = True
            raise
        finally:
            entry["finished_at"] = datetime.now(timezone.utc).isoformat()
            self.save()

    def close(self):
        self.record["closed_at"] = datetime.now(timezone.utc).isoformat()
        try:
            with ExitStack() as cleanup:
                cleanup.callback(self.save)
                if self.backend and self.workdir:
                    cleanup.callback(self.backend.cleanup, self.workdir)
                cleanup.callback(harness.cleanup_harness_session, self.capture)
                if self.environment is not None:
                    cleanup.callback(self.environment.cleanup)
                if self.actors and not self.actors.runtime.closed.is_set():
                    cleanup.callback(self.actors.close)
                if self.controller:
                    cleanup.callback(self.controller.stop)
                cleanup.callback(self._finish_budget_timer)
        finally:
            self.workdir = None
            self.capture = {}
            self.environment = None


class ContractExperiment:
    """Use the same lifecycle and scorers as execution in a separate instance."""

    def __init__(self, item, config, target_id, directory):
        from ..execution.task_runtime import ContractSession
        from ..types import TargetModelConfig
        self.item, self.config, self.directory = item, config, directory
        self.target = next((t for t in config.targets if t.id == target_id), None)
        if target_id and self.target is None:
            raise ValueError(f"Unknown target binding: {target_id}")
        self.target = self.target or (config.targets[0] if config.targets else TargetModelConfig(provider="openai", model="inspection"))
        self.record = {"purpose": "laaj_exploration", "operations": []}
        self.runtime = ContractSession(item, config, self.target, directory)
        self.workspace_trial = None
        try:
            if self.target.harness and item.environment is not None:
                from ..execution.contract_capabilities import binding_issues, workspace_projection
                from ..execution.contract_workspace import evaluate_workspace
                issues = binding_issues(item, config, self.target)
                if issues:
                    raise ValueError("; ".join(issues))
                self.workspace_trial = TaskExperiment(workspace_projection(item), config, self.target.id, directory)
                self.runtime.prepare_scorers()
                trial = self.workspace_trial
                self.runtime.episode.bindings["purpose"] = "scripted_trial"
                trial.evaluation_callback = lambda evidence: evaluate_workspace(
                    self.runtime, trial.backend, trial.image, trial.workdir, evidence, trial.capture["container_name"])
            else:
                self.runtime.prepare()
        except BaseException:
            self.close()
            raise

    def save(self):
        if self.directory:
            write_json(self.directory / "reviewer.json", self.record, redact=True)
        self.runtime.save()

    def describe(self):
        if self.workspace_trial:
            return self.workspace_trial.describe()
        return {"status": "open", "tools": [t.model_dump(mode="json") for t in self.runtime.tools],
                "initial_messages": self.runtime.messages,
                "note": "Independent reviewer experiment; its operations are not target-model performance."}

    def perform(self, args):
        operation = args["operation"]
        if self.workspace_trial:
            result = self.workspace_trial.perform(args)
            if operation == "evaluate":
                result["metrics"] = [m.model_dump(mode="json") for m in self.runtime.episode.metrics]
            return result
        if self.runtime.target_ended:
            raise ValueError("Experiment ended; reset before another trial")
        self.record["operations"].append(copy.deepcopy(args))
        if operation == "action":
            from ..protocols.tool import ToolCall
            action = args["action"]
            call = ToolCall(id=f"reviewer-{len(self.record['operations'])}", name=action["action"], arguments=action.get("args", {}))
            if args.get("perspective", "target") == "reviewer":
                result = self.runtime.tool_call(call, origin="reviewer")
            else:
                self.runtime.trial_submit(calls=[call])
                result = {"status": "completed", "last_event": self.runtime.episode.events[-1].model_dump(mode="json")}
        elif operation == "command":
            if args.get("perspective", "target") != "reviewer":
                return self.perform({"operation": "action", "action": {"action": "run_command", "args": {"command": args["command"]}}})
            env = self.runtime.legacy_environment
            if env is not None and hasattr(env, "_container_name"):
                from ..execution.judge_sandbox import JudgeSandbox
                with JudgeSandbox(env.docker_executable, env._container_name, env.workdir) as sandbox:
                    proc = sandbox.command(args["command"], 120)
                    result = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
            elif self.runtime.environment is None or "inspect" not in self.item.environment.capabilities:
                raise ValueError("This environment has no reviewer inspection capability; use its declared action tools")
            else:
                result = self.runtime.environment.call("inspect", {"query": args["command"]})
            self.runtime.emit("inspection", "reviewer", result)
        elif operation == "evaluate":
            if self.runtime.protocol.protocol not in {"response", "tool_loop"}:
                raise ValueError("Use trial with scripted responses for dialogue or controller protocols")
            env = self.runtime.legacy_environment
            if env is not None and env.done:
                if args.get("final_answer") and args["final_answer"] != getattr(env, "final_answer", ""):
                    raise ValueError("Environment already ended; cannot replace the submitted answer")
            else:
                self.runtime.trial_submit(args.get("final_answer", ""))
            self.runtime.episode.termination = "reviewer_trial"
            self.runtime.emit("submission", "reviewer", args.get("final_answer", ""))
            self.runtime.finalize()
            result = {"metrics": [m.model_dump(mode="json") for m in self.runtime.evaluate()]}
        elif operation == "trial":
            if self.runtime.episode.outputs:
                raise ValueError("Reset before running a complete scripted trial")
            result = {"metrics": [m.model_dump(mode="json") for m in self.runtime.run_trial(args["responses"])]}
        else:
            raise ValueError(f"Unknown exploration operation: {operation}")
        if operation in {"evaluate", "trial"}:
            from ..execution.task_runtime import scalar_score
            self.runtime.require_valid_scoring()
            result["score"] = scalar_score(self.item, self.runtime.episode)
        self.save()
        return result if isinstance(result, dict) else {"result": result}

    def close(self):
        try:
            if self.workspace_trial:
                self.workspace_trial.close()
        finally:
            self.runtime.close()


def _experiment(item, config, target_id, directory):
    return (ContractExperiment if item.content is not None else TaskExperiment)(item, config, target_id, directory)


class LaajExploration:
    def __init__(self, suite: TaskSuite, analysis: AnalysisReport | None, config: BenchmarkConfig, directory: Path | None):
        self.suites = {0: suite}
        if analysis:
            self.suites.update({i.iteration: i.suite for i in analysis.iterations if i.suite is not None})
        self.config = config
        self.directory = directory
        self.sessions: dict[str, TaskExperiment] = {}

    def handle(self, call: ToolCall) -> ToolResult:
        args = call.arguments
        try:
            operation = args.get("operation")
            session_id = str(args.get("session_id") or "")
            if operation == "open":
                scope = args.get("scope", "main")
                if scope not in {"main", "probe"}:
                    raise ValueError("scope must be main or probe")
                iteration = int(args.get("iteration", 0)) if scope == "probe" else 0
                if scope == "probe" and iteration < 1:
                    raise ValueError("probe scope requires iteration >= 1")
                suite = self.suites.get(iteration)
                item = next((i for i in suite.tasks if i.id == args.get("item_id")), None) if suite else None
                if item is None or (item.task_type != TaskType.agent and item.content is None):
                    raise ValueError("Unknown agent task in the requested scope")
                session_id = uuid.uuid4().hex[:12]
                directory = self.directory / session_id if self.directory else None
                experiment = _experiment(item, self.config, str(args.get("target_id") or ""), directory)
                self.sessions[session_id] = experiment
                experiment.record.update(scope=scope, iteration=iteration)
                experiment.save()
                result = experiment.describe()
            else:
                experiment = self.sessions[session_id]
                if operation in {"reset", "close"}:
                    experiment.close()
                    del self.sessions[session_id]
                    if operation == "reset":
                        new_id = uuid.uuid4().hex[:12]
                        directory = self.directory / new_id if self.directory else None
                        replacement = _experiment(experiment.item, self.config, experiment.target.id if experiment.target else "", directory)
                        session_id = new_id
                        self.sessions[session_id] = replacement
                        replacement.record.update(
                            scope=experiment.record["scope"], iteration=experiment.record["iteration"],
                            reset_from=args["session_id"],
                        )
                        replacement.save()
                        result = replacement.describe()
                    else:
                        result = {"status": "closed"}
                else:
                    result = experiment.perform(args)
            return ToolResult(tool_call_id=call.id, name=call.name, content=json.dumps(
                redact_secrets({"session_id": session_id, **result}), ensure_ascii=False,
            ))
        except Exception as exc:
            return ToolResult(tool_call_id=call.id, name=call.name,
                              content=redact_secrets(f"{type(exc).__name__}: {exc}"), error="exploration_failed")

    def close(self):
        try:
            with ExitStack() as cleanup:
                for experiment in self.sessions.values():
                    cleanup.callback(experiment.close)
        finally:
            self.sessions.clear()
