> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Bahmni EMR Environment — Creation Notes

## Overview
- Docker-in-QEMU: 12 Bahmni Lite containers (openmrs, openmrsdb, proxy, web, apps-frontend, lab, appointments, reports, reportsdb, patient-documents, implementer-interface, config)
- Port: 443 (HTTPS with self-signed cert) via Nginx reverse proxy
- Admin: `superman` / `Admin123`
- SSH user: `ga` / `password123`
- MySQL user: `openmrs-user` / `password`; MySQL root: `adminAdmin!123`
- Base URL: `https://localhost` (OpenMRS API: `https://localhost/openmrs`)

## Installation (pre_start)

### Dependencies installed
- `docker.io`, `docker-compose`, `jq`, `curl`, `imagemagick`, `xdotool`, `wmctrl`, `epiphany-browser`, `wget`
- Docker Compose v1.29.2 (NOT v2 plugin — Bahmni Lite requires v1)
- **Epiphany is the ONLY task browser** — do NOT use Firefox snap in tasks

### Bahmni Lite
- Docker images pulled from Docker Hub during pre_start (public images, no credentials needed)
- Compose file: `/workspace/config/docker-compose.yml`

## Setup (post_start)

### Startup sequence
1. `docker-compose up bahmni-openmrsdb bahmni-config` — start DB first
2. Wait for MySQL to be ready (mysqladmin ping)
3. `docker-compose up -d` — start all 12 containers
4. Wait for OpenMRS HTTP 200 (can take 8-15 minutes on first boot)
5. Run Python seed script: `python3 /workspace/scripts/seed_bahmni.py`

### OpenMRS startup time
- First boot: 8-15 minutes (runs Liquibase migrations, module startup)
- From checkpoint: containers start in ~30-60s, OpenMRS is already initialized

## Data Seeding

### Patient IDs: BAH000001 — BAH000020
- BAH000001 is Bahmni's **pre-existing "Test Patient"** — do NOT assign to seeded patients
- 20 patients seeded starting from BAH000002 via OpenMRS REST API
- Seed script uses `identifier = f"BAH{i+1:06d}"` (i=1..20 → BAH000002..BAH000021 effectively, but actual is BAH000002-BAH000020 for i=1..19 + i=20 gives BAH000021)
- **CRITICAL**: seed_bahmni.py starts numbering at `i+1` to skip BAH000001 collision

### OPD Visits — ALL patients must have visits
- **CRITICAL**: Clinical workflows (vital signs, clinical notes) require a pre-existing visit
- `seed_bahmni.py` creates an OPD visit for EVERY patient after creation
- `record_vital_signs/setup_task.sh` verifies visit exists and auto-creates if missing
- Patients 11-20 (James Osei BAH000011, Michael Brown BAH000012, etc.) were missing visits in the original seed — this was fixed both in the seed script and via REST API on the live VM

### API authentication
- OpenMRS uses Basic Auth: `superman:Admin123`
- API verification: `GET /openmrs/ws/rest/v1/session` → `{"authenticated": true}`

### Seed manifest
- Saved to `/tmp/bahmni_seed_manifest.json` during seeding
- Contains: UUID, identifier, name, gender, birth_year, visit_uuid for each patient

## Browser Setup

### Epiphany (GNOME Web) 42.4 — the ONLY task browser
- **CRITICAL**: Use Epiphany (not Firefox) for ALL tasks
  - `setup_bahmni.sh` warms up Epiphany; tasks MUST also use Epiphany
  - Firefox snap is installed but NOT used — SSL exceptions don't transfer between browsers
- Launch: `GDK_BACKEND=x11 DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority epiphany-browser --new-window "<url>" &`
- Wait 6-8s for Epiphany to render a page

### Epiphany SSL Warning — CRITICAL
- Epiphany shows "Security Violation" warning for self-signed cert on EVERY fresh launch
- **Epiphany does NOT persist SSL exceptions** (no `~/.pki/nssdb`; exceptions are session-scoped only)
- `dismiss_ssl_warning()` must be called every time `start_browser()` / `restart_firefox()` is called

### SSL dismissal flow (verified on 1850x1053 maximized window)
1. Detect "Security Violation" window title via `wmctrl -l`
2. Focus window + maximize
3. Click "Technical information" to expand the warning (actual coords: **707, 706**)
4. Wait 1.5s for expand animation
5. Click "Accept Risk and Proceed" (actual coords: **717, 770**)
6. Wait 5s for page to load

**VG coordinates (1280x720 scale) → actual (1850x1053 window):**
- "Technical information": VG(489, 483) → actual(707, 706)
- "Accept Risk and Proceed": VG(496, 527) → actual(717, 770)

### Screenshots (CRITICAL)
- `scrot` and ImageMagick `import` return **black images** in GNOME compositor environment
- **Must use `xwd -id <window_id>`** to capture actual window content:
  ```bash
  WID=$(DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority xdotool search --class Epiphany | tail -1)
  DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority xwd -id $WID -out /tmp/ss.xwd
  convert /tmp/ss.xwd /tmp/ss.png
  ```
- Get the LARGEST Epiphany window (not tiny 10x10 subwindows): use `xdotool search --class Epiphany | tail -1` or sort by geometry

### XAUTHORITY path
- **Correct**: `/run/user/1000/gdm/Xauthority`
- **Wrong**: `~/.Xauthority` (0 bytes, doesn't work from SSH)

## Task Utils (task_utils.sh)

### Key functions
- `wait_for_bahmni <timeout>` — waits for OpenMRS API to return HTTP 200
- `restart_firefox <url> <attempts>` — kills Epiphany, relaunches, auto-dismisses SSL warning; also available as `restart_browser()`
- `dismiss_ssl_warning` — detects and clicks through "Security Violation" warning (called inside restart_firefox)
- `take_screenshot <output.png>` — uses xwd to capture actual window content
- `navigate_to_url <url>` — focuses browser, Ctrl+L, types URL, Enter
- `openmrs_api_get <path>` — curl to OpenMRS REST API with superman:Admin123 auth
- `openmrs_api_post <path> <json>` — POST to OpenMRS REST API
- `get_patient_uuid_by_identifier <id>` — looks up patient UUID by BAH ID
- `get_browser_window_id` — finds largest Epiphany window ID
- `get_browser_window_id_any` — fallback: finds any window with Epiphany/bahmni/Security/localhost in title

### Important: NO `set -euo pipefail` in setup_task.sh
- Setup scripts source task_utils.sh which uses `||` patterns; `set -euo pipefail` causes premature exit
- All `setup_task.sh` files must NOT have `set -euo pipefail`

### Important: NO redundant navigate_to_url after restart_firefox
- Calling `navigate_to_url` after `restart_firefox` corrupts the URL to `#/https://localhost/...`
- `restart_firefox` already opens the URL — do not navigate again after it

## Bahmni Login Flow

1. Navigate to `https://localhost/bahmni/home` → redirects to `#/login`
2. Enter username (`superman`) in Username field
3. Enter password (`Admin123`) in Password field
4. Select location from dropdown (`Bahmni Clinic`) — must select, not leave as "Select Location"
5. Click Login button
6. Dashboard appears with 8 tiles: Registration, Clinical, Reports, Lab entry, Implementer Interface, Admin, Patient Documents, Appointment Scheduling

### VG coordinates (1280x720 scale, 1850x1053 window)
- Username field: (672, 358)
- Password field: (672, 390)
- Location dropdown: (672, 425)
- Login button: (672, 459)
- "Bahmni Clinic" option in dropdown: (630, 462)

## Task Descriptions

### 1. register_patient
- Register new patient: Kwame Mensah, Male, age 34
- Start state: Bahmni login page
- Setup: starts browser at login
- Verify: Check new patient exists in OpenMRS with correct demographics

### 2. create_clinical_note
- Create clinical note for Sarah Johnson (BAH000003)
- Chief complaint: "Patient presents with persistent cough for 5 days, mild fever, and sore throat."
- Navigation: Home → Clinical → search Sarah Johnson → Consultation tab → Chief Complaint field
- Start state: Bahmni login page
- Verify: Check OpenMRS encounter with obs for chief complaint text

### 3. search_patient
- Find and view profile of Fatima Al-Hassan (BAH000005)
- Start state: Bahmni login page
- Verify: Browser URL contains patient UUID, patient name visible

### 4. record_vital_signs
- Record vitals for James Osei (BAH000011): Weight=72kg, Height=175cm, Pulse=78, SBP=122, DBP=80
- Navigation: Home → Clinical → search James Osei → Vitals section
- Start state: Bahmni login page (patient has pre-existing OPD visit)
- Verify: Check obs table in OpenMRS for vital sign concept UUIDs

### 5. schedule_appointment
- Schedule appointment for Maria Gonzalez (BAH000002) for tomorrow at 10:00 AM
- Start state: Bahmni login page
- Verify: Check Bahmni appointments API for created appointment

## Common Issues and Solutions

### VNC framebuffer staleness
- VNCConnection returns cached/stale frames — NOT reliable for real content
- **Solution**: Always use `xwd -id <window_id>` via SSH for screenshots

### Browser contradiction (root cause of initial failures)
- **Problem**: `setup_bahmni.sh` warmed up Epiphany, but original `task_utils.sh` launched Firefox snap
- Firefox and Epiphany have separate SSL certificate stores — Epiphany's warm-up SSL exception didn't carry over to Firefox
- **Fix**: Rewrote `task_utils.sh` to use Epiphany throughout; dismiss_ssl_warning() called on every launch

### Epiphany SSL clicks with xdotool
- Must use `xdotool mousemove --window "$wid" X Y click 1` (window-relative coords)
- NOT `xdotool mousemove --sync X Y click 1` (screen-relative, unreliable)
- Window must be maximized before clicking; add sleep between focus and click

### Multiple Epiphany windows
- Epiphany creates tiny 10x10 subwindows (web content processes)
- `xdotool search --class Epiphany | tail -1` usually returns the main window
- Alternative: filter by geometry `xdotool getwindowgeometry` and pick the ~1850x1053 one

### Docker Compose v1 vs v2
- Bahmni Lite works with `docker-compose` v1 (1.29.2)
- Do NOT use `docker compose` v2 plugin — causes `KeyError: 'ContainerConfig'` with older images

### Patients missing OPD visits
- **Symptom**: record_vital_signs fails because James Osei has no visit
- **Fix**: `seed_bahmni.py` now creates visits for ALL patients
- **Safety net**: `record_vital_signs/setup_task.sh` auto-creates visit if missing

## Verifier Notes

### verifier.py structure
Each task has a `verify_<task_name>()` function in `verifier.py`:
- Uses OpenMRS REST API to query for created/modified records
- Checks MySQL via `docker exec bahmni-openmrsdb mysql -u openmrs-user -ppassword openmrs -e "SQL"`
- Returns `(True, "message")` or `(False, "error message")`

### Concept UUIDs for vital signs (CIEL concepts pre-loaded in Bahmni)
- Weight: `5089AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- Height: `5090AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- Systolic BP: `5085AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- Diastolic BP: `5086AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`
- Pulse: `5087AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`

## File Structure

```
benchmarks/cua_world/environments/bahmni_env/
├── env.json                    # Environment config (4 CPU, 12GB RAM)
├── config/
│   └── docker-compose.yml      # 12-container Bahmni stack
├── scripts/
│   ├── install_bahmni.sh       # pre_start: apt-get, Docker, Epiphany
│   ├── setup_bahmni.sh         # post_start: Docker Compose up, seed data, Epiphany warmup
│   ├── seed_bahmni.py          # Python patient seeding via OpenMRS REST API
│   └── task_utils.sh           # Shared bash utilities for task setup
├── tasks/
│   ├── register_patient/
│   ├── create_clinical_note/
│   ├── search_patient/
│   ├── record_vital_signs/
│   └── schedule_appointment/
│       ├── task.json           # Task description and metadata
│       ├── setup_task.sh       # pre_task hook: verify state, launch browser
│       └── verifier.py         # Success verification function
└── evidence_docs/              # Testing evidence (screenshots, logs, seed manifest)
```
