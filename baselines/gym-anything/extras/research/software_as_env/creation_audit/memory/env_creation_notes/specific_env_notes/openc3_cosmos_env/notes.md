> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenC3 COSMOS Environment Notes

## Installation Quirks

### Docker Version
- Ubuntu 22.04's default `docker.io` package does NOT include `docker-compose-plugin`
- Must install Docker CE from official Docker repository (`download.docker.com`)
- This gives `docker compose` v2 which OpenC3 requires (v1 `docker-compose` has bugs)

### Docker Image Pull
- OpenC3 uses 8 Docker images from `openc3inc/` namespace on Docker Hub
- Total pull size: ~2-3GB compressed, ~9GB on disk
- Images: openc3-traefik, openc3-redis (x2), openc3-minio, openc3-cosmos-cmd-tlm-api, openc3-cosmos-script-runner-api, openc3-operator, openc3-cosmos-init
- The init container exits after seeding (normal behavior)

### cosmos-project Repository
- Clone from: `https://github.com/OpenC3/cosmos-project.git`
- Key file: `.env` - controls demo mode (`OPENC3_DEMO=1`), version tags
- Key file: `openc3.sh` - manages COSMOS lifecycle (run/stop/cleanup)
- Current version: 6.10.4

## Authentication

### Critical Discovery: Token = Password
- In open-source COSMOS (non-Enterprise), the auth token IS literally the password
- There is no JWT, no OAuth, no session token generation
- API calls use `Authorization: <password>` header directly
- Browser stores password in `localStorage.openc3Token`

### Password Setup
- First visit to `http://localhost:2900` shows password creation form
- The `auth/set` API endpoint does NOT work reliably for headless setup
- Must set password via xdotool UI automation (click fields, type password, click Set)
- After password is set, `auth/token-exists` returns `{"result":true}`

### Password Setup Coordinates (1920x1080)
- New Password field: (1125, 369)
- Confirm Password field: (1125, 447)
- Set button: (396, 517)
- (Derived from 1280x720 visual grounding: 750,246 / 750,298 / 264,345)

## Service Timing

### Startup Sequence
1. `openc3.sh run` starts all containers via docker compose
2. Redis containers ready first (~5s)
3. MinIO ready next (~10s)
4. API containers ready (~30s)
5. Traefik proxy ready (~30s)
6. Init container seeds plugins and demo data (~60-120s)
7. Operator starts interface microservices (~30s after init)
8. INST/INST2 telemetry begins flowing (~10s after operator)
9. Total cold start: ~3-5 minutes

### Readiness Polling
- Web UI: Poll `http://localhost:2900` for HTTP 200/302/401
- API: POST to `/openc3-api/api` with `get_target_names` method
- Both need the password/token for authenticated requests

## INST Target Details

### Telemetry Packets
- **HEALTH_STATUS** (1 Hz): TEMP1-4, COLLECTS, GROUND1STATUS, GROUND2STATUS, CCSDSAPID
- Multiple other 1 Hz packets with ~15 items each
- One 10 Hz packet with ~20 items
- Temperature values fluctuate realistically, triggering limit violations

### Commands
- **COLLECT**: `INST COLLECT with TYPE 'NORMAL', DURATION 5.0, TEMP 0.0`
- **ABORT**: `INST ABORT` (no parameters)
- **CLEAR**: `INST CLEAR` (clears alarm/error state)
- Command API uses `keyword_params: {"scope": "DEFAULT"}` (no "type" field!)
- Telemetry API uses `keyword_params: {"type": "FORMATTED", "scope": "DEFAULT"}`

### Important: keyword_params Difference
- **Commands**: `{"scope": "DEFAULT"}` only
- **Telemetry**: `{"type": "FORMATTED", "scope": "DEFAULT"}` (or "CONVERTED", "RAW")
- Including "type" in command keyword_params causes `Unknown symbol keyword(s): type` error

## Web UI Tool URLs

| Tool | URL Path |
|------|----------|
| CmdTlmServer | /tools/cmdtlmserver |
| Limits Monitor | /tools/limitsmonitor |
| Command Sender | /tools/cmdsender |
| Script Runner | /tools/scriptrunner |
| Packet Viewer | /tools/packetviewer |
| Telemetry Viewer | /tools/tlmviewer |
| Telemetry Grapher | /tools/tlmgrapher |
| Data Extractor | /tools/dataextractor |
| Data Viewer | /tools/dataviewer |
| Admin | /tools/admin |

## Script Runner Gotcha
- Script Runner's code editor captures keyboard shortcuts (Ctrl+L, Ctrl+A, etc.)
- Cannot use `xdotool key ctrl+l` to navigate while Script Runner is focused
- Command Sender's "Editable Command History" also captures Ctrl+L
- **Fix**: Click the Firefox address bar directly at (480, 128) in 1920x1080 instead of using Ctrl+L
- Use sidebar navigation links or click directly on the browser address bar instead
- Sidebar links have external link icons and open in current tab

## Monaco Editor Input
- The Script Runner uses a Monaco code editor
- `xdotool type` without `--window` does NOT work (fails silently)
- Must use `xdotool type --window $WID` where $WID is from `xdotool getactivewindow`
- `xdotool key --window $WID` also needed for individual keystrokes
- Monaco auto-completes brackets: typing `{` inserts `{}`, causing f-string errors
- **Fix**: Use `str()` concatenation instead of f-strings for xdotool-injected scripts

## Hazardous Commands
- INST CLEAR is a hazardous command (prompts confirmation dialog in UI)
- API call with `cmd()` raises HazardousError (but still counts the command)
- Use `cmd_no_hazardous_check()` for programmatic API calls
- In the Command Sender UI, clicking Send for hazardous commands shows a confirmation dialog

## Resource Requirements
- RAM: 16GB recommended (8 containers + QEMU overhead)
- Disk: ~10GB after full install with images
- CPU: 4 cores
- Network: Required (Docker Hub pulls, container networking)
