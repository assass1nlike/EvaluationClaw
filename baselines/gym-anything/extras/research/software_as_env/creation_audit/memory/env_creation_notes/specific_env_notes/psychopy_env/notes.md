> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# PsychoPy Environment (`psychopy_env`) - Creation Notes

## Overview
PsychoPy is an open-source Python application for creating psychology/neuroscience experiments. It provides Builder (visual drag-drop) and Coder (Python scripting) interfaces. This environment installs PsychoPy on a GNOME desktop via QEMU/Apptainer.

## Base Image
- `ubuntu-gnome-systemd_highres` (1920x1080)
- 4 CPU, 8GB RAM, net=true

## Key Technical Decisions

### OpenGL in VNC
PsychoPy requires OpenGL. Solution: Mesa LLVMpipe software renderer + `LIBGL_ALWAYS_SOFTWARE=1`.
```bash
apt-get install -y libgl1-mesa-glx libgl1-mesa-dri mesa-utils libglu1-mesa
export LIBGL_ALWAYS_SOFTWARE=1
```

### wxPython Installation
Use prebuilt wheel from extras.wxpython.org (building from source takes 30+ min):
```bash
pip3 install -f https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-22.04/ wxPython
```

### NumPy/SciPy Compatibility
System apt packages (numpy 1.21, scipy 1.8) are incompatible with pip-installed numpy 2.x. Must remove system packages and install via pip:
```bash
apt-get remove -y python3-numpy python3-scipy python3-matplotlib python3-pil python3-pandas
pip3 install "numpy>=1.26,<2.0" "scipy>=1.11"
```
**Note**: Despite the `<2.0` constraint, pip may install numpy 2.x if PsychoPy depends on it. PsychoPy 2025.2.4 works fine with NumPy 2.2.6.

### PsychoPy Startup Dialogs (CRITICAL)
PsychoPy shows a "Changes in X.Y.Z" dialog on first launch based on `lastVersion` in `~/.psychopy3/appData.cfg`. PsychoPy also auto-generates `userPrefs.cfg` on first launch, overwriting any pre-placed config.

**Solution**: Launch PsychoPy first to generate default configs, then patch them:
1. Launch PsychoPy (first launch generates `appData.cfg` and `userPrefs.cfg`)
2. Wait for window to appear
3. Patch `appData.cfg`: set `lastVersion` to current version
4. Patch `userPrefs.cfg`: set `showStartupTips=False`, `checkForUpdates=False`, `allowUsageStats=False`, `showSplash=False`
5. Kill and restart PsychoPy with patched configs
6. Close remaining dialogs (`PsychoPy Error`, `Additional configuration needed`) via `wmctrl -c`

**CRITICAL BUG FIX**: The setup script must NOT use `set -e` because:
- `python3 -c "import psychopy"` aborts with dbus error when run without proper D-Bus session
- Even though the version string IS printed before the abort, `set -e` causes the script to exit
- This prevents the `sed` command from ever running to patch `lastVersion`
- Fix: Remove `set -e` and use `|| true` guards on PsychoPy python commands

**Version detection**: Use `python3 -c "..." | tr -d '[:space:]'` with `|| true` guard, plus fallback to `pip3 show psychopy | grep Version`.

### PsychoPy API for Experiment Creation
When programmatic experiment creation is needed:
```python
from psychopy import experiment
from psychopy.experiment.components.text import TextComponent
from psychopy.experiment.components.keyboard import KeyboardComponent
from psychopy.experiment.loops import TrialHandler  # NOT from psychopy.experiment.flow

exp = experiment.Experiment()
routine = exp.addRoutine('trial')
# Add components to routine, then:
exp.flow.addRoutine(routine, pos=0)
loop = TrialHandler(exp=exp, name='trials')
exp.flow.addLoop(loop, startPos=0, endPos=1)
exp.saveToXML('output.psyexp')
```

### File Formats
- `.psyexp` - XML-based experiment files for Builder (`<PsychoPy2experiment>` root)
- `.py` - Python scripts for Coder
- `.csv` - Conditions files for experiment loops

## Tasks (5)

| Task | Difficulty | Description |
|------|-----------|-------------|
| create_stroop_experiment | Easy | Create Stroop color-word experiment in Builder with text, keyboard, loop |
| modify_demo_experiment | Medium | Load bundled Stroop demo, add instructions routine, change loop nReps |
| create_conditions_file | Easy | Create flanker_conditions CSV with proper columns and 8+ rows |
| configure_experiment_settings | Medium | Set experiment name, window size, fullscr=False in settings |
| code_simple_experiment | Medium | Write PsychoPy Python script in Coder view |

## Verification Pattern
1. `export_result.sh` runs in VM:
   - Checks file existence, modification time
   - Greps XML/Python for expected components
   - Writes JSON to `/tmp/<task>_result.json`
2. `verifier.py` runs on host:
   - Uses `copy_from_env()` to fetch JSON
   - Programmatic scoring (70 pts)
   - VLM scoring (30 pts)
   - Pass threshold: 60 pts

## Test Results (2026-02-06)

### create_stroop_experiment
- Programmatic: 70/70 (all 7 checks pass)
- VLM: not tested (would add up to 30 pts)
- "Do nothing" case: 0/100
- Boot time: ~171s total (159s install + 11s task hooks)

### code_simple_experiment
- Programmatic: 70/70 (all checks pass)
- VLM: not tested

### create_conditions_file
- Programmatic: 75/100 (all checks pass; `has_header` requires 3+ of 4 columns)
- "Do nothing" case: 0/100

## Known Issues
1. **PsychoPy dbus abort**: `python3 -c "import psychopy"` aborts with dbus error when run without DISPLAY or as root. This is a known PsychoPy bug with GameMode. PsychoPy works fine when `DISPLAY=:1` and `LIBGL_ALWAYS_SOFTWARE=1` are set.
2. **Demo unpacking**: `psychopy.demos.unpackDemos()` not available in v2025.2.4; fallback copies from package directory
3. **"Additional configuration needed" dialog**: Appears on restart, must be closed via `wmctrl -c "Additional configuration"`
4. **"PsychoPy Error" dialog**: May appear due to missing audio config, closeable
5. **First run generates configs**: Cannot pre-place userPrefs.cfg; must patch after first launch
6. **Install timeout**: PsychoPy installation takes ~159 seconds but the hook continues running
7. **`set -e` kills setup**: Must NOT use `set -e` in setup_psychopy.sh due to dbus abort
8. **Font Arial dialog**: When creating Text components with non-system fonts, a "Font Arial is not installed" dialog may appear. Close with "No" button.
9. **XDG_RUNTIME_DIR warnings**: PulseAudio warnings appear when running PsychoPy as root; safe to ignore

## Evidence
- `benchmarks/cua_world/environments/psychopy_env/evidence_docs/` - Contains screenshots, log snippets, and verification results
  - `builder_with_experiment.png` - PsychoPy Builder with loaded Stroop experiment
  - `runner_view.png` - PsychoPy Runner panel
  - `coder_view.png` - PsychoPy Coder panel
  - `install_log_snippet.txt` - Last 50 lines of pre_start hook
  - `setup_log_snippet.txt` - Full post_start hook output
  - `task_setup_log.txt` - pre_task hook output
  - `verification_result.json` - Export script JSON output
  - `README.md` - Detailed evidence documentation
