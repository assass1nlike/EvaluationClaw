# Docker Workspace Environment

Use runtime environment type `docker_workspace`.

- Choose a suitable common image, use `image: "auto"`, or define `image_build` only when a common image is insufficient.
- Put target-visible files that are part of the declared initial environment in `visible_files`, setup-only server/application material in `runtime_files`, and evaluator-only tests in `hidden_files`.
- Files created or downloaded through construction tools that are task inputs may remain in top-level `assets`; the framework copies them into the container workdir under their filenames. Never put their host paths in the prompt or environment.
- Set `environment.workdir` to an absolute POSIX path inside the container, using `/workspace` unless the task requires another directory; `.` and other relative paths are invalid.
- Use `setup_commands` for bounded initialization and provide the exact `test_command` for deterministic scoring; use `evaluation` to configure how that command's structured result is interpreted.
- For a custom image, use the construction tools to create and verify the Dockerfile and build context. Preserve the returned relative `image_build.context_dir`, `image_build.tag`, and `image_build.enabled=true` in the final environment.
- Specify timeout and resource limits appropriate to the workload.
- If browser interaction is required, configure the canonical browser runtime with a start URL and allowed origins.
- Ensure the selected image or image build actually contains the declared runtime dependencies, but do not infer capabilities from image names alone.
- Do not expose raw command execution when protected runtime or hidden files exist; use structured workspace tools and runner-private evaluation.
- Keep image-build packages, commands, Dockerfile, and context files only as detailed as required by the TaskDesign.
