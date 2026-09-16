> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenVSP Environment Notes

## Installation Quirks

### libstdc++ Version Requirement
OpenVSP 3.48.0 (and likely 3.46+) requires `libstdc++6 >= 13.1`. Ubuntu 22.04 ships with version 12.3. Solution:
```bash
add-apt-repository -y ppa:ubuntu-toolchain-r/test
apt-get update
apt-get install -y libstdc++6
```
This upgrades to GCC 15's libstdc++ from the toolchain PPA.

### Other Dependencies
- `libcminpack1` - Required for OpenVSP
- `libglew2.2` - Required for OpenGL
- Pre-install these before running `dpkg -i` to avoid `apt-get install -f` removing the package

### Download URLs
- Current version: `https://openvsp.org/download.php?file=zips/current/linux/OpenVSP-X.XX.X-Ubuntu-22.04_amd64.deb`
- Old versions: `https://openvsp.org/download.php?file=zips/old/linux/OpenVSP-X.XX.X-Ubuntu-22.04_amd64.deb`

## Binary Location
After .deb install: `/usr/local/bin/vsp`

## Window Title Format
```
OpenVSP 3.48.0 - MM/DD/YY     filename.vsp3
```
Use `xdotool search --name "OpenVSP"` to find the window.

## setsid Gotcha
When launching via SSH, `setsid` must come AFTER the DISPLAY variable:
```bash
# WRONG - setsid tries to execute "DISPLAY=:1" as a binary
su - ga -c "setsid DISPLAY=:1 /usr/local/bin/vsp"

# RIGHT
su - ga -c "DISPLAY=:1 setsid /usr/local/bin/vsp"
```

## Secondary Window
OpenVSP creates a secondary untitled window alongside the main GUI window. `wmctrl -l` shows:
```
0x01a00005  0 ga-base OpenVSP 3.48.0 - 02/28/26     filename.vsp3
0x01a00008  0 ga-base
```
The untitled window doesn't interfere with operation.

## Data Sources
- Cessna-210_metric.vsp3: https://github.com/daptablade/docs (dapta tutorials)
- eCRM-001_wing_tail.vsp3: https://github.com/OpenMDAO/RevHack2020 (NASA OpenMDAO)
- More models at: https://hangar.openvsp.org/ and https://airshow.openvsp.org/

## UI Layout
- Menu bar: File, Edit, Window, View, Model, Analysis, Help
- Geom Browser panel: right side, shows component tree
- 3D viewport: main area with XYZ axes
- Status bar: shows file path and version info

## File Format
.vsp3 files are XML format containing:
- Vehicle parameters (name, view settings)
- Geometry components (fuselage, wings, tails, etc.)
- Each component has detailed parametric parameters
