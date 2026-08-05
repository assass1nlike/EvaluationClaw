# Workspace Environment

Use runtime environment type `workspace`.

- Use this runtime only for EvaluationClaw's built-in room, object, inventory, and outgoing-bin interaction model. Use `code_sandbox` or `docker_workspace` for file or shell work.
- Put the complete state under `environment.workspace` using exactly this shape:

```json
{
  "environment": {
    "type": "workspace",
    "workspace": {
      "start_room": "office",
      "rooms": {
        "office": ["brief"],
        "mailroom": []
      },
      "item_descriptions": {
        "brief": "The document the target must inspect and deliver."
      },
      "goal": {
        "outgoing_bin": ["brief"]
      },
      "max_steps": 8
    }
  }
}
```

- `rooms` must be an object mapping room names to arrays of item ID strings. Do not use a room-object array, a separate `objects` array, or room `exits`; the built-in runtime makes every named room directly reachable.
- `goal.outgoing_bin` must be a non-empty array of item IDs, and every required item must appear in one of the `rooms` arrays. Include the `mailroom` required by the built-in `place` action.
- Use only the built-in look, move, inspect, take, place, and final actions. `environment.tools` cannot add custom behavior.
- Do not add files, shell setup, browser state, VM state, or evaluator commands; the runtime scores the final room/inventory/outgoing-bin state directly.
