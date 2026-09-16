> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Anaconda Navigator Environment - Learnings

## Installation

### Anaconda Installer
- Download URL: `https://repo.anaconda.com/archive/Anaconda3-2024.10-1-Linux-x86_64.sh`
- Silent install: `bash installer.sh -b -p /home/ga/anaconda3`
- The `-b` flag accepts license and skips prompts
- Install takes ~60-80 seconds (large download ~1GB)
- Must run `conda init bash` after install for shell integration

### Qt Dependencies
Anaconda Navigator 2.6.x uses Qt5 with Qt Quick/QML. These system packages are needed:
```
libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 libxcb-xinerama0
libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0
libxcb-render-util0 libxcb-shape0 libxcb-cursor0 libegl1
```

### conda_token Compatibility Fix (CRITICAL)
Navigator 2.6.3 imports `from conda_token.repo_config import ...` but conda-token 0.7.x moved this to `anaconda_auth._conda.conda_token`. Without the shim, Navigator crashes on import with `ModuleNotFoundError: No module named 'conda_token'`.

**Fix**: Create shim at `site-packages/conda_token/`:
- `__init__.py`: re-exports from `anaconda_auth._conda.conda_token`
- `repo_config.py`: dynamically re-exports all attributes (can't use `from ... import *` because some names lack `__all__`)

### libstdc++ Mesa Conflict (CRITICAL)
Anaconda bundles `libstdc++.so.6.0.29` which lacks `GLIBCXX_3.4.30` required by system's Mesa LLVM. Without fix, Qt Quick rendering fails and Navigator gets stuck on splash screen indefinitely.

**Fix**: `ln -sf /usr/lib/x86_64-linux-gnu/libstdc++.so.6 /home/ga/anaconda3/lib/libstdc++.so.6`

### Mesa DRI Path Fix
Mesa looks for drivers in `/usr/lib/dri/` but the actual file is at `/usr/lib/x86_64-linux-gnu/dri/swrast_dri.so`.

**Fix**: `mkdir -p /usr/lib/dri && ln -sf /usr/lib/x86_64-linux-gnu/dri/swrast_dri.so /usr/lib/dri/swrast_dri.so`

## UI Quirks

### GNOME Dock Interference
The GNOME dock overlaps with Navigator's sidebar. Auto-hide the dock:
```bash
su - ga -c "DISPLAY=:1 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus gsettings set org.gnome.shell.extensions.dash-to-dock dock-fixed false"
su - ga -c "DISPLAY=:1 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus gsettings set org.gnome.shell.extensions.dash-to-dock autohide true"
```
**Note**: gsettings must run as the ga user with DBUS_SESSION_BUS_ADDRESS set.

### Sidebar Click Failure (MAJOR FINDING)
Navigator 2.6.x uses Qt Quick (QML) with QtWebEngine for its sidebar rendering. The sidebar tabs do NOT respond to ANY programmatic mouse click method:
- xdotool (X11 SendEvent) - FAILS
- pyautogui (python-xlib) - FAILS
- XTest extension - FAILS
- python-evdev (kernel uinput) - FAILS

This is because Qt Quick renders on a separate compositing surface with its own event handling. X11 mouse events reach the window but aren't processed by the QML layer.

**Internal state can be changed** via GDB injection or source patches (`setCurrentIndex`), but the Qt Quick visual rendering doesn't sync with QWidget state changes.

**Impact**: Agents cannot programmatically navigate sidebar tabs. Tasks must be designed to start on the Home tab (Navigator's default).

### GNOME Focus-Stealing Prevention
Navigator MUST be launched from the post_start hook (before desktop is interactive). If killed and relaunched from pre_task hooks, GNOME's Mutter compositor blocks the window from becoming visible.

### Navigator Startup Timing
- First run: 3-5 minutes (downloads package metadata, builds index)
- Cached/subsequent runs: 4-10 seconds (window detection via wmctrl)
- Use `setsid` to prevent process termination on shell exit

### Dialog Suppression
Suppress update and what's-new dialogs in `anaconda-navigator.ini`:
```ini
hide_update_dialog = True
hide_whats_new_dialog = True
```

### Sidebar Coordinates (1920x1080, maximized)
- **Home**: x=90, y=190
- **Environments**: x=90, y=260
- **Learning**: x=90, y=330
- **Community**: x=90, y=400

## Data

### Wine Quality Dataset
- Source: UCI ML Repository (CC BY 4.0)
- Format: **Semicolon-separated** CSV (not comma!)
- 1599 samples, 12 columns (11 features + quality score)
- Agent needs to know about semicolon separator for pandas: `pd.read_csv(path, sep=';')`

### Iris Dataset
- Source: UCI ML Repository
- Format: Comma-separated CSV with headers
- 150 samples, 5 columns (4 features + species)

## Conda Configuration
- `auto_activate_base: true` ensures base environment is always active
- `report_errors: false` prevents error reporting prompts
- Navigator version 2.6.3 comes with Anaconda3-2024.10-1, conda 24.11.3

## Common Issues

| Issue | Solution |
|-------|----------|
| Navigator crashes on import | Install conda_token compatibility shim |
| Navigator stuck on splash screen | Fix libstdc++ symlink for Mesa compatibility |
| Dock intercepts sidebar clicks | Auto-hide dock via gsettings |
| Navigator window hidden after relaunch | Only launch from post_start hook |
| Sidebar tabs don't respond to clicks | Known Qt Quick limitation; start on Home tab |
| Navigator slow first startup | Normal; 3-5 min on first run to build package index |
| Firefox first-run dialogs | Pre-configure Firefox profile with user.js |
