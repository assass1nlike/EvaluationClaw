# Dialogue Environment

Use runtime environment type `dialogue`.

- Put the task-facing role and secrecy rules in `system_prompt`.
- Put a positive turn limit and either scripted user turns or a concrete follow-up policy in `interaction`; include the initial user message and stop condition when they differ from the task prompt and turn bound.
- Keep the conversation horizon bounded and make success observable from the transcript.
- Define scoring that distinguishes full, partial, and failed handling of the interaction.
- Do not create files, VM configuration, or tool APIs unless another loaded reference requires them.
