> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenRocket Environment Notes

## Application Overview

- **Type**: Java Swing desktop GUI application for model rocket design and flight simulation
- **Version**: 24.12 (released July 2025)
- **Installation**: JAR file (80MB) from GitHub releases
- **Runtime**: Requires Java 17 (OpenJDK)
- **File format**: `.ork` (ZIP archive containing XML, or plain XML for older versions)
- **Source**: https://github.com/openrocket/openrocket

## Installation Quirks

### Java 17 Required
OpenRocket 24.12 requires Java 17. Install via:
```bash
apt-get install -y openjdk-17-jdk openjdk-17-jre
```

### JAR Download
The universal JAR file is preferred over platform-specific installers:
```bash
wget https://github.com/openrocket/openrocket/releases/download/release-24.12/OpenRocket-24.12.jar -O /opt/openrocket/OpenRocket.jar
```

### No AppImage for Latest Version
As of version 24.12, OpenRocket uses `.sh` Linux installers instead of AppImage. The JAR file is the cleanest option for headless deployment.

## Launch Pattern

### CRITICAL: setsid + bash -c for GUI Launch from SSH

`setsid` interprets environment variable assignments as a command name. **This does NOT work**:
```bash
# WRONG — setsid tries to execute "DISPLAY=:1" as a command
setsid DISPLAY=:1 java -jar OpenRocket.jar &
```

**Correct pattern**:
```bash
# RIGHT — wrap in bash -c so environment variables are set by the shell
setsid bash -c 'export DISPLAY=:1; java -Xms512m -Xmx2048m -jar /opt/openrocket/OpenRocket.jar &'
```

Or via `su`:
```bash
su - ga -c "setsid bash -c 'export DISPLAY=:1 JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64; java -Xms512m -Xmx2048m -jar /opt/openrocket/OpenRocket.jar > /tmp/openrocket.log 2>&1 &'"
```

### JVM Memory Settings
- `-Xms512m` — initial heap
- `-Xmx2048m` — max heap (2GB is sufficient for most designs)

### Startup Warnings (Safe to Ignore)
```
WARN info.openrocket.swing.startup.OSXSetup -- Attempting to set up OSX properties on non-MAC_OS
libEGL warning: DRI2: failed to authenticate
```

## Window Detection

OpenRocket window titles follow the pattern:
```
<Design Name> (<filename>.ork)
```

Example: `"A simple model rocket (simple_model_rocket.ork)"`

Detection via wmctrl:
```bash
DISPLAY=:1 wmctrl -l | grep -qi "openrocket\|rocket"
```

**Note**: The window title always contains the rocket name or filename, and the word "rocket" appears in the title of the design, making detection reliable.

## First-Run Behavior

- **No EULA or first-run wizard**
- **Splash screen**: Appears briefly on every launch (no dismiss needed)
- **Update check**: May show a dialog if internet is available. Dismiss with Escape or Enter.
- **No tip-of-the-day dialog**

The warm-up launch pattern in `post_start` is recommended but not strictly necessary.

## VNC Configuration

**IMPORTANT**: Must explicitly set VNC password in env.json:
```json
"vnc": {
    "enable": true,
    "password": "password"
}
```

Without this, the VNC password defaults to `None` (literal string), causing VNC connection failures in the framework.

## Real Data Sources

### Official Example Rockets
GitHub: `https://raw.githubusercontent.com/openrocket/openrocket/master/core/src/main/resources/datafiles/benchmarks/cua_world/environments/`

18 example .ork files available, including:
- A simple model rocket
- Two stage high power rocket
- Three stage low power rocket
- Dual parachute deployment
- Clustered motors
- Tube fin rocket

### University Team Rockets (Real Designs)
GitHub: `https://github.com/RocketPy-Team/RocketSerializer/tree/master/examples`

- EPFL BellaLui 2020
- NDRT Rocket 2020
- Projeto Jupiter Valetudo 2019

### 3D-Printable Rockets
GitHub: `https://github.com/3dp-rocket/rockets`

## .ork File Format

Two variants exist:
1. **ZIP format** (newer): ZIP containing `rocket.ork` XML + optional decal images
2. **Plain XML** (older/some sources): Direct XML file with `.ork` extension

Both are valid and OpenRocket handles both transparently.

## Task Design Notes

### Component Palette
The "Add new component" panel on the right side of the Rocket Design tab provides buttons for:
- Assembly: Stage, Boosters, Pods
- Body: Nose Cone, Body Tube, Transition
- Fins: Trapezoidal, Elliptical, Freeform, Tube Fins
- Mass: Rail Button, Launch Lug
- Internal: Inner Tube, Coupler, Centering Ring, Bulkhead, Engine Block
- Recovery: Parachute, Streamer, Shock Cord, Wadding

### Key Tabs
1. **Rocket design** — component tree + component palette + visualization
2. **Motors & Configuration** — motor selection from thrust curve database
3. **Flight simulations** — create/run simulations, view plots, export data

### Simulation Data Export
OpenRocket can export simulation data to CSV via the plot/data dialog. The export button is in the simulation results window after running a simulation.

## Timing

| Operation | Duration |
|-----------|----------|
| pre_start (install + download) | ~160s first run |
| post_start (setup + warm-up) | ~10s |
| pre_task (launch + detect window) | ~5-15s |
| OpenRocket window appearance | ~2-10s after launch |
