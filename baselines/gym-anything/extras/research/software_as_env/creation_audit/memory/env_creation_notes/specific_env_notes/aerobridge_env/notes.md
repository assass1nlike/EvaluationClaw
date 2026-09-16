> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Aerobridge Environment — Creation Notes

## Overview
- Django-based drone/UAV operations management system (archived Dec 2023, v1.0.1)
- Port: 8000 (HTTP, no SSL) — no SSL complications
- Admin: `admin` / `adminpass123` (created via `createsuperuser` in setup script)
- SSH user: `ga` / `password123`
- Database: SQLite at `/opt/aerobridge/aerobridge.sqlite3` (settings.py: `BASE_DIR / 'aerobridge.sqlite3'`)
- App root: `/opt/aerobridge/`, venv: `/opt/aerobridge_venv/`
- Django settings: `aerobridge.settings`

## Installation (pre_start) — `install_aerobridge.sh`

### Key steps
1. Install system deps: `git python3-pip python3-venv python3-dev libpq-dev libssl-dev libffi-dev scrot`
2. Clone Aerobridge: `git clone https://github.com/openskies-sh/aerobridge.git /opt/aerobridge`
3. Create venv: `python3 -m venv /opt/aerobridge_venv`
4. Pip install: `pip install -r /opt/aerobridge/requirements.txt`
5. **CRITICAL**: Upgrade `django-simple-history` to `>=3.7.0` — the pinned version causes migration errors
   ```bash
   pip install --upgrade 'django-simple-history>=3.7.0'
   ```
6. Create `.env` file with `SECRET_KEY`, `ALLOWED_HOSTS=*`, and other env vars (NO DATABASE_URL needed — Aerobridge settings.py hardcodes `BASE_DIR / 'aerobridge.sqlite3'`)
7. Run Django setup: `migrate`, `collectstatic`, `createsuperuser --noinput`
8. **CRITICAL**: Load fixture data from `aerobridge/fixtures/` (DJI drone data, etc.)
   ```bash
   python3 manage.py loaddata /opt/aerobridge/fixtures/*.json
   ```
   This provides pre-loaded Aircraft records (`F1 #1`, `F1 #2`) that FlightOperation tasks reference.

### Why `django-simple-history` upgrade is needed
- Aerobridge pins an old version that doesn't support newer Django
- Running `migrate` fails with `TypeError: integer argument expected` without the upgrade
- Fix: install after the main `requirements.txt` install

## Setup (post_start) — `setup_aerobridge.sh`

### Startup sequence
1. Start Aerobridge as systemd service (or `gunicorn` via `nohup` if systemd not available)
2. Wait for HTTP 200 on `http://localhost:8000/`
3. Launch Firefox to `http://localhost:8000/admin/` to warm up the profile

### Gunicorn launch (non-systemd path)
```bash
cd /opt/aerobridge
source /opt/aerobridge_venv/bin/activate
nohup gunicorn aerobridge.wsgi:application --bind 0.0.0.0:8000 \
    --workers 2 --timeout 120 --access-logfile /tmp/gunicorn_access.log \
    --error-logfile /tmp/gunicorn_error.log &
```

## Critical: Model Fields (verified via Django shell)

### `registry` app models

**Aircraft**:
- `name` — aircraft name/call sign (e.g., "Phoenix Mk3")
- There is NO `nick_name`, `serial_number`, or `registration_mark` field at the Django model level for filtering
- Use `Aircraft.objects.filter(name='...')` for cleanup

**Company** (NOT Manufacturer):
- **CRITICAL**: There is NO `Manufacturer` model. Use `Company` from `registry.models`.
- `full_name` — company's full name (e.g., "SkyTech Innovations")
- `country` — 2-letter ISO country code (e.g., "IN" for India)
- Do NOT use `name`, `country_of_domicile` — those fields don't exist
- Admin panel shows this as "Companys" (Django pluralization of Company)
- **CRITICAL (discovered interactive testing)**: Company admin requires ALL of:
  `full_name`, `common_name`, `website`, `email`, `documents` (M2M — select at least one), `country`
  `blank=False` on `documents` ManyToManyField means you MUST select an item from the list widget

**Person**:
- `first_name`, `last_name`, `email`, `phone_number` (required), `documents` (M2M, required)
- Pilots are created via a separate `Pilot` model that FKs to `Person`
- Admin shows "Pilots" (accessing via Pilot FK)
- **CRITICAL (discovered interactive testing)**: Person is NOT registered in Django admin by default
  → the '+' popup button does NOT appear next to the Person field on the Pilot add form
  → Fix: patch `/opt/aerobridge/registry/admin.py` to add:
    ```python
    from .models import ..., Person, ...
    admin.site.register(Person)
    ```
  → This is done in `setup_task.sh` for the `add_pilot` task

**Pilot**:
- FKs: `person` (OneToOneField to Person), `operator` (FK to Company), `address` (FK to Address)
- `documents` (M2M) — also required
- **CRITICAL**: Pilot form requires `address` field (FK to Address model) — not optional

### `gcs_operations` app models

**FlightPlan**:
- `name` — display name of the plan
- `plan_file_json` — JSONField for plan data
- `geo_json` — GeoJSON geometry
- **CRITICAL (discovered interactive testing)**: Both `plan_file_json` and `geo_json` have `blank=False`.
  Django JSONField with `blank=False` rejects empty dict `{}` — "This field cannot be blank."
  Agent must enter a NON-EMPTY JSON object, e.g.: `{"name": "Mumbai Coastal Survey"}`
  For geo_json, use a valid GeoJSON: `{"type": "Point", "coordinates": [72.8777, 19.0760]}`

**FlightOperation**:
- `name` — display name
- `drone` — FK to Aircraft
- `flight_plan` — FK to FlightPlan
- `operator` — FK to Company
- `purpose` — text field

## Browser: Snap Firefox

### CRITICAL: Snap profile path
- Ubuntu's Firefox snap stores actual profile data in:
  `/home/ga/snap/firefox/common/.mozilla/firefox/`
- **NOT** in `/home/ga/.mozilla/firefox/` (this dir doesn't exist until Firefox runs non-snap)
- The `-profile` flag must point to the snap path
- **MUST create the profile directory** in the snap path before launching; if it doesn't exist,
  Firefox shows "Profile Missing" dialog and fails to open the URL
- The snap base directory (`/home/ga/snap/firefox/common/.mozilla/firefox/`) IS auto-created
  by Firefox snap on first run, but the named profile (`aerobridge.profile`) must be created manually

### Firefox launch pattern (working — verified)
```bash
pkill -9 -f firefox 2>/dev/null || true
sleep 2
# Remove lock files from BOTH locations
rm -f /home/ga/.mozilla/firefox/aerobridge.profile/lock \
       /home/ga/.mozilla/firefox/aerobridge.profile/.parentlock \
       /home/ga/snap/firefox/common/.mozilla/firefox/aerobridge.profile/.parentlock \
       /home/ga/snap/firefox/common/.mozilla/firefox/aerobridge.profile/lock
# IMPORTANT: remove snap locks inside su -ga shell too (snap sandbox)
su - ga -c "rm -f /home/ga/snap/firefox/common/.mozilla/firefox/aerobridge.profile/.parentlock \
    /home/ga/snap/firefox/common/.mozilla/firefox/aerobridge.profile/lock; \
    DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority setsid firefox --new-instance \
    -profile /home/ga/snap/firefox/common/.mozilla/firefox/aerobridge.profile \
    'http://localhost:8000/admin/' &"
sleep 6
```

### Key flags
- `--new-instance` (NOT `--no-remote`): Creates a fresh browser process regardless of running instances
- `-profile <snap_path>`: Use the snap profile path directly
- `setsid`: Detaches the process from the shell session
- Lock removal inside `su - ga` shell: The snap sandbox means the ga user's perspective of the filesystem matters

### Why the "Close Firefox" dialog appears
1. Firefox snap writes `.parentlock` to `/home/ga/snap/firefox/common/.mozilla/firefox/<profile>/`
2. When Firefox crashes/is killed, `.parentlock` remains
3. On next launch without the lock removal, Firefox shows "Close Firefox" dialog and hangs
4. The fix: remove lock files AS the `ga` user (inside the `su - ga` command), AND use `--new-instance`

### Firefox profile creation (setup script)
Must create the profile in the snap path IN `setup_aerobridge.sh` (before first Firefox launch):
```bash
SNAP_FF_DIR="/home/ga/snap/firefox/common/.mozilla/firefox"
mkdir -p "${SNAP_FF_DIR}/aerobridge.profile"
# Write user.js to suppress dialogs
cat > "${SNAP_FF_DIR}/aerobridge.profile/user.js" << 'EOF'
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.startup.page", 0);
EOF
# Write profiles.ini so Firefox finds the profile by name
cat > "${SNAP_FF_DIR}/profiles.ini" << 'EOF'
[Profile0]
Name=aerobridge
IsRelative=1
Path=aerobridge.profile
Default=1

[General]
StartWithLastProfile=1
Version=2
EOF
chown -R ga:ga /home/ga/snap/firefox/
```

## QEMU Mounts Are Copies, NOT Live Mounts

**CRITICAL**: In the QEMU+Apptainer runner, files listed in `env.json` `mounts` are COPIED to the VM
disk at `env.reset()` time. They are NOT 9p/virtio live mounts.

Evidence: `cat /proc/mounts` showed no 9p or virtio-fs entries; `/workspace` is on `/dev/vda1`.

**Implication for development/testing**:
- If you edit a script on the host and want to test it in an already-running VM, you MUST push the
  file via SFTP/SCP to the VM
- `env.reset()` with `use_cache=False` re-copies all mount files to a fresh VM disk
- Use: `sftp -P <port> ga@localhost <<< $'put scripts/task_utils.sh /workspace/scripts/task_utils.sh'`

## Admin Panel Structure

After logging in at `http://localhost:8000/admin/`:
- **AUTHENTICATION AND AUTHORIZATION**: Users, Groups
- **DIGITALSKY_PROVIDER**: Credentials, Tokens
- **GCS_OPERATIONS**: Flight logs, Flight operations, Flight plans, Transactions
- **PKI_FRAMEWORK**: Aerodrome certificates, ...
- **REGISTRY**: Aircrafts, Authorizations, Companys, Contact informations, Manufacturers, Pilots, ...

Note: "Companys" (not "Companies") — Django default pluralization.

## Task Descriptions

### 1. `register_aircraft`
- Add aircraft "Phoenix Mk3" (serial: PHX-MK3-2024-001, mark: VT-P001)
- Via: REGISTRY → Aircrafts → Add Aircraft
- Cleanup: `Aircraft.objects.filter(name='Phoenix Mk3').delete()`
- Verification: count increased by 1, Aircraft with name "Phoenix Mk3" exists

### 2. `add_manufacturer`
- Add company/manufacturer "SkyTech Innovations" (country: India = "IN")
- Via: REGISTRY → Companys → Add Company
- Cleanup: `Company.objects.filter(full_name='SkyTech Innovations').delete()`
- Verification: Company with `full_name='SkyTech Innovations'`, `country='IN'` exists
- **CRITICAL**: Model is `Company`, field is `full_name` (NOT `Manufacturer`, NOT `name`)

### 3. `add_pilot`
- Add person "Aditya Kumar" (email: aditya.kumar@droneops.in)
- Via: REGISTRY → Pilots → Add Pilot (which creates a Person)
- Cleanup: `Person.objects.filter(first_name='Aditya', last_name='Kumar').delete()`
- Verification: Person with correct name and email exists

### 4. `create_flight_plan`
- Create flight plan "Mumbai Coastal Survey"
- Via: GCS_OPERATIONS → Flight plans → Add Flight plan
- Cleanup: `FlightPlan.objects.filter(name='Mumbai Coastal Survey').delete()`
- Verification: FlightPlan count increased, plan with name exists

### 5. `create_flight_operation`
- Create flight operation "Rajasthan Corridor Inspection"
- Via: GCS_OPERATIONS → Flight operations → Add Flight operation
- Cleanup: `FlightOperation.objects.filter(name='Rajasthan Corridor Inspection').delete()`
- Verification: FlightOperation count increased, operation with name exists
- Note: Pre-loaded aircraft "F1 #1", "F1 #2" available from fixture data

## Task Starting State

- Firefox opens to `http://localhost:8000/admin/` but REDIRECTS to `/admin/login/?next=/admin/`
  because no session cookie exists in the fresh profile
- **This is CORRECT** — the task description says "Log in to the admin panel... using username
  'admin' and password 'adminpass123'" — login is part of the task
- After login, agent sees the Django admin dashboard with REGISTRY, GCS_OPERATIONS, etc. sections
- GTK warnings about `canberra-gtk-module` in the shell output are harmless (Firefox snap issue)

## Server Startup: Systemd Service (post_start)

In `setup_aerobridge.sh`, the server is started as a systemd service (more reliable than setsid):
```bash
cat > /etc/systemd/system/aerobridge.service << 'UNITEOF'
[Unit]
Description=Aerobridge Drone Management Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/aerobridge
EnvironmentFile=/opt/aerobridge/.env
ExecStart=/opt/aerobridge_venv/bin/python manage.py runserver 0.0.0.0:8000
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/aerobridge_server.log
StandardError=append:/var/log/aerobridge_server.log
UNITEOF

systemctl daemon-reload
systemctl enable aerobridge
systemctl start aerobridge
```

The `task_utils.sh` `wait_for_aerobridge()` function includes auto-restart logic:
- If server doesn't respond within 15s, calls `systemctl restart aerobridge`
- Falls back to direct setsid launch if systemd unavailable
- env.json has `"use_systemd": true` so systemd IS available

## Interactive Testing Results (Phase 6, 2026-02-20)

All 5 tasks completed end-to-end via VNC + xdotool by human tester.

| Task | Result | Evidence |
|------|--------|----------|
| register_aircraft | ✓ Phoenix Mk3 saved | evidence_docs/evidence_register_aircraft_*.png |
| add_manufacturer | ✓ SkyTech Innovations saved | evidence_docs/evidence_add_manufacturer_success.png |
| add_pilot | ✓ Aditya Kumar saved | evidence_docs/evidence_add_pilot_success.png |
| create_flight_plan | ✓ Mumbai Coastal Survey saved | evidence_docs/evidence_create_flight_plan_success.png |
| create_flight_operation | ✓ Rajasthan Corridor Inspection saved | evidence_docs/evidence_create_flight_operation_success.png |

**Task descriptions updated** to accurately reflect all required form fields.
**setup_task.sh for add_pilot updated** to auto-patch admin.py for Person registration.

## Common Issues and Solutions

### `Manufacturer` model does not exist
- **Symptom**: `ImportError: cannot import name 'Manufacturer' from 'registry.models'`
- **Fix**: Use `Company` model with `full_name` and `country` fields

### Aircraft cleanup using wrong field
- **Symptom**: `Aircraft.objects.filter(nick_name='...')` raises `FieldError`
- **Fix**: Use `Aircraft.objects.filter(name='...')`

### `django-simple-history` migration errors
- **Symptom**: `TypeError: integer argument expected` or `HistoricalRecords` migration failures
- **Fix**: `pip install --upgrade 'django-simple-history>=3.7.0'` after main requirements install

### Firefox "already running" dialog
- **Cause**: Stale `.parentlock` file in snap profile directory
- **Fix**: Remove snap profile lock files inside the `su - ga` command, AND use `--new-instance`
- See "Snap Firefox" section above for complete working pattern

### Gunicorn workers not starting
- **Cause**: `DJANGO_SETTINGS_MODULE` or `DATABASE_URL` not in environment
- **Fix**: Set them explicitly in the launch command or via `.env` with `set -a; source .env; set +a`

### Person model '+' button missing on Pilot add form
- **Symptom**: No green '+' button next to the Person field when adding a Pilot
- **Cause**: `Person` is not registered in Django admin (`registry/admin.py`)
- **Fix**: Patch admin.py to add `admin.site.register(Person)` (done in add_pilot setup_task.sh)
- Django runserver auto-reloads within 1-2 seconds of admin.py modification

### JSONField "This field cannot be blank" with `{}`
- **Symptom**: Submitting FlightPlan form with `{}` in plan_file_json or geo_json fails validation
- **Cause**: Django `JSONField(blank=False)` treats empty dict as blank
- **Fix**: Agent must enter non-empty JSON: `{"name": "Mumbai Coastal Survey"}`

### Company admin form missing fields
- **Symptom**: Saving Company form fails with multiple required field errors
- **Cause**: Task description only listed Full Name + Country; Company requires 6 fields
- **Fix**: Updated task.json to list all required fields (common_name, website, email, documents, country)

### Aircraft flight_controller_id validation
- **Symptom**: Aircraft form rejects flight_controller_id with spaces or dashes
- **Cause**: Field requires alphanumeric characters only
- **Fix**: Use only letters and digits, e.g., "PHX001" not "PHX-001"

## File Structure

```
benchmarks/cua_world/environments/aerobridge_env/
├── env.json                        # 4 CPU, 6GB RAM, ubuntu-gnome-systemd_highres base
├── scripts/
│   ├── install_aerobridge.sh       # pre_start: apt, clone, pip, migrate, fixtures
│   ├── setup_aerobridge.sh         # post_start: start gunicorn, create admin, launch Firefox
│   └── task_utils.sh               # Shared bash utilities (wait_for_aerobridge, etc.)
├── tasks/
│   ├── register_aircraft/
│   ├── add_manufacturer/
│   ├── add_pilot/
│   ├── create_flight_plan/
│   └── create_flight_operation/
│       ├── task.json               # Task description and metadata
│       ├── setup_task.sh           # pre_task: cleanup, count baseline, launch Firefox
│       ├── export_result.sh        # Exports task result to JSON for verifier
│       └── verifier.py             # Score-based verification function
├── artifacts/                      # Test episode recordings
└── evidence_docs/
    └── README.md                   # Testing evidence documentation
```
