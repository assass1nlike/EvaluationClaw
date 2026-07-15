# Task-Agent Interaction Contract

Use `system_prompt` and `interaction` to describe task-specific agent behavior. EvaluationClaw packages them into canonical `metadata.task_agent`.

- Keep `system_prompt` concise: role, non-disclosure rules, and high-level turn policy only.
- Put initial files, scenario state, session configuration, evaluator rules, and large structured content in their dedicated fields.
- For multi-turn tasks, use the exact `interaction` fields `initial_user_message`, `max_turns`, `user_turns` (a list of strings) or `followup_instruction`, and `stop_condition`. Do not invent aliases or nest these fields under `environment`.
- Make interaction scoring inspect the relevant transcript, state, artifact, or tool trace.
- Do not describe a code sandbox or workspace controller as a conversational helper when the target itself is meant to operate the environment.
