# EvaluationClaw

EvaluationClaw is an automated evaluation framework for building model benchmarks
from natural-language goals.

It currently supports:

- Planner-driven `EvalSpec` and general `TaskBlueprint` generation from vague goals.
- **Deep research** (`--deep-research`): a bounded search→compress→reflect loop that
  turns a vague field into a structured `ResearchBrief` (taxonomy, existing benchmarks
  and their weaknesses, seed sources, challenge-effort anchors, citations) that grounds the
  planner and task builder.
- Pluggable web-search backends (`--search-backend auto|gemini|keyless|none`):
  Gemini Google-Search grounding when `GEMINI_API_KEY` is set, or a key-free
  combination of arXiv + Wikipedia + DuckDuckGo otherwise.
- One blueprint-driven construction route for multiple-choice, open-generation, code,
  multimodal, multi-turn, and environment-interaction tasks. Execution fields are optional.
- Self-generated benchmark tasks with optional web research, HuggingFace support, and
  programmatic local fallbacks.
- Deterministic and LLM-assisted QC gates with targeted task-slot repair.
- Direct model execution with rule scoring, code execution sandboxing, multi-turn tasks,
  simulated agent interaction tasks, and double-pass LLM judge audit.
- Loop 3 self-improvement that diagnoses QC/run results and regenerates targeted items.
- LiteLLM-backed provider calls with a protocol/adapter-only legacy fallback, including **Azure OpenAI**
  deployments via `azure/<deployment-name>` model names.
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

## Quick Start

Generate a benchmark draft without running target models:

```bash
python evalclaw_cli.py generate \
  -g "Evaluate strict format following" \
  --no-interactive \
  --no-research \
  --task-builder local \
  --scale-budget low \
  --qpd 1
```

Azure OpenAI end-to-end with deep research (vague field → researched benchmark → run):

```bash
python evalclaw_cli.py generate \
  -g "Evaluate LLM truthfulness and deception under pressure" \
  --orchestrator-model azure/gpt-5.5 \
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
  --orchestrator-model deepseek-v4-pro \
  -m deepseek-v4-flash \
  --no-interactive \
  --no-research \
  --scale-budget mid \
  --qpd 1 \
  --max-hf-records 1 \
  --runner direct \
  --llm-backend litellm
```

For faster smoke runs that still exercise Loop 3, use local diagnosis:

```bash
DEEPSEEK_API_KEY="..." python evalclaw_cli.py generate \
  -g "Evaluate agent planning, noisy tool correction, code reasoning, and calibration" \
  --orchestrator-model deepseek-v4-pro \
  -m deepseek-v4-flash \
  --no-interactive \
  --no-research \
  --qpd 1 \
  --runner direct \
  --llm-backend litellm \
  --single-pass-judge \
  --improve-iterations 1 \
  --loop3-diagnosis local \
  --loop3-max-actions 3
```

`--model`, `--compare`, and `--target-config` are optional. When none is
provided, EvalClaw plans, builds, QC-checks, and exports the benchmark without
running a target. Use `--no-run` when targets are configured but should be
recorded without being called in the current run.

### Custom endpoints and multiple targets

Each orchestration role can override the default model and connection with
`--planner-*`, `--task-builder-*`, `--qc-*`, `--judge-*`, `--research-*`, and
`--loop3-*`. Unspecified role fields fall back to the corresponding
`--orchestrator-*` setting. For example:

```bash
evalclaw generate \
  --planner-model claude-opus-4-6 \
  --task-builder-model claude-sonnet-4-6 \
  --qc-model gpt-5-mini \
  --judge-model gpt-5 \
  --research-model gemini-2.5-pro \
  --loop3-model claude-sonnet-4-6
```

When a role uses a different provider or endpoint, configure that role's
`--*-provider`, `--*-api-key`, and `--*-base-url` explicitly.

An Anthropic-compatible Claude/Claude Code endpoint can be used for the
orchestrator with its native `/v1/messages` protocol:

```bash
evalclaw generate \
  --orchestrator-model claude-sonnet-4-6 \
  --orchestrator-provider anthropic \
  --orchestrator-base-url https://claude-gateway.example/v1 \
  --api-key "$CLAUDE_GATEWAY_KEY"
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
- `research_brief.json` / `research_brief.md` - the deep-research brief (when `--deep-research`).
- `manifest.json` - machine-readable artifact index.
- `lm-eval/<task>.jsonl` - lm-eval dataset export.
- `lm-eval/<task>.yaml` - lm-eval task export.
- `lm-eval/<task>.metadata.json` - EvaluationClaw metadata.
- `lm-eval-results/<target>/...` - optional lm-eval-harness results.

## Notes

The direct runner is the source of truth for rubric-based open-generation tasks.
The lm-eval runner is currently an interoperability layer and works best for
standard exact-match or multiple-choice tasks unless a custom metric is added.
`agent_interaction` tasks run through the EvaluationClaw direct runner because
they require a stateful action/observation environment and deterministic
environment scoring.
Tasks that need interaction may optionally request built-in environments such as
`workspace`, `code_sandbox`, `docker_workspace`, `dialogue`, or `gui_desktop`.
Tasks that do not need an environment omit these fields entirely and still pass
through the same planner, builder, QC, execution, and reporting pipeline.
