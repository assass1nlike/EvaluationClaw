---
name: build-environment-tasks
description: Construct agent benchmark tasks that require container, browser, desktop, VM, or other executable environments. Use only for TaskDesigns with non-empty environment requirements.
---

# Build Environment-Backed Tasks

Implement only the environment capabilities requested by each TaskDesign. The runtime supplies a routing table that maps TaskDesign IDs to the references loaded for them. Apply a reference only to the listed TaskDesigns.

For every environment-backed task:

- Return an `environment` object using the runtime environment type in the routing table.
- Implement every TaskDesign-required input, fixture, initial-state property, action capability, output, and scoring check; do not merely describe what another system is assumed to provide.
- Make the initial state, permitted actions, completion condition, and scoring oracle executable and mutually consistent.
- If a required repair needs administrator, owner, privileged service, or delegated access, provision a concrete target-visible elevation or authorization path scoped to that repair. Do not assign a required privileged action to an account that cannot perform it.
- Use only actions and setup mechanisms the selected EvaluationClaw runtime actually exposes. Never invent a custom tool or provisioning path that exists only in prose.
- Represent task-specific setup through structured files, commands, provisioning, session state, or a concrete runner-resolvable prebuilt artifact. Keep descriptive explanation separate from image, template, snapshot, path, command, and tool identifiers.
- When a clean/default environment is sufficient, say so through the concrete launch state and do not add unnecessary setup. When non-default hidden or mutable state is required, provide both its setup or prebuilt-state reference and a baseline check that can establish it before the target starts.
- Populate only fields required by the TaskDesign and its loaded references.
- Keep target-visible inputs separate from setup-only material and evaluator-only material.
- Never expose hidden tests, reference answers, evaluator secrets, bridge credentials, or provider credentials.
- Prefer deterministic state, artifact, test, or trajectory checks over vague judge-only scoring when the environment permits them.
- Ensure the evaluator consumes the target's actual final answer, artifacts, state, or trajectory. It must not create, repair, or substitute for the work being scored.
- Keep task-specific files and state in structured fields rather than embedding them in long prompts.
- Put files that belong to the environment's declared initial visible state in `visible_files`. Treat top-level asset paths as framework-private host locations for task-input files created or downloaded during construction; for container tasks, refer to each asset only by its filename in target-visible fields because the framework copies it into the runtime workdir.
- Make every generated setup and evaluation command internally exact: create required parent objects before using them, keep paths/identifiers/values byte-consistent across setup, baseline, prompt, and evaluation, and ensure commands work from the declared clean base rather than an assumed intermediate state.
- Ensure every evaluation condition is attainable from the target-visible instructions and executable fixture. Do not require an undisclosed arbitrary value, invocation mode, artifact, or event that neither the environment nor the compliant workflow can produce.
- When an evaluator creates fresh probes with unique identifiers, bind every relevant assertion to those exact identifiers; do not scan for any matching pre-existing artifact or event.
- The runner records the agent trajectory for audit, but generic environment scoring does not automatically judge or weight that trace. Do not assign score weight to diagnosis order, tool choice, or other trajectory behavior unless the selected runtime exposes a concrete executable trajectory check. Keep unsupported trajectory expectations qualitative and non-scoring.
- When several artifact paths are alternatives, list the candidate paths and set `artifact_requirement` to `any` or `exactly_one`; the default `all` means every listed artifact is required.

Before returning, trace every TaskDesign requirement through the concrete task and verify this chain is complete: initial state -> exposed observations/actions -> target-produced result -> evaluator evidence -> score. If the runtime cannot realize a required link, do not claim the task is complete or hide the gap in `construction_notes`.

EvaluationClaw derives canonical `metadata.agent_env`, `metadata.task_agent`, and `metadata.agent_task_package` records from the returned task fields during packaging. Do not duplicate those protocol objects manually unless the TaskDesign explicitly requires a protocol extension that cannot be expressed through `environment`, `system_prompt`, `interaction`, `scoring`, or ordinary task metadata.

Read only the references selected by the runtime:

- `references/docker-workspace.md`
- `references/gui.md`
- `references/task-agent.md`
- `references/agent-task-package.md`
