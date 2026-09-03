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
are required for the main pipeline; QC, Research, and the Analyser are optional.
Use `--planner-*`, `--task-builder-*`, `--qc-*`, `--research-*`, and
`--analyser-*` to configure them independently. Task-specific judges and dialogue
simulators are selected with repeated `--task-model` or `--task-config` options.
For example:

```bash
evalclaw generate \
  --planner-model claude-opus-4-6 \
  --task-builder-model claude-sonnet-4-6 \
  --qc-model gpt-5-mini \
  --task-model gpt-5 \
  --research-model gemini-2.5-pro \
  --analyser-model claude-sonnet-4-6 \
  --analysis-iterations 1
```

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
- `manifest.json` - machine-readable artifact index.
- `lm-eval/<task>.jsonl` - lm-eval dataset export.
- `lm-eval/<task>.yaml` - lm-eval task export.
- `lm-eval/<task>.metadata.json` - EvaluationClaw metadata.
- `lm-eval-results/<target>/...` - optional lm-eval-harness results.

## Notes

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
