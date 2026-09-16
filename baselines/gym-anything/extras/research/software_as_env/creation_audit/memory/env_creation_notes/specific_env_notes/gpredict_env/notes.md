> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# GPredict Environment Notes

## Installation

- **Package**: `apt-get install gpredict` (available in Ubuntu 22.04 repos)
- **No `gpredict-doc` package** on Ubuntu 22.04 (jammy) — only exists on newer versions. Don't include it in the install script or it will fail with `set -e`.
- Version on Ubuntu 22.04: standard repo version (GTK3-based)

## First-Time Initialization

GPredict has a **silent first-time initialization** (no wizard/dialog) implemented in `src/first-time.c`. It runs when `~/.config/Gpredict/` does NOT exist.

**Critical gotcha**: Do NOT pre-create `~/.config/Gpredict/` subdirectories before the first launch. If the parent directory already exists, GPredict's first-time init may skip steps (e.g., it won't copy `Amateur.mod` to modules/).

**Recommended approach**:
1. Let GPredict do its own first-time initialization during the warm-up launch
2. After warm-up, copy additional files (QTH, TLE data)
3. As a fallback, explicitly copy `Amateur.mod` from `/usr/share/gpredict/data/Amateur.mod`

## Configuration

- **Config directory**: `~/.config/Gpredict/`
- **Main config**: `~/.config/Gpredict/gpredict.cfg`
- **Ground stations**: `~/.config/Gpredict/*.qth` (key-value format)
- **Modules**: `~/.config/Gpredict/modules/*.mod` (GKeyFile format)
- **Satellite data**: `~/.config/Gpredict/satdata/*.sat` (one per satellite)
- **TLE cache**: `~/.config/Gpredict/satdata/cache/` (raw TLE text files)
- **Default window**: 700x700 pixels at position (0,0)

## QTH File Format

```ini
[GROUND STATION]
LOCATION=Pittsburgh, PA
LAT=40.4406
LON=-79.9959
ALT=230
WX=KPIT
GPSD_SERVER=
GPSD_PORT=2947
```

## Ground Station Default

GPredict uses `sample.qth` as the default ground station. Simply adding a new `.qth` file alongside does NOT switch the active ground station.

**Display name**: GPredict displays the **filename** (without `.qth` extension) as the ground station name in the UI. So `sample.qth` shows as "sample", `Pittsburgh.qth` shows as "Pittsburgh". The `LOCATION` field inside the file is NOT used for display.

**To properly set a custom default ground station**:
1. Copy your QTH file with the desired display name (e.g., `Pittsburgh.qth`)
2. Remove `sample.qth`
3. Update `gpredict.cfg` to set `DEFAULT_QTH=Pittsburgh.qth` under `[GLOBAL]` section

```bash
# After warm-up, set Pittsburgh as default:
cp Pittsburgh.qth "${GPREDICT_CONF_DIR}/Pittsburgh.qth"
rm -f "${GPREDICT_CONF_DIR}/sample.qth"
sed -i 's/^DEFAULT_QTH=.*/DEFAULT_QTH=Pittsburgh.qth/' "${GPREDICT_CONF_DIR}/gpredict.cfg"
```

**Previous (incorrect) approach**: Overwriting `sample.qth` content with Pittsburgh data — this works functionally but the UI still displays "sample" as the station name.

## pkill -f Gotcha

**CRITICAL**: Never use `pkill -f gpredict` in scripts named `*gpredict*.sh`. The `-f` flag matches against the full command line, which includes the script's own filename. Use `pkill -x gpredict` instead for exact process name matching.

```bash
# WRONG (kills the setup script itself):
pkill -f gpredict || true

# CORRECT (matches only the "gpredict" process name):
pkill -x gpredict || true
```

## setsid Syntax

The `setsid` command takes the first non-option argument as the program to execute. Environment variables MUST come BEFORE `setsid`:

```bash
# CORRECT:
su - ga -c "DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority setsid gpredict > /tmp/log 2>&1 &"

# WRONG (setsid tries to execute "DISPLAY=:1" as a program):
su - ga -c "setsid DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority gpredict > /tmp/log 2>&1 &"
```

## Window Management

- wmctrl commands must run as the `ga` user (not root) for X display access
- Use `wmctrl -r 'Gpredict' -b add,maximized_vert,maximized_horz` (by name, not -i with WID)
- The `-i` flag requires precise window ID matching which can be fragile

## UI Navigation

- **Context menu on satellite**: Right-click on satellite label on the map
- Satellite labels move in real-time, so coordinates are time-dependent
- Menu items: "Satellite info", "Show next pass", "Future passes", "Highlight Footprint", "Ground Track"
- **Preferences**: Edit > Preferences (or Alt+E then Preferences)
- Preferences tabs: Number Formats, Ground Stations, TLE Update, Message Logs
- Left sidebar: General, Modules, Interfaces, Predict

## Real Data

- **TLE data from CelesTrak**: `https://celestrak.org/NORAD/elements/gp.php?GROUP=<group>&FORMAT=tle`
  - `stations` = ISS and space stations
  - `amateur` = Amateur radio satellites
  - `weather` = Weather satellites
- Default module (Amateur) tracks satellites: 24278, 25544 (ISS), 27607, 39444, 40967, 43017
- Default ground station: Pittsburgh, PA via `Pittsburgh.qth` with `DEFAULT_QTH=Pittsburgh.qth` in gpredict.cfg (original default is Copenhagen, Denmark via `sample.qth`)

## Timing

- Warm-up launch needs ~10 seconds for first-time initialization
- Task setup needs ~5 seconds for GPredict to start and load modules
- Total setup (install + configure + task): ~65 seconds
