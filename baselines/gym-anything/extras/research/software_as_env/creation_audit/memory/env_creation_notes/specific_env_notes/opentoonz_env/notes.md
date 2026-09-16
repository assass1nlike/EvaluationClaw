> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenToonz Environment Notes

## Overview

OpenToonz is a free, open-source 2D animation software originally developed by Digital Video (now part of DWANGO). It has been used by major animation studios including Studio Ghibli and Rough Draft Studios.

## Installation

The environment uses snap to install OpenToonz:
```bash
snap install opentoonz
```

Alternative installation methods if snap fails:
- Debian Multimedia repository (apt)
- Flatpak
- AppImage from Morevna Project

## Sample Data

Official sample data is downloaded from:
- GitHub: https://github.com/opentoonz/opentoonz_sample
- Official page: https://opentoonz.github.io/e/download/sample.html

Sample scenes include:
- `dwanko_run.tnz` - Camera follow shot with ray light effect
- `cleanup.tnz` - Cleanup process demonstration
- `tga_paint.tnz` - Ink & paint work testing

**Location**: `/home/ga/OpenToonz/samples/`

## TNZ File Format

TNZ files are OpenToonz scene files containing:
- XML-formatted data specifying scene properties
- References to assets (not the assets themselves)
- Project settings and timeline information

## Known Issues & Solutions

### 1. Startup Dialogs
OpenToonz shows multiple dialogs on first run:
- "OpenToonz Startup" dialog - project wizard
- "Information" dialog - version info

**Solution**: The setup script:
1. Waits for main window to appear (polling with timeout)
2. Uses wmctrl + xdotool to dismiss dialogs
3. Multiple retry loops for reliability

### 2. Firefox Auto-Opening
The snap version sometimes opens Firefox to the OpenToonz homepage.

**Solution**: `pkill -f firefox` after dialog dismissal

### 3. Long Startup Time
OpenToonz takes ~20-30 seconds to fully initialize.

**Solution**: Wait 20 seconds after launch, then poll for main window

### 4. Preferences Not Applied
The preferences.ini file doesn't fully disable startup dialogs.

**Solution**: Programmatic dialog dismissal is required

## Verification Strategy

The render_animation task verifies:
1. Output video file exists (30 points)
2. File size >= 10KB (30 points)
3. Render success indicator (20 points)
4. New output created vs initial state (20 points)

Pass threshold: Output found AND file size >= 10KB

## Resources

- Documentation: https://opentoonz.readthedocs.io/
- Official Website: https://opentoonz.github.io/e/
- GitHub: https://github.com/opentoonz/opentoonz

## Debugging Tips

1. Check OpenToonz logs:
   ```bash
   cat /tmp/opentoonz.log
   ```

2. Verify OpenToonz is running:
   ```bash
   ps aux | grep -i toonz
   ```

3. Check sample data location:
   ```bash
   ls -la /home/ga/OpenToonz/samples/
   ```

4. Check window state:
   ```bash
   DISPLAY=:1 wmctrl -l
   ```

5. Take screenshot for debugging:
   ```bash
   DISPLAY=:1 scrot /tmp/debug.png
   ```

## Final Verification (Completed 2026-01-23)

All Phase 7.2 checklist items verified:
- [x] Installation script completes without errors
- [x] Setup script completes without errors
- [x] Application is visible in screenshot
- [x] Application is in correct initial state (no dialogs, maximized)
- [x] Task setup runs without errors
- [x] Export script produces valid JSON
- [x] Verifier can read and process the result
- [x] Verification returns expected result
