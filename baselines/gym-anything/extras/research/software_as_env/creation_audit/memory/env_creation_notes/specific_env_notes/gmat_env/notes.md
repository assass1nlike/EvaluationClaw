> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# GMAT Environment Notes

## Application
- **Name**: NASA GMAT (General Mission Analysis Tool)
- **Version**: R2022a
- **Type**: Desktop GUI (wxWidgets/C++/OpenGL)
- **Download**: SourceForge `gmat-ubuntu-x64-R2022a.tar.gz` (~370MB)

## Installation Quirks

### Tarball Extraction Structure
The R2022a tarball extracts to `GMAT/R2022a/` (nested directory). The install script must detect this and move the versioned subdirectory to `/opt/GMAT/` directly. The extraction creates:
```
/opt/GMAT/R2022a/bin/
/opt/GMAT/R2022a/data/
/opt/GMAT/R2022a/samples/
```
Must be moved to:
```
/opt/GMAT/bin/
/opt/GMAT/data/
/opt/GMAT/samples/
```

### Binary Names
- GUI binary: `GMAT-R2022a` (ELF executable)
- Symlink: `GMAT_Beta` -> `GMAT-R2022a`
- Console: `GmatConsole` and `GmatConsole-R2022a`
- IMPORTANT: `GMAT.ini` is NOT an executable (it's a config file). Always use `file` command to verify ELF format.

### Dependencies
All dependencies are bundled in the tarball. Only system libraries needed:
- Mesa/OpenGL: `libgl1-mesa-glx`, `libgl1-mesa-dri`, `libglu1-mesa`
- X11: `libx11-6`, `libxext6`, etc. (already in base image)
- wxWidgets libraries are bundled in bin/

### Working Directory
GMAT must be launched from its `bin/` directory (`cd /opt/GMAT/bin`) for data file paths to resolve correctly.

## Setup Notes

### Warm-up Launch
GMAT shows a splash screen on first launch but no blocking first-run wizard. The warm-up launch:
1. Launches GMAT
2. Window appears within ~2 seconds
3. Dismiss with Escape
4. Kill the process

### Sample Missions (Real Data)
GMAT ships with 160 sample `.script` files in `samples/` directory. These are real NASA mission scenarios:
- `Ex_HohmannTransfer.script` - LEO to GEO Hohmann transfer
- `Ex_GivenEpochGoToTheMoon.script` - Lunar trajectory
- `Ex_DoubleLunarSwingby.script` - Double lunar swingby
- `Ex_LCROSSTrajectory.script` - LCROSS mission (actual NASA mission)
- `Ex_LEOStationKeeping.script` - LEO station keeping
- `Ex_GEOTransfer.script` - GEO transfer orbit
- And 154 more covering attitude, finite burns, force models, integrators, etc.

### Script Format
GMAT scripts (`.script`) use a custom language:
- Comments: `%` (single-line only)
- Object creation: `Create Spacecraft DefaultSC;`
- Property setting: `GMAT DefaultSC.SMA = 6678.14;`
- Mission sequence starts after: `BeginMissionSequence;`

### GUI Structure
- **Resources tab**: Tree view of all mission objects (Spacecraft, Burns, Propagators, etc.)
- **Mission tab**: Sequence of mission events
- **Output tab**: Log/console output
- **Sync status**: Shows "Synchronized" when GUI and script match
- **Toolbar**: Run button (green play arrow), Stop, Pause, etc.

### State Type Display
Spacecraft properties default to **Cartesian** display. To see Keplerian elements (SMA, ECC, INC), change the "State Type" dropdown in the spacecraft properties dialog. IMPORTANT: When using sample scripts that don't explicitly set spacecraft state, the default is Cartesian with position (7100, 0, 1300) km and velocity (0, 7.35, 1) km/s (SMA ~7191 km). Tasks that reference specific SMA values must inject `DisplayStateType = Keplerian` and explicit SMA into the script.

### Default Spacecraft Parameters
The default spacecraft in GMAT Ex_HohmannTransfer.script does NOT set orbital elements explicitly. It uses GMAT's built-in default (Cartesian, ~7191 km SMA). If your task requires a specific SMA, you must inject the parameters via `sed` in setup_task.sh after the `Create Spacecraft` line.

### Browser Opening on Startup
GMAT attempts to open `gmatcentral.org` in the default browser on startup. Block this by adding to `/etc/hosts`:
```
127.0.0.1 gmatcentral.org
127.0.0.1 www.gmatcentral.org
```
Also kill any Firefox processes after GMAT window appears.

## VNC Configuration
MUST include `"vnc": {"password": "password"}` in env.json. Without this, the VNCSpec defaults to `password=None`, causing the VNC connection to fail with "VNC password required but not provided".

## Timing
- Full environment setup (fresh, no cache): ~7 minutes
  - GMAT download: ~3-4 minutes (370MB from SourceForge)
  - Package install + extraction: ~2 minutes
  - Post-start (warm-up launch): ~1 minute
  - Task setup: ~15 seconds

## Resource Requirements
- CPU: 4 cores
- Memory: 6GB (GMAT + OpenGL rendering)
- GPU: Not required (uses Mesa software rendering)
- Network: Required for SourceForge download
