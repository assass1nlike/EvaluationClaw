> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# KNIME Analytics Platform Environment Notes

## Application Overview
- KNIME Analytics Platform is a free, open-source Java desktop application for visual data analytics
- Built on Eclipse RCP with Chromium Embedded Framework (CEF) for the modern UI
- Ships with bundled JRE (no system Java needed)
- Installation: download tarball, extract, run `./knime`

## Installation
- **Download URL**: `https://download.knime.org/analytics-platform/linux/knime-latest-linux.gtk.x86_64.tar.gz`
- **Install dir**: `/opt/knime/`
- **Binary**: `/opt/knime/knime`
- **JVM config**: `/opt/knime/knime.ini` (set `-Xmx4096m` for 8GB VM)
- **Size**: ~1.5GB tarball, ~2GB extracted

## Critical Quirks

### 1. Workspace Lock File
KNIME creates `.metadata/.lock` in the workspace directory. If KNIME crashes or is killed without proper shutdown, this lock file persists and prevents KNIME from starting again. The lock file must be manually removed:
```bash
rm -f /home/ga/knime-workspace/.metadata/.lock
rm -f /home/ga/knime-workspace/.metadata/.plugins/org.eclipse.core.resources/.snap
```

### 2. XAUTHORITY for GUI Access
When launching KNIME via `sudo -u ga` or `su - ga`, you must explicitly set XAUTHORITY:
```bash
sudo -u ga bash -c "DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority nohup /opt/knime/knime -data /home/ga/knime-workspace > /tmp/knime.log 2>&1 &"
```
Without it, KNIME silently fails to connect to the X display.

### 3. CEF-Based UI
KNIME 5/6 renders its entire UI using Chromium Embedded Framework. This means:
- The UI is essentially a web application inside an embedded browser
- xdotool clicks work, but coordinates must be determined empirically (not from visual estimates on thumbnails)
- Multiple child processes spawn: Java main, CEF crash handler, zygote, GPU process, network service, renderer
- All must be killed when stopping KNIME

### 4. First-Run Dialogs
- **"Help Improve KNIME"** telemetry dialog: appears on first launch per workspace. Dismiss with Escape.
- **Workspace chooser**: suppressed by passing `-data <workspace_path>` on command line
- No multi-step wizard or account creation required

### 5. UI Coordinates (1920x1080 Maximized)
Determined empirically via pixel color analysis:
- **"Create new workflow" button**: (1806, 472) - golden/yellow button on Welcome page
- **"Create" dialog button**: (1141, 536) - golden button in the workflow creation dialog

### 6. Process Kill Order
Must kill all KNIME-related processes:
```bash
pkill -u ga -f "knime"
pkill -u ga -f "eclipse"
pkill -u ga -f "equochro"  # CEF helper processes
pkill -9 -u ga -f "java.*knime"
```

## Data Sources
- **Titanic**: `https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv` (891 real historical records)
- **Iris**: `https://raw.githubusercontent.com/mwaskom/seaborn-data/master/iris.csv` (150 real botanical measurements)
- Fallback URLs available in install script

## Timing
- Pre-start (install KNIME + download data): ~50-60s
- Post-start (setup + warm-up launch): ~20-25s
- Task setup (launch + create workflow): ~30-35s
- Total: ~100-120s from env.reset() to agent-ready
