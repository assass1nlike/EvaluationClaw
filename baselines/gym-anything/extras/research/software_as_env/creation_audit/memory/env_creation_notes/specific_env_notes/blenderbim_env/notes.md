> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# BlenderBIM (Bonsai) Environment Notes

## Overview

BlenderBIM environment for BIM/IFC architectural modeling tasks using Blender 4.2.4 LTS with the Bonsai (BlenderBIM) extension. Targets architects and construction engineers working with IFC building models.

## Installation Quirks

### Blender 4.2.4 Uses Python 3.11 (Not 3.12)

Blender 4.2.4 LTS bundles Python 3.11, not 3.12 as one might expect. The install script auto-detects the Python version:

```bash
BLENDER_PY_VER=$(/opt/blender/blender --background --python-expr "import sys; print(f'py{sys.version_info.major}{sys.version_info.minor}')" 2>/dev/null | grep -E '^py' | head -1)
```

This is critical because Bonsai release ZIPs are tagged by Python version (e.g., `bonsai_py311-0.8.5-alpha260306-linux-x64.zip`).

### Bonsai Extension Installation (3-Step Process)

Installing Bonsai is not a simple `apt install`. It requires:

1. **Install the extension ZIP** via Blender's CLI:
   ```bash
   /opt/blender/blender --command extension install-file -r user_default /path/to/bonsai.zip --enable
   ```

2. **Install bundled wheel dependencies** into Blender's Python:
   ```bash
   WHEELS_DIR="/home/ga/.config/blender/4.2/extensions/user_default/bonsai/wheels"
   "$BLENDER_PYTHON" -m pip install --no-deps "$WHEELS_DIR"/*.whl
   ```
   The `--no-deps` flag is important because Bonsai bundles specific versions.

3. **Fix tzfpy (native dependency)**:
   The bundled tzfpy wheel is often cp310-only (incompatible with py311). Install via pip and copy to the extension's site-packages:
   ```bash
   "$BLENDER_PYTHON" -m pip install tzfpy
   EXT_SP="/home/ga/.config/blender/4.2/extensions/.local/lib/python3.11/site-packages"
   cp -r $(python3 -c "import tzfpy; import os; print(os.path.dirname(tzfpy.__file__))") "$EXT_SP/"
   ```

### Blender Extension Site-Packages Path

Blender 4.2 uses a separate site-packages for extensions at:
```
/home/ga/.config/blender/4.2/extensions/.local/lib/python3.11/site-packages/
```
This is different from Blender's built-in Python site-packages. Libraries like tzfpy must be copied here for the extension system to find them.

## Real Data: FZK-Haus IFC Model

The environment uses the FZK-Haus IFC4 building model from Karlsruhe Institute of Technology (KIT):
- **URL**: `https://www.ifcwiki.org/images/e/e3/AC20-FZK-Haus.ifc`
- **Size**: ~2.5 MB
- **Contents**: Two-story residential house with:
  - 13 walls (IfcWallStandardCase)
  - 5 doors
  - 11 windows
  - 4 slabs
  - 2 storeys (Erdgeschoss and Dachgeschoss)

Many other IFC model download URLs (e.g., GitHub raw URLs for buildingSMART Sample-Test-Files) are broken or have moved. The ifcwiki.org URL is reliable.

## GUI Interaction Patterns

### XAUTHORITY Required for Root-Launched X11 Commands

All `xdotool`, `wmctrl`, `scrot` commands run as root need `XAUTHORITY=/home/ga/.Xauthority` in addition to `DISPLAY=:1`:

```bash
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool key Escape
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority wmctrl -l
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority scrot /tmp/screenshot.png
```

### Bonsai Extension Enable Race Condition

Do NOT use `--enable` flag with `blender --command extension install-file`. It causes partial class registration, and when you later try `bpy.ops.preferences.addon_enable()`, it fails with "already registered as a subclass". Instead:

1. Install without `--enable`: `blender --command extension install-file -r user_default bonsai.zip`
2. Install all wheel dependencies first
3. Then enable in a clean background session: `bpy.ops.preferences.addon_enable(module='bl_ext.user_default.bonsai')`

### setsid for Launching GUI Apps from SSH/Hooks

Blender must be launched with `setsid` to prevent it from being killed when the SSH session or hook script ends. **CRITICAL**: the `DISPLAY` env var must come BEFORE `setsid`, not after. `setsid` passes its arguments directly to exec and does not process shell variable assignments:

```bash
# CORRECT:
su - ga -c "DISPLAY=:1 setsid /opt/blender/blender > /tmp/blender_task.log 2>&1 &"

# WRONG (setsid tries to exec "DISPLAY=:1" as a program):
su - ga -c "setsid DISPLAY=:1 /opt/blender/blender > /tmp/blender_task.log 2>&1 &"
```

### Blender Splash Screen Dismissal

Blender shows a splash screen on first launch. The warm-up launch in post_start handles this, but task setup scripts should also dismiss dialogs:

```bash
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool key Escape
sleep 0.5
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool key Escape
```

### pgrep -c Bug

When using `pgrep -c` in a command substitution with `|| echo 0` fallback, the output gets corrupted because `pgrep -c` outputs "0" AND exits non-zero when no matches are found, causing both the pgrep output and the fallback to be captured. Use:

```bash
count=$(pgrep -c -f "/opt/blender/blender" 2>/dev/null) || count=0
```

Instead of:
```bash
count=$(pgrep -c -f "/opt/blender/blender" 2>/dev/null || echo 0)  # BUG: may get "0\n0"
```

## VNC Password Fix

The framework's `VNCSpec` defaults `password` to `None`. The runner code `vnc_cfg.password if vnc_cfg else "password"` returns `None` because `VNCSpec` is always created (so `vnc_cfg` is truthy but `.password` is `None`). Fix by explicitly setting in env.json:

```json
"vnc": {"password": "password"}
```

## Task Design Notes

### open_ifc_project (Easy)
- Blender launches empty; agent must use **File > Open IFC Project** (Bonsai-specific menu item, not standard File > Open)
- The IFC file is pre-placed at `/home/ga/IFCModels/duplex_apartment.ifc`

### inspect_wall_properties (Medium)
- IFC model is pre-loaded via `bpy.ops.bim.load_project(filepath=...)` in the setup script
- Agent must click a wall in the 3D viewport, then navigate to Properties panel to view IFC data

### create_new_ifc_project (Medium)
- Blender launches empty; agent must find Bonsai's "Create Project" button in Scene Properties
- After creating, agent must rename the project and save via **File > Save IFC**

## Bonsai API for Scripted IFC Operations

For task setup scripts that need to pre-load IFC files:

```python
import bpy
bpy.ops.bim.load_project(filepath='/path/to/model.ifc')
```

For querying IFC data in background mode (e.g., counting elements):

```python
import ifcopenshell
ifc = ifcopenshell.open('/path/to/model.ifc')
walls = ifc.by_type('IfcWall') + ifc.by_type('IfcWallStandardCase')
print(len(walls))
```

The ifcopenshell library path for Bonsai-installed version:
```
/home/ga/.config/blender/4.2/extensions/user_default/bonsai/libs/site/packages
```
