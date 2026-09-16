> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Jamovi Environment — Creation Notes

## Overview
Jamovi is an open-source statistical software built on Electron + R. Version 2.7.2 (stable, 2026-02).
Available only via Flatpak on Linux (`org.jamovi.jamovi`).

## Installation
- **Only Linux method: Flatpak from Flathub**
  - `flatpak install --system --noninteractive flathub org.jamovi.jamovi`
  - Use a 3-attempt retry loop (though in practice it succeeded on attempt 1)
  - Jamovi 2.7.2 was installed (latest stable as of 2026-02)
  - If JASP was installed previously, shared Flatpak runtimes are already cached → faster install

## Critical: D-Bus Session Bus Required (zypak)
Jamovi uses `zypak` (a Flatpak-compatible Electron sandbox replacement). `zypak` requires a D-Bus session bus to function:
```
[5 zypak-helper] Failed to connect to session bus: [org.freedesktop.DBus.Error.Spawn.ExecFailed]
/usr/bin/dbus-launch terminated abnormally without any error message
[5 zypak-helper] src/helper/main.cc:42(DetermineZygoteStrategy): Assertion failed: bus
/app/bin/jamovi: line 14:     5 Aborted  /app/bin/zypak-wrapper /app/bin/electron "$@"
```

**Fix**: The launcher script must export `DBUS_SESSION_BUS_ADDRESS` and `XDG_RUNTIME_DIR`:
```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export XDG_RUNTIME_DIR=/run/user/1000
```

The `/run/user/1000/bus` socket exists in the GNOME session (uid 1000 = ga user).

## Chromium Sandbox Issue
Like JASP, Jamovi's Electron (Chromium) sandbox fails in QEMU VMs. The fix is different from JASP:
- **JASP (Qt WebEngine)**: `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox"` (env var)
- **Jamovi (Electron)**: pass `-- --no-sandbox --disable-gpu` as app args to Flatpak

## Launcher Wrapper
The launcher script at `/usr/local/bin/launch-jamovi`:
```bash
#!/bin/bash
export DISPLAY=:1
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export XDG_RUNTIME_DIR=/run/user/1000
exec flatpak run org.jamovi.jamovi -- --no-sandbox --disable-gpu "$@"
```

All task setup_task.sh scripts call:
```bash
su - ga -c "setsid /usr/local/bin/launch-jamovi $DATASET > /tmp/jamovi_task.log 2>&1 &"
```

## File Opening
Jamovi accepts a file path as a positional argument after `--`:
```bash
flatpak run org.jamovi.jamovi -- --no-sandbox --disable-gpu /path/to/data.csv
```
Supports `.omv` (native Jamovi) and `.csv` files.

## Window Title
Jamovi sets the window title to the filename (without extension):
- `Sleep.csv` → window title "Sleep"
- **Do NOT use `wmctrl -r "jamovi"`** — it won't match
- **Use `wmctrl -r ":ACTIVE:"`** to maximize the active window

## Process Detection
```bash
pgrep -f "jamovi.server"    # Server process (backend Python)
pgrep -f "org.jamovi.jamovi" # Flatpak bwrap wrapper
```

## Datasets
Real research datasets from `jasp-stats/jasp-desktop` GitHub repo (same source as JASP env):
- `Sleep.csv` (178 bytes) — Gosset/Student 1908 sleep study
- `Invisibility Cloak.csv` (185 bytes) — Field 2013 field experiment
- `Viagra.csv` (206 bytes) — Field 2013 pharmacological study
- `Exam Anxiety.csv` (2249 bytes) — Field 2013 exam performance
- `NeuroticiIndex.csv` — **Real** bfi dataset (Revelle 2010, psych R package): 2,694 participants, N1-N5 on 1-6 Likert scale, Cronbach's α=0.813, McDonald's ω=0.818

**IMPORTANT**: The `Big Five Personality Traits.csv` from JASP GitHub has COMPOSITE scores (5 columns: Neuroticism, Extraversion, etc.) — NOT individual item responses. Cronbach's α requires item-level data. `NeuroticiIndex.csv` uses REAL item-level data from the psych R package `bfi` dataset (Revelle 2010).

Stored at `/opt/jamovi_datasets/` (from pre_start). Python script `extract_bfi_neuroticism.py` downloads the real bfi.csv from Rdatasets GitHub and extracts N1-N5 columns (filtering NAs) to create `NeuroticiIndex.csv` in `/home/ga/Documents/Jamovi/` during post_start.

## Non-fatal Error Messages
These appear in logs but do NOT prevent Jamovi from working:
- `Failed to connect to socket /run/dbus/system_bus_socket: No such file or directory` — system bus warnings, non-fatal
- `ANGLE Display::initialize error` — Vulkan/GPU warnings in QEMU, non-fatal (--disable-gpu suppresses most)
- `Gtk-Message: Failed to load module "canberra-gtk-module"` — audio module missing, non-fatal

## Tasks
1. `descriptive_statistics` — Sleep.csv; Exploration → Descriptives on `extra` split by `group`; Statistics (mean/median/SD/min/max) + Histogram
2. `independent_samples_t_test` — InvisibilityCloak.csv; T-Tests → Independent Samples T-Test; Mischief DV, Cloak grouping; effect size (Cohen's d=-0.700, p=.101)
3. `one_way_anova` — Viagra.csv; ANOVA → One-Way ANOVA; libido DV, dose grouping; Fisher's + Tukey post-hoc + Descriptives table; F(2,27)=2.42, p=.108
4. `linear_regression` — ExamAnxiety.csv; Regression → Linear Regression; Exam DV, Revise+Anxiety covariates; R²=0.209, β shown, CIs shown
5. `reliability_analysis` — NeuroticiIndex.csv; Factor → Reliability Analysis; N1-N5 items; α=0.789, ω=0.789, α-if-dropped shown

**CRITICAL: One-Way ANOVA module limitations**:
- No "Effect size (η²)" checkbox — only available in full ANOVA module
- Additional Statistics section only has: Descriptives table, Descriptives plots

## Timing
- Fresh reset (use_cache=False): ~240s (158s pre_start + 28s post_start + 28s pre_task + ~26s overhead)
- Post_start cached reset: ~28s
- Pre_start is fast when Flatpak runtimes are already cached from JASP

## Jamovi UI Layout
- **Top tabs**: Variables, Data, Analyses, Plots, Edit
- **Analysis buttons** (under Analyses tab): Exploration, T-Tests, ANOVA, Regression, Frequencies, Factor
- **Version**: 2.7.2 (shown in right panel when no analysis is open)
- **Status bar**: Shows Row count, Filtered, Deleted, Added, Cells edited
