# Code Sandbox Environment

Use runtime environment type `code_sandbox`.

- Put starter code and target-visible fixtures in `visible_files` when the task needs them; an empty mapping is valid for a create-from-scratch task.
- Put setup-only fixtures in `runtime_files` and hidden tests in `hidden_files`.
- Provide the exact deterministic `test_command` the runner must invoke.
- Keep hidden tests out of the prompt, visible files, setup commands, and task-visible tool output.
- Make the requested code change and the evaluator agree on paths, APIs, dependencies, and expected behavior.
- Prefer the minimal runtime needed for the task; use Docker workspace only when OS packages, non-Python runtimes, services, or native builds are genuinely required.
