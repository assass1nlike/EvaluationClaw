> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# SeisComP Environment Notes

## Application Overview

SeisComP is an open-source seismological software for earthquake monitoring, data acquisition, processing, event detection, and interactive analysis. Version 7.1.2 is used.

Key GUI applications:
- **scolv** (Origin Locator View) - Interactive event review and analysis
- **scconfig** - Configuration tool for managing SeisComP settings and station bindings
- **scrttv** - Real-time trace viewer for waveform monitoring
- **scmv** - Map view for earthquake visualization

## Installation

### Binary Package (Recommended)

Building from source is complex and slow (20+ minutes, unreliable GUI build). Use the pre-built binary package from gempa:

```
URL: https://data.gempa.de/packages/Public/seiscomp/7/ubuntu/22.04/x86_64/seiscomp-7.1.2-ubuntu-22.04-x86_64.tar.gz
Size: ~71 MB
Extracts to: /home/ga/seiscomp/
```

The package includes all binaries (scolv, scconfig, scrttv, scmv, scmaster, etc.) pre-compiled.

### Critical Dependencies

```bash
apt-get install -y \
    python3-dev python3-pip python3-numpy \
    qtbase5-dev libqt5svg5-dev libqt5opengl5-dev \
    libssl-dev libxml2-dev libmariadb-dev \
    mariadb-server mariadb-client \
    libboost-all-dev \        # CRITICAL: scolv/scconfig need libboost_iostreams
    xdotool wmctrl scrot      # GUI automation tools
```

**Key gotcha**: Without `libboost-all-dev`, scolv and other SeisComP binaries fail at runtime with missing `libboost_iostreams.so.1.74.0`.

### Source Code Repository Structure

- All SeisComP GitHub repos use `main` branch (NOT `master`)
- There is NO separate `gui` repository - GUI apps live in `SeisComP/main` under `apps/gui-qt/`
- `scconfig` lives in the base `seiscomp` repository under `src/system/apps/config`

## Database Configuration

### MySQL/MariaDB Setup

SeisComP uses MariaDB as its database backend. Schema is at `$SEISCOMP_ROOT/share/db/mysql.sql`.

```sql
CREATE DATABASE IF NOT EXISTS seiscomp CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS 'sysop'@'localhost' IDENTIFIED BY 'sysop';
GRANT ALL PRIVILEGES ON seiscomp.* TO 'sysop'@'localhost';
```

### Plugin Loading (CRITICAL)

SeisComP 7 does NOT load the MySQL driver by default. You MUST add this to `global.cfg`:

```
plugins = dbmysql
```

Without this, ALL SeisComP tools fail with `"Database driver 'mysql' is not supported"`.

GUI tools also benefit from `--plugins dbmysql` on the command line for reliability.

## scmaster Configuration

The messaging server (scmaster) needs specific plugin and queue configuration:

```ini
plugins = dbmysql, dbstore
queues = production
queues.production.groups = AMPLITUDE, PICK, LOCATION, MAGNITUDE, FOCMECH, EVENT, QC, PUBLICATION, GUI, INVENTORY, CONFIG, LOGGING, SERVICE_REQUEST, SERVICE_PROVIDE
queues.production.processors.messages = dbstore
queues.production.processors.messages.dbstore.driver = mysql
queues.production.processors.messages.dbstore.read = sysop:sysop@localhost/seiscomp
queues.production.processors.messages.dbstore.write = sysop:sysop@localhost/seiscomp
```

### Known Issues

1. **`dbstore` plugin**: Must be loaded explicitly - it lives in `$SEISCOMP_ROOT/share/plugins/scmaster/`
2. **`STATUS_GROUP`**: Do NOT add this to the groups list - scmaster adds it automatically and will error on duplicate
3. **Config precedence**: Files in `$SEISCOMP_ROOT/etc/defaults/` override user config in unexpected ways. The setup script must `rm -f` defaults files and write to `$SEISCOMP_ROOT/etc/` directly
4. **Setup wizard bypass**: Create `$SEISCOMP_ROOT/var/run/seiscomp.init` to skip the interactive setup wizard

## Data Import

### Station Inventory

FDSN StationXML from GEOFON/IRIS CANNOT be imported directly via `scdb`. Must convert first:

```bash
# Convert FDSN StationXML to SeisComP XML
fdsnxml2inv ge_stations.xml ge_stations.scml

# Import converted file
seiscomp exec scdb --plugins dbmysql -i ge_stations.scml -d mysql://sysop:sysop@localhost/seiscomp
```

### Event Data (QuakeML)

USGS QuakeML CANNOT be imported directly either. Use the custom `convert_quakeml.py` script that uses the SeisComP Python API (`seiscomp.datamodel`, `seiscomp.core`, `seiscomp.io`) to convert.

```bash
python3 convert_quakeml.py noto_earthquake.xml noto_earthquake.scml
seiscomp exec scdb --plugins dbmysql -i noto_earthquake.scml -d mysql://sysop:sysop@localhost/seiscomp
```

### Real Data Sources

| Data Type | Source | URL Pattern |
|-----------|--------|-------------|
| Station inventory | GEOFON FDSN | `geofon.gfz-potsdam.de/fdsnws/station/1/query?...&format=xml` |
| Station inventory (fallback) | IRIS FDSN | `service.iris.edu/fdsnws/station/1/query?...&format=xml` |
| Events | USGS FDSN | `earthquake.usgs.gov/fdsnws/event/1/query?format=quakeml&...` |
| Waveforms | IRIS FDSN | `service.iris.edu/fdsnws/dataselect/1/query?...` |

### Noto Peninsula Earthquake Data

The environment uses data from the 2024-01-01 M7.5 Noto Peninsula, Japan earthquake:
- 5 GE network stations: TOLI, GSI, KWP, SANI, BKB
- Waveform time window: 07:10-07:40 UTC
- Event query: `starttime=2024-01-01T07:00:00&endtime=2024-01-01T08:00:00&minmagnitude=7.0`

## GUI Application Launch

### Launch Pattern

GUI apps must be launched with proper environment and in background:

```bash
setsid su - ga -c "DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority \
    SEISCOMP_ROOT=$SEISCOMP_ROOT \
    PATH=$SEISCOMP_ROOT/bin:\$PATH \
    LD_LIBRARY_PATH=$SEISCOMP_ROOT/lib:\$LD_LIBRARY_PATH \
    $SEISCOMP_ROOT/bin/scolv --plugins dbmysql -d mysql://sysop:sysop@localhost/seiscomp" \
    > /tmp/scolv.log 2>&1 &
```

Key points:
- Use `setsid` to detach from the shell session
- Set `DISPLAY=:1` and `XAUTHORITY`
- Always add `--plugins dbmysql` for database connectivity
- Redirect output to log for debugging

### First-run Dialog Suppression

Create `/home/ga/.seiscomp/scconfig.cfg` with `showWelcome = false`.

## Tasks

### Task 1: Set Event Type in scolv
- Launch scolv with database connection
- Agent finds the Type dropdown in event details panel
- Changes from "not set" to "earthquake"
- Commits the change

### Task 2: Configure Station Binding in scconfig
- Launch scconfig
- Navigate to Bindings panel
- Drag "global" profile onto station GE.TOLI
- Save configuration (Ctrl+S)

## Critical Learnings

### scolv Event Loading

scolv's `--load-event-db` flag (and `loadEventDB` config) controls how many days back to load events from the database. Default is 1 day. Since the Noto earthquake is from 2024-01-01, and the environment runs in 2026, you need `loadEventDB = 1000` in `scolv.cfg` or `--load-event-db 1000` on the command line.

**Gotcha**: The `-E` flag means `--event` (load specific event by ID), NOT event time span.

### OriginReference Table

scolv's Event tab shows an Origins list that requires an `OriginReference` row linking the Event to its Origin. Without it, the Event tab shows an empty origins panel. The `convert_quakeml.py` script must create an `OriginReference` object and add it to the Event. A SQL safety net in `setup_seiscomp.sh` also ensures this link exists.

### scconfig Bindings Panel

scconfig's Bindings panel reads station inventory from `$SEISCOMP_ROOT/etc/inventory/` (NOT from the database) and station names from `$SEISCOMP_ROOT/etc/key/station_*` files. Both must exist for stations to appear in the Bindings tree.

`seiscomp update-config inventory` often fails with "Option not found for: interface.bind" errors. Direct creation of key files with `touch` is more reliable.

### pkill -f Danger

`pkill -f "scolv"` matches ANY process with "scolv" in the command line, including SSH commands running `set_event_type_scolv/setup_task.sh`. This kills the SSH session and causes the pre_task hook to fail with exit 255. Use `pkill -f "$SEISCOMP_ROOT/bin/scolv"` to only match the specific binary.

### Bundled Data (No Network Dependency)

All FDSN data is pre-downloaded and bundled in `data/fdsn/` to eliminate network dependency during setup:
- Station inventory: `ge_stations.xml` (1.3MB, from GEOFON FDSN)
- Event data: `noto_earthquake.xml` (2.8KB, from USGS FDSN)
- Waveforms: 3 of 5 stations (BKB 73KB, GSI 57KB, SANI 57KB from GEOFON dataselect); TOLI and KWP had no data for this time period

The `setup_seiscomp.sh` script copies from `/workspace/data/fdsn/` instead of downloading live.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Database driver 'mysql' is not supported` | Missing dbmysql plugin | Add `plugins = dbmysql` to global.cfg |
| `No queues configured, exiting` | Wrong scmaster config | Use proper queue config with `queues = production` |
| `Failed to create message processor 'dbstore'` | Missing dbstore plugin | Add `dbstore` to `plugins` in scmaster.cfg |
| `Group name is not unique: STATUS_GROUP` | STATUS_GROUP in explicit list | Remove it - auto-added by scmaster |
| scolv won't start | Missing boost libraries | Install `libboost-all-dev` |
| `no valid entry found in file` (scdb) | Wrong XML format | Convert StationXML via fdsnxml2inv, QuakeML via convert_quakeml.py |
| Defaults override user config | Files in etc/defaults/ | Remove defaults files, write to etc/ directly |
| scolv Events (0/0) | Default load-event-db is 1 day | Set `loadEventDB = 1000` in scolv.cfg |
| scolv Event tab empty origins | Missing OriginReference row | Add OriginReference in convert_quakeml.py and SQL safety net |
| scconfig Bindings empty | Missing etc/inventory/ or etc/key/ | Copy SCML to etc/inventory/, create station key files |
| SSH killed during pre_task | `pkill -f "scolv"` too broad | Use `pkill -f "$SEISCOMP_ROOT/bin/scolv"` |
