> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# CAMEO Chemicals Environment Notes

## Application Details
- **CAMEO Chemicals** is a NOAA/EPA hazardous materials database
- Web version at https://cameochemicals.noaa.gov/ (no desktop Linux app)
- Contains thousands of chemical datasheets, ERG guides, reactivity predictions
- Part of the CAMEO software suite (also includes ALOHA, MARPLOT, CAMEO Data Manager)

## Key Implementation Decisions

### Browser-Based Approach
- CAMEO Chemicals desktop app is Windows/macOS only — no Linux version
- Used Firefox to access the web version
- Requires `net: true` for internet access
- No Docker containers needed

### VNC Password Issue
- **CRITICAL**: The base image preset (`ubuntu-gnome-systemd_highres`) provides a default `VNCSpec` with `password=None`
- The QEMU runner logic: `vnc_cfg.password if vnc_cfg else "password"` — when `vnc_cfg` exists but `.password` is `None`, the VNC client cannot authenticate
- **Fix**: Explicitly set `"vnc": {"enable": true, "password": "password"}` in env.json
- Without this fix, `env.reset()` hangs indefinitely (VNC retries fail silently)

### Firefox Already in Base Image
- Firefox 146+ is pre-installed in the `ubuntu-gnome-systemd_highres` base image
- The install script's Firefox installation steps are mostly no-ops (already installed)
- The script still installs GUI automation tools (xdotool, wmctrl, scrot) and utilities
- Total pre_start time: ~224s (mostly apt operations)

### Firefox Profile Configuration
- Two-layer dialog suppression: user.js prefs + warm-up launch
- Homepage set to `https://cameochemicals.noaa.gov/`
- `browser.startup.page = 1` (load homepage on startup, not blank)
- All telemetry, updates, and first-run wizards disabled

### Warm-Up Launch Pattern
- Post_start launches Firefox, waits for window, then kills it
- This clears first-run state and creates initial profile data
- Pre_task then launches Firefox cleanly with the correct URL

## CAMEO Chemicals Website Structure
- **Homepage**: `https://cameochemicals.noaa.gov/` — links to Search, MyChemicals, Reactivity
- **Search**: `https://cameochemicals.noaa.gov/search/simple` — Name, CAS, UN/NA search
- **Reactivity**: `https://cameochemicals.noaa.gov/reactivity` — requires chemicals in MyChemicals
- **Reactive Groups**: `https://cameochemicals.noaa.gov/browse/react` — browse 68 reactive groups

## Reactivity Prediction Workflow
1. Search for chemical by name/CAS/UN number
2. View chemical datasheet
3. Click "Add to MyChemicals" on the datasheet
4. Repeat for second chemical
5. Navigate to Predict Reactivity page
6. View compatibility chart with hazard predictions

## Data Files
All use real chemical identifiers (UN numbers, CAS numbers, NFPA ratings):
- Chemical inventory CSV with 15 real industrial chemicals
- Hazmat incident scenarios with real UN classifications
- Workplace safety assessment requests

## Timing
- VM boot: ~30s
- Pre_start (install): ~224s
- Post_start (setup): ~10s
- Pre_task: ~11s
- Total: ~275s for clean start
