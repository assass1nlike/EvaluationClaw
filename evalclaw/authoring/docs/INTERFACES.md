All paths below are relative to the task directory. JSON keys outside the
documented interfaces are errors. Importing never runs your programs or calls
a model. UTF-8 text, whitespace and message order are preserved.

## Inputs and files

Use `prompt` for the path of one user message, or `messages` for an ordered
list. Each message has `role` (system, developer, user, assistant, tool) and
exactly one of `content` or `file`. Optional `name`, `tool_call_id`, and
`tool_calls` preserve native message associations. A tool call has `id`, `name`
and `arguments`. `origin` is `task` by default; use `seeded_context` for supplied
history or `prefill` for an externally supplied final assistant prefix.
Past conversations supplied for analysis belong in the input text, not in
the active message sequence.

`content` is text or an ordered list of blocks:

```json
[{"type":"text","text":"Read this material:\n"},
 {"type":"asset","asset_id":"document","presentation":"text"}]
```

Declare that resource in `files`:

```json
[{"id":"document","path":"document.txt","audience":["target"],"media_type":"text/plain"}]
```

An asset's `presentation` can be text, json or image. Text/JSON assets are
inserted without reformatting; separate text blocks are joined without an
invented separator. Images retain their bytes and media type. Inline blocks
also accept `type:json` with `data`, or `type:image` with base64 `data` and
`media_type`. Listing a file does not by itself insert it into a message.

File audience defaults to `["judge"]`. `target` grants the target access;
actor IDs grant named actors access. `mount` gives a relative destination
for workspace or program mounts. Programs receive only the assets listed in
their own `assets` declaration. All original files are retained for review;
review access does not grant target access. Duplicate public destinations and
public/private scoring-file collisions are invalid.

Optional task `stop` contains explicit generation stop strings. `operation`
defaults to `generate`; `continuation_likelihood` requires `continuations`.
These features require support in the selected model interface. Task `output`
can hold a submission description; only the documented runtime submission
protocol may introduce machine-rendered submission instructions. Normally put
all response requirements directly in your prompt.

## Workspace or custom environment

A shell workspace is declared with `workspace`:

```json
{"image":"python:3.11-slim","setup":[],"network":"none","workdir":"/workspace"}
```

Alternatively, supply `dockerfile` and `context` instead of `image`.
`dockerfile` is a file path inside the context directory; `context` defaults
to `.`. Image construction happens during runtime preparation, not import.
Keep private grading files outside a public Docker build context if its
Dockerfile copies the context into the target image.

Target-visible `files` are mounted into the workspace. `setup` commands run
before the target starts. `command_timeout` defaults to 120 seconds;
`max_steps` defaults to 500 for the native workspace loop. Set these explicitly
when appropriate. They do not replace an external harness's own limits.
`network` defaults to `none`; `bridge` enables outbound network access.

For workspace-state grading, declare `score_command` and optional
`private_files`, a list of task-relative UTF-8 source paths, for example
`["private/grade.py"]`. These files retain their relative paths under the
workspace; with workdir `/workspace`, the corresponding command is
`python3 /workspace/private/grade.py`. The evaluator runs on
a private copy after the episode, and prints `{"score":0.0}` as JSON.
It can read the preserved final workspace and `/evalclaw-evidence/episode.json`,
including target responses, tool trace and termination. Select grading method
`environment`. Private files are installed for grading, not target execution.
To grade binary resources, declare them as assets and use a grading program.

Private file placement does not make arbitrary grader code safe to execute
candidate code. Keep trusted checks outside candidate import paths: never put
a submitted directory ahead of private modules on sys.path or import a private
module by a name the candidate can shadow. Separate trusted checks from candidate
execution and compare observed outputs. If the task exposes only constrained
operations, a service keeps its implementation and scorer outside target access.
Include a negative test with incorrect output and a same-named candidate module
when testing a Python grader's import boundary. Arbitrary author programs are
not automatically protected from flaws in their own evaluation logic.

For other action interfaces, declare `service` as a program (below) instead
of `workspace`. The target receives only the tools returned by the service,
not shell access to its implementation. `initial_state` is passed unchanged.
`service_capabilities` may explicitly enable `inspect` or `checkpoint`.

## Programs

A `service`, interaction `driver`, or grading `program` uses this declaration:

```json
{"image":"python:3.11-slim","command":["python","-u","service.py"],
 "files":["service.py"],"version":"1"}
```

Programs run in their declared image with working directory `/component`.
Listed UTF-8 source files retain their relative paths. `benchmark_io.py` is
provided there automatically. Optional `assets` names declared file IDs;
their binary bytes appear at `/component/assets/<mount-or-id>`. `config` is an
arbitrary JSON object passed unchanged to each handler. `network` defaults to
false; `timeout_seconds` defaults to 300 per method call. Declare auxiliary
model roles in `model_roles` (`actor` or `judge`); models are configured by
the operator. Your program must not include model credentials.

Python handlers can use the dependency-free helper:

```python
from benchmark_io import serve

def initialize(params, config):
    return {"state": params.get("initial_state"), "tools": []}

def finalize(params, config):
    return {"state": None, "artifacts": {}}

def call_tool(params, config):
    raise ValueError("No tools registered")

serve({"initialize": initialize, "call_tool": call_tool, "finalize": finalize})
```

This illustrates transport only; implement your own state and operations.
Use `event(kind, data)` to record observations. `model(role, messages)` requests
an auxiliary model from within a handler and returns `content` and `raw`.
Model callbacks are synchronous and must run on the handler thread. Log to
stderr; stdout is reserved for protocol messages. Handler errors remain
execution errors, never valid zero scores.

Other languages use one JSON object per line on stdin/stdout:
request `{"id":"...","method":"...","params":{},"config":{}}`, response
`{"id":"...","result":{}}` or `{"id":"...","error":"..."}`.
Implement `describe` returning `{"version":"1","methods":[...]}`.
An event is `{"event":{"kind":"...","data":{}}}`. A model callback is
`{"id":"...","model_request":{"role":"actor","messages":[...]}}`;
its reply has the same ID and `model_result`. The Python helper handles these
envelopes; version defaults to `1` and must match the declaration.

To exercise the actual wire interface without a target model, write a JSON list:

```json
[{"task":"task-01","component":"environment","calls":[
  {"method":"initialize","params":{"initial_state":null,"seed":42}},
  {"method":"call_tool","params":{"name":"read","arguments":{"id":"missing"},"participant":"target"},
   "result_schema":{"required":["error"],"properties":{"error":{"type":"string"}}}}
]}]
```

Run `benchmark-package exercise PACKAGE CASES.json`. Components are named
`environment`, `controller`, or `grader-0`, `grader-1`, etc. in grading-rule
order; suite programs use task `@suite` and their aggregation ID. Each case
starts a fresh container; calls in a case share state. For score cases, supply
`params: {"episode": {...}}` using an exported episode or synthetic evidence.
The runner supplies the selected task object and the scorer's references using
the same payload builder as actual evaluation. Conflicting hand-written inputs
are rejected. Synthetic episodes may omit task_id, task_digest and defaulted
fields; supplied event records must follow the episode format below.
Score results are checked against the declared metric names, types and bounds.
Use `result_schema` to check the expected score, not just that metrics exist.
Callbacks to models are unavailable in these model-free cases. A passing report
covers only the supplied paths, not task correctness or untested branches.
No generated task, score or interface error is silently repaired.

Environment methods:

| Method | Input | Result |
| --- | --- | --- |
| initialize | initial_state, seed | state, tools, optional messages |
| call_tool | name, arguments, participant | content, optional error and user messages |
| finalize | episode | state, artifacts, optional artifact_files mapping names to container file paths |
| score | task, episode, references | metrics; required for environment grading |
| inspect | query, optional state and episode | reviewer observations; optional |
| checkpoint | empty object | opaque JSON snapshot; optional |
| restore | checkpoint | restore the declared snapshot; required with checkpoint |

Tool declarations use name, description and a JSON Schema `parameters`.
`call_tool` returns a JSON object. Its `content` is the target-visible result;
omit `error` or set it to null on success, and use a descriptive string on
failure (not a boolean). For example, `{"content":"Record saved"}` or
`{"content":"","error":"Permission denied"}`. Optional `messages` is a
list of user-message objects, each with `role:"user"` and `content`.
The service process persists across calls. Scoring uses a fresh process with
the recorded final state, so do not rely on the original service's memory.
Exported files are available to scorers under `/component/outputs/<name>`.
Inspection is privileged reviewer access, not a target tool. Initial input,
state, events, final outputs and scoring operations are recorded separately.

## Interaction

Without `interaction`, tasks receive one response, or an ordinary tool loop
when an environment is present. For scripted subsequent user messages use:

```json
{"turns":[{"role":"user","file":"followup.md"}],"reset_between_turns":false}
```

The preceding answer remains in history unless `reset_between_turns` is true.
Environment state persists across turns. For dynamic interaction, provide
`driver` (a program) or `instructions` (an auxiliary model's control policy),
not both. A driver implements `next(params, config)`, receives `events` since
its last call and its own `state`, and returns `state` plus a nonempty
`actions` list. Eventually return `{"action":"end"}`.

Declare allowed action names in interaction `actions`. Payloads are:

| Action | Fields |
| --- | --- |
| message | message |
| target | one model response; leaves requested tools pending |
| target_turn | a complete assistant turn, executing environment tools until the model responds without tool calls |
| execute_tool | call_id of a pending target call; executes it in the environment and delivers its result |
| tool_call | call containing id, name, arguments |
| tool_result | call_id, content, optional error |
| register_tools | tools |
| reset_session | session, messages |
| checkpoint | id, scopes |
| restore | id of a checkpoint |
| branch | id of a checkpoint, branch (new branch name) |
| actor | recipient (actor ID), message |
| end | no additional fields |

Use `target_turn` for ordinary work sessions. For intervention between individual
model responses, use `target`, inspect the returned `tool_call` events, then
`execute_tool` for each call ID before requesting another response. To simulate
a tool rather than execute it, use `tool_result`. `tool_call` is an independent
controller operation: it neither resolves a target call nor counts as target
work. All pending calls must be resolved before the next `target`/`target_turn`.
Both modes share the task's token, tool, request and time budgets. A reset
discards conversation and pending calls; it does not execute them.

For example, a program with `actions:["target_turn","end"]` can return
`{"state":1,"actions":[{"action":"target_turn"}]}` on its first call and
`{"state":2,"actions":[{"action":"end"}]}` on its next call. It receives
the entire turn's events on that next call. Use `message` or `reset_session`
followed by `target_turn` for subsequent sessions.

Test connected interaction with an episode case in the same `cases.json`:

```json
[{"task":"task-01","component":"episode","responses":[
  {"tool_calls":[{"id":"c1","name":"read_file","arguments":{"path":"input.txt"}}]},
  {"content":"Done"}
]}]
```

Replace these example responses with your own scripted interaction. The real
controller and environment execute with those responses instead of a target
model. Include follow-up sessions and resets when present. Missing/unused
responses, unresolved tools and protocol errors are reported with episode
evidence. `expected_termination` defaults to `completed`; it may instead be
`budget_exhausted`. Supply `usage.total_tokens` when testing a token budget.
Episode cases test interaction and finalization, not grading or task quality;
use component score cases for grading. They never invoke auxiliary models,
so model-controlled or actor-dependent paths need separate component tests.

Consult structural feedback for invalid action declarations. Conversation,
environment and actor snapshots are distinct scopes. Rollback retains the
full audit and does not refund budget. `observations` defaults to target,
task and runtime events; select the event origins needed by your controller.
For a model policy, `model_role` defaults to `actor`.

Optional `participants` declares actors using id, role=`actor`, system_prompt,
tools (names), visible_assets (IDs), history_scope (`session` or `episode`),
and model_role (`actor`). `actor_contact_tool` explicitly names the contact
tool offered to the target. Tools and file grants restrict access; role
instructions define behavior. Runtime capability checks report unsupported
participant/interface combinations.

Optional `interaction.budget` fields: target_calls, tool_calls, target_tokens,
wall_time_seconds, controller_calls, actor_calls, branches. Tool calls count
target invocations including failures, excluding other participants. Tokens
count reported target input plus output and are checked after responses;
remaining budget caps output generation. Wall time starts after preparation,
includes interaction with other participants, and excludes finalization and
grading. Transport retries do not count as new logical target requests.
Budget exhaustion and execution errors remain distinct episode outcomes.

## Grading and metrics

`grading` is one rule or a list of rules. Each rule declares `method`:

| Method | Required delivery |
| --- | --- |
| exact | answer or answer_file |
| json | answer or answer_file containing expected JSON |
| judge | instructions or rubric file |
| agent | instructions or rubric file; reviewer can explore the environment |
| program | program implementing score(params, config) |
| environment | environment's evaluator |
| aggregate | depends_on and weights for previously computed metrics |

`answer_file` is read as UTF-8 text unless `answer_format` is `json`. `answer`
is an inline JSON value. Supply only one. JSON matching parses the candidate;
text matching preserves case and whitespace unless `case_sensitive:false`
or `strip:true` is explicitly set. A list answer is one JSON value, not an
implicitly inferred set of acceptable answers. Use a program or explicit
judge instructions for other acceptance rules.

Optional `reference_is` is example, exhaustive or criterion. Exact/JSON
comparison uses exhaustive references. Other references default to example.
`reference_kind` can be answer, labels, trajectory, tests, state or rubric.
`response_view` defaults to generated; completed_message includes supplied
assistant prefill. Model graders receive the instructions and references
unchanged inside the fixed runner grading protocol.

Each rule defaults to one numeric metric named `score`, range [0,1], higher
being better. Use `name` to rename it, or `metrics` to supply definitions:
id, description, value_type (number/boolean/string/array/object), minimum,
maximum, direction (higher/lower/descriptive), and unit. Each metric must have
exactly one producer. Exact/JSON rules return 0/1 (or booleans); they do not
rescale the result. A workspace environment evaluator returns one [0,1] score.

Program score receives these JSON fields:

- `task`: the converted task object, not an ID string or the delivery's
  `task.json`. Read its identifier as `params["task"]["id"]`; public messages
  are in `task.content.messages` and scoring definitions in `task.evaluation`.
- `references`: a list of the current scorer's declared references, each with
  `id`, `kind`, `value`, `asset_ids`, and `semantics`. Read answer content from
  `value`. With no declared references this is `[]`, not an object.
- `episode`: recorded evidence as described below. Earlier grading events are
  excluded; `metrics` contains only the scorer's declared dependencies.
- `submission_contract`: included only when the task declares a structured
  submission contract.

It returns:

```json
{"metrics":[{"metric":"score","value":1,"status":"valid","reason":"...","evidence":[]}]}
```

Return exactly the rule's declared metric names. Status may instead be error
or not_applicable, with a reason. `reason` is a string; `evidence` is a list of
strings identifying evidence, not a list of objects. Both may be omitted.
The episode is an object containing task_id, task_digest, bindings, events,
initial_state, final_state, outputs, final_messages, artifacts, usage,
termination and metrics. `outputs` is a list of target responses;
`final_messages` is a list of message objects with role, content and optional
tool_calls. Initial and final state are the JSON values exported by the service.
Each event has id, index, kind, origin, session, branch, call_id, parent_id,
timestamp and data. For example, `event("read", {"path":"a.txt"})` from an
environment is recorded with kind `component_event`, origin `environment`,
and data `{"kind":"read","data":{"path":"a.txt"}}`.
A score program is independent of target privileges and receives the
recorded evidence; it must not pretend its own checks were target actions.

For multiple metrics, optional task `primary` selects metric, minimum,
maximum and direction for a scalar report. A sole bounded numeric metric is
selected automatically. There is no implicit averaging of different metrics.
An aggregate rule sums earlier metric values times explicitly supplied
weights. Its dependencies and weight keys must match.

Optional task `labels` is an arbitrary JSON object for reporting groups;
`tags` is a list of descriptive strings. Neither changes execution.

Optional benchmark `aggregation` contains suite metric definitions with id,
metric, aggregation (mean/sum/micro/program), optional group_by, and numerator /
denominator for micro aggregation. These aggregate native results and do not
change individual task scores. `group_by` names task label keys.
For `aggregation:program`, supply `program` using paths relative to the benchmark
root. It implements `aggregate(params, config)`, receiving tasks, results and
group labels. Referenced asset IDs must be unique across the benchmark.
Suite aggregation currently supports deterministic programs without auxiliary
model callbacks; importing a callback-dependent aggregator reports this limit.

## Execution support

Use publicly obtainable images, or declare local image dependencies in
benchmark.json, for example:

```json
{"images":[{"image":"my-runtime:local","source":"python:3.11-slim"}]}
```

Alternatively use `{"image":"my-runtime:local","dockerfile":"runtime/Dockerfile","context":"runtime"}`.
Paths are benchmark-relative and the Dockerfile must be inside its context.
`benchmark-package prepare PACKAGE` fetches the explicit source or builds the
included Dockerfile, prepares all required images, and prints image IDs for the
operator to save with the run. Use digest-pinned sources for stable dependencies.
Declared local aliases are never pulled from registries during task execution;
preparation must succeed first. Programs and workspaces can also set
`pull_image:false` for externally provisioned images. A README alone does not
provision an image. Preparation is separate from deterministic conversion.

The operator declares `supported_message_roles` per target in the run config,
based on that endpoint's supported roles. `check --config` reports undeclared
support as unverified and incompatible messages as unsupported. Dynamic model
requests are checked against the same declaration. Roles are never rewritten;
incompatible tasks must follow a predeclared experimental handling policy.

Static messages, tools, custom services/controllers, likelihood and prefill
are separate capabilities. The package does not force every task through a
shell harness. The operator must bind an interface supporting the declared
capabilities. Current shell-workspace bindings support one initial user text
message, ordinary tool use and scripted user follow-ups; custom native tool
services/controllers and native likelihood require direct model bindings.
Images require a compatible model. Missing support is an execution mismatch,
not a model failure and not a reason for the importer to alter your task.

This version supplies Docker workspaces and versioned custom programs. Desktop
or external services can be implemented behind those programs when available;
the package format does not provision a VM, GPU, or external account merely
because a task requests one. Input serialization is not a promise that every
backend can execute every possible digital task.
