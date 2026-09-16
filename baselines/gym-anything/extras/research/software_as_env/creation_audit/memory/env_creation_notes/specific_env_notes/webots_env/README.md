> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Webots Environment Notes

## Overview

The Webots environment provides a Cyberbotics Webots R2023b robot simulator for 3D robotics simulation tasks, running inside a QEMU VM with Mesa software rendering.

## Installation Quirks

### Package Download
- **Webots R2023b** `.deb` downloaded from GitHub releases (~146 MB)
- URL: `https://github.com/cyberbotics/webots/releases/download/R2023b/webots_2023b_amd64.deb`
- Fallback: R2025a if R2023b is unavailable
- Install with `dpkg -i || true` followed by `apt-get install -f -y` to resolve dependencies

### Memory Requirements
- Webots installation + Mesa rendering requires **8 GB RAM minimum**
- Earlier tests with 6 GB caused SIGKILL (OOM) during `dpkg` operations
- The `.deb` post-install scripts are memory-hungry

### Install Path
- Binary: `/usr/local/webots/webots`
- Symlink: `/usr/local/bin/webots`
- Demo worlds: `/usr/local/webots/projects/samples/demos/worlds/`
- Available demos: `soccer.wbt`, `highway_overtaking.wbt`, `moon.wbt`, and 3 others

### Dependencies
- Mesa/OpenGL: `libgl1-mesa-dri`, `libglu1-mesa`, `libegl1-mesa`, `mesa-utils`
- Qt/XCB: `libxkbcommon-x11-0`, `libxcb-xinerama0`, `libxcb-icccm4`, `libxcb-image0`, `libxcb-keysyms1`, `libxcb-render-util0`
- GUI tools: `xdotool`, `wmctrl`, `scrot`, `x11-utils`

## Dialog Suppression

Webots shows several first-run dialogs (guided tour, telemetry consent, update check, welcome). These are suppressed via two mechanisms:

1. **Qt QSettings config file** at `/home/ga/.config/Cyberbotics/Webots-R2023b.conf`:
   ```ini
   [General]
   StartupMode=Pause
   telemetry=false
   updatePolicy=Never

   [MainWindow]
   dontShowAgainBox=guided_tour;telemetry;welcome;openWorld
   maximized=true
   ```

2. **`--batch` command-line flag**: Suppresses all interactive dialogs at runtime

Config files are created for both R2023b and R2025a versions. No warm-up launch is needed — this was removed because it consumed too much memory with software rendering and caused crashes.

## Service Timing Issues

### SSH After Checkpoint Restore
- Framework's `exec()` method tries SSH key auth first (no keys configured → fails with code 255)
- Falls back to paramiko password auth, which usually works
- Sometimes the first SSH attempt after checkpoint restore hangs or drops
- Workaround: The framework handles this internally via retry/fallback

### Webots Startup Time
- Webots takes 20-40 seconds to show a window with Mesa software rendering
- Task setup scripts use `wait_for_webots_window 90` with 2-second polling
- After window appears, an additional 5-second sleep is needed before the UI is fully interactive
- The `--mode=pause` flag ensures simulation doesn't start before the agent is ready

### Desktop Readiness
- `setup_webots.sh` sleeps 5 seconds at the start to wait for the GNOME desktop
- This is a conservative wait; the desktop is usually ready within 2-3 seconds after `post_start`

## Task Setup Pattern

All tasks follow the same pattern:
1. Source `/workspace/scripts/task_utils.sh` for shared utilities
2. Detect Webots installation via `detect_webots_home()`
3. Copy the needed demo world to a writable user directory (e.g., `/home/ga/webots_projects/`)
4. Kill any existing Webots instances
5. Launch Webots with `setsid`, `--batch`, `--mode=pause`, and the world file
6. Wait for the window with `wait_for_webots_window`
7. Focus and maximize with `focus_webots()`
8. Dismiss any residual dialogs with `xdotool key Escape/Return`
9. Take initial screenshot

### Why Copy World Files
Demo worlds in `/usr/local/webots/projects/` are read-only. Tasks that modify world properties (gravity, timestep) or save to new locations need a writable copy.

## Verification Approach

All verifiers are **stub verifiers** that return `passed: True`. Actual verification is done externally via VLM evaluators, which analyze screenshots of the Webots UI state.

The VLM approach is appropriate because:
- Webots world file format is complex (VRML-like `.wbt` files)
- Visual confirmation of property changes is straightforward from the scene tree
- Simulation running state is visible from the toolbar play/pause indicators

## Rendering Notes

- **No GPU in QEMU VM**: All rendering uses Mesa LLVMpipe (software)
- **`LIBGL_ALWAYS_SOFTWARE=1`** must be set in all Webots launch commands
- 3D viewport renders at acceptable quality for task verification
- Heavy scenes may render slowly; `soccer.wbt` works well as a lightweight demo
- `webots --version` crashes without a DISPLAY set (Qt plugin error) — not an issue during normal operation

## Useful Commands

```bash
# Check if Webots is installed
ls /usr/local/webots/webots

# Launch Webots with a world file (from inside VM)
DISPLAY=:1 LIBGL_ALWAYS_SOFTWARE=1 WEBOTS_HOME=/usr/local/webots \
    /usr/local/webots/webots --batch --mode=pause /path/to/world.wbt

# List available demo worlds
ls /usr/local/webots/projects/samples/demos/worlds/

# Check Webots window title (useful for task verification)
DISPLAY=:1 wmctrl -l | grep -i webots

# Kill Webots
pkill -f "webots"

# Check Webots logs
cat /tmp/webots_task.log
```

## Verification Gotchas

### Demo World Gravity Values Differ
- `soccer.wbt` has default Earth gravity (9.81) — good for tasks that start from Earth gravity
- `moon.wbt` has lunar gravity (1.62) — do NOT use for tasks that expect gravity=9.81
- Always check the demo world's actual gravity before writing task descriptions
- The `modify_gravity` task was initially set up with `moon.wbt` (gravity=1.62) but the task description said "currently set to 9.81". Fixed by switching to `soccer.wbt`.

### Save World As Keyboard Shortcut
- `Ctrl+Shift+S` in Webots is "Save World" (overwrites current file), NOT "Save World As..."
- "Save World As..." has no keyboard shortcut — must use File menu
- Agents need to navigate File > Save World As... for saving to a new path

### WorldInfo Field Editing
- Click a WorldInfo field in the scene tree to select it
- The editable spinbox appears in the properties panel below the scene tree
- After changing a value, press Enter to confirm — clicking elsewhere may not apply the change
- Double-click WorldInfo in the scene tree to expand it and see all fields

## Checkpoint Caching

The environment supports checkpoint caching at the `pre_start` level:
- `cache_level="pre_start"` creates a checkpoint after Webots is installed (saves ~3 min on subsequent launches)
- `cache_level="post_start"` would also cache the setup script results
- Checkpoint file: `checkpoint_<hash>_pre_start.qcow2` in the cache directory
