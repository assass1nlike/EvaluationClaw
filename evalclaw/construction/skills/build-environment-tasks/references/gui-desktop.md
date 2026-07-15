# GUI Desktop Environment

Use runtime environment type `gui_desktop`.

- Set `requires_vm` only when a VM is needed. Put runner-resolvable image, template, snapshot, or disk identifiers in their identifier fields; put descriptions in notes. Define how each run returns to the required baseline.
- Identify the application or desktop surface and describe its concrete launch state, input assets, workflow stages, handoff artifacts, and expected final artifacts in `session`.
- Put guest files in `visible_files` or session asset files; never put evaluator secrets there.
- Use setup commands, runtime files, VM provisioning, or a prebuilt image/snapshot only when the selected provider and guest OS can actually apply them. A sentence saying that a snapshot already contains task-specific state is not a snapshot reference or setup mechanism.
- Set `vm.guest_os` to `linux` or `windows` whenever files or provisioning are OS-specific. EvaluationClaw builds a per-task NoCloud config-drive ISO: Linux guests consume it with cloud-init; Windows guests consume PowerShell user data with Cloudbase-Init's NoCloud service. A Windows base template must therefore have Cloudbase-Init installed and configured for NoCloud before EvaluationClaw can customize it.
- For Windows provisioning, use `winget_packages`, `choco_packages`/`chocolatey_packages`, `windows_features`, `pip_packages`, `npm_packages`, `powershell_commands`, generic command fields, or PowerShell install steps. Do not use Linux package-manager fields. Relative visible paths are rooted at `C:\Users\Public` by default, so `Desktop/...` reaches the public desktop; override `vm_materialization.guest_root` only when the template uses a known different profile.
- For task-specific hidden or mutable initial state, include a runner-private setup/prebuilt-state mechanism and executable `session.baseline_checks` that verify the state exists before the target acts. The bridge must return `baseline_verified=true` when creating the session; otherwise EvaluationClaw fails closed. Final-state checks do not create the initial state.
- Bound `max_steps` and timeout, and define bridge-executable artifact, UI-state, page-state, final-state, or trajectory checks with full, partial, and failure criteria.
- For multi-application workflows, require observable handoffs and provenance instead of reducing the task to one application.
- Never include bridge URLs, API keys, VM-provider credentials, or other runtime secrets in task metadata.
