> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Bridge Command Environment Notes

## Installation

### .deb Package Does Not Work on Ubuntu 22.04
The official BridgeCommand5.10.3_amd64.deb package requires:
- libc6 >= 2.38 (Ubuntu 22.04 has 2.35)
- libstdc++6 >= 13.1 (Ubuntu 22.04 has 12.3)
- libopenxr-loader1

**Solution**: Build from source. The source build compiles successfully on Ubuntu 22.04 with the right dependencies.

### Build Dependencies (Ubuntu 22.04)
```bash
apt-get install -y cmake build-essential mesa-common-dev libxxf86vm-dev \
    freeglut3-dev libxext-dev libxcursor-dev portaudio19-dev libsndfile1-dev \
    libopenxr-dev
```

Note: `libopenxr-dev` is required - cmake fails without it.

### Build Process
```bash
cd /tmp
git clone --depth 1 https://github.com/bridgecommand/bc.git
cd bc/bin
cmake ../src
make -j$(nproc)
```

The build takes ~3 minutes with 4 cores. The binary and all data files (Scenarios, Models, World) are in the `bin/` directory.

## Running Bridge Command

### Critical: Must Run From Data Directory
Bridge Command looks for its data files (Models/, World/, Scenarios/) relative to the working directory. If launched from any other directory, it fails to find assets.

```bash
# CORRECT:
cd /opt/bridgecommand && DISPLAY=:1 ./bridgecommand

# WRONG (will fail to find assets):
DISPLAY=:1 /opt/bridgecommand/bridgecommand
```

### setsid Syntax
Using `setsid DISPLAY=:1 ./bridgecommand` fails because setsid treats `DISPLAY=:1` as the command. Use:
```bash
cd /opt/bridgecommand && DISPLAY=:1 ./bridgecommand
# or with su:
su - ga -c "cd /opt/bridgecommand && DISPLAY=:1 ./bridgecommand > /tmp/bc.log 2>&1 &"
```

### Configuration File
Bridge Command reads `bc5.ini` from:
1. Program directory (`/opt/bridgecommand/bc5.ini`) - first
2. User config (`~/.config/Bridge Command/bc5.ini`) - overrides

For VM usage, set `graphics_mode=2` (windowed) and `disable_shaders=1` (software rendering).

## UI Flow

```
Launcher Screen → "Start Bridge Command" → Scenario Selection → OK → Loading → PAUSED → Click/Enter → Running
```

### Launcher Buttons (1280x720 coordinates)
- Start Bridge Command: (160, 227)
- Scenario Editor: (151, 268)
- Settings: Main: (151, 368)
- Exit: (151, 511)

### Scenario Selection
- Dropdown at approximately (380, 218-365)
- OK button at (397, 390)
- Scenarios listed alphabetically a) through l) plus custom

### Settings Editor
- Tabbed interface: Graphics, Language, Sound, Joystick, Network, RADAR, Startup
- view_angle field at approximately (480, 245)
- "Save and exit" button at (315, 648)

## Bundled Scenarios (Real Data)
All scenarios use real-world coordinates and maritime data:
- Simple Estuary training area (50.04°N, 9.98°W)
- Portsmouth Harbour (50.78°N, 1.10°W)
- Swinomish Channel, WA, USA
- Various vessel types: Yacht, Tanker, Timber carrier, ASD Tug

## Known Issues
- Warm-up launch via `su - ga -c` can fail silently; not critical since BC has no first-run wizard
- FPS is ~5 with software rendering in QEMU VM (functional but slow)
- The launcher window is small (~300x450 px); no maximize behavior needed
- Version from source build is v5.10.4-alpha.4 (latest development)
