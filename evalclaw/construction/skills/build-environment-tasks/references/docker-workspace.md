# Docker Workspace Environment

Use runtime environment type `docker_workspace`.

- Choose a suitable common image, use `image: "auto"`, or define `image_build` only when a common image is insufficient.
- Put target-visible files that are part of the declared initial environment in `visible_files`, setup-only server/application material in `runtime_files`, and evaluator-only tests in `hidden_files`.
- Every `visible_files` / `runtime_files` / `hidden_files` key is a path relative to `workdir` (e.g. `app/app.py`, `tests/test_regression.py`). Do not use absolute paths or paths outside the workdir; the runtime writes each entry at `workdir/<key>`. So an evaluator script should live at a path like `tests/run_tests.sh`, not `/evaluator/run_tests.sh`.
- Files created or downloaded through construction tools that are task inputs may remain in top-level `assets`; the framework copies them into the container workdir under their filenames. Never put their host paths in the prompt or environment.
- Set `environment.workdir` to an absolute POSIX path inside the container, using `/workspace` unless the task requires another directory; `.` and other relative paths are invalid.
- Use `setup_commands` for bounded initialization and provide the exact `test_command` for deterministic scoring; use `evaluation` to configure how that command's structured result is interpreted.
- For a custom image, use the construction tools to create and verify the Dockerfile and build context. Preserve the returned relative `image_build.context_dir`, `image_build.tag`, and `image_build.enabled=true` in the final environment.
- Set `timeout` (seconds per command) and `max_steps` (maximum interaction steps) appropriate to the workload. The field is named `timeout`, not `timeout_s`.
- If browser interaction is required, configure the canonical browser runtime with a start URL and allowed origins.
- Ensure the selected image or image build actually contains the declared runtime dependencies, but do not infer capabilities from image names alone.
- Do not expose raw command execution when protected runtime or hidden files exist; use structured workspace tools and runner-private evaluation.
- Keep image-build packages, commands, Dockerfile, and context files only as detailed as required by the TaskDesign.
