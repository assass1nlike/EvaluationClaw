# Propose-and-Amplify

Generates the task folders for an existing gym-anything environment.
This is the §4 pipeline from the CUA-World paper:

1. **propose** — an agentic Claude Code session reads the task creation
   notes, inspects the env, and writes a small set of hard, realistic
   seed tasks **directly into `<env>/tasks/`**. Three internal phases
   (read notes, create tasks, blind nudge) match the original driver
   one-for-one.
2. **amplify** — non-agentic Gemini expands the seeds into many more
   tasks. Three passes: a README pass that generates task spec
   markdown, a files pass that fills in `setup_task.sh` /
   `verifier.py` / `export_result.sh` / `README.md` for each spec, and
   a snapshot pass that records the generated task names into
   `<env>/tasks/seed_tasks.json` so subsequent amplify runs see them
   as seeds.
3. **extract** — the files-pass pickle is unpacked into final task
   folders under `<env>/tasks/`.

End-to-end takes a few hours per environment depending on
`--amplify-count`, the size of the env, and rate limits.

## Prerequisites

- **`gym-anything` installed** (`pip install -e ".[all]"`).
- **An environment already exists** under
  `benchmarks/cua_world/environments/<env_dir>/`. Build one with the
  `creation_audit` method if it doesn't.
- **Claude Code CLI** (`claude`) on `PATH` for the proposer. Set
  `CLAUDE_BIN` or pass `--claude-bin`.
- **Anthropic API key** (`ANTHROPIC_API_KEY`) — used by the files pass
  if you choose a Claude amplifier model. Not needed when amplifier is
  Gemini.
- **Gemini API key** (`GEMINI_API_KEY`) — used by the default amplifier.
- **The `visual_grounding` MCP server** if you want the proposer to
  verify task setup live; setup at
  `extras/research/software_as_env/creation_audit/mcp/`. The proposer
  prompt references it but the run will proceed without it.

## Quickstart

```bash
gym-anything-extras research task_generation propose_and_amplify \
    --software "Moodle" --env-dir moodle_env
```

What happens after you press enter:

1. **propose** — Claude Code opens a session, reads
   `memory/task_creation_notes/`, looks at the existing tasks under
   `moodle_env/tasks/`, and writes 5 new hard, realistic seed tasks
   directly to that folder. A blind nudge round catches anything
   skipped.
2. **amplify** — Gemini 3 Pro generates 75 more task specs (markdown),
   then runs a second pass to produce the implementation files for
   each. Outputs land as pickle files under
   `task_generation_runs/moodle_env/`. After both passes, the
   amplifier's generated task names are merged into
   `moodle_env/tasks/seed_tasks.json` for future runs to use as seeds.
3. **extract** — task folders are written under
   `benchmarks/cua_world/environments/moodle_env/tasks/`. Existing
   tasks (including the 5 seeds the proposer wrote) are preserved;
   pass `--overwrite` to replace them.

## Common variations

```bash
# Generate more tasks
... propose_and_amplify --software "Bahmni" --env-dir bahmni_env \
    --amplify-count 150

# Re-run only the amplify stage (e.g. after fixing a verifier template)
... propose_and_amplify --software "Moodle" --env-dir moodle_env \
    --stage amplify

# Use a different proposer model
... propose_and_amplify --software "Moodle" --env-dir moodle_env \
    --proposer-model opus

# Resume the proposer from phase 2 (after notes are read) of an
# earlier session
... propose_and_amplify --software "Moodle" --env-dir moodle_env \
    --propose-start-idx 1 --session-id <existing-session-uuid>
```

Run `... propose_and_amplify --help` for the full flag list.

## Output

- **`benchmarks/cua_world/environments/<env_dir>/tasks/<task_name>/`** —
  the task folders. Each contains `task.json`, `setup_task.sh`,
  `export_result.sh`, `verifier.py`, and `README.md`. They conform to
  the gym-anything `TaskSpec` contract.
- **`task_generation_runs/<env_dir>/`** — stage pickles and run logs.
  Re-running the pipeline picks up from these.

## After it finishes

```bash
# Validate every new task spec
gym-anything verify spec <env_dir>

# Run one of the new tasks live to sanity-check setup + verifier
gym-anything run <env_dir> --task <new_task_name> -i --open-vnc
```
