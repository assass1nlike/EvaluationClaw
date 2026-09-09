# EvalClaw Experiments

Plain-argparse scripts that reuse the `evalclaw` package in-process.

| Script | Question it answers |
| --- | --- |
| `run_ranking_check.py` | Does a generated benchmark preserve a publicly known strong>weak model ordering? (ranking sanity check) |

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
- `goals`: the vague evaluation goals under test.
- `scale_budget`: keep `low` until the smoke run looks sane.

## 3. Run smoke first

```bash
python experiments/run_ranking_check.py --smoke --config experiments/config.example.json
```

Smoke mode uses 1 goal and `low` scale budget. Check
`experiments/results/exp2_<slug>/report.md` to confirm the ranking check
actually executed.

## 4. Full run

```bash
python experiments/run_ranking_check.py --config experiments/config.example.json
```

## Outputs

```
experiments/results/
  exp2_<slug>/
    metrics.json
    report.md        # PASS/FAIL ranking verdict + gap
```

The ranking check runs the benchmark against a strong and a weak target model
and verifies that the strong model scores at least as well as the weak one.
