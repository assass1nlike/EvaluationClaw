> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Google Earth Pro Environment - Lessons Learned

## What Works

### Installation
- Google Earth Pro installs successfully via .deb package
- Location: `/usr/bin/google-earth-pro`
- Free since 2015, no license issues

### Starting the Application
```bash
DISPLAY=:1 nohup google-earth-pro >/dev/null 2>&1 &
```

### Verification that it's running
```bash
ps aux | grep google-earth | grep -v grep
DISPLAY=:1 wmctrl -l  # Shows "Google Earth Pro" window
```

## Known Issues

### First-Run Dialogs
Google Earth shows multiple dialogs on first launch:
1. "Start-up Tips" dialog
2. "Not all terrain data in this area" notification
3. "Find infrastructure assets" promotional overlay
4. Possible "Another instance running" warning if started twice

### UI Automation Difficulties
- Search/Fly To functionality was difficult to trigger via xdotool
- Clicking in sidebar often missed the input field
- GNOME Activities overlay interferes with clicks near top-left

### Network Dependency
- Requires internet to load satellite imagery (`net: true` in env.json)
- Without network, shows blank globe

## Recommendations for Tasks

### Avoid UI-dependent verification
Instead of verifying the user navigated by checking screenshots, consider:
- Checking if specific KML files were created in `~/.googleearth/`
- Checking `myplaces.kml` for new placemarks
- Using screenshot comparison as a fallback, not primary verification

### Pre-configure to reduce dialogs
Create config files in `config/googleearth/` to:
- Disable startup tips
- Accept terms
- Set default view

### Task design
- Tasks that create files (placemarks, screenshots) are easier to verify
- Navigation tasks are hard to verify without reliable UI automation
- Measurement tasks leave no persistent state - difficult to verify
