# Executable Agent Task Package

EvaluationClaw derives canonical `metadata.agent_task_package` during packaging. Construct enough structured task and environment information for that package to be complete.

- Identify the measured capability and provide concise task content.
- Separate visible inputs, setup-only runtime material, and evaluator-only references.
- Define required outputs or expected artifacts, including paths, formats, and side-effect constraints.
- Provide deterministic setup, execution, and evaluation semantics with bounded timeout and steps.
- Define full, partial, and failure criteria on a normalized score range.
- State which artifacts, logs, screenshots, and tool traces must be retained.
- Specify required tools and forbidden shortcuts when process behavior matters.
- Record source kind, public source URIs, license requirements, and construction notes when relevant.
- Do not copy environment file contents or secrets into package-like metadata; the environment remains the sole executable state definition.
