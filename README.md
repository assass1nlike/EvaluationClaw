# EvaluationClaw

EvaluationClaw is an automated evaluation framework for building model benchmarks
from natural-language goals.

It currently supports:

- Planner-driven `EvalSpec` generation from vague goals.
- Self-generated benchmark items with optional web research, HuggingFace dataset discovery,
  and lightweight HuggingFace row ingestion.
- Static and LLM-assisted QC gates.
- Direct model execution with rule scoring, code execution sandboxing, multi-turn tasks,
  simulated agent interaction tasks, and double-pass LLM judge audit.
- Loop 3 self-improvement that diagnoses QC/run results and regenerates targeted items.
- LiteLLM-backed provider calls with a legacy fallback.
- lm-eval-harness interoperability via generated JSONL/YAML artifacts and optional runner.
- Markdown reports with source coverage, canonical JSON packages, and artifact manifests.

## Environment

The project environment used during development is:

```bash
/zfspool/zangyihe/conda_envs/evalclaw/bin/python
```

Install optional runner dependencies with:

```bash
/zfspool/zangyihe/conda_envs/evalclaw/bin/pip install lm-eval
```

## Quick Start

Generate a benchmark draft without running target models:

```bash
/zfspool/zangyihe/conda_envs/evalclaw/bin/python evalclaw_cli.py generate \
  -g "Evaluate strict format following" \
  --no-interactive \
  --no-run \
  --no-research \
  --qpd 1
```

Run DeepSeek V4 Pro as planner/generator/QC/judge against DeepSeek V4 Flash:

```bash
DEEPSEEK_API_KEY="..." /zfspool/zangyihe/conda_envs/evalclaw/bin/python evalclaw_cli.py generate \
  -g "Evaluate whether the model strictly follows specified output formats" \
  --orchestrator-model deepseek-v4-pro \
  -m deepseek-v4-flash \
  --no-interactive \
  --no-research \
  --qpd 1 \
  --max-hf-records 1 \
  --runner direct \
  --llm-backend litellm
```

Run both EvaluationClaw direct judging and lm-eval-harness interoperability:

```bash
DEEPSEEK_API_KEY="..." /zfspool/zangyihe/conda_envs/evalclaw/bin/python evalclaw_cli.py generate \
  -g "Evaluate whether the model strictly follows specified output formats" \
  --orchestrator-model deepseek-v4-pro \
  -m deepseek-v4-flash \
  --no-interactive \
  --no-research \
  --qpd 1 \
  --runner auto \
  --llm-backend litellm
```

For faster smoke runs that still exercise Loop 3, use local diagnosis:

```bash
DEEPSEEK_API_KEY="..." /zfspool/zangyihe/conda_envs/evalclaw/bin/python evalclaw_cli.py generate \
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

## Outputs

Each run writes:

- `evalclaw_<timestamp>.json` - canonical EvaluationClaw package.
- `evalclaw_<timestamp>.md` - human-readable report.
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
The built-in agent environments currently include `workspace` for toy
state-manipulation tasks and `code_sandbox` for multi-step coding tasks where
the model writes files, runs tests, reads failures, and revises code.
