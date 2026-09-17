# EvaluationClaw

EvaluationClaw is an automated evaluation framework for building model benchmarks
from natural-language goals.

It currently supports:

Deep Research is a Benchmark Design Research stage: it gathers evidence that can
change the requested benchmark's dimensions, difficulty factors, task patterns,
scoring, or source choices. It is not intended to produce a general field survey.

- Skill-driven `BenchmarkPlan` generation from vague goals: non-overlapping dimensions plus
  adaptive `family`/`archetype`/`per_task` Blueprints sized for one TaskBuilder call.
- **Deep research** (`--deep-research`): a bounded search→compress→reflect loop that
  produces a Benchmark Design Research `ResearchBrief` containing candidate dimensions,
  observable difficulty factors, task/scoring patterns, verified source recommendations,
  and design evidence for the requested evaluation. It is not a general field survey.
- Pluggable web-search backends (`--search-backend auto|gemini|keyless|none`):
  Gemini Google-Search grounding when `GEMINI_API_KEY` is set, or a key-free
  combination of arXiv + Wikipedia + DuckDuckGo otherwise.
- One blueprint-driven construction route for multiple-choice, open-generation, code,
  file-backed, multi-turn, and environment-interaction tasks. Execution fields are optional.
- Model-generated benchmark tasks with optional web research and HuggingFace support.
- Deterministic and LLM-assisted QC gates that replace only failed tasks and preserve
  QC-passed tasks from the same Blueprint.
- Direct model execution with rule scoring, code execution sandboxing, multi-turn tasks,
  simulated agent interaction tasks, and double-pass LLM judge audit.
- Optional post-run Analysis that diagnoses model weaknesses, recommends strengthening
  directions, and runs focused verification tasks when the main results are inconclusive.
- LiteLLM-backed standard model calls, including **Azure OpenAI** deployments via
  `azure/<deployment-name>` model names, plus explicit native protocol adapters where required.
- lm-eval-harness interoperability via generated JSONL/YAML artifacts and optional runner.
- Markdown reports with source coverage, canonical JSON packages, and artifact manifests.
- An A/B experiment harness under `experiments/` (baseline vs deep-research, plus a
  ranking-preservation check) with dataset-quality metrics.

## Environment

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # + extras as needed: .[datasets], .[lm-eval]
```

or with uv:

```bash
uv run --extra dev pytest -q
```

Copy `.env.example` to `.env` and fill in the keys for the providers you use.
Model-name → provider routing is automatic:

| Model name | Provider | Key env vars |
|---|---|---|
| `azure/<deployment>` | Azure OpenAI | `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` |
| `deepseek-*` | DeepSeek | `DEEPSEEK_API_KEY` |
| `gemini*` | Gemini (OpenAI-compatible) | `GEMINI_API_KEY` |
| `gpt-*`, `o1/o3/o4*` | OpenAI | `OPENAI_API_KEY` |
| `claude-*` (default) | Anthropic | `ANTHROPIC_API_KEY` |

For reasoning models (`gpt-5*`, `o1/o3/o4`, `deepseek-reasoner`) the completion budget
is raised automatically and truncated responses are retried; set
`EVALCLAW_REASONING_EFFORT=low` to cut latency and cost substantially.
Role-specific CLI options such as `--task-builder-reasoning-effort high` override this
global fallback for that framework role.

## ID Ownership

Canonical benchmark entity IDs are assigned by the framework. Planner and Task
Builder responses should provide content, not IDs for plans, dimensions,
TaskDesigns, tasks, resources, or choice options. Choice
answers use zero-based `correct_choice_indices`; the framework maps them to
canonical option IDs. IDs such as `item_id`, existing `dimension_id`,
`resource_ids`, and `task_model_id` remain references to objects already supplied
by the framework, not newly generated identities.

## Quick Start

Generate a benchmark draft without running target models:

```bash
ANTHROPIC_API_KEY="..." python evalclaw_cli.py generate \
  -g "Evaluate strict format following" \
  --planner-model claude-sonnet-4-6 \
  --task-builder-model claude-sonnet-4-6 \
  --no-interactive \
  --scale-budget low
```

Azure OpenAI end-to-end with deep research (vague field → researched benchmark → run):

```bash
python evalclaw_cli.py generate \
  -g "Evaluate LLM truthfulness and deception under pressure" \
  --planner-model azure/gpt-5.5 \
  --task-builder-model azure/gpt-5.5 \
  --research-model azure/gpt-5.5 \
  -m azure/gpt-4o \
  --deep-research \
  --search-backend keyless \
  --no-interactive \
  --scale-budget low
```

Use DeepSeek V4 Pro as the default orchestration model against DeepSeek V4 Flash:

```bash
DEEPSEEK_API_KEY="..." python evalclaw_cli.py generate \
  -g "Evaluate whether the model strictly follows specified output formats" \
  --planner-model deepseek-v4-pro \
  --task-builder-model deepseek-v4-pro \
  -m deepseek-v4-flash \
  --no-interactive \
  --scale-budget mid \
  --max-hf-records 1 \
  --runner direct \
  --llm-backend litellm
```

Analyse a completed target run and allow one round of focused verification tasks:

```bash
DEEPSEEK_API_KEY="..." python evalclaw_cli.py generate \
  -g "Evaluate agent planning, noisy tool correction, code reasoning, and calibration" \
  --planner-model deepseek-v4-pro \
  --task-builder-model deepseek-v4-pro \
  --analyser-model deepseek-v4-pro \
  -m deepseek-v4-flash \
  --no-interactive \
  --runner direct \
  --llm-backend litellm \
  --single-pass-judge \
  --analysis-iterations 1 \
  --analysis-max-tasks 3
```

`--model`, `--compare`, and `--target-config` are optional. When none is
provided, EvalClaw plans, builds, QC-checks, and exports the benchmark without
running a target. Use `--no-run` when targets are configured but should be
recorded without being called in the current run.

Interrupted runs can be continued with `--resume-run <run-id-or-directory>`.
The run directory keeps completed research, planning, construction, QC, and
execution checkpoints; provide the current role credentials again when
resuming. Omit `--goal` to use the goal recorded in the run.

Automatic source search and TaskBuilder web research are disabled by default;
enable them with `--web-research`. Explicit `--deep-research` is independent
and still runs its Benchmark Design Research search stage.

### Custom endpoints and multiple targets

Each model role has its own connection options. Planner and TaskBuilder roles
are required for the main pipeline; QC, LaaJ, Research, and the Analyser are optional.
LLM QC is enabled by default when a QC model is configured; use `--no-llm-qc` to disable it.
Use `--planner-*`, `--task-builder-*`, `--qc-*`, `--research-*`, and
`--analyser-*` to configure them independently. Configure `--laaj-*` to score
benchmark clarity, correctness, faithfulness, and diversity on a 1–5 scale; when
Analysis runs, it also scores systematicness and credibility. Task-specific judges and dialogue
simulators are selected with repeated `--task-model` or `--task-config` options.

Agent-task LaaJ can explore private environment copies, run terminal/native tools,
contact actors, and submit trial answers to the original evaluator. Target actions
use target permissions; privileged inspections are labelled as reviewer access.
Experiments and resets are saved under `debug/runs/<run>/laaj/exploration/` and do
not change target-run results. VM exploration requires a fresh VM specification;
shared desktops and multi-stage workflows remain available through saved evidence.
The pooled tool budget is 200 calls per sampled item plus each probe agent item,
with a minimum of 500 (`--laaj-tool-calls-per-item`). Analyser evidence reads allow
500 calls per decision/review (`--analyser-tool-max-calls`). Planner allows 500
calls, Builder 2000 per invocation; explicit configuration may increase either.
Builder sub-budgets allow 100 image builds, 500 image checks, 100 Docker/VM starts,
and 2000 Docker/VM commands per invocation. Actor interactions allow 200 model
turns, 500 tool calls, and 3600 seconds by default.

For scoring an agent's actual answer, a single-stage Docker task can declare
`environment.judge` with `mode: "judge"`, task-specific `instructions`, and
`criteria: [{id, rubric, weight}]`. Each rubric defines evidence requirements and
score anchors in [0,1]. The judge uses a configured `--task-model` (selected by
`metadata.task_model_id`) and can inspect a private copy of the completed task
filesystem plus recorded episode evidence. It has 500 tool calls by default
(`--agent-judge-tool-max-calls`). Scores, cited evidence, commands, outputs, and
model calls are saved in the episode's `judge/` directory.

`mode: "hybrid"` combines the weighted criterion score with `test_command` using
an explicit `script_weight`. `script_gate: true` forces zero unless the script
scores 1. Omitting `environment.judge` retains script scoring. Preflight exercises
the configured evaluator, including the judge when selected. Judge errors remain
evaluation errors. Review copies preserve filesystem permissions and directory
mounts, but not running processes, memory, or external network. Optional
`judge.setup_commands` can restart local services without resetting submitted
data. VM and multi-stage workflow judge scoring are not supported.

Builder resource tools read local UTF-8 text and PDFs, inspect ZIP/TAR members,
and extract selected files or entire archives (up to 64 files and 1 GiB per call).
Extraction preserves layout and executable permissions; returned paths work as
task assets or Docker build context sources. Documents, archive listings, web
page text, and retained Planner text support pagination. Local processing is
available without web research. PDF text extraction requires Poppler's
`pdftotext`; scanned-page OCR is not included.

LaaJ judges each sampled task in a separate conversation, scoring clarity,
correctness, and faithfulness together. Their reported scores are arithmetic
means with equal weight per task. Per-task scores and reasons are retained in
`laaj.item_results` and, when debug traces are enabled, `laaj/items/`.
Agent tasks retain private environment exploration. A separate overall judgment
scores diversity and, when analysis is available, the Analyser's systematicness
and credibility. Failed item judgments are retried; exhausted failures stop the
evaluation rather than becoming zero scores or disappearing from the average.
The main benchmark and every Analyser iteration receive separate quality and
contamination evaluations, both in standard runs and the similar-tasks ablation.
Iteration judgments use the original user goal and are stored in
`laaj.iteration_reports` and `analysis/iteration-NN/laaj.json`; their traces stay
inside the corresponding iteration directory. Completed round evaluations are
reused on resume. Analyser systematicness and credibility are evaluated once
for the complete analysis, and LaaJ scores do not feed back into construction.

With LaaJ configured, a separate contamination evaluation runs by default;
disable it with `--no-contamination`. It searches every constructed item unless
`--contamination-sample-size` sets a stratified sample. A research agent searches,
opens pages, follows static page links, downloads documents, and revises its
queries based on the evidence. It keeps looking after the first match and
records unresolved leads when it stops. Each item has a budget of 500 research
tool calls, at most 100 queries and 200 distinct source URLs, configurable with
`--contamination-max-tool-calls`, `--contamination-max-queries`, and
`--contamination-max-sources`. Search, navigation, inspection, and match
confirmation all consume the shared tool budget.
Search uses `--search-backend` (Gemini requires `GEMINI_API_KEY`), independently
of construction's `--web-research` switch. Gemini retries temporary connection
failures, timeouts, and HTTP 429/500/502/503/504 responses up to 8 total attempts,
using exponential backoff with jitter capped at 30 seconds. Configure these with
`GEMINI_SEARCH_MAX_ATTEMPTS` and `GEMINI_SEARCH_RETRY_MAX_DELAY_S`. It uses the
standard HTTP proxy environment variables and keeps TLS certificate verification
enabled. Failed searches retain the query, failure reason, attempt count, and
retryability in tool evidence; they are distinct from successful empty searches.
These settings also apply to Planner and Builder research.
The LaaJ model drives the research
agent and, in a separate call, judges confirmed overlaps on a 1–5 resistance
scale. Agent environment and file inspection tools are available at both stages.
Only contiguous passages verified against both the task and retrieved original
text qualify as overlap. The default minimum is 200 characters after whitespace
normalization (`--contamination-min-overlap-chars`); case and punctuation must
match exactly. Search-generated summaries alone do not qualify. Reports include the confirmed
overlap fraction, the mean score conditional on scored matches, and individual
search/inspection failures. Unmatched items receive no score. Research queries,
retrieved text, and model exchanges are retained under `contamination/` in the
debug run directory. Downloads support UTF-8 text, PDF (requires `pdftotext`),
ZIP and TAR; archives are read without extracting paths or executing contents.
Downloads are capped at 64 MiB, archives at 64 inspected members and 64 MiB read,
and each document at 100,000 extracted characters. Later portions of retained
text can be read in pages. Unreadable, truncated, dynamic, or inaccessible content
is reported as a coverage limitation. This measures observable reuse, not
training-data membership or an exhaustive search of the Internet.

For example:

```bash
evalclaw generate \
  --planner-model claude-opus-4-6 \
  --task-builder-model claude-sonnet-4-6 \
  --qc-model gpt-5-mini \
  --laaj-model gpt-5 \
  --task-model gpt-5 \
  --research-model gemini-2.5-pro \
  --analyser-model claude-sonnet-4-6 \
  --analysis-iterations 1
```

Paper ablations use `--ablation-authoritative-research` for restricted-source
research, `--no-web-research` for no research, and
`--ablation-no-builder-harness` for direct construction of the complete task
representation without Builder tools or repair feedback.
The similarity-based Analyzer baseline is selected with
`--ablation-analyser similar-tasks`; the default `none` is hypothesis-driven.

Restricted-source research uses curated benchmarks, Hugging Face datasets,
English Wikipedia, and arXiv throughout planning and construction. Planner and
Builder use catalog search and raw-content loading, retaining source identifiers
and original material instead of receiving an LLM-generated research summary.
Planner snapshots are available to Builder without refetching. Source discovery
remains demand-driven within these channels; this does not freeze a collection
of materials in advance. Ordinary runtime dependency installation remains available.

`--no-web-research` constructs generated tasks without external source material or
Builder-assistance URLs. It disables source search, reading, fetching, and downloading
during construction while retaining local construction tools and runtime dependency
installation. LaaJ contamination detection, when enabled, still performs its own searches.

When a role uses a different provider or endpoint, configure that role's
`--*-provider`, `--*-api-key`, and `--*-base-url` explicitly.

An Anthropic-compatible Claude/Claude Code endpoint can be used for any role
with its native `/v1/messages` protocol. Configure each required role explicitly:

```bash
evalclaw generate \
  --planner-model claude-sonnet-4-6 \
  --planner-provider anthropic \
  --planner-base-url https://claude-gateway.example/v1 \
  --planner-api-key "$CLAUDE_GATEWAY_KEY" \
  --task-builder-model claude-sonnet-4-6 \
  --task-builder-provider anthropic \
  --task-builder-base-url https://claude-gateway.example/v1 \
  --task-builder-api-key "$CLAUDE_GATEWAY_KEY"
```

For multiple targets with independent protocols, endpoints, and credentials,
repeat `--target-config`. Supplying this option replaces `--model` and
`--compare` target selection:

```bash
evalclaw generate \
  --target-config '{"id":"relay","model":"model-a","provider":"openai_compatible","base_url":"https://relay.example/v1","api_key_env":"RELAY_KEY"}' \
  --target-config '{"id":"claude","model":"claude-sonnet-4-6","protocol":"anthropic","base_url":"https://claude.example/v1","api_key_env":"CLAUDE_KEY"}'
```

Use `provider: "openai_compatible"` explicitly when a Claude-named model is
served by an OpenAI-compatible relay. Without that override, `claude*` models
with a custom base URL use the native Anthropic protocol.

### External agent harnesses

For an agent target, `harness` is part of the evaluated system, not an
implementation detail. Compare models with the same harness and tool-image
version when the goal is model comparison; different harnesses measure
different model-agent systems and are reported separately.

```bash
docker build -f docker/harness-runtime/Dockerfile -t evalclaw-harness-runtime:latest .
docker build -f docker/openclaw/Dockerfile -t evalclaw-openclaw:latest .
docker build -f docker/openhands/Dockerfile -t evalclaw-openhands:latest .
docker build -f docker/model-gateway/Dockerfile -t evalclaw-model-gateway:latest .

evalclaw generate \
  --target-config '{"id":"codex-gpt5","model":"gpt-5","provider":"openai","harness":"codex"}'
```

Manifest harnesses execute inside the task image; a separate `harness_image`
is mounted read-only only to provide the agent CLI. The runner records the
task, harness, and model-gateway image identities plus the harness manifest.
The model credential stays in the restricted egress gateway; the agent receives
only a gateway placeholder. Hidden evaluator files are injected only after the
agent exits. Trusted setup, non-privileged target execution, and trusted scoring
run sequentially in one task container, so container-local state remains available
to the evaluator without granting setup privileges to the target.
Unsupported contracts fail closed: external harnesses currently accept only
`docker_workspace` tasks rooted at `/workspace`, without browser/tool
restrictions, private `runtime_files`, or multi-stage workflows.
OpenHands is supplied through its dedicated tool image; invoking a host-installed
OpenHands CLI is intentionally unsupported because it cannot enforce task-image isolation.

Docker agent tasks may define environment roles under `environment.actors` and
reusable capability groups under `environment.actor_toolsets`. All external shell
harnesses access contacts through `python3 /run/evalclaw-contacts/contacts.py list`
and `python3 /run/evalclaw-contacts/contacts.py send CONTACT_ID 'message'`.
Actor task images must contain Python 3. Each actor
keeps an isolated conversation history, receives only its own public benchmark
system prompt and incoming messages, and can modify the shared workspace through
its configured tools. Configure
the single actor model used for a run with `--actor-model` and the corresponding
`--actor-provider`, `--actor-base-url`, and `--actor-api-key` options; per-interaction
limits use the `--actor-max-*` and `--actor-timeout` options. Actor definitions,
messages, tool calls, usage, and failures are saved under each run's `actors/`
artifacts, while credentials remain outside the task container.

## Experiments

`experiments/` contains a self-contained harness that validates the pipeline on real APIs:

```bash
python experiments/run_ab_deep_research.py --config experiments/config.json --smoke   # probe first
python experiments/run_ab_deep_research.py --config experiments/config.json          # full A/B
python experiments/run_ranking_check.py --package <evalclaw_*.json>                  # ranking check
```

Per-goal metrics (coverage/validity audits, semantic diversity, strong-vs-weak
discriminative gap, wall time) land in `experiments/results/`, with the run log
tee'd to `experiments/results/exp1_run.log`. See `experiments/README.md`.

## Outputs

Each run writes:

- `evalclaw_<timestamp>.json` - canonical EvaluationClaw package.
- `evalclaw_<timestamp>.md` - human-readable report.
- `tasks_<timestamp>.html` - standalone page for browsing the generated tasks.
- `research_brief.json` / `research_brief.md` - the deep-research brief (when `--deep-research`).
- `debug/runs/<run-id>/analysis/` - analysis conclusions and any independently
  constructed verification suites and runs (when an Analyser is configured).
- `debug/runs/<run-id>/laaj.json` - benchmark and Analyser quality scores (when
  a LaaJ model is configured).
- `manifest.json` - machine-readable artifact index.
- `lm-eval/<task>.jsonl` - lm-eval dataset export.
- `lm-eval/<task>.yaml` - lm-eval task export.
- `lm-eval/<task>.metadata.json` - EvaluationClaw metadata.
- `lm-eval-results/<target>/...` - optional lm-eval-harness results.

## Notes

When analysis ends, the Analyser returns its narrative and a benchmark grouped
by observed model weaknesses. Each group contains a name, a brief description,
and references to selected tasks and target results from the main run
(`iteration: 0`) or completed probe iterations. The selection must meet the
original evaluation need and exclude task or infrastructure defects. The
groups are saved in `analysis/report.json` and displayed in the reports.

The direct runner is the source of truth for rubric-based open-generation tasks.
The lm-eval runner is currently an interoperability layer and works best for
standard exact-match or multiple-choice tasks unless a custom metric is added.
`agent` tasks run through the EvaluationClaw direct runner because
they require a stateful action/observation environment and deterministic
environment scoring.
Agent tasks may use `docker_workspace` or `gui`. Multi-turn dialogue is
expressed through the task interaction contract rather than an agent environment.
Tasks that do not need an environment omit these fields entirely and still pass
through the same planner, builder, QC, execution, and reporting pipeline.
