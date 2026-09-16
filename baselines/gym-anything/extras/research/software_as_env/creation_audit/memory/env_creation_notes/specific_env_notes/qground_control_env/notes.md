> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# QGroundControl Environment Notes

## Overview
QGroundControl (QGC) v5.0.8 with ArduPilot SITL simulated copter running in a QEMU VM.

## Installation Quirks

### QGC AppImage Download
- The old CloudFront URL (`https://d176tv9ibo4jno.cloudfront.net/latest/QGroundControl.AppImage`) returns **403 Forbidden** as of 2026.
- Use the GitHub releases URL instead: `https://github.com/mavlink/qgroundcontrol/releases/download/v5.0.8/QGroundControl-x86_64.AppImage`
- The filename changed from `QGroundControl.AppImage` to `QGroundControl-x86_64.AppImage` in v5.0.
- File is ~180MB. Always verify download size > 100MB.

### QGC Software Rendering
- QGC requires OpenGL. In a VM without GPU, use:
  - `LIBGL_ALWAYS_SOFTWARE=1`
  - `QT_QUICK_BACKEND=software`
- The `--appimage-extract-and-run` flag is needed to avoid FUSE mount issues.

### QGC Config Path
- v5.0 stores settings at `~/.config/QGroundControl/QGroundControl.ini` (NOT `QGroundControl.org`)
- Pre-creating this file helps suppress some first-run prompts but does NOT prevent all dialogs.

### QGC Window State (Critical)
- QGC saves window position/size in `~/.config/QGroundControl/QGroundControl.ini` under `[MainWindowState]`
- Must pre-set `visibility=5` (maximized), `x=0`, `y=0`, `width=1920`, `height=1048`
- Without this, QGC may start at a smaller size (e.g., 985x628 at offset 109,48), causing all click coordinates to miss their targets
- `wmctrl` maximize commands alone are NOT reliable — QGC overrides with saved window state

### NetworkManager / Map Tile Loading (Critical)
- Qt 6 (QGC v5) checks NetworkManager's D-Bus API for connectivity status
- The base image uses systemd-networkd via netplan — NM sees interfaces as "unmanaged" and Qt reports "Network Not Available"
- This prevents QGC from fetching map tiles (Bing satellite imagery) even though internet works
- **Fix**: Change the netplan renderer from `networkd` to `NetworkManager` in `/etc/netplan/50-cloud-init.yaml`
- After `netplan apply`, NM picks up the interface and reports "connected full"
- **WARNING**: Do NOT enable NetworkManager at boot (`systemctl enable`) — it conflicts with systemd-networkd during boot and can make the VM unreachable via SSH
- Install `network-manager` in pre_start, but only configure netplan in post_start

### QGC First-Run Dialogs (3 dialogs on first launch)
1. **Serial permissions warning** - "The current user does not have the correct permissions to access serial devices"
   - Ok button at (1262, 459) in 1920x1080
   - Ok button at (841, 306) in 1280x720
2. **Measurement Units** dialog - asks user to select units
   - Ok button at (1065, 383) in 1920x1080
   - Ok button at (710, 255) in 1280x720
3. **Vehicle Information** dialog - shows vehicle details on first connection
   - Ok button at (1031, 444) in 1920x1080
   - Ok button at (687, 296) in 1280x720
4. **Missing parameters** dialog (in Vehicle Configuration) - "Parameters are missing from firmware... ARMING_CHECK"
   - Ok button at (1260, 509) in 1920x1080
   - This appears when entering Vehicle Configuration, normal for SITL

**CRITICAL**: Do NOT use Escape key to dismiss dialogs — it triggers the "Close QGroundControl" quit dialog.

### ArduPilot SITL
- The `install-prereqs-ubuntu.sh` script **refuses to run as root**. Must install Python deps manually or run as a regular user.
- Key Python dependency: `empy==3.3.4` (NOT the latest empy, must be exactly 3.3.4).
- Other pip deps: `pexpect`, `future`, `pymavlink`, `MAVProxy`.
- Shallow clone (`--depth 1 --recurse-submodules --shallow-submodules`) reduces download from ~20GB to ~2-3GB.
- Build with `waf configure --board sitl && waf copter` as the ga user (not root).
- Build time: ~2-3 minutes on 4 cores.
- `/opt/ardupilot` must be owned by `ga` before building.
- Current version: ArduCopter 4.7.0dev (firmware version shown in Vehicle Configuration)

## Service Startup

### SITL Launch
- Use `sim_vehicle.py --no-mavproxy --vehicle ArduCopter -A "--serial0=udpclient:127.0.0.1:14550"`
- The `--no-mavproxy` flag is critical - avoids MAVProxy intermediary.
- SITL sends MAVLink heartbeats to UDP 14550 (QGC auto-discovery port).
- Takes ~6s to start after `sim_vehicle.py` is invoked.
- Must wait 10s after SITL starts before launching QGC for reliable connection.

### QGC Launch
- Use `setsid` for both SITL and QGC (Pattern #18 - survive SSH exit).
- QGC window appears within ~3s of launch.
- Use `wmctrl -r "QGroundControl" -b add,maximized_vert,maximized_horz` to maximize.
- GNOME dock should be hidden (`dock-fixed false`, `autohide true`) to prevent overlap.

## Process Detection
- SITL process: `pgrep -f "/opt/ardupilot/build/sitl/bin/arducopter"`
- QGC process: The QGC AppImage extracts and runs, so `pgrep -f "QGroundControl"` may not work reliably. Check `wmctrl -l` for the window name instead.

## QGC Navigation (v5.0)

### Q Icon Menu (Primary Navigation)
- The Q icon is at the extreme top-left of the QGC toolbar
- Click position: approximately **(10, 14)** in 1920x1080 (NOT 20,20 — must be at the very edge)
- Opens a drawer menu with these items (verified via visual grounding, 1920x1080):
  - **Plan Flight** - center at (96, 95)
  - **Analyze Tools** - center at (105, 146)
  - **Vehicle Configuration** - center at (126, 197)
  - **Application Settings** - center at (122, 248)
  - **Close (Disconnect)** - center at (131, 299)

### Plan View
- Shows: Create Plan panel (Empty Plan, Survey, Corridor Scan, Structure Scan)
- Right panel: Mission/Fence/Rally tabs, Mixed Ascent, Vehicle Info, Launch Position
- "Exit Plan" button at top-left to return to Fly View

### Vehicle Configuration
- Left sidebar: Summary, Frame, Radio, Flight Modes, Sensors, Power, Motors, Safety, Tuning, Camera, Remote Support, Parameters, Firmware
- Parameters view: Alphabetical categories, search box, "Tools" button
- WPNAV_SPEED = 500.000 (Waypoint Horizontal Speed Target) — confirmed present
- Parameters category for WPNAV is listed as "WP" in the sidebar

## Timing
- Full install (pre_start): ~4 minutes (apt + QGC download + ArduPilot clone + build)
- Setup (post_start): ~40 seconds (SITL start + QGC launch + dialog dismissal)
- Task setup: ~6 seconds

## Real Data
- Sample mission file: `data/sample_mission.plan` (from MAVSDK test suite, GitHub)
- Mission format: QGC JSON .plan format with waypoints, geofence, rally points
- The mission contains real coordinates near Zurich (47.3977, 8.5456) with 6 items including takeoff, waypoints, image capture, and RTL.

## Flying the Drone via Pymavlink

### Connection
- QGC uses UDP 14550 (SITL's `--serial0=udpclient:127.0.0.1:14550`)
- SITL also exposes TCP ports **5762** and **5763** for additional MAVLink connections
- Use `tcp:127.0.0.1:5762` for pymavlink — does NOT conflict with QGC's UDP connection
- After connecting, must request data streams: `MAV_DATA_STREAM_ALL` at 4Hz

### Arming
- SITL has pre-arm checks enabled by default — standard `arducopter_arm()` blocks indefinitely
- **Fix**: Disable ARMING_CHECK parameter (`param_set ARMING_CHECK 0`) before arming
- Then use force-arm: `MAV_CMD_COMPONENT_ARM_DISARM` with param2=21196 to bypass remaining checks
- Check armed state via HEARTBEAT `base_mode & MAV_MODE_FLAG_SAFETY_ARMED`

### Takeoff
- Set mode to GUIDED first
- For takeoff, use `set_position_target_global_int` with target altitude (works reliably)
- `MAV_CMD_NAV_TAKEOFF` alone did NOT work reliably in GUIDED mode

### Mission Flight
- Upload mission via `waypoint_clear_all_send` + `waypoint_count_send` + `mission_item_int_send`
- Mission format: Home (frame 0) -> Takeoff (cmd 22) -> Waypoints (cmd 16) -> RTL (cmd 20)
- Switch to AUTO mode after reaching altitude to execute mission
- SITL default home position: lat=-35.363262, lon=149.165237 (Canberra, Australia)
- WPNAV_SPEED=500 cm/s (default) = ~5 m/s cruise speed, accelerates up to ~9-10 m/s

### QGC Display During Flight
- Fly View shows: "Flying Auto", red mission path polygon, drone icon moving, telemetry HUD updating
- Plan View shows: altitude profile graph at bottom, waypoints on map
- MAVLink Console shows: Vehicle Messages (timestamped logs) + Sensor Status overlay on the map
