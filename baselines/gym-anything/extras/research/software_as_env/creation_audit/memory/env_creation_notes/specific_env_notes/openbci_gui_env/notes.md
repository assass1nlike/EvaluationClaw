> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenBCI GUI Environment Notes

## Installation

**Application**: OpenBCI GUI v5.2.2 (Java/Processing desktop app)
**Release date**: 2023-08-21
**Source**: GitHub releases — `https://github.com/OpenBCI/OpenBCI_GUI/releases/download/v5.2.2/openbcigui_v5.2.2_2023-08-21_16-14-34_linux64.zip`
**Fallback**: v5.2.1 release zip
**Install path**: `/opt/openbci_gui/OpenBCI_GUI/` (extracted from zip)
**Executable**: Located by `find "$OPENBCI_DIR" -name "OpenBCI_GUI" -type f`; path saved to `/opt/openbci_exec_path.txt`
**Base dir**: Saved to `/opt/openbci_base_dir.txt`
**Wrapper**: `/usr/local/bin/openbci_gui` (wraps executable, sets DISPLAY)
**Launch script**: `/home/ga/launch_openbci.sh` — used by all setup scripts; cds to base dir before running (Processing apps require this)

### System Dependencies
```bash
apt-get install -y xdotool wmctrl x11-utils scrot imagemagick unzip tar curl wget \
    libxrender1 libxtst6 libxi6 libxrandr2 libgl1 libglu1-mesa libasound2 fonts-dejavu-core \
    python3-pip python3-numpy python3-scipy
pip3 install pyEDFlib
```

### Critical: Launch From Base Directory
OpenBCI GUI is a Processing app that uses relative paths for its assets and settings. It MUST be launched with `cd "$OPENBCI_BASE_DIR" && exec "$OPENBCI_EXEC"`. Launching from any other directory causes startup failures or missing assets.

### Warm-Up Launch in post_start
`setup_openbci.sh` performs a warm-up launch to initialize OpenBCI's settings/prefs files (e.g., `GuiWideSettings.json`). The warm-up launches the GUI, waits for the window, presses Escape to dismiss dialogs, then kills it. Without warm-up, the first real task launch may show unexpected first-run dialogs.

## Window & Process Management

- **Window title**: Contains "OpenBCI" — detected by `wmctrl -l | grep -qi "openbci"`
- **Process name**: `OpenBCI_GUI` — killed by `pkill -f "OpenBCI_GUI"`
- **CRITICAL**: `pkill -f "OpenBCI_GUI"` matches the string literally in all running processes' cmdlines. If called from an SSH session where the SSH command itself contains "OpenBCI_GUI" (e.g., `sudo bash -c "pkill -f OpenBCI_GUI"`), it may kill the caller's bash process. Always call kill via a pre-written script file (so the bash argv is `bash /path/to/script.sh`, not the literal string).
- **Kill pattern used**: `pkill -f "OpenBCI_GUI" 2>/dev/null || true`, then `sleep 2`, then `pkill -9 -f "OpenBCI_GUI"`.

## GUI Startup Timing

- **Startup takes ~20-25 seconds** on a QEMU VM with KVM
- **Readiness signal**: The LAST log message is "not being run with Administrator access". This appears after "Setup is complete!" and confirms the Control Panel is fully initialized and interactive.
- **DO NOT use "TopNav: Internet Connection"** — appears too early; Control Panel is not yet interactive at that point
- **Fallback signal**: "Setup: Setup is complete!" — accept if the Administrator message doesn't appear
- **Settle time**: Add 5 seconds after the readiness signal before sending clicks

```bash
# Correct wait pattern in launch_openbci():
for i in $(seq 1 $timeout); do
    if grep -q "not being run with Administrator access" /tmp/openbci_task.log 2>/dev/null; then
        break
    fi
    sleep 1
done
sleep 5  # Settle time
```

## xdotool Absolute Coordinate Clicks — CRITICAL LIMITATIONS

**Root cannot send absolute X11 click events.** The task setup scripts run as root (via `sudo -n bash`). xdotool mouse clicks at absolute coordinates silently fail when run as root.

### Solution: `su - ga -c` with semicolons in ONE shell

```bash
# WORKS: single su -ga -c with semicolons
su - ga -c 'export DISPLAY=:1; export XAUTHORITY=/run/user/1000/gdm/Xauthority; xdotool mousemove --sync 180 207; sleep 0.1; xdotool click 1'

# FAILS: combined "mousemove X Y click 1" (X11 sync issue in su -ga context)
su - ga -c 'export DISPLAY=:1; export XAUTHORITY=/run/user/1000/gdm/Xauthority; xdotool mousemove --sync 180 207 click 1'

# FAILS: separate su -ga -c calls (race condition — mouse position can change between calls)
su - ga -c 'export DISPLAY=:1; export XAUTHORITY=/run/user/1000/gdm/Xauthority; xdotool mousemove --sync 180 207'
su - ga -c 'export DISPLAY=:1; export XAUTHORITY=/run/user/1000/gdm/Xauthority; xdotool click 1'

# FAILS: calling xdotool directly as root
DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority xdotool mousemove --sync 180 207 click 1
```

**Always use single-shell semicolons**: `mousemove --sync X Y; sleep 0.1; click 1` in ONE `su - ga -c` call.

Also: `su - ga -c` must be called from a root context. If called from a non-root SSH session as `ga`, `su` will prompt for password and hang.

## Control Panel UI Coordinates (1920×1080)

Empirically verified (inner window at 70,64; window at 80,109; size 1024×768):

| Element | x | y |
|---------|---|---|
| SYNTHETIC (algorithmic) | 180 | 207 |
| START SESSION button | 200 | 275 |
| CYTON (live) | 180 | ~171 |
| GANGLION (live) | 180 | ~184 |
| PLAYBACK (from file) | 180 | ~198 |
| STREAMING (from external) | 180 | ~221 |

**Note**: `visual_grounding` returns 1280×720 scale coords. For xdotool on a 1920×1080 screen, coordinates in the scripts are already in 1920×1080 — these match directly.

## Launching Synthetic Session

The `launch_openbci_synthetic()` function in `utils/openbci_utils.sh`:
1. Calls `launch_openbci` (waits for "not being run with Administrator access" + 5s settle)
2. Finds window ID with `xdotool search --name "OpenBCI"`
3. Raises window with `wmctrl -ia "$WID"`
4. Clicks SYNTHETIC: `su - ga -c 'xdotool mousemove --sync 180 207; sleep 0.1; xdotool click 1'`
5. Clicks START SESSION: `su - ga -c 'xdotool mousemove --sync 200 275; sleep 0.1; xdotool click 1'`
6. Waits for `[SUCCESS]: Session started!` in log (up to 20s)
7. Sends SPACEBAR to start data stream: `su - ga -c 'xdotool key space'`

## Expert Mode

Expert Mode reveals per-channel toggle buttons and extra controls in the Time Series widget.

**Enable Expert Mode via JSON (most reliable)**:
```python
SETTINGS_FILE = "/home/ga/Documents/OpenBCI_GUI/Settings/GuiWideSettings.json"
import json
with open(SETTINGS_FILE) as f:
    data = json.load(f)
data['expertMode'] = 'ON'
with open(SETTINGS_FILE, 'w') as f:
    json.dump(data, f, indent=2)
```
The JSON file is created during the warm-up launch. Set `expertMode = 'ON'` **before** launching the GUI — OpenBCI reads it on startup.

## EEG Data

**Source**: PhysioNet EEG Motor Movement/Imagery Dataset (eegmmidb 1.0.0)
- Subject S001, Run R01 (eyes open baseline, ~60s)
- Subject S001, Run R04 (motor imagery)
- Original format: EDF (European Data Format), 64 channels, 160 Hz
- Converted to OpenBCI CSV format (8 channels, 250 Hz, 120s max)
- Files: `/opt/openbci_data/OpenBCI-EEG-S001-EyesOpen.txt`, `OpenBCI-EEG-S001-MotorImagery.txt`
- Also copied to `/home/ga/Documents/OpenBCI_GUI/Recordings/` in post_start

**OpenBCI CSV format headers**:
```
%OpenBCI Raw EEG Data
%Number of channels = 8
%Sample Rate = 250 Hz
%Board = OpenBCI_V3
...
Sample Index, EXG Channel 0..7, Accel Channel 0..2, Other x7, Timestamp (Formatted), Timestamp (Unix)
```

## Screenshots (in-app)

OpenBCI GUI saves screenshots when 'm' is pressed (in Expert Mode):
- **Path**: `/home/ga/Documents/OpenBCI_GUI/Screenshots/`
- **Format**: `.jpg` files named `OpenBCI-*.jpg`
- **Count verification**: `find /home/ga/Documents/OpenBCI_GUI/Screenshots/ \( -name "OpenBCI-*.jpg" -o -name "OpenBCI-*.png" \) | wc -l`
- **Expert Mode required**: The 'm' shortcut only works when Expert Mode is enabled

## Task Summary

All 10 tasks verified working. Setup times (from post_start cache): ~20-25s each.

| Task | Setup type | Start state |
|------|-----------|-------------|
| `start_synthetic_session` | `launch_openbci` only | Control Panel, no session |
| `load_playback_recording` | `launch_openbci` only | Control Panel, no session |
| `add_fft_widget` | `launch_openbci_synthetic` | Running synthetic session |
| `add_band_power_widget` | `launch_openbci_synthetic` | Running synthetic session |
| `change_timeseries_scale` | `launch_openbci_synthetic` | Running synthetic session |
| `change_widget_layout` | `launch_openbci_synthetic` | Running synthetic session |
| `set_bandpass_filter` | `launch_openbci_synthetic` | Running synthetic session |
| `enable_expert_mode` | `launch_openbci_synthetic` | Running synthetic session, Expert Mode OFF |
| `disable_eeg_channel` | Expert Mode ON + `launch_openbci_synthetic` | Running synthetic session, Expert Mode ON |
| `take_gui_screenshot` | Expert Mode ON + `launch_openbci_synthetic` | Running synthetic session, Expert Mode ON |

### start_synthetic_session
Control Panel shown. Agent must: select SYNTHETIC → click START SESSION → data stream appears.

### load_playback_recording
Control Panel shown. EEG file at `~/Documents/OpenBCI_GUI/Recordings/OpenBCI-EEG-S001-EyesOpen.txt`. Agent must: select PLAYBACK → navigate file browser to that path → click START SESSION.

### add_fft_widget / add_band_power_widget
Running session. Default layout shows Time Series + one other widget. Agent must: click the dropdown on a widget panel → select FFT Plot / Band Power.

### change_timeseries_scale
Running session. Agent must: find the "Vert Scale" dropdown in the Time Series widget → change to the target value.

### change_widget_layout
Running session. Agent must: click the "Layout" dropdown in the top toolbar → select 4-panel layout.

### set_bandpass_filter
Running session. Default BPF is hard-coded to 5.0-50.0 Hz BandPass Butterworth. Agent must: click "Filters" button in top toolbar → change Start from 5.0 Hz to 1.0 Hz (target: 1-50 Hz). NOTE: task target was updated from 5-50 Hz (trivially pre-satisfied) to 1-50 Hz.

### enable_expert_mode
Running session with Expert Mode OFF. Agent must: navigate to Settings → find Expert Mode toggle → enable it.

### disable_eeg_channel
Running session with Expert Mode ON. Expert Mode shows numbered channel buttons in the Time Series widget. Agent must: click on the Time Series area to focus it → press '3' to toggle Channel 3 off.

### take_gui_screenshot
Running session with Expert Mode ON. Agent must: click on the data visualization area → press lowercase 'm' to save a screenshot.

## Verifiers

All verifiers are in `tasks/<task_name>/verify.py`. Common patterns:
- SSH into VM, check state via file inspection or xdotool screenshots
- Screenshot count verifier: `count_screenshots()` via SSH command
- Session started verifier: check `/tmp/openbci_task.log` for `[SUCCESS]: Session started!`
- Expert Mode verifier: read `GuiWideSettings.json` for `expertMode == 'ON'`

## openbci_utils.sh Reference

Located at `benchmarks/cua_world/environments/openbci_gui_env/utils/openbci_utils.sh` (copied to VM at `/workspace/utils/openbci_utils.sh`).

All setup scripts source it: `source /workspace/utils/openbci_utils.sh || true`

Functions:
- `kill_openbci()` — kills all OpenBCI GUI processes, waits for window to disappear
- `launch_openbci([timeout])` — kills, starts fresh, waits for "not being run with Administrator access"
- `launch_openbci_synthetic()` — calls `launch_openbci`, then clicks SYNTHETIC + START SESSION + SPACE
- `take_screenshot([output_path])` — takes xwd window screenshot, converts to PNG (fallback: scrot)
- `count_screenshots()` — counts `OpenBCI-*.jpg` + `*.png` files in Screenshots directory

## Common Errors and Fixes

1. **"xdotool click does nothing"** — root cannot send X11 clicks; use `su - ga -c` with semicolons
2. **"Separate su -ga -c calls have race condition"** — must chain mousemove + click in ONE shell invocation
3. **"Combined mousemove X Y click 1 fails in su -ga"** — X11 sync issue; use `mousemove --sync X Y; sleep 0.1; click 1`
4. **"Control Panel not interactive after 'Setup is complete!'"** — wait for "not being run with Administrator access" instead
5. **"pkill -f OpenBCI_GUI kills SSH session"** — run kills from a script file, not inline via SSH `-c`
6. **"GuiWideSettings.json not found"** — created during warm-up launch in post_start; expert mode write must run after post_start
7. **"Transient session start failure"** — after many consecutive task runs, GUI may accumulate state; retry succeeds. Not a code bug.
8. **QEMU mounts are copies** — after editing openbci_utils.sh locally, push to VM with: `sshpass -p 'password123' scp -P PORT file ga@localhost:/workspace/utils/openbci_utils.sh`

## Bulk Task Fix (2026-03-16) — 67 Unverified Tasks Fixed

### Summary
67 auto-generated tasks had systematic issues in their setup_task.sh scripts. All were fixed programmatically.

### Issues Fixed
1. **`set -e` removed** (57 tasks): Caused scripts to exit on non-zero returns from pkill, wmctrl, etc.
2. **Source path fixed** (53 tasks): Changed from `/home/ga/openbci_task_utils.sh` to `/workspace/utils/openbci_utils.sh`
3. **Manual launch patterns replaced** (~40 tasks): Replaced `su - ga -c "setsid ... launch_openbci.sh"` + wmctrl wait loops with `launch_openbci` or `launch_openbci_synthetic` from utils
4. **Window maximize removed** (~40 tasks): `wmctrl -b add,maximized_vert,maximized_horz` changes UI coordinates and breaks xdotool
5. **XAUTHORITY missing on wmctrl** (~40 tasks): Added `XAUTHORITY=/run/user/1000/gdm/Xauthority`
6. **post_task hooks removed** (66 tasks): Removed `export_result.sh` hooks (unnecessary for stub verifiers)
7. **Broken task.json fixed** (1 task): `configure_timeseries_window` had truncated JSON

### Start State Categories
- **Control Panel** (most tasks): Agent starts from System Control Panel, does everything
- **Synthetic Session** (11 tasks): Session already running via `launch_openbci_synthetic`
- **Playback Data** (~27 tasks): Control Panel + EEG recording files pre-staged in Recordings/

### Verified Test Results (2026-03-16)
- `configure_16ch_synthetic` (control_panel): Control Panel visible, ready for agent
- `set_notch_filter_50hz` (synthetic_session): Running session with 8 channels streaming
- `analyze_alpha_playback_fft` (playback): Control Panel visible, EEG files in Recordings/

Evidence screenshots in `evidence_docs/`.

---

## Interactive Testing Notes (2026-02-22) — All 10 Tasks Verified

**Environment**: Ubuntu 22.04 GNOME, QEMU/KVM, 1920×1080, OpenBCI GUI v5.2.2

### Clean Test Results
- `env.reset(seed=42, use_cache=False, use_savevm=True)` — completed in **86 seconds** (pre_start + post_start)
- post_start includes warm-up launch (~45s) + directory setup + EEG data copy
- Task reset from post_start cache: ~48s (23s VM restore + 24s task hook)

### All 10 task start states confirmed (VNC screenshots in `evidence_docs/`)
Each screenshot saved as `evidence_docs/<task_name>.png`. Screenshots show task-specific UI elements (menus open, task-relevant start states).

### Key Findings (Post-Audit Verified 2026-02-22)

**Widget/Settings overwrite behavior (CRITICAL)**:
- OpenBCI GUI OVERWRITES `SynthEightDefaultSettings.json` at session start with its internal state
- Cannot reliably pre-modify widget assignments by editing the file before launch
- Workaround: use xdotool AFTER session starts to click widget dropdowns (see `add_fft_widget/setup_task.sh`)

**Default filter state**:
- BPF is hard-coded to 5.0-50.0 Hz BandPass Butterworth 4th order — NOT stored in any settings file
- Filter settings are NOT persisted in `SynthEightDefaultSettings.json` or `GuiWideSettings.json`
- This caused `set_bandpass_filter` task to be trivially pre-satisfied (was changed from 5-50 Hz target → 1-50 Hz target)

**Expert Mode and channel buttons**:
- Channel buttons (numbered 1-8) are ALWAYS visible in Time Series widget, regardless of Expert Mode state
- Expert Mode toggle indicator: hamburger menu (≡) appears in top-right toolbar ONLY when Expert Mode is ON
- `GuiWideSettings.json` default after warm-up: `expertMode: "OFF"`
- Expert Mode toggle location: accessible via the hamburger (≡) button at ~(716, 53) in VG scale

**Filters button location (1920×1080)**:
- "Filters" button: (187, 75) in VG scale = (280, 112) in 1920×1080
- Opens a dialog with Filter type, Start Hz, Stop Hz, Butterworth order

**Layout and Vert Scale UI (VG scale 1280×720)**:
- Layout button: (707, 75) → opens 3×3 grid of panel layout options
- Vert Scale dropdown: (320, 107) → options: Auto, 12, 100, 200, 500, 1000, 10000 uV
- Widget dropdown: (660, 138) → all widget types listed (FFT, Time Series, Accelerometer, Band Power, Head Plot, etc.)

**add_fft_widget fix**:
- Problem: default layout always has FFT in upper-right panel (Widget_1: 3) — task was pre-satisfied
- Solution: after `launch_openbci_synthetic`, use xdotool to click FFT dropdown (660, 138) → select Head Plot (652, 266)
- "Head Plot" is not in any other panel, so no SWAP occurs. Result: Time Series + Head Plot + Accelerometer
