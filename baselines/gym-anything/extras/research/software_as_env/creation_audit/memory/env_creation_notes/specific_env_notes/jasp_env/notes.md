> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# JASP Environment — Creation Notes

## Overview
JASP is a free/open-source statistical software GUI application (University of Amsterdam).
Supports Bayesian and frequentist analyses. Version: 0.95.4 (stable as of 2026-02).

## Installation
- **Only viable Linux install method: Flatpak from Flathub**
  - PPA only supports Ubuntu 18.04 (bionic) — too old
  - GitHub releases: Windows/Mac only, no Linux binaries
  - Flatpak: `flatpak install --system --noninteractive flathub org.jaspstats.JASP`
- Use a **3-attempt retry loop** — first attempt sometimes fails with 404 on the JASP app itself
  (runtimes get installed on attempt 1, app succeeds on attempt 2)
- Install dependencies first: flatpak, xz-utils, gnupg, software-properties-common

## Critical: QEMU/Chromium Sandbox Issue
- JASP uses **Qt WebEngine (Chromium-based)** for its interface
- Chromium sandbox FAILS in QEMU VMs → JASP crashes with `Trace/breakpoint trap (SIGTRAP)` on startup
- **Fix**: Set `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"` before launching
- Cannot pass env vars reliably through `su - ga -c "VAR=val flatpak ..."` chain
- **Solution**: Create `/usr/local/bin/launch-jasp` wrapper script that sets the var internally

## Launcher Wrapper Pattern
```bash
#!/bin/bash
export DISPLAY=:1
export QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"
exec flatpak run org.jaspstats.JASP "$@"
```
- All task setup_task.sh scripts call: `su - ga -c "setsid /usr/local/bin/launch-jasp $DATASET > /tmp/jasp_task.log 2>&1 &"`
- `setsid` is critical: prevents SIGHUP from killing JASP when `su` exits

## Spaces in Filenames
- JASP datasets have spaces: "Invisibility Cloak.csv", "Exam Anxiety.csv", "Big Five Personality Traits.csv"
- Spaces cause argument splitting through multi-layer shell chains (`su -c` → `setsid` → `flatpak`)
- Error: `File to open /home/ga/Documents/JASP/Invisibility does not exist`
- **Fix**: Copy datasets with space-free names in setup_jasp.sh (ExamAnxiety.csv, etc.)

## Config Path (Flatpak)
- JASP config lives at: `/home/ga/.var/app/org.jaspstats.JASP/config/JASP/JASP.conf`
- Key setting to suppress update dialog: `checkUpdatesAskUser=false`
- Also set: `checkUpdatesAutomatic=false`, `recentFolders=/home/ga/Documents/JASP`
- Pre-create this config in setup_jasp.sh before warm-up launch

## Dataset Sources
Real research datasets from `jasp-stats/jasp-desktop` GitHub repo:
```
https://raw.githubusercontent.com/jasp-stats/jasp-desktop/master/Resources/Data%20Sets/Data%20Library/
```
Files: Sleep.csv, Invisibility%20Cloak.csv, Viagra.csv, Exam%20Anxiety.csv, Big%20Five%20Personality%20Traits.csv

## Warm-up Launch Pattern
In `setup_jasp.sh` (post_start hook):
1. Pre-create config with `FirstLoad` settings
2. `su - ga -c "setsid /usr/local/bin/launch-jasp > /tmp/jasp_warmup.log 2>&1 &"`
3. Wait 22 seconds for JASP to fully initialize
4. Dismiss dialogs: `xdotool key Escape` → sleep 1 → `xdotool key Return`
5. Kill: `pkill -f 'JASP'` or `pkill -f 'org.jaspstats'`

## Pre-task Setup
Each task's `setup_task.sh`:
1. Kill any running JASP: `pkill -f "org.jaspstats.JASP"`
2. Verify dataset exists (copy from `/opt/jasp_datasets/` if needed)
3. Launch JASP with dataset: `su - ga -c "setsid /usr/local/bin/launch-jasp $DATASET > /tmp/jasp_task.log 2>&1 &"`
4. Wait 22 seconds
5. Dismiss dialogs (Escape + Return)
6. Maximize window: `wmctrl -r "JASP" -b add,maximized_vert,maximized_horz`
7. Wait 1 more second

## Tasks
1. `descriptive_statistics` — Sleep.csv; Descriptives on `extra` split by `group`
2. `independent_samples_t_test` — InvisibilityCloak.csv; compare Mischief between Cloak groups
3. `one_way_anova` — Viagra.csv; ANOVA on libido by dose, Tukey post-hoc
4. `linear_regression` — ExamAnxiety.csv; predict Exam from Revise + Anxiety
5. `correlation_matrix` — BigFivePersonalityTraits.csv; Pearson corr matrix with heatmap

## Timing
- Fresh reset (use_cache=False): ~249s (218s pre_start + 30s pre_task)
- Cached reset (cache_level="post_start"): ~71s (40s loadvm + 30s pre_task)

## Process Detection
- Process name: `JASP`
- Full path: via flatpak bwrap — use `pgrep -f 'org.jaspstats.JASP'` or `pgrep -f 'JASP'`
- Log file: `/tmp/jasp_task.log` (per-task) or `/tmp/jasp_warmup.log` (warm-up)
