"""Ordered stages inside a single evaluated agent item."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..diagnostics import error_record, new_debug_dir, write_json
from ..execution.agent_envs import build_agent_environment
from ..execution.workflow_state import (
    evaluate_environment,
    export_file,
    import_file,
    release_environment,
    restore_environment,
    save_environment,
)
from ..models.llm import call_target_model, call_target_model_with_tools
from ..protocols.task_agent import task_agent_system_prompt
from ..protocols.tool import ToolSpec, format_tool_specs_for_prompt, object_schema
from ..protocols.tool_adapters import tool_adapter_for_target
from ..types import BenchmarkConfig, BenchmarkItem, Message, TargetModelConfig, WorkflowStage
from .agent import _run_agent_interaction_json_actions, _run_agent_interaction_native_tools


class StageEnvironment:
    """Scope completion and evaluator feedback to one agent stage."""

    def __init__(self, env: Any, stage: WorkflowStage):
        self.env = env
        self.stage = stage
        self.max_steps = stage.max_steps
        self.steps = 0
        self.invalid_actions = 0
        self.done = False
        self.finished = False
        self.final_answer = ""
        env.steps = 0
        env.max_steps = stage.max_steps
        env.done = False
        if hasattr(env, "last_test"):
            env.last_test = None
        if hasattr(env, "last_evaluation"):
            env.last_evaluation = None

    def tool_specs(self) -> list[ToolSpec]:
        excluded = {"final"}
        if not self.stage.allow_evaluation_feedback:
            excluded.update({"run_tests", "run_test", "evaluate"})
        return [tool for tool in self.env.tool_specs() if tool.name not in excluded] + [
            ToolSpec(name="final", description="Finish the current stage and return its output.",
                     parameters=object_schema({"answer": {"type": "string"}}, required=["answer"]))
        ]

    def action_schema(self) -> str:
        return format_tool_specs_for_prompt(self.tool_specs())

    def observation(self) -> str:
        # Evaluation stage results are private; only explicit inputs may expose them.
        return self.env.observation()

    def step(self, action: dict[str, Any]) -> Any:
        from types import SimpleNamespace

        self.steps += 1
        if action["action"] == "final":
            self.final_answer = action.get("args", {}).get("answer", "")
            self.done = self.finished = True
            return SimpleNamespace(observation="Stage completed.", error=None, done=True)
        self.env.steps = self.steps - 1
        self.env.done = False
        outcome = self.env.step(action)
        self.invalid_actions = self.env.invalid_actions
        # A passing intermediate test does not submit the stage's output.
        self.done = self.steps >= self.max_steps
        return SimpleNamespace(observation=outcome.observation, error=outcome.error, done=self.done)

    def score(self) -> float:
        return self.env.score() if self.stage.allow_evaluation_feedback else 0.0

    def state(self) -> dict[str, Any]:
        return {**self.env.state(), "stage_id": self.stage.id, "stage_steps": self.steps,
                "done": self.done, "output": self.final_answer}

    def summary(self) -> str:
        return f"stage={self.stage.id}; steps={self.steps}/{self.max_steps}"


def stage_item(item: BenchmarkItem, stage: WorkflowStage) -> BenchmarkItem:
    metadata = copy.deepcopy(item.metadata)
    if stage.environment_spec is not None:
        metadata["agent_env"] = stage.environment_spec.model_dump(mode="json")
    # Only the current stage's public prompt is sent to the target.
    metadata["task_agent"] = {"system_prompt": stage.system_prompt or task_agent_system_prompt(item, "You are the target agent.")}
    return item.model_copy(update={"workflow": None, "prompt": stage.prompt, "metadata": metadata})


def _configure_evaluator(env: Any, stage: WorkflowStage, base: dict[str, Any]) -> None:
    if hasattr(env, "test_command"):
        env.test_command = stage.test_command or base.get("test_command", "")
        env.evaluation = stage.evaluation or base.get("evaluation", {})
    else:
        env.evaluation_config = stage.evaluation or base.get("evaluation", {})


def _stage_prompt(stage: WorkflowStage, results: dict[str, Any]) -> str:
    inputs = [{"stage_id": ref.stage_id, "field": ref.field,
               "value": results[ref.stage_id][ref.field]} for ref in stage.inputs]
    return stage.prompt + ("\n\nStage inputs:\n" + json.dumps(inputs, ensure_ascii=False) if inputs else "")


def _save_checkpoint(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    write_json(temporary, value)
    os.replace(temporary, path)


def run_workflow(
    item: BenchmarkItem, target: TargetModelConfig, config: BenchmarkConfig, *,
    artifact_dir: Path | None = None,
) -> tuple[str, float, str]:
    workflow = item.workflow
    assert workflow is not None
    root = artifact_dir or new_debug_dir(config.output_dir, "workflow")
    if root is None:
        raise ValueError("Workflow execution requires an output directory for stage checkpoints.")
    root.mkdir(parents=True, exist_ok=True)
    identity = {"item": item.model_dump(mode="json"),
                "target": target.model_dump(mode="json", exclude={"api_key"}), "backend": config.llm_backend}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    checkpoint_path = root / "workflow-checkpoint.json"
    checkpoint: dict[str, Any] = {
        "fingerprint": fingerprint, "results": {}, "messages": [], "environment": None,
        "environment_config": {}, "resume_commands": [],
    }
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint["fingerprint"] != fingerprint:
            raise ValueError("Workflow checkpoint belongs to a different task or target configuration.")
    results = checkpoint["results"]
    native = tool_adapter_for_target(target) in {"openai", "anthropic"}
    messages = copy.deepcopy(checkpoint["messages"])
    if not native:
        messages = [Message.model_validate(message) for message in messages]
    env = None
    successful = False
    stage = None
    try:
        for index, stage in enumerate(workflow.stages):
            if stage.id in results:
                continue
            stage_dir = root / "stages" / stage.id
            stage_dir.mkdir(parents=True, exist_ok=True)
            write_json(stage_dir / "input.json", stage.model_dump(mode="json"))
            if stage.kind != "evaluate" and stage.context == "fresh":
                messages = []
            if stage.kind != "text":
                if stage.environment == "fresh":
                    if env is not None:
                        release_environment(env, keep_checkpoint=False)
                    env = build_agent_environment(stage_item(item, stage), config)
                    checkpoint["environment_config"] = copy.deepcopy(
                        stage_item(item, stage).metadata["agent_env"]
                    )
                    checkpoint["resume_commands"] = stage.resume_commands
                elif env is None:
                    env = restore_environment(checkpoint["environment"], config)
                    for command in checkpoint["resume_commands"]:
                        if hasattr(env, "_exec_shell"):
                            env._require_ok(env._exec_shell(command), "resume command")
                        else:
                            raise ValueError("resume_commands apply to Docker filesystem checkpoints only.")
                for ref in stage.files:
                    import_file(env, Path(results[ref.stage_id]["files"][ref.path]), ref.destination)
                _configure_evaluator(env, stage, checkpoint["environment_config"])
            output = ""
            evaluation = None
            trace: Any = []
            if stage.kind == "agent":
                scoped = StageEnvironment(env, stage)
                current = stage_item(item, stage).model_copy(update={"prompt": _stage_prompt(stage, results)})
                run = _run_agent_interaction_native_tools if native else _run_agent_interaction_json_actions
                raw, _, _ = run(current, target, config, artifact_dir=stage_dir,
                                environment=scoped, messages=messages, max_tokens=stage.max_tokens)
                trace = json.loads(raw)["trace"]
                if not scoped.finished:
                    raise RuntimeError(f"Workflow stage {stage.id} did not finish within its tool budget.")
                output = scoped.final_answer
            elif stage.kind == "text":
                prompt = _stage_prompt(stage, results)
                system = stage.system_prompt or "Produce the requested stage output."
                if native:
                    messages.append({"role": "user", "content": prompt})
                    response = call_target_model_with_tools(
                        messages, target, [], system_prompt=system, backend=config.llm_backend,
                        max_tokens=stage.max_tokens, trace_dir=stage_dir / "llm",
                    )
                    if response.tool_calls:
                        raise ValueError("Text stage returned a tool call without available tools.")
                    messages.append(response.assistant_message)
                    output = response.content
                else:
                    output = call_target_model(
                        prompt, target, system_prompt=system, history=messages, backend=config.llm_backend,
                        max_tokens=stage.max_tokens, trace_dir=stage_dir / "llm",
                    )
                    messages.extend([Message(role="user", content=prompt), Message(role="assistant", content=output)])
                if not output.strip():
                    raise ValueError(f"Text stage {stage.id} returned empty output.")
            else:
                evaluation = evaluate_environment(env, results)
            files: dict[str, str] = {}
            for file_index, guest_path in enumerate(stage.output_files):
                destination = stage_dir / "files" / str(file_index)
                export_file(env, guest_path, destination)
                files[guest_path] = str(destination.resolve())
            result = {"output": output, "transcript": trace, "evaluation": evaluation, "files": files}
            if stage.kind == "text":
                result["transcript"] = [{"role": "user", "content": prompt}, {"role": "assistant", "content": output}]
            write_json(stage_dir / "result.json", result)
            next_environment_stage = next((s for s in workflow.stages[index + 1:] if s.kind != "text"), None)
            if stage.kind != "text":
                checkpoint["environment"] = (
                    save_environment(env, stage_dir)
                    if next_environment_stage is not None and next_environment_stage.environment == "reuse"
                    else None
                )
            results[stage.id] = result
            checkpoint["messages"] = messages if native else [m.model_dump(mode="json") for m in messages]
            _save_checkpoint(checkpoint_path, checkpoint)
        scores = {s.id: float(results[s.id]["evaluation"]["score"])
                  for s in workflow.stages if s.kind == "evaluate"}
        metrics = {}
        for name, metric in workflow.metrics.items():
            values = [scores[ref] for ref in metric.stages]
            metrics[name] = values[0] - values[1] if metric.operation == "difference" else sum(values) / len(values)
        raw = {"stages": results, "stage_scores": scores, "metrics": metrics}
        write_json(root / "workflow-result.json", raw)
        successful = True
        return json.dumps(raw, ensure_ascii=False), scores[workflow.score_stage], json.dumps({"stage_scores": scores, "metrics": metrics})
    except BaseException as exc:
        write_json(root / "workflow-error.json", {"stage_id": stage.id if stage else None, **error_record(exc)})
        raise
    finally:
        if env is not None:
            release_environment(env, keep_checkpoint=not successful and checkpoint["environment"] is not None)
