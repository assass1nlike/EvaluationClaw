> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ImageJ Environment - Creation Notes

## Environment Overview

- **ID**: `imagej_env@0.1`
- **Base**: `ubuntu-gnome-systemd_highres`
- **Application**: Fiji (ImageJ distribution with bundled plugins)
- **Category**: Science/Biology/Microscopy

## Installation Details

### Fiji Distribution Choice
- Used **Fiji** instead of vanilla ImageJ because:
  - Bundled plugins for common operations (Auto Threshold, Watershed, etc.)
  - Auto-update mechanism for plugins
  - More complete out-of-box experience
  - Community standard for bioimage analysis

### Download Source
- Official: https://fiji.sc/
- Direct Linux download: `https://downloads.imagej.net/fiji/latest/fiji-latest-linux64-jdk.zip`
- Fallback mirror: `https://downloads.micron.ox.ac.uk/fiji_update/mirrors/fiji-latest/fiji-latest-linux64-jdk.zip`

### Package Structure (Updated 2026)
- **Extracts to**: `Fiji/` directory (not `Fiji.app/` as older versions)
- **Executable**: `fiji-linux-x64` (native binary) or `fiji` (shell wrapper)
- **Java**: Bundled JDK, no separate installation needed

### CRITICAL: Fiji Wrapper Script Issue
The default `fiji` shell wrapper uses `$dir` to find executables, which breaks when symlinked:
- Symlink at `/usr/local/bin/fiji` → `$dir` becomes `/usr/local/bin` (wrong!)
- Native binary at `/opt/fiji/Fiji/fiji-linux-x64` can't be found

**Solution**: Create a proper wrapper script instead of symlinking:
```bash
cat > /usr/local/bin/fiji << 'EOF'
#!/bin/bash
cd /opt/fiji/Fiji || exit 1
exec ./fiji-linux-x64 "$@"
EOF
chmod +x /usr/local/bin/fiji
```

### Dependencies
- Java: OpenJDK 17 (Fiji bundles its own Java, but system Java as fallback)
- GUI tools: xdotool, wmctrl, scrot, imagemagick
- Python: numpy, scipy, pillow, scikit-image (for verification utilities)

## CRITICAL FINDING: Image Inversion Required

**Analyze Particles counts WHITE objects on BLACK background.**

When analyzing images like the 'blobs' sample:
- **Without inversion**: Count = 1 (entire white background counted as one object)
- **With inversion**: Count = 64 (correct particle count)

**Solution**: Always invert binary images before running Analyze Particles:
```
Edit > Invert (or Ctrl+Shift+I)
```

This is documented in:
- `task.json` description
- `setup_task.sh` instructions
- `evidence_docs/README.md`

## Service Timing Issues

### First-Run Dialogs (HANDLED AUTOMATICALLY)
Fiji shows ImageJ Updater dialog on first launch:
- Message: "Your ImageJ installation cannot be updated because it is read-only"
- **Automatically dismissed in setup_task.sh** using:
  ```bash
  UPDATER_WID=$(DISPLAY=:1 wmctrl -l | grep -i "Updater" | head -1 | awk '{print $1}')
  DISPLAY=:1 wmctrl -i -a "$UPDATER_WID"
  DISPLAY=:1 xdotool key Return
  ```
- Coordinates at 1920x1080: approximately (993, 367)

### Startup Timing
- Fiji takes 3-5 seconds to fully initialize
- Use `wmctrl` to detect window appearance:
  ```bash
  wait_for_fiji() {
      for i in {1..30}; do
          if wmctrl -l | grep -qi "ImageJ\|Fiji"; then
              return 0
          fi
          sleep 0.5
      done
      return 1
  }
  ```

### Memory Requirements
- Default heap: 4GB (set via `-Xmx4g`)
- For large images (BBBC005): Consider 4-6GB
- Set in launch script or Edit > Options > Memory & Threads

## Verification Notes

### Results File vs Summary File
- **Results table**: Individual measurements per particle (Area, Circularity, etc.)
- **Summary table**: Aggregate statistics (Count, Average Size, %Area)
- For count_particles task, Summary is sufficient

### Export Script Environment Variables
Environment variables must be `export`ed for Python heredocs:
```bash
export RESULTS_FILE=""
export SUMMARY_FILE=""
```

### Verifier Accepts Both File Types
Modified verifier to accept:
- `results_file_found` OR `summary_file_found`
- `results_window_visible` OR `summary_window_visible`

### CSV Format
- Summary CSV: `Slice,Count,Total Area,Average Size,%Area,Mean`
- Data line example: `blobs.gif,64,22243,347.547,34.207,255`

## Coordinate Scaling

CUA returns coordinates normalized to 1280x720. Scale to actual resolution:
```python
actual_x = int(cua_x * 1920 / 1280)
actual_y = int(cua_y * 1080 / 720)
```

## Data Sources

### BBBC005 Dataset
- **Source**: Broad Bioimage Benchmark Collection
- **URL**: https://data.broadinstitute.org/bbbc/BBBC005/
- **Description**: Synthetic fluorescence microscopy images with ground truth
- **Format**: 16-bit TIFF
- **Usage**: measure_cell_areas task

### Built-in Samples
- Accessed via File > Open Samples
- "Blobs" image used for count_particles task
- 256x254 pixels, 8-bit grayscale
- Contains approximately 64 particles

## Task-Specific Notes

### count_particles (Easy)
- Uses built-in "blobs" sample image
- **Workflow**:
  1. Open sample: File > Open Samples > Blobs
  2. Threshold: Image > Adjust > Threshold > Apply
  3. **INVERT**: Edit > Invert (Ctrl+Shift+I) ← CRITICAL
  4. Analyze: Analyze > Analyze Particles (with Summarize)
  5. Save: Summary table to CSV
- Expected: 50-80 particles (actual: 64)
- Average area: 300-400 px²

### measure_cell_areas (Medium)
- Uses BBBC005 fluorescence image
- 16-bit, needs conversion to 8-bit
- Requires: Gaussian blur → Threshold → Watershed → Analyze Particles
- Must measure circularity
- Expected: 10-200 cells

## Testing Results (2026-02-04)

### Verification Score: 75/100 (PASSED)
- Particle count: 64 (expected 50-80) ✓
- Average area: 347.55 px² (expected 100-500) ✓
- VLM checks: Skipped (not available in test)

### Setup Timing
- Environment setup: ~160 seconds
- Task hooks: ~68 seconds
- Total: ~230 seconds

## Second Audit Fixes (2026-02-04)

### Issue 1: Fiji Startup Unreliable
- **Problem**: First fix only worked intermittently (4/5 episodes had Fiji NOT running)
- **Root Cause**: Single launch attempt with insufficient error handling
- **Solution**: Implemented robust launch with retry logic:
  ```bash
  launch_and_verify_fiji() {
      # Kill lingering processes, launch Fiji, wait for window (90s timeout)
      # Monitor process for early termination
      # Handle Updater dialog automatically
      # Final verification before returning success
  }

  # Up to 3 attempts with explicit failure if all fail
  for attempt in 1 2 3; do
      if launch_and_verify_fiji $attempt; then
          FIJI_RUNNING=true
          break
      fi
  done

  if [ "$FIJI_RUNNING" = false ]; then
      exit 1  # Do not proceed with broken state
  fi
  ```

### Issue 2: Export Script Summary Parsing Bug
- **Problem**: Summary file parsed correctly (64 particles) but JSON output showed zeros
- **Root Cause**: Condition `[ "$PARTICLE_COUNT" -eq 0 ]` didn't properly trigger
- **Solution**: Always use summary data when valid count > 0:
  ```bash
  if [ -f "/tmp/summary_stats.json" ]; then
      SUMMARY_COUNT=$(python3 -c "..." 2>/dev/null)
      if [ "$SUMMARY_COUNT" -gt 0 ]; then
          PARTICLE_COUNT="$SUMMARY_COUNT"
          AVG_AREA=$(...)
          HAS_MEASUREMENTS="true"
      fi
  fi
  ```

## Common Agent Failure Modes

1. **Not inverting image** - Count = 1 instead of 64
2. **Forgetting to save Results** - Results visible but not exported
3. **Wrong threshold direction** - Light objects on dark vs dark on light
4. **Skipping watershed** - Touching cells counted as one
5. **Not enabling circularity** - Missing measurement column
6. **Binary conversion issues** - Not fully converting to 8-bit binary

## File Locations

| Component | Location |
|-----------|----------|
| Fiji binary | `/opt/fiji/Fiji/fiji-linux-x64` |
| Fiji wrapper | `/opt/fiji/Fiji/fiji` |
| Symlinks | `/usr/local/bin/fiji`, `/usr/local/bin/imagej` |
| Sample data | `/opt/imagej_samples/` |
| User data | `~/ImageJ_Data/` |
| Results | `~/ImageJ_Data/results/` |

## Environment Testing Checklist

- [x] Fiji downloads and extracts successfully
- [x] Sample images accessible in ~/ImageJ_Data/raw/
- [x] Fiji launches without errors
- [x] Built-in samples (blobs) open correctly
- [x] Analyze Particles produces Results/Summary table
- [x] Results can be saved to CSV
- [x] Export script generates valid JSON
- [x] Verifier parses results correctly
- [x] Verification passes with score >= 60

## File Structure
```
imagej_env/
├── env.json
├── scripts/
│   ├── install_imagej.sh      # Fiji installation
│   ├── setup_imagej.sh        # User configuration
│   └── task_utils.sh          # Shared utilities
├── tasks/
│   ├── count_particles/
│   │   ├── task.json
│   │   ├── setup_task.sh
│   │   ├── export_result.sh
│   │   └── verifier.py
│   └── measure_cell_areas/
│       ├── task.json
│       ├── setup_task.sh
│       ├── export_result.sh
│       └── verifier.py
├── config/                    # Configuration files
├── utils/                     # Python utilities
├── assets/                    # Task-specific assets
└── evidence_docs/
    ├── README.md              # Full documentation with logs
    ├── pre_start_log.txt      # Installation log
    ├── post_start_log.txt     # Configuration log
    ├── pre_task_log.txt       # Task setup log
    ├── export_result_log.txt  # Export script output
    └── *.png                  # Evidence screenshots
```

## Author
gym-anything team

**Last Updated**: 2026-02-04
