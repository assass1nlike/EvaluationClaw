# Workspace Environment

Use runtime environment type `workspace`.

- Use this runtime only for EvaluationClaw's built-in room, object, inventory, and outgoing-bin interaction model. Use `code_sandbox` or `docker_workspace` for file or shell work.
- Define non-empty rooms, include the `mailroom` required by the built-in `place` action, place every required goal item in a reachable room, and define a non-empty `goal.outgoing_bin`.
- Use only the built-in look, move, inspect, take, place, and final actions. `environment.tools` cannot add custom behavior.
- Do not add files, shell setup, browser state, VM state, or evaluator commands; the runtime scores the final room/inventory/outgoing-bin state directly.
