# EvalClaw Harness

EvalClaw Harness turns externally supplied task designs into a validated benchmark task package. It owns task construction, Builder tools, task packaging, static and optional LLM quality control, and executable agent-environment preflight. It does not plan evaluation goals, run target models, analyse failures, or produce evaluation reports.

The public request format is versioned and accepts task designs from a person or another framework. Builder and QC model credentials may be supplied directly or, preferably, by environment-variable name.

```bash
export BUILDER_API_KEY=...
evalclaw-harness build \
  --request harness/examples/request.json \
  --config harness/examples/config.json \
  --output-dir benchmark-output/harness-run
```

The run directory contains the redacted request and configuration, the task suite, QC report, combined result, and complete Builder/QC/preflight traces. A run directory with existing Harness artifacts is rejected to prevent accidental overwrites.

An existing task package can be checked independently:

```bash
evalclaw-harness validate \
  --suite path/to/suite.json \
  --config harness/examples/config.json \
  --output-dir benchmark-output/harness-validation
```

Python callers can use `evalclaw_harness.build(...)` and `evalclaw_harness.validate(...)` with the corresponding Pydantic models.
