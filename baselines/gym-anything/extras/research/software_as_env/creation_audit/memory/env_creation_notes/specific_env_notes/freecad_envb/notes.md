> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# FreeCAD Environment (freecad_envb) — Creation Notes

## Overview
- FreeCAD 0.19.2 on Ubuntu 22.04 (via `apt-get install freecad`)
- 5 tasks: create_box, create_cylinder, create_sketch, export_to_stl, fuse_shapes
- All tasks run in a QEMU VM with VNC display at 1920x1080

## Installation
- `apt-get install -y freecad` installs FreeCAD 0.19.2
- Also install `wmctrl`, `xdotool` for window management and GUI automation
- FreeCAD binary at `/usr/bin/freecad`

## Critical: FCStd File Creation Must Use GUI Mode

**Problem**: Creating FCStd files headlessly (Python with PYTHONPATH set to FreeCAD libs) produces files
WITHOUT a `GuiDocument.xml`. When FreeCAD opens such files, the 3D viewport is empty — no objects appear.

**Root Cause**: The `GuiDocument.xml` file inside the FCStd zip contains:
- ViewObject visibility flags for each object
- Camera position/orientation for the viewport
- DiffuseColor, LineColorArray, PointColorArray per object

Without GuiDocument.xml, FreeCAD has no viewport data and shows an empty scene.

**What Does NOT Work**:
- `python3 script.py` with `PYTHONPATH=/usr/lib/freecad-python3/lib` — no FreeCADGui, no GuiDocument.xml
- `FreeCADGui.setupWithoutGUI()` — only 7 methods, does NOT generate GuiDocument.xml on save
- Manually injecting GuiDocument.xml — error-prone (need exact DiffuseColor XML structure, wrong camera)

**What WORKS**:
```bash
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority freecad /tmp/create_samples.py
```
When FreeCAD runs a Python script as a macro (passing script path as argument in GUI mode), it has full
FreeCADGui access. The `doc.saveAs()` call writes complete FCStd with proper GuiDocument.xml.

## Critical Macro Patterns

### Setting Visibility
Use `obj.ViewObject.Visibility` NOT `Gui.ActiveDocument.getObject(obj.Name).Visibility`:
```python
for obj in doc.Objects:
    if hasattr(obj, 'ViewObject') and obj.ViewObject is not None:
        obj.ViewObject.Visibility = (obj.Name == 'Bracket')  # only show final shape
```

### Setting Camera (Required!)
Call `Gui.SendMsgToActiveView('ViewFit')` before saving. Default camera height is 4mm — too small to
see any geometry. ViewFit auto-fits all visible objects and persists camera in GuiDocument.xml:
```python
Gui.SendMsgToActiveView('ViewFit')
import time; time.sleep(0.5)  # let FreeCAD process the view change
doc.saveAs('/opt/freecad_samples/bracket.FCStd')
```

### Close FreeCAD After Macro
```python
App.closeDocument(doc.Name)
Gui.getMainWindow().close()  # kill the FreeCAD process cleanly
```

## Sample Files Created

### bracket.FCStd (17+ KB)
- 80x60x10mm mounting bracket plate with 4 bolt holes (M8 clearance, 9mm diameter)
- Hole positions: (10,10), (70,10), (10,50), (70,50) mm
- Final solid named `Bracket` (important: matches task description)
- Intermediate objects named BracketCut1–BracketCut3 (hidden)
- Stored in `/opt/freecad_samples/bracket.FCStd`

### two_boxes.FCStd (5+ KB)
- Two overlapping 40x30x20mm boxes, Box2 offset +20mm in X from Box1
- Both Box1 and Box2 visible (needed for fuse_shapes task)
- Stored in `/opt/freecad_samples/two_boxes.FCStd`

Verify with: `stat -c%s /opt/freecad_samples/bracket.FCStd` → should be >5000 bytes.
If < 1000 bytes, it was created headlessly and lacks GuiDocument.xml.

## Combo View (Model Tree Panel)

**Problem**: After warm-up launch, FreeCAD saves its layout state WITH Python console visible but WITHOUT
Combo View. Subsequent launches inherit this layout — no model tree on the left.

**What Does NOT Work**:
- `xdotool key ctrl+shift+c` — no effect in FreeCAD 0.19
- Expecting layout to persist between processes (pkill kills the process, config may not be saved)

**What WORKS** — navigate via menu in each setup_task.sh:
```bash
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool mousemove 153 72 click 1   # View menu
sleep 0.6
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool mousemove 177 603 click 1  # Panels
sleep 0.6
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool mousemove 561 655 click 1  # Combo View
```
These are actual pixel coordinates at 1920x1080 resolution (VG coords × 1.5).

## XAUTHORITY Required

All commands that touch the display must include XAUTHORITY when running as root:
```bash
su - ga -c "DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority freecad ..."
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool ...
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority wmctrl ...
```
Without XAUTHORITY, X11 commands silently fail (no error, no effect).

## Viewport Fit After Loading

For tasks that open an existing file, add viewport fit after Combo View navigation:
```bash
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool mousemove 900 500 click 1  # focus viewport
sleep 0.3
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool key v   # FreeCAD view key
sleep 0.3
DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool key f   # fit all
```
This uses FreeCAD's V+F shortcut to fit the view, same as View > Standard views > Fit All.

## FreeCAD 0.19 user.cfg Suppression

Suppress the Start Center (splash screen with recent files) via user.cfg:
```xml
<?xml version='1.0' encoding='utf-8'?>
<FCParameters>
  <FCParamGroup Name="Root">
    <FCParamGroup Name="BaseApp">
      <FCParamGroup Name="Preferences">
        <FCParamGroup Name="General">
          <FCText Name="AutoloadModule">PartWorkbench</FCText>
          <FCBool Name="CheckOpenFileAtStartUp" v="0"/>
        </FCParamGroup>
        <FCParamGroup Name="Mod">
          <FCParamGroup Name="Start">
            <FCBool Name="ShowOnStartup" v="0"/>
            <FCBool Name="AllowOpenFileAtStartup" v="0"/>
          </FCParamGroup>
        </FCParamGroup>
      </FCParamGroup>
    </FCParamGroup>
  </FCParamGroup>
</FCParameters>
```
Write to `/home/ga/.FreeCAD/user.cfg` in pre_start.

## Verified Coordinates (1920x1080)

All coordinates are actual pixel values (VG returns 1280x720 scale, multiply by 1.5):
- View menu: (153, 72)
- View > Panels: (177, 603)
- View > Panels > Combo View: (561, 655)
- Viewport center (safe click): (900, 500)

## Task Start States Verified

All 5 tasks confirmed working interactively:
1. **create_box**: FreeCAD opens with empty "Unnamed" doc, Part workbench, Combo View visible
2. **create_cylinder**: Same as create_box (identical setup)
3. **create_sketch**: Same as create_box — agent must switch to Sketcher workbench
4. **export_to_stl**: FreeCAD opens bracket.FCStd, bracket visible in top view, 'Bracket' in tree
5. **fuse_shapes**: FreeCAD opens two_boxes.FCStd, Box1+Box2 visible, both shown in tree

## File Sizes

Healthy FCStd files created in GUI mode:
- bracket.FCStd: ~17323 bytes
- two_boxes.FCStd: ~5377 bytes

If files are only ~1-3KB, they were created headlessly and lack GuiDocument.xml — rebuild using GUI macro.

## Verifier Scripts

Each task verifier (verify.sh) checks:
- **create_box**: Output file box_model.FCStd exists, size > 1000 bytes, contains Document.xml with Part::Box type
- **create_cylinder**: cylinder_model.FCStd exists, contains Part::Cylinder type
- **create_sketch**: sketch_model.FCStd exists, contains Sketcher::SketchObject type
- **export_to_stl**: exported_model.stl exists, size > 1000 bytes (valid STL), starts with "solid"
- **fuse_shapes**: fused_model.FCStd exists, contains Part::MultiFuse or Part::Fuse type
