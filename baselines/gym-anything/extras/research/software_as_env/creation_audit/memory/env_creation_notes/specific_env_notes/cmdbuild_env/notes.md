> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# CMDBuild Environment Notes

## Docker Image Selection

- **Use `itmicus/cmdbuild:4.1.0`** (plain CMDBuild), NOT `r2u-2.4-4.1.0` (READY2USE) or `om-2.4-4.1.0` (openMAINT)
- The READY2USE image has a known issue where `demo.dump.xz` requires database patches that fail with `BadSqlGrammarException` on PL/pgSQL `DO` blocks
- The plain 4.1.0 image with `demo.dump.xz` boots cleanly with `status: READY` (no pending patches)
- The `empty.dump.xz` dump creates a minimal schema with no CI classes - unsuitable for CMDB tasks

## Database

- Database name: `cmdbuild_db4` (default for 4.1.0 image)
- User: `cmdbuild` (internal), Admin: `postgres`/`postgres`
- The demo database includes pre-configured CI classes: Server, Desktop, Laptop, Monitor, Printer, NetworkDevice, Notebook, Room, Building, Floor, Employee, Supplier, etc.
- Server class has 25 attributes including Code, Description, SerialNumber, Notes, Brand, Model, Room, Assignee, RAM, CPUNumber, CPUSpeed, HDSize, IPAddress, RAID, RedundantPowerSupply

## REST API

- Base URL: `http://localhost:8090/cmdbuild/services/rest/v3`
- Authentication: HTTP Basic with `admin:admin`
- Session API (`POST /sessions`) returns 500 with demo.dump.xz - use Basic Auth instead
- Key endpoints:
  - `GET /classes` - list all classes
  - `GET /classes/{className}/cards` - list cards (records)
  - `POST /classes/{className}/cards` - create a card
  - `PUT /classes/{className}/cards/{id}` - update a card
  - `GET /boot/status` - check system readiness (should return `READY`)
  - `GET /classes/{className}/attributes` - list class attributes

## ExtJS Login Form Issue

CMDBuild uses ExtJS for its web UI. The login form's `<input>` fields do not respond to:
- `xdotool type` (X11 synthetic key events)
- `pyautogui.write()` or `pyautogui.typewrite()`
- `xclip` clipboard paste + `Ctrl+V`
- `pyautogui.press()` for individual characters (works intermittently)

This is because ExtJS uses virtual DOM components that handle input events at the JavaScript framework level, not through standard DOM input events triggered by X11 synthetic key presses.

**Workaround for testing**: Use Firefox developer console (F12 > Console) to execute JavaScript that fills form fields or creates a session via the REST API.

**Agent impact**: Agents using VNC-level keyboard injection (RFB protocol) should be able to type into ExtJS fields since VNC events are processed at a lower level than X11 synthetic events.

## Timing Considerations

- CMDBuild (Tomcat + Java) takes 20-60 seconds to fully start after container creation
- The `demo.dump.xz` is loaded during container first start (database restoration)
- Docker healthcheck uses `curl -f -L http://localhost:8080/cmdbuild/ui/` with 120s start_period
- Always poll for API readiness (`GET /boot/status` == `READY`) before seeding data
- Data seeding via REST API takes ~5-10 seconds for 8 records

## Data Seeding

- The `seed_data.py` script creates 8 realistic server CIs with Dell/HP/Cisco product specs
- Serial numbers follow real manufacturer formats (Dell service tags, HP serial numbers, Cisco serial numbers)
- Data is seeded via the REST API using HTTP Basic auth
- The script discovers available classes dynamically and falls back through a priority list

## Lookup Types

The demo database includes 33+ lookup types including:
- Brand, Asset state, Monitor type, Network device type, Printer type
- Employee level/qualification/state/type
- License category, Invoice type
- Calendar-related lookups (for scheduling features)

## Resource Requirements

- mem_gb: 8 (CMDBuild + Tomcat needs ~3GB heap, plus PostgreSQL and OS)
- cpu: 4 cores
- net: true (for Docker image pulls)
- Disk: ~2GB for Docker images + database
