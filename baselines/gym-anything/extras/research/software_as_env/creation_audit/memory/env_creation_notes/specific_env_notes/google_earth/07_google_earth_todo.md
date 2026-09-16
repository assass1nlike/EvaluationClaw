> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Google Earth Environment - Remaining Work

## Status: Partially Complete

### What's Done
- [x] Directory structure created
- [x] env.json created
- [x] install_google_earth.sh - works, installs successfully
- [x] setup_google_earth.sh - creates desktop shortcut
- [x] 5 task folders with task.json, verifier.py, setup/export scripts
- [x] constants.py updated
- [x] Execute permissions set on scripts

### What's Verified Working
- [x] Environment starts successfully
- [x] Google Earth Pro installs correctly
- [x] Google Earth Pro launches and shows globe
- [x] Screenshots can be captured
- [x] SSH access works

### What Needs Work

#### 1. First-Run Dialog Handling
Google Earth shows multiple dialogs on first launch:
- "Start-up Tips"
- "Not all terrain data" notification
- "Find infrastructure assets" promotional popup

**TODO:** Create pre-configured settings in `config/googleearth/` to suppress these.

#### 2. Task Verifiers Need Testing
None of the verifier.py files have been tested against actual task completion.

**TODO:** For each task, manually complete it and verify the verifier correctly detects success.

#### 3. setup_task.sh Scripts Need Review
The task setup scripts attempt to start Google Earth, but:
- May cause "multiple instance" warnings
- Don't handle existing running instances

**TODO:** Update scripts to check for running instance first.

#### 4. UI Automation Strategy
Direct xdotool interaction with Google Earth proved unreliable.

**TODO:** Consider alternative verification approaches:
- Check for created KML files
- Check myplaces.kml modifications
- Use screenshot comparison with reference images

### Tasks Status

| Task | Setup Script | Verifier | Tested |
|------|-------------|----------|--------|
| navigate_to_location | Created | Created | No |
| search_coordinates | Created | Created | No |
| measure_distance | Created | Created | No |
| create_placemark | Created | Created | No |
| take_screenshot | Created | Created | No |

### Open Questions
1. Can Google Earth be controlled via command-line arguments?
2. Is there a way to pre-load a specific location on startup?
3. Can we disable all first-run dialogs via config files?
