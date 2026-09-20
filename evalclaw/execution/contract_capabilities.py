"""One capability contract for planning, construction and execution."""
from __future__ import annotations

from ..protocols.task_definition import ServiceEnvironment
from ..protocols.tool_adapters import tool_adapter_for_target
from .harness_compatibility import external_harness_issues


def message_role_issues(messages, target):
    if target.supported_message_roles is None:
        return []
    roles = {m["role"] if isinstance(m, dict) else m.role for m in messages}
    unsupported = roles - set(target.supported_message_roles)
    return ([f"Target {target.id} does not support message roles: {', '.join(sorted(unsupported))}"]
            if unsupported else [])


def validate_message_roles(messages, target, system_prompt=None):
    supplied = [*messages, *([{"role": "system"}] if system_prompt else [])]
    issues = message_role_issues(supplied, target)
    if issues:
        raise ValueError("; ".join(issues))


def native_workflow_issues(task):
    if task.workflow is None:
        return []
    from ..protocols.submission import validate_output_contract
    issues = []
    environments = [task.environment, *[s.environment_spec for s in task.workflow.stages]]
    if any(env is not None and env.interventions for env in environments):
        issues.append("Legacy native workflows cannot execute environment interventions across checkpoints; use explicit dialogue or an external persistent workspace")
    contract = validate_output_contract(task.output_contract)
    if contract and contract.artifacts:
        issues.append("Legacy native workflow scorers do not consume the submission manifest; use explicit dialogue or an external workspace")
    return issues


def runtime_capabilities(config):
    return {
        "targets": [{"id": t.id, "harness": t.harness,
                     "native_messages": tool_adapter_for_target(t) in {"openai", "anthropic"} and config.llm_backend != "litellm",
                     "native_environment_protocols": ["response", "dialogue", "tool_loop", "program", "model"] if not t.harness and tool_adapter_for_target(t) in {"openai", "anthropic"} and config.llm_backend != "litellm" else [],
                     "optional_model_capabilities": t.capabilities,
                     "supported_message_roles": t.supported_message_roles} for t in config.targets],
        "explicit_shell_workspace": "Docker workspace, one initial user text message, response/tool_loop/dialogue. Dialogue has scripted user turns in a persistent workspace, with reset_between_turns for fresh conversations. Continuation requires a harness session command. No native participant/tool grants or controller. Existing environment actors and scorers are supported.",
        "tool_service": "Native bindings only; declare versioned initialize/call_tool/finalize/score methods. checkpoint/inspect are opt-in.",
        "participants": "Target and actor entries only. Use interaction.controller/controller_prompt for controllers; implement simulated services in the environment component.",
        "assets": "mount_path is a package-relative destination. writable=null leaves native behavior unchanged; explicit filesystem read-only grants are currently unsupported and are rejected. Text/image inputs are immutable requests.",
        "scoring": "Use evaluation exclusively for explicit tasks. Exact/JSON scorers require inline references; model scorers require instructions. Native metrics are preserved.",
        "scalar_required": bool(config.analyser_api_key),
    }


def binding_issues(task, config, target):
    issues = []
    protocol = task.interaction
    env = task.environment
    issues.extend(message_role_issues([*task.content.messages, *protocol.turns], target))
    if config.analyser_api_key and task.evaluation.scalar is None:
        issues.append("This run enables Analyzer: select evaluation.scalar before target execution")
    if target.harness and env is not None:
        if isinstance(env, ServiceEnvironment):
            issues.append("A shell harness cannot implement a native tool_service; select a native target binding")
        else:
            issues.extend(external_harness_issues(env.model_dump(mode="json"), [target.harness]))
        messages = task.content.messages
        if len(messages) != 1 or messages[0].role != "user" or messages[0].origin != "task" or messages[0].tool_calls or messages[0].name:
            issues.append("Shell workspace contracts require one user message; role histories must use a native binding")
        if protocol.protocol not in {"response", "tool_loop", "dialogue"} or protocol.participants or protocol.controller or protocol.actor_contact_tool:
            issues.append("Shell workspace contracts do not implement native participants or controllers; use environment actors or a native binding")
        if protocol.protocol == "dialogue" and not isinstance(env, ServiceEnvironment):
            if env.verification_cases:
                issues.append("CLI dialogue requires stage-aware verification; single-stage command verification_cases are unsupported")
            if any(m.role != "user" or m.origin != "task" or m.tool_calls or m.name for m in protocol.turns):
                issues.append("Shell workspace dialogue requires task-authored user turns")
            else:
                try:
                    from .harness_compatibility import external_workflow_issues
                    issues.extend(external_workflow_issues(
                        _dialogue_workflow(task, ["Input"] * (1 + len(protocol.turns))), [target.harness]))
                except ValueError as exc:
                    issues.append(str(exc))
        if task.content.stop or task.content.operation != "generate":
            issues.append("Shell workspace contracts cannot enforce stop sequences or continuation likelihood")
        if any(v is not None for k, v in protocol.budget.model_dump().items() if k != "wall_time_seconds"):
            issues.append("Shell workspace contracts support wall-time budgets only; native call/token budgets require a native binding")
        if task.evaluation.verification_cases:
            issues.append("Shell workspace verification uses environment.verification_cases; native scripted responses cannot impersonate CLI tool calls")
        if any(isinstance(m.content, list) and any(b.type == "image" or b.presentation == "image" for b in m.content) for m in [*messages, *protocol.turns]):
            issues.append("Shell workspace input must be text; place files in the workspace instead")
    elif tool_adapter_for_target(target) not in {"openai", "anthropic"} or config.llm_backend == "litellm":
        issues.append("Explicit message contracts require a direct OpenAI-compatible or Anthropic binding")
    if env is not None and not isinstance(env, ServiceEnvironment) and not target.harness:
        if env.actors:
            issues.append("Native contracts must put actors in interaction.participants; environment.actors requires an external shell harness")
        if env.budget:
            issues.append("Native contracts use interaction.budget, not the shell environment.budget")
    if env is not None:
        for asset in task.assets:
            if asset.writable is False and (isinstance(env, ServiceEnvironment) or "target" in asset.visibility):
                issues.append(f"Filesystem read-only asset {asset.id or asset.path} is not enforced by this backend; use immutable input content or a service tool permission")
    return issues


def _dialogue_workflow(task, prompts):
    from ..types import AgentWorkflow, WorkflowStage
    stages = [WorkflowStage(id=f"turn-{i}", kind="agent", prompt=p,
                context="fresh" if i == 0 or task.interaction.reset_between_turns else "continue",
                environment="fresh" if i == 0 else "reuse") for i, p in enumerate(prompts)]
    stages.append(WorkflowStage(id="score", kind="evaluate", environment="reuse"))
    return AgentWorkflow(stages=stages, score_stage="score")


def workspace_projection(task):
    """Derived CLI view; keep the canonical definition and score separately."""
    from ..construction.packaging import _environment_for_runner
    from ..types import BenchmarkItem, TaskType
    from .task_runtime import render_messages

    prompt = render_messages(task, task.content.messages)[0]["content"]
    if not isinstance(prompt, str):
        raise ValueError("Shell workspace input must render as text")
    item = BenchmarkItem.model_validate(task.model_dump(mode="json"))
    item = item.model_copy(update={"content": None, "evaluation": None, "interaction": {},
                                  "prompt": prompt, "task_type": TaskType.agent,
                                  "output_contract": task.content.output_contract})
    env = _environment_for_runner(task)
    wall = task.interaction.budget.wall_time_seconds
    if wall is not None:
        existing = (env.get("budget") or {}).get("wall_time_seconds")
        if existing is not None and existing != wall:
            raise ValueError("Conflicting environment and interaction wall-time budgets")
        env["budget"] = {"wall_time_seconds": wall}
    item.metadata = {**item.metadata, "agent_env": env}
    if task.interaction.protocol == "dialogue":
        prompts = [prompt, *[m["content"] for m in render_messages(task, task.interaction.turns)]]
        if any(not isinstance(p, str) for p in prompts):
            raise ValueError("Shell workspace dialogue must render as text")
        item.workflow = _dialogue_workflow(task, prompts)
    return item
