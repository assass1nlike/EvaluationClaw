# VM Environment

Use runtime environment type `vm`.

- Use this canonical field layout. Do not move `evaluation` into `session`, rename
  `vm_provisioning` to `provisioning`, or invent aliases such as
  `session.surface` or `session.evaluation_checks`:

```json
{
  "environment": {
    "type": "vm",
    "requires_vm": true,
    "vm": {
      "guest_os": "windows",
      "required_capabilities": [
        "desktop_bridge",
        "cloudbase_init_nocloud",
        "powershell"
      ]
    },
    "vm_provisioning": {
      "powershell_commands": ["task-specific state-building command"],
      "interactive_powershell_commands": [],
      "restart_after_provisioning": false
    },
    "session": {
      "application": "Windows Desktop",
      "launch_state": "The signed-in desktop is visible.",
      "baseline_checks": [
        {
          "id": "initial_state_present",
          "method": "command",
          "command": "PowerShell command that succeeds only when the required initial state exists",
          "expected_exit_code": 0
        }
      ]
    },
    "evaluation": {
      "method": "bridge_state_check",
      "checks": [
        {
          "id": "final_state_correct",
          "method": "command",
          "command": "PowerShell command that succeeds only when the target produced the required final state",
          "expected_exit_code": 0
        }
      ],
      "pass_criteria": "All required final-state checks pass.",
      "partial_criteria": "Only a strict subset of independent checks pass.",
      "fail_criteria": "No required final-state check passes."
    },
    "max_steps": 200,
    "timeout": 3600
  }
}
```

- Set `requires_vm` only when a VM is needed. Prefer `guest_os` plus `required_capabilities` so the runtime can resolve a compatible provider image. Pin an image, template, snapshot, or disk identifier only when that concrete identifier was supplied by runtime/user input; put descriptions in notes. Define how each run returns to the required baseline.
- Set `session.application` (or `session.applications` for multiple applications) and describe the concrete `session.launch_state`, input assets, workflow stages, handoff artifacts, and expected final artifacts. `session.surface` is not a runtime field.
- Put guest files in `visible_files` or session asset files; never put evaluator secrets there.
- Use setup commands, runtime files, VM provisioning, or a prebuilt image/snapshot only when the selected provider and guest OS can actually apply them. A sentence saying that a snapshot already contains task-specific state is not a snapshot reference or setup mechanism.
- Set `vm.guest_os` to `linux` or `windows` whenever files or provisioning are OS-specific. EvaluationClaw builds a per-task NoCloud config-drive ISO: Linux guests consume it with cloud-init; Windows guests consume PowerShell user data with Cloudbase-Init's NoCloud service. A Windows base template must therefore have Cloudbase-Init installed and configured for NoCloud before EvaluationClaw can customize it.
- For Windows provisioning, use `winget_packages`, `choco_packages`/`chocolatey_packages`, `windows_features`, `pip_packages`, `npm_packages`, `powershell_commands`, generic command fields, or PowerShell install steps. Do not use Linux package-manager fields. Relative visible paths are rooted at `C:\Users\Public` by default, so `Desktop/...` reaches the public desktop; override `vm_materialization.guest_root` only when the template uses a known different profile.
- When registering a password-backed Windows scheduled task, use the `Register-ScheduledTask` parameter set with `-User`, `-Password`, and optional `-RunLevel`. Do not combine `-Principal` with `-Password`; PowerShell rejects that ambiguous parameter set at runtime.
- A scheduled task's RunAs identity does not grant that account permission to modify a task registered by SYSTEM. If the target must repair task actions, triggers, or settings, provision concrete task ownership or a scoped task ACL that lets the target perform those exact changes. Prefer having the target identity create an `Interactive` task when the benchmark already guarantees that account is signed in. Add a non-repairing baseline check, such as reapplying the unchanged action, that proves the target can update the task before evaluation starts.
- When Windows provisioning changes the account that must own the interactive desktop session, configure that account through a concrete guest-supported logon mechanism and set `vm_provisioning.restart_after_provisioning` to `true`. EvaluationClaw then records successful provisioning before restarting and exposes the bridge only after the next boot. Verify the signed-in identity in `session.baseline_checks`; a `launch_state` sentence alone does not switch users.
- When a capability-resolved base VM is not guaranteed to contain the named target account, create that local user explicitly before referencing it in ACLs, Scheduled Task principals, or auto-logon configuration. Writing an unknown account name into those commands does not create the user and will fail provisioning.
- Put setup that must execute under the actual signed-in Windows user token (for example HKCU state, user-owned Scheduled Tasks, or GUI first-run initialization) in `vm_provisioning.interactive_powershell_commands` and also set `restart_after_provisioning=true`. EvaluationClaw installs it as one-time post-login setup and withholds the desktop bridge until it succeeds. Do not put evaluator secrets or other target-sensitive setup in this user-readable phase.
- Assign each setup command to exactly one identity phase. Never duplicate an `interactive_powershell_commands` entry in `powershell_commands` or `powershell_script`, because the duplicate would execute early as SYSTEM.
- Every VM-backed task must include runner-private executable `session.baseline_checks` that verify its required initial state before the target acts. For task-specific hidden or mutable state, also include either concrete `vm_provisioning` commands that create it or a runner-resolvable prebuilt image/snapshot identifier. The bridge must return `baseline_verified=true` when creating the session; otherwise EvaluationClaw fails closed. Final-state checks belong in `environment.evaluation` and must not create the initial state.
- A check with `method: "command"` must put the complete executable guest shell command in its `command` field. Opaque names such as `RUNNER_PRIVATE_BRIDGE_COMMAND:validator_name` are not registered or resolved by the generic bridge and are invalid.
- On Windows, the bridge executes `method: "command"` values as raw PowerShell script bodies. Do not wrap them in `powershell.exe -Command`/`pwsh -Command`, and do not use backslash-escaped quotes such as `\"`; use ordinary PowerShell quoting. The built-in bridge supports only `command` and `file_exists` check methods.
- Generate JSON fixture files from PowerShell objects with `ConvertTo-Json`; do not hand-write JSON inside a quoted PowerShell string with `\"`, `\n`, or backtick-newline escapes. Those characters can be written literally and produce a file that `ConvertFrom-Json` cannot read. For multiline scripts or data embedded in the Builder response, prefer an array of complete lines joined with `[Environment]::NewLine`; a PowerShell here-string header must be followed immediately by a real newline.
- Every evaluation command must itself decide whether the scored state is correct by returning a success or failure exit code (or by using an output comparison explicitly supported by the bridge). A command that only prints or serializes observations and then exits successfully is not an evaluator. Ordinary task metadata is descriptive and cannot register a runner-private or host-side evaluator.
- Do not invent a task-specific image or snapshot identifier. Use a prebuilt artifact only when its concrete identifier was supplied in the TaskDesign or runtime inputs; otherwise declare OS/capability requirements and construct the task-specific fixture with `vm_provisioning` on the provider-resolved base image.
- When a remote VM provider advertises `image_build`, the Builder may submit a declarative `build_vm_image` plan containing a base image selector, guest provisioning, files, and provider-executed checks. Use the returned `image_id` in `environment.vm.image`; the image is usable only after the provider reports successful checks.
- Bound `max_steps` and timeout, and define bridge-executable artifact, UI-state, page-state, final-state, or trajectory checks with full, partial, and failure criteria.
- `expected_artifacts` lists candidate paths. Set `artifact_requirement` to `all` (default), `any`, or `exactly_one` so alternative formats are not misrepresented as jointly required.
- The desktop bridge executes both target actions and final-state evaluator commands as the signed-in target user. An evaluator therefore cannot read an oracle directory protected for only SYSTEM or Administrators. Keep private oracle material inaccessible to the target and embed the required expected values or hashes directly in evaluator commands; never make a private oracle target-readable merely so scoring can access it.
- For multi-application workflows, require observable handoffs and provenance instead of reducing the task to one application.
- Never include bridge URLs, API keys, VM-provider credentials, or other runtime secrets in task metadata.
