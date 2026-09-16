> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# LibreCAD Environment — Creation Notes

## Installation

- Package: `apt-get install librecad` (version 2.1.3-3 on Ubuntu)
- Additional tools: `scrot`, `wmctrl`, `xdotool`, `imagemagick`, `poppler-utils`, `wget`, `curl`
- Python DXF library: `pip3 install ezdxf --break-system-packages`

## Real Data Source

**floorplan.dxf** — Apache-licensed real architectural floor plan (2-car garage)
- URL: `https://raw.githubusercontent.com/jscad/sample-files/master/dxf/dxf-parser/floorplan.dxf`
- Size: ~1.1 MB (1,117,143 bytes)
- Layers: 24 (A-DIMS-1, A-NOTE, A-TEXT, ANNTEXT, xref-Bishop-Overland-* series, etc.)
- Entities: 967 total (TEXT, LINE, ARC, INSERT)
- Contains: wall bracing specs, "2 CAR GARAGE 21'2 x 20'10" label, "16070 O.H. DOOR", dimension annotations

**CRITICAL**: Always hard-fail (exit 1) if file is < 100KB. No synthetic fallback allowed.

## First-Run Dialog Suppression

Pre-write config file with `FirstLoad=false` before warm-up launch:
```
mkdir -p /home/ga/.config/LibreCAD
cat > /home/ga/.config/LibreCAD/LibreCAD.conf << 'EOF'
[Startup]
FirstLoad=false
[Units]
Default=4
[Window]
Maximized=true
EOF
```

Then warm-up launch:
```bash
su - ga -c "DISPLAY=:1 librecad > /tmp/librecad_warmup.log 2>&1 &"
sleep 8
su - ga -c "DISPLAY=:1 xdotool key Return" 2>/dev/null || true
sleep 2
pkill -f librecad 2>/dev/null || true
```

## Task Setup Scripts

**CRITICAL**: When SSHed in as `ga`, do NOT use `su - ga` inside scripts — that requires a password and fails. SSH directly as `ga` and use `DISPLAY=:1 librecad ...` directly.

The setup scripts use `su - ga` which works when invoked as root from post_start hook, but fails when called interactively as `ga`. The setup scripts are designed for root-level execution (by the gym_anything hook system), which is correct.

For interactive testing: launch LibreCAD directly without `su`:
```bash
DISPLAY=:1 librecad /home/ga/Documents/LibreCAD/floorplan.dxf > /tmp/librecad_task.log 2>&1 &
```

## Screenshot Capture

- **CORRECT**: `import -window root /tmp/screen.png` — captures GNOME composited desktop
- **WRONG**: `scrot /tmp/screen.png` — returns black (compositor issue)
- **WRONG**: VNC screenshot — returns black (compositor issue)

Window-specific: `import -window <WID> /tmp/screen.png` (WID from `wmctrl -l`)
- LibreCAD window is 1850×1016 (GNOME work area, not full 1920×1080)

## Coordinate Scaling

- visual_grounding returns 1280×720 coords
- Screenshot resolution is 1920×1080 (full desktop) or 1850×1016 (window)
- For full desktop: `actual_x = vg_x * 1920/1280 = vg_x * 1.5`
- For full desktop: `actual_y = vg_y * 1080/720 = vg_y * 1.5`

## LibreCAD UI Notes

- **Layers**: Layer list panel on right side (~x=1088-1280)
- **Command area**: Bottom of window — "Command:" prompt accepts coordinate input
- **Rectangle tool**: Tools > Line > Rectangle (NOT a single-click toolbar button)
- **Dimension tool**: Tools > Dimensions > Aligned/Horizontal (for DIMLINEAR type)
- **Text tool**: Tools > Text
- **Export to PDF**: File > Export > Export as PDF (NOT File > Print Preview for saving)
- Window starts maximized due to `Maximized=true` in config

## DXF Verification (ezdxf)

```python
import ezdxf
doc = ezdxf.readfile('/home/ga/Documents/LibreCAD/floorplan.dxf')
msp = doc.modelspace()

# Check layers
layers = [l.dxf.name for l in doc.layers]

# Check entities
entities = list(msp)

# Add layer
doc.layers.add("Dimensions", dxfattribs={"color": 7})

# Check for dimension entities
dims = [e for e in msp if e.dxftype() == 'DIMENSION']

# Save
doc.saveas('/home/ga/Documents/LibreCAD/output.dxf')
```

## Environment Config (env.json key fields)

```json
{
  "id": "librecad_env@0.1",
  "base": "ubuntu-gnome-systemd_highres",
  "resources": {"cpu": 4, "mem_gb": 4, "gpu": 0, "net": true},
  "vnc": {"password": "password"},
  "user_accounts": [{"name": "ga", "password": "password123", "uid": 1000, "sudo": true}]
}
```

## Tasks Summary

| Task | Input | Output | Key verification |
|------|-------|--------|-----------------|
| draw_rectangle | New blank drawing | rectangle_task.dxf | 4 LINE entities at (0,0)-(3000,0)-(3000,2000)-(0,2000) |
| add_layer | floorplan.dxf | floorplan_layers.dxf | Layers "Dimensions" (red=1) and "Notes" (blue=5) exist |
| add_dimensions | floorplan.dxf | floorplan_dims.dxf | New layer "Dimensions" + DIMENSION entity present |
| export_to_pdf | floorplan.dxf | floorplan_export.pdf | PDF file exists and is > 1KB |
| modify_text | floorplan.dxf | floorplan_text.dxf | TEXT entity with "APPROVED FOR CONSTRUCTION" on layer A-TEXT |

## Known LibreCAD Behaviors

1. LibreCAD logs `RS_FilterDXF::addLayer: layer View Port have extended data` when loading floorplan.dxf — this is normal, not an error.
2. LibreCAD can crash when multiple concurrent xdotool/wmctrl commands hit it — serialize operations with sleeps.
3. The `RS_DEBUG` output at startup is normal debug spew, not errors.
4. LibreCAD's command-line area (bottom panel) accepts coordinate input, but the GUI rectangle tool requires two canvas clicks.
5. Layer colors in DXF use ACI (AutoCAD Color Index): 1=red, 2=yellow, 3=green, 4=cyan, 5=blue, 6=magenta, 7=white/black.

## Verifier Notes

All verifiers use `ezdxf` to parse the output DXF:
- Layer existence check: `doc.layers.get("LayerName")`
- Entity checks: iterate `doc.modelspace()` for entity types
- PDF check: `os.path.exists()` + `os.path.getsize()` > 0
- Text content check: compare `entity.dxf.text` (case-insensitive or exact as specified)
