Direct frontier-model authoring experiment.

The author receives the user's goal, requested count, DELIVERY.md, optional
INTERFACES.md, the transport helper and interface-check commands. It chooses
content, interaction and grading. There is no Planner, research stage, semantic
QC or target-performance feedback. Author-written tests may be repaired within
the same author session and budget. No human edits delivered tasks.

settings.json fixes goals, counts, model endpoints, reasoning, worker counts,
budgets, seed, native target role capabilities and quality metrics. Author,
task-model and LaaJ calls share a per-credential request spacing, including
retries and all concurrent processes. `request_spacing_seconds` defaults to
2.1. `key_pools` maps a role's credential environment variable to a list of
interchangeable credential environment variables for its endpoint. Requests
select the earliest available key; each actual key retains its own quota even
when multiple roles or environment-variable aliases use it. For two independent
keys capped at 50 RPM each, use 1.21-second spacing for a small timing margin.
Logs record the selected environment variable name, never the credential.
The shared gateway checks every reported response model against the requested
model before delivering output. Missing or inconsistent identities discard the
response and retry, with at most `model_identity_attempts` attempts (default 3).
Each attempt records reported identities and remains subject to the shared
rate limit. Streams are buffered until validation completes, so callers receive
output only after the full upstream response. Exhaustion returns an error.
This checks provider metadata; it cannot independently verify model weights.
evaluation_model selects the target; task_model selects actors, controllers,
graders and program model callbacks; laaj_model selects quality reviewers.
Each has a separate credential environment variable. If either auxiliary model
is omitted, it uses evaluation_model and evaluation_key_env for legacy configs.
The target calls its endpoint directly. Correctness and faithfulness are per
task; diversity compares the same sample. `laaj_sample_size` defaults to all
tasks; when set, sampling is uniform without replacement using the experiment
seed. `evaluation/laaj-sampling.json` records the population size and selected
IDs. Sampling never reduces the target's task set or filters by target results.
Contamination is optional and disabled in the acceptance pilot. No Analyser.

source/ and snapshot.json freeze executable code, author instructions, hashes,
author container image ID, Codex version and installed Python package versions.
The launcher detaches the coordinator into its own session. Evaluation workers
are separate processes sharing the configured memory admission budget. Source
and settings integrity are checked before execution. Secrets remain in process
environment variables; they are not part of the public configuration snapshot.

Each job keeps prompt.txt, codex.jsonl, author-result.json and the complete
work/package delivery. checks/ stores immutable submitted snapshots, check
requests, concrete interface feedback and image preparation results. These
checks have no target-model or LaaJ access. Program cases can cover successful
operations, recoverable tool errors and scoring; passing covers only tested
paths. Each author's gateway token is restricted to its own job.

After delivery, bundle/ preserves original bytes and deterministic conversion.
Evaluation prepares declared dependencies and pins the loaded runtime view to
image IDs; evaluation/prepared-suite.json and images.json record that binding.
The original bundle remains unchanged. Author cases are replayed if supplied;
failure is recorded without silently rewriting the task or selecting it out.
The target then answers compatible tasks. The LaaJ sampling population includes
all imported tasks, including tasks with unsupported target bindings.

Every requested job remains in summary.json, including author timeout, wrong
count, conversion failure, dependency preparation failure, incompatibility or
evaluation failure. Requested, generated, attempted and valid-scored counts are
separate. An author timeout is not relabeled a successful delivery even if its
partial package converts. Interface failures are not target wrong answers.
mean_score_valid_only is explicitly conditional on valid runs; report it beside
coverage and failure counts, never as accuracy over the requested benchmark.
Missing tasks, failed deliveries and execution errors remain in the experiment
accounting. No post-hoc manual repairs or replacement tasks are generated.

To inspect progress, read each job's status.json and the batch.log file. A final
summary.json marks coordinator completion. To run a new batch, set the
credential environment variables named in settings.json and launch from the
repository with an explicitly chosen new output directory:

```bash
.venv/bin/python -m evalclaw.authoring.batch start CONFIG.json OUTPUT_DIRECTORY
```

Use `freeze` instead of `start` to prepare a snapshot without running models.
The `proxy` setting is the shared author/task/LaaJ API route; null bypasses environment
proxies. `direct_hosts` extends NO_PROXY only in experiment subprocesses, e.g.
for a target endpoint reachable directly. These choices are part of the frozen
settings and do not change the machine's proxy configuration.

Old experiment directories are immutable evidence, not restart destinations.
