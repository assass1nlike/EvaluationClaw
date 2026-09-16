> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Diagrams.net (draw.io) Environment Notes

## Application Overview

- **Name**: diagrams.net (formerly draw.io)
- **Type**: Desktop diagramming application
- **Installation**: AppImage from GitHub releases
- **Version tested**: 26.0.9

## Key Technical Details

### Installation Method
- Download AppImage from: `https://github.com/jgraph/drawio-desktop/releases`
- Requires `libfuse2` for AppImage support
- Must use `--no-sandbox` flag in container environments

### File Format
- Native format: `.drawio` (XML-based)
- Can also save as `.xml`, export to PNG/PDF/SVG
- XML structure uses mxCell elements for shapes and connections

### XML Structure Analysis
```xml
<mxfile>
  <diagram name="Page-1">
    <mxGraphModel>
      <root>
        <mxCell id="0" />  <!-- Root cell -->
        <mxCell id="1" parent="0" />  <!-- Default parent -->
        <mxCell id="X" value="text" style="..." vertex="1" />  <!-- Shape -->
        <mxCell id="Y" value="" style="..." edge="1" />  <!-- Connection -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Key attributes:
- `vertex="1"` = shape (rectangle, diamond, etc.)
- `edge="1"` = connection line
- `style` attribute contains shape type info

### Useful Style Patterns
- `rounded=0` or `rounded=1` - rectangle roundedness
- `rhombus` - diamond/decision shape
- `ellipse` - oval/terminal shape
- `whiteSpace=wrap` - process rectangle

## Common Issues

### 1. Update Dialog on Startup
**Problem**: Draw.io checks for updates on every launch and shows dialog
**Solution**: Dismiss with Escape key in task setup scripts
```bash
for i in 1 2 3; do
    if DISPLAY=:1 wmctrl -l 2>/dev/null | grep -qi "update\|confirm"; then
        DISPLAY=:1 xdotool key Escape
        sleep 1
    fi
done
```

### 2. Sandbox Mode
**Problem**: AppImage fails in container without --no-sandbox
**Solution**: Always launch with `--no-sandbox` flag

### 3. Shape Detection
**Problem**: Counting shapes vs connections
**Solution**: Use grep for `vertex="1"` (shapes) and `edge="1"` (connections)
```bash
NUM_SHAPES=$(grep -c 'vertex="1"' "$FILE" | tr -d '\n' || echo "0")
NUM_CONNECTIONS=$(grep -c 'edge="1"' "$FILE" | tr -d '\n' || echo "0")
```

## Verification Approach

1. **Export script** runs in container:
   - Analyzes .drawio XML file
   - Counts shapes and connections
   - Detects shape types via style attributes
   - Searches for text content
   - Outputs JSON to /tmp/task_result.json

2. **Verifier** runs on host:
   - Uses copy_from_env to get JSON
   - Evaluates against task criteria
   - Returns pass/fail with score

## Useful Commands

```bash
# Launch draw.io
/opt/drawio/drawio.AppImage --no-sandbox

# Inspect diagram file
drawio-info /path/to/file.drawio

# Export to PNG (CLI)
drawio-export input.drawio output.png
```

## Performance Notes

- AppImage is ~140MB
- First launch takes ~5-8 seconds
- Subsequent operations are fast
- Memory usage: ~200-400MB

## Coordinate Scaling

CUA returns coordinates normalized to 1280x720. For 1920x1080 displays:
```python
actual_x = int(cua_x * 1920 / 1280)
actual_y = int(cua_y * 1080 / 720)
```

## Shape Palette Locations (1920x1080)

- General shapes panel: Left sidebar, ~x=100
- Rectangle: approx (97, 364) after scaling
- Shapes are dragged to canvas, not clicked

## Save Dialog Navigation

- Desktop button: ~(445, 183) in save dialog
- Save button: ~(1564, 100) in save dialog
- Filename field auto-focused on Ctrl+S
