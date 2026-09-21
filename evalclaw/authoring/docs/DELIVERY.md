Build a benchmark for the supplied evaluation request. Choose the task content,
interaction and grading appropriate to that request. These instructions specify
how to deliver your work, not how to design the tasks.

Deliver a directory containing `benchmark.json` and a directory for each task:

```json
{"format":"benchmark-package/v1","objective":"The supplied evaluation request","tasks":["task-01"]}
```

Each task directory contains `task.json` and the files it references. A task
with a single text prompt and a reference-based model judge can use:

```json
{"id":"task-01","prompt":"prompt.md","grading":{"method":"judge","answer_file":"answer.txt","rubric":"grading.md"}}
```

Write the actual input in `prompt.md`, a reference in `answer.txt`, and the
grading instructions in `grading.md`. Reference answers are optional for
methods that do not require one. The default grading metric is `score`, from
0 to 1, higher being better. A reference for a model judge is an example
unless you explicitly declare otherwise. Exact text or JSON comparison must
be explicitly selected; neither is inferred from the answer's appearance.

If the task needs other input messages, files, an environment, interaction
logic, or a grading program, consult `INTERFACES.md`. These interfaces can be
combined; they do not prescribe task categories. General programs can maintain
state, expose operations, request auxiliary model responses, control interaction,
and score recorded evidence. You do not need to describe these programs using
a task-design taxonomy.

Only explicitly public inputs and files reach the evaluated model. Other
package files remain available to reviewers. Declare how the model should
respond or submit its work in the task itself; the importer does not invent
submission instructions or modify the grading rules.

Use package-relative paths and include required source files. Supply binary
resources as files; archive directory trees when symbolic links are required.
Keep credentials outside the package. Runtime models and credentials are bound
by the experiment operator. The Codex process used to author the package is
separate from the model and interface used to answer its tasks.

Use `benchmark-package check PACKAGE` to receive structural errors. This does
not judge content quality or prove the environment works. For programs, supply
JSON call cases covering initialization, successful and unsuccessful operations,
and grading; `benchmark-package exercise PACKAGE CASES.json` runs these with the
same wire validation as the evaluator, without a target model. See the optional
manual for the case format. Use your normal development tools for content tests.
For a program-controlled interaction, also provide episode cases with scripted
target responses, including tool calls, to test the controller and environment
together. Component calls alone do not verify this connected protocol.
Declare obtainable runtime images or include image dependencies as described
in the manual; the operator prepares these with `benchmark-package prepare PACKAGE`.
The operator checks declared model compatibility with `check --config CONFIG.json`.
Unsupported features are reported explicitly, not rewritten into another task.
