# Dialogue Environment

Use runtime environment type `dialogue`.

- Put the complete target-visible role, scenario, and opening request in `prompt`. The runtime sends `prompt` as the first target turn, so do not rely on `initial_user_message` to supply separate target context.
- Put the other participant's private role, facts, elicitation policy, and non-disclosure rules in `system_prompt`; this is the task-specific dialogue simulator prompt, not the target's prompt.
- Return the exact task-level structure below for an adaptive dialogue.

```json
{
  "system_prompt": "Task-facing role and secrecy rules.",
  "environment": {"type": "dialogue"},
  "interaction": {
    "max_turns": 4,
    "followup_instruction": "Read the transcript and latest target reply, then generate one task-specific next turn.",
    "stop_condition": "Concrete terminal condition."
  }
}
```

- Set exactly one of `interaction.user_turns` and `interaction.followup_instruction`. For scripted tasks, `user_turns` must be a list of non-empty strings; do not rename it to `scripted_user_turns`, `turns`, or another alias, and do not place it inside `environment`. Use 1 to 5 follow-up turns and set `interaction.max_turns` between 1 and 5, matching the runtime bound.
- Follow the TaskDesign's `interaction_requirements.followup_mode`. For `adaptive`, provide a task-specific `system_prompt` and `followup_instruction`, and omit `user_turns`; the simulator must use the transcript and latest target reply to choose one next turn. For `scripted`, provide `user_turns` and omit `followup_instruction`.
- Keep the conversation horizon bounded and make success observable from the transcript.
- Define scoring that distinguishes full, partial, and failed handling of the interaction.
- Do not create files, VM configuration, or tool APIs unless another loaded reference requires them.
