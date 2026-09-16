> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ReqView Environment Notes

## Overview
ReqView is an Electron-based requirements management tool. The env provides 5 tasks covering core ReqView workflows on the built-in DEMO example project.

## Tasks
1. `add_requirement` — Add a new functional requirement to the SRS document
2. `update_requirement_status` — Change SRS-246's status from Draft → Approved
3. `export_to_csv` — Export SRS document to CSV
4. `create_traceability_link` — Link SRS-245 → NEEDS-82
5. `add_custom_attribute` — Add a custom attribute to requirements

## Key Bugs Found and Fixed

### 1. Missing Attachment Files → FileSystemError (CRITICAL)
The ExampleProject JSON documents reference attachment files:
- `INF-2_1_reqview_icon.png`
- `INF-9_1_Project Traceability Diagram.png`
- `ASVS-9_1_license.png`
- `ASVS-23_1_asvs_40_levels.png`
- `ARCH-7_1_reqview_architecture.png`
- `SRS-130_1_ReqView File Data Format v11.pdf`

These files were absent from `data/ExampleProject/attachments/`. ReqView's `createProjectFromFolder()` throws a `FileSystemError` during `loadAttachments()`, which surfaces an errorsDialog, then falls back to "No project loaded" state.

**Fix**: Created minimal placeholder files (1x1 PNG, empty PDF) with the correct names in `data/ExampleProject/attachments/`.

### 2. setup_task_project() Polluted $PROJECT_PATH (CRITICAL)
The `setup_task_project` function in `task_utils.sh` echoed informational messages to stdout:
```bash
echo "Copied example project to $task_project_dir"  # goes to stdout → captured in PROJECT_PATH!
echo "$task_project_dir"  # the actual return value
```
When called as `PROJECT_PATH=$(setup_task_project "add_requirement")`, `$PROJECT_PATH` contained:
```
Copied example project to /home/ga/Documents/ReqView/add_requirement_project
/home/ga/Documents/ReqView/add_requirement_project
```
This caused `reqview open -p <multiword path>` to fail silently (window opens but no project loaded).

**Fix**: Changed informational echo statements to `>&2` (stderr) so only the path is captured in stdout.

### 3. EULA Acceptance Needed Window Maximization
ReqView shows an EULA dialog on first run. The Accept button coordinates `(1266, 840)` assume a maximized 1920×1080 window. The original setup_reqview.sh didn't maximize the window before clicking.

**Fix**: Added `wmctrl -r "ReqView" -b add,maximized_vert,maximized_horz` before EULA click.

### 4. Contact Form Tab Sequence Had Extra Tab-Stop
The "Set Up Your Contact Details" dialog has this tab order:
Name → Email → Company → **"I agree to Privacy Policy" link** → Agree button

The Privacy Policy link IS a tab-stop. Original code used 2 tabs after Email to reach Agree, but 3 are needed:
```bash
xdotool key Tab  # → Company
xdotool key Tab  # → Privacy Policy link (was MISSING!)
xdotool key Tab  # → Agree button
xdotool key Return
```

### 5. welcomeDialog After Contact Submission
After submitting contact details, reqview shows a "Welcome / New User Tour" dialog. This appears only once and is not a problem — the warm-up kills reqview during this dialog, and subsequent launches don't show it again (stored in IndexedDB as "tour started").

## Dialog Sequence During Warm-Up (setup_reqview.sh)
1. Launch reqview with no project
2. Wait for window to appear (15–30s for Electron)
3. **Maximize window** (CRITICAL — must be BEFORE EULA click)
4. Scroll EULA text (5 scroll-downs)
5. Click Accept at (1266, 840) in maximized 1920×1080
6. Wait 4s for Contact dialog
7. Click Name field at (765, 498), type "GA User"
8. Tab → Email, type "ga@example.com"
9. Tab → Company (leave blank)
10. Tab → Privacy Policy link (skip)
11. Tab → Agree button
12. Return → submit
13. Wait 3s, then close/kill reqview
14. Verify: log should contain `Hide dialog 'eulaDialog'` and `Hide dialog 'userContactDialog'`

## ReqView CLI
```bash
reqview open -p <project_folder>   # Open a project folder (-p is required)
reqview open --help                # Show help
```
Note: `reqview open <path>` WITHOUT `-p` just prints help and exits!

## Log File
`/home/ga/.config/ReqView/logs/ReqView.log` — key events to look for:
- `Show dialog 'eulaDialog'` / `Hide dialog 'eulaDialog'` — EULA shown/accepted
- `Show dialog 'userContactDialog'` / `Hide dialog 'userContactDialog'` — contact form
- `startup Opened project` — project loaded (but may be a "no project" startup too)
- `startup Startup finished` — app fully ready
- `FileSystemError` — attachment files missing → project won't load

## Project Structure (ExampleProject)
```
ExampleProject/
  project.json      # project metadata, id="DEMO"
  attachments/      # PNG + PDF files referenced from documents (MUST EXIST!)
  config/
    dashboard.json
  documents/
    INF.json, NEEDS.json, ASVS.json, RISKS.json, SRS.json, TESTS.json, ARCH.json
```

## task_utils.sh Functions
- `setup_task_project <name>` → copies ExampleProject to `/home/ga/Documents/ReqView/<name>_project/`, returns path on stdout (only)
- `launch_reqview_with_project <path>` → kills reqview, launches with `reqview open -p <path>`, waits up to 90s for window
- `dismiss_dialogs` → sends Escape×3 (handles errorsDialog, trial notices)
- `maximize_window` → wmctrl maximize
- `take_screenshot <path>` → scrot

## Testing
```python
env = gym_anything.api.from_config('benchmarks/cua_world/environments/reqview_env', task_id='add_requirement')
obs = env.reset(seed=42, use_cache=True, cache_level="post_start", use_savevm=True)
# Expected: ~40s from checkpoint, no EULA/contact dialogs
# Window title should be: "DEMO - /home/ga/.../add_requirement_project - ReqView"
```

## Checkpoint Hash
`checkpoint_3051db7ee348df4b_post_start` — this is the post_start checkpoint for the reqview env.
