> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# SolveSpace Environment — Creation Notes

## Installation

- Package: `apt-get install solvespace` (version 3.0.rc2 on Ubuntu 22.04)
- Also installs `solvespace-cli` bundled in the same package
- Additional tools: `scrot`, `wmctrl`, `xdotool`, `imagemagick`, `wget`, `curl`, `unzip`, `file`
- Paths: `/usr/bin/solvespace`, `/usr/bin/solvespace-cli`

## Real Data Source

**Official SolveSpace tutorial box parts** — real parametric CAD parts from SolveSpace's own documentation.
- URL: `https://solvespace.com/dl/box-parts.zip` (~40KB zip)
- Source: `https://solvespace.com/box.pl` (official SolveSpace assembly tutorial)
- Extracted to: `/opt/solvespace_samples/`
- Files:
  - `base.slvs` — 259085 bytes — floor/lid of the wooden box
  - `divider.slvs` — 80251 bytes — internal divider panel (2D profile)
  - `side.slvs` — 252461 bytes — side panel with dado/groove cutouts

**CRITICAL**: Always hard-fail (exit 1) if any of these files is < 100 bytes.

### Do NOT download box-asm.zip
- `box-asm.zip` also exists at `https://solvespace.com/dl/box-asm.zip` but contains `side.slvs` which overlaps with `box-parts.zip`
- Without the `-o` (overwrite) flag, `unzip -q` prompts interactively when a file exists
- This hangs SSH commands → timeout of the `pre_start` hook
- Tasks only need `box-parts.zip`; do NOT download `box-asm.zip`

## First-Run Dialog Suppression

SolveSpace uses a JSON config at `~/.config/solvespace/settings.json`:
```bash
mkdir -p /home/ga/.config/solvespace
cat > /home/ga/.config/solvespace/settings.json << 'EOF'
{
    "checkForUpdates": false
}
EOF
chown -R ga:ga /home/ga/.config/solvespace
```

Warm-up launch in post_start:
```bash
su - ga -c "DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority solvespace > /tmp/solvespace_warmup.log 2>&1 &"
sleep 8
su - ga -c "DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority xdotool key Escape" 2>/dev/null || true
sleep 2
pkill -f /usr/bin/solvespace 2>/dev/null || true
sleep 1
```

## Screenshot Capture

- **CORRECT**: `DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority import -window root /tmp/screen.png`
- **WRONG**: `scrot` — returns black screenshot with GNOME compositor
- VNC-based screenshots also work via `VNCConnection("localhost", 5900, password="password")`

## Coordinate Scaling

- `visual_grounding` returns 1280×720 normalized coords
- Actual resolution: 1920×1080
- Scale factor: `actual = vg * 1.5`

## SolveSpace UI Structure (version 3.0.rc2)

### Menu bar
```
File | Edit | View | Group | Sketch | Constrain | Analyze | Help
```

### Key menu items
| Action | Menu path | Shortcut |
|--------|-----------|----------|
| New file | File > New | Ctrl+N |
| Open file | File > Open | Ctrl+O |
| Save | File > Save | Ctrl+S |
| Save As | File > Save As | Ctrl+Shift+S |
| Export 2D section | File > Export 2d Section... | Ctrl+Shift+2 |
| Export mesh (STL/OBJ) | File > Export Mesh... | Ctrl+Shift+M |
| Line segment | Sketch > Line Segment | L |
| Rectangle | Sketch > Rectangle | R |
| Circle | Sketch > Circle | C |
| Arc | Sketch > Arc of Circle | A |
| Horizontal constraint | Constrain > Horizontal | H |
| Vertical constraint | Constrain > Vertical | V |
| Distance/Diameter | Constrain > Distance / Diameter | D |
| Perpendicular | Constrain > Perpendicular | I |
| Parallel/Tangent | Constrain > Parallel / Tangent | L |
| Equal length | Constrain > Equal Length / Radius | Q |
| New extrude group | Group > New Group > Extrude | - |
| New revolve group | Group > New Group > Revolve | - |

### Workflow for 3D extrusion
1. Draw 2D sketch in default XY workplane (group g001)
2. Add constraints (horizontal, vertical, distance)
3. Group menu → New Group → Extrude
4. A new extrude group is created; set depth in property browser
5. File > Save

### Export to DXF workflow
1. File > Export 2d Section... (Ctrl+Shift+2)
2. File chooser dialog opens; set filename with `.dxf` extension
3. Format is auto-detected by extension; click Save

## Task Setup Script Pattern

Each `setup_task.sh` follows:
```bash
#!/bin/bash
set -e
source /workspace/scripts/task_utils.sh

# Clean any previous output
rm -f /home/ga/Documents/SolveSpace/<output_file>

# Kill any existing SolveSpace
kill_solvespace

# Launch SolveSpace (with or without file)
launch_solvespace [/opt/solvespace_samples/input.slvs]

# Wait and settle
wait_for_solvespace 30
sleep 5

# Maximize
maximize_solvespace

# Take start-state screenshot
take_screenshot /home/ga/Documents/SolveSpace/task_start.png
```

## Process Management

```bash
# Kill SolveSpace
pkill -f /usr/bin/solvespace; sleep 2; pkill -9 -f /usr/bin/solvespace 2>/dev/null || true

# Check if running
pgrep -f /usr/bin/solvespace

# Detect window
wmctrl -l | grep -i solvespace

# Maximize window
wmctrl -r "SolveSpace" -b add,maximized_vert,maximized_horz
```

## Task Files

| Task | Input | Output | Key action |
|------|-------|--------|------------|
| `draw_rectangle` | (none) | `rectangle.slvs` | Draw 80×50mm constrained rectangle |
| `draw_circle` | (none) | `circle.slvs` | Draw circle with radius=25mm constraint |
| `export_to_dxf` | `divider.slvs` | `divider.dxf` | File > Export 2d Section (Ctrl+Shift+2) |
| `extrude_sketch` | (none) | `block.slvs` | Draw 40×30mm rect, extrude 15mm via Group > New Group > Extrude |
| `add_constraint` | `side.slvs` | `side_constrained.slvs` | Add horizontal constraint via Constrain > Horizontal (H) |

## .slvs File Format

Binary header: `±²³` (3-byte magic) followed by text content.
- Groups: `Group.v 5000` = References (always present), `5001` = Sketch-in-plane, `5100` = Extrude, `5201` = Translate
- Constraints: type 20 = Horizontal, type 21 = Vertical, type 31 = Distance/Diameter
- Entities: Line segments, arcs, circles stored with their UUIDs

## Known Issues / Lessons Learned

1. **Interactive unzip**: NEVER use `unzip -q` without `-o` when the destination file may already exist. Use `unzip -q -o` or remove destination first.

2. **SSH timeout from pre_start**: The `pre_start` hook runs as root via SSH. If any command prompts interactively (like unzip overwrite prompt), SSH times out. All commands must be non-interactive.

3. **solvespace --version without DISPLAY**: Running `solvespace --version` in pre_start (no X11) causes `Gtk-WARNING: cannot open display:`. Use `2>&1 || true` to suppress. Not critical — just version logging.

4. **wait_for_solvespace polling**: Uses `wmctrl -l | grep -i solvespace`. SolveSpace window title is literally "SolveSpace" (not filename until a file is opened). After loading a file it becomes "filename.slvs – SolveSpace".

5. **File paths with spaces**: `/opt/solvespace_samples/` filenames don't have spaces; `/home/ga/Documents/SolveSpace/` doesn't have spaces. No quoting issues.
