# Dialogue Environment

Use runtime environment type `dialogue`.

- Put the task-facing role and secrecy rules in `system_prompt`.
- Return the exact task-level structure below. `user_turns` must be a list of non-empty strings; do not rename it to `scripted_user_turns`, `turns`, or another alias, and do not place it inside `environment`.

```json
{
  "system_prompt": "Task-facing role and secrecy rules.",
  "environment": {"type": "dialogue"},
  "interaction": {
    "max_turns": 4,
    "initial_user_message": "Optional first user turn; otherwise the task prompt is used.",
    "user_turns": ["First scripted follow-up.", "Second scripted follow-up."],
    "followup_instruction": "Use this instead of user_turns only when follow-ups must adapt to the transcript.",
    "stop_condition": "Concrete terminal condition."
  }
}
```

- Set exactly one of `interaction.user_turns` and `interaction.followup_instruction`. Use 1 to 5 follow-up turns and set `interaction.max_turns` between 1 and 5, matching the runtime bound; include the initial user message and stop condition when they differ from the task prompt and turn bound.
- Keep the conversation horizon bounded and make success observable from the transcript.
- Define scoring that distinguishes full, partial, and failed handling of the interaction.
- Do not create files, VM configuration, or tool APIs unless another loaded reference requires them.
