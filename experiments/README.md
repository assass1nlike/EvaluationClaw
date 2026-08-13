# EvalClaw Experiments

Validation harness for the deep-research upgrade (plan section "P2. 实验验证").
Two experiments, both plain argparse scripts that reuse the `evalclaw` package
in-process:

| Script | Question it answers |
| --- | --- |
| `run_ab_deep_research.py` | Does `--deep-research` produce better benchmarks than the baseline single-shot research path? (Experiment 1, A/B) |
| `run_ranking_check.py` | Does a generated benchmark preserve a publicly known strong>weak model ordering? (Experiment 2, ranking sanity check) |

## 1. Set credentials

Copy the repo-root `.env.example` and export the variables you have. For an
Azure-only setup:

```bash
export AZURE_API_KEY=...                                   # or AZURE_OPENAI_API_KEY
export AZURE_API_BASE=https://<your-resource>.openai.azure.com
export AZURE_API_VERSION=2024-06-01
```

Optional: `GEMINI_API_KEY` enables the Gemini search backend (otherwise the
free keyless backend — arXiv + Wikipedia + DuckDuckGo — is used automatically).

Planner and TaskBuilder credentials are required; benchmark construction fails
closed when their model calls are unavailable. Optional audits and embedding
metrics may still be skipped when their role-specific credentials are absent.

## 2. Fill the config

Copy `config.example.json` (or edit it in place) and set your deployment names:

- `role_model` / `strong_target` / `weak_target`: use `azure/<deployment-name>`
  (e.g. `azure/gpt-4o`, `azure/gpt-4o-mini`). Any provider the evalclaw CLI
  supports works here (`gpt-*`, `claude-*`, `deepseek-*`, `gemini*`).
- `embedding_model`: optional Azure embedding deployment
  (e.g. `azure/text-embedding-3-small`) for the semantic-diversity metric;
  set to `null` to use the token-Jaccard fallback.
- `goals`: the vague evaluation goals under test (defaults to the plan's three).
- `scale_budget`: keep `low` until the smoke run looks sane.

## 3. Run smoke first

```bash
python experiments/run_ab_deep_research.py --smoke --config experiments/config.example.json
python experiments/run_ranking_check.py --smoke --config experiments/config.example.json
```

Smoke mode uses 1 goal, `low` scale budget, 1 deep-research iteration, and
minimal audit samples. Check `experiments/results/exp1_<slug>/report.md`: wall
time, LLM call counts, and that audits/runner actually executed (not
`skipped`). This is the cheap connectivity + cost-magnitude probe before
scaling up.

## 4. Full runs

```bash
python experiments/run_ab_deep_research.py --config experiments/config.example.json
python experiments/run_ranking_check.py --config experiments/config.example.json
# Reuse a benchmark produced by experiment 1 for the ranking check:
python experiments/run_ranking_check.py --package experiments/results/exp1_<slug>/deep_research/evalclaw_<ts>.json
```

## Outputs

```
experiments/results/
  exp1_<goal-slug>/
    baseline/        # full EvalClaw package for the baseline run
    deep_research/   # full EvalClaw package incl. research_brief.json/md
    metrics.json     # all comparison metrics
    report.md        # human-readable A/B comparison
  exp2_<slug>/
    metrics.json
    report.md        # PASS/FAIL ranking verdict + gap
```

Metrics in experiment 1: dimension-coverage/relevance LLM audit (1–5), item
validity rate (LLM audit on a stratified sample), semantic diversity (mean
pairwise cosine distance via the embedding deployment, Jaccard fallback),
discriminative power (strong-vs-weak average score gap), and cost proxies
(wall time per stage + LiteLLM/httpx call counts; the direct runner does not
capture tokens).

## Expected cost (order of magnitude)

- Smoke (`--smoke`, low budget, 1 goal, 2 variants): roughly 20–60 LLM calls
  with short prompts — typically well under $1 on gpt-4o-class deployments.
- Full (3 goals × 2 variants, low budget + audits + both targets): a few
  hundred LLM calls — single-digit dollars. Raise `scale_budget` to `mid` only
  after reviewing the low-budget reports; cost scales roughly linearly with
  item count.
