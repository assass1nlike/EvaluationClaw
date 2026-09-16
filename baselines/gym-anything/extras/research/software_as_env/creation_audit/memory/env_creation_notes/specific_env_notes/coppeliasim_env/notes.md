> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# CoppeliaSim Environment - Specific Notes

## Application Details

- **App**: CoppeliaSim EDU V4.9.0 rev6
- **Download**: https://downloads.coppeliarobotics.com/V4_9_0_rev6/CoppeliaSim_Edu_V4_9_0_rev6_Ubuntu22_04.tar.xz
- **License**: Free for education/research (EDU license)
- **Install location**: /opt/CoppeliaSim
- **Launcher**: /usr/local/bin/coppeliasim

## Key Dependencies

- Qt5 libraries (libqt5core5a, libqt5gui5, libqt5widgets5, libqt5opengl5)
- Mesa OpenGL (libgl1-mesa-dev, libgl1-mesa-dri) for software rendering
- X11 libraries for display
- Multimedia codecs (libavcodec, libavformat, libswscale)
- Python packages: cbor, pyzmq (for ZMQ Remote API)

## Software Rendering

CoppeliaSim works with Mesa llvmpipe software rendering:
```bash
export LIBGL_ALWAYS_SOFTWARE=1
```
This is set in env.json user_accounts env_vars and in all launch scripts.

## Installation Quirks

1. **Download URL versioning**: The tar.xz filename contains the version. A fallback to V4_9_0_rev2 is included if rev6 is unavailable.
2. **Extracted directory name varies**: The extracted folder is named like `CoppeliaSim_Edu_V4_9_0_rev6_Ubuntu22_04`, needs to be renamed to `/opt/CoppeliaSim`.
3. **Qt platform plugins**: Must set `QT_QPA_PLATFORM_PLUGIN_PATH=/opt/CoppeliaSim` or Qt plugins won't be found.

## First-Run Dialog Suppression

CoppeliaSim may show:
- OpenGL settings warning (Mesa software rendering is detected)
- Crash recovery dialog
- Update check notification
- Scene selection at startup

Suppressed via:
1. Pre-creating config at **`~/.CoppeliaSim/usrset.txt`** (this is the REAL config path CoppeliaSim reads — NOT `~/.config/CoppeliaSim/`) with settings:
   - `doNotShowOpenglSettingsMessage = true`
   - `doNotShowCrashRecoveryMessage = true`
   - `doNotShowUpdateCheckMessage = true`
   - `doNotShowSceneSelectionAtStartup = true`
   - `preferredScriptingLanguage = lua`
   - `doNotShowLanguageSelectionAtStartup = true`
2. Warm-up launch in post_start to clear first-run state
3. Click "Set up for Lua" button at (867, 675) in 1920x1080 if Welcome dialog appears

**IMPORTANT**: The config is at `~/.CoppeliaSim/usrset.txt`, NOT `~/.config/CoppeliaSim/usrset.txt`. Both are written by setup_coppeliasim.sh as a safety net.

## Process Detection

Use full path to avoid false matches:
```bash
pgrep -f /opt/CoppeliaSim/coppeliaSim
```
NOT `pgrep coppeliaSim` (too generic).

## GUI Layout

CoppeliaSim has a rich GUI with:
- **Scene hierarchy** (left panel): tree of all scene objects
- **Model browser** (left panel, tab): drag-and-drop robot models
- **3D viewport** (center): main rendering area
- **Properties panel** (right): object properties, joint values
- **Script editor**: Lua scripting for robot control
- **Toolbar**: simulation controls (play, pause, stop)
- **Menu bar**: File, Edit, Add, Tools, etc.

## Task Design Notes

### Real Data
CoppeliaSim ships with:
- ~25+ demo scenes in `/opt/CoppeliaSim/scenes/` (pickAndPlaceDemo, motorControllerExamples, kinematics/*, hapticRobot, spot, youBotAndHanoiTower, etc.)
- ~100+ robot models in `/opt/CoppeliaSim/models/robots/` (UR3/5/10, Panda, KUKA, Jaco, etc.)
- These are production-grade simulation assets, not synthetic toy data

### Scene Files
CoppeliaSim uses `.ttt` format for scenes and `.ttm` for models. These are binary files.

### ZMQ Remote API
CoppeliaSim exposes a ZMQ-based remote API on port 23000 for programmatic scene inspection. Python client at:
```
/opt/CoppeliaSim/programming/zmqRemoteApi/clients/python/
```
Not always reliable from hooks — use as optional signal.

## Potential Issues

1. **Mesa rendering performance**: Software rendering is slow. Keep scene complexity reasonable.
2. **Large download**: The tar.xz is ~200MB. Ensure network is enabled in env.json.
3. **Qt5 version mismatch**: CoppeliaSim V4.9 bundles Qt5. If the base image has conflicting Qt5 libraries, there may be symbol errors. The `QT_QPA_PLATFORM_PLUGIN_PATH` setting helps.
4. **setsid required**: GUI app must be launched with `setsid` to survive SSH session termination (pattern #18).
