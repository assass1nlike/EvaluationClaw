> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# GNU Health HIS Environment - Creation Notes

## Overview
GNU Health is an open-source Hospital Information System built on the Tryton framework.
- Application server: trytond 7.0.x
- Web client: Sao (JavaScript), served by trytond at port 8000
- Database: PostgreSQL with peer auth (Unix socket)
- Direct install in VM (not Docker-in-QEMU)

## Installation

### Software Versions
- GNU Health: `gnuhealth==5.0.*` (PyPI)
- All modules: `gnuhealth-all-modules==5.0.*` (REQUIRED meta-package)
- Trytond: `trytond>=7.0,<7.1` (GNU Health 5.0 requires this exact series, installs 7.0.45)
- Sao web client: `tryton-sao-last.tgz` from `https://downloads.tryton.org/7.0/`
- psycopg2-binary: for PostgreSQL connectivity

### Install Path
- Python venv: `/opt/gnuhealth/venv/`
- Sao client: `/opt/gnuhealth/sao/`
- Config: `/opt/gnuhealth/trytond.conf`
- Service: `/etc/systemd/system/gnuhealth.service`
- OS user: `gnuhealth` (created with `useradd -m`)
- DB user: `gnuhealth` (PostgreSQL role with createdb, no password)

### CRITICAL: Must install gnuhealth-all-modules
The demo DB activates ALL 50+ GNU Health modules. If only the base gnuhealth package
is installed, Pool initialization fails because activated modules in DB != installed modules.
```bash
pip install 'gnuhealth==5.0.*'
pip install 'gnuhealth-all-modules==5.0.*'  # REQUIRED
```

## PostgreSQL Configuration

### Peer Auth (Unix Socket)
trytond runs as the `gnuhealth` OS user, which matches the `gnuhealth` PostgreSQL role.
PostgreSQL peer auth works automatically over Unix socket (no password needed).

**CORRECT** trytond.conf URI:
```
uri = postgresql://gnuhealth@/health50
```

**WRONG** (requires password, will fail):
```
uri = postgresql://gnuhealth@localhost/health50
```

### DB Commands
```bash
# Connect as gnuhealth
sudo -u gnuhealth psql -d health50

# From root
su - gnuhealth -c "psql -d health50 -c 'SELECT ...'"
```

## Demo Database

### Source
- URL: `https://www.gnuhealth.org/downloads/postgres_dumps/gnuhealth-50-demo.sql.gz`
- Size: ~35MB compressed, ~271MB uncompressed
- Content: "GNU Solidario Hospital" demo with realistic clinical data

### Key Data
Patients (PUID system):
- **Ana Isabel Betz** (PUID: GNU777ORG) - T1D, BRCA1+, multiple allergies, prescriptions, lab results
- **Zenon Betz Mali** - family history, pediatric patient
- **John Zenon** - adult male patient
- 8+ additional patients

Users (all password: gnusolidario):
- `admin` - System administrator (full access)
- `cmegolsa` - Demo doctor/physician
- `demo_frontdesk` - Front desk staff
- `demo_doctor` - Another doctor account
- 9+ other specialized users

### CRITICAL: Password Hash Incompatibility
The demo DB was created with an older trytond that used bcrypt password hashes (`$2b$12$...`).
Trytond 7.0.45 uses passlib with scrypt format. When a user tries to login:
1. `CRYPT_CONTEXT.verify_and_update(password, bcrypt_hash)` raises `ValueError`
2. Fallback code in `res/user.py:791` tries `getattr(cls, 'check_' + hash_method)`
3. `hash_method = hash_.split(', 1)[0]` returns empty string for `$2b$12$...`
4. `check_` attribute doesn't exist → `AttributeError`

**Fix**: After restoring the DB, run a Python script to rehash all passwords:
```python
from passlib.context import CryptContext
import psycopg2

CRYPT_CONTEXT = CryptContext(schemes=['scrypt'], deprecated='auto')
new_hash = CRYPT_CONTEXT.hash('gnusolidario')

conn = psycopg2.connect(dbname='health50', user='gnuhealth')
cur = conn.cursor()
cur.execute(
    "UPDATE res_user SET password_hash = %s WHERE password_hash IS NOT NULL",
    (new_hash,)
)
conn.commit()
```
**IMPORTANT**: Must use psycopg2 parameterized SQL. The scrypt hash contains `$` characters
that bash would expand as variables if used in a shell SQL string.

## trytond Configuration

```ini
[database]
uri = postgresql://gnuhealth@/health50

[web]
listen = 0.0.0.0:8000
root = /opt/gnuhealth/sao

[session]
timeout = 43200

[cache]
clean_timeout = 0
```

**IMPORTANT**: Always write trytond.conf with `cat >` (heredoc), NEVER use `sed` to modify it.
The `sed` approach caused duplication bugs (`health50health50`) during testing.

## Pre_start Hook Timeout Issue

The install script takes 12-18 minutes (pip install of 50+ modules + demo DB download).
The framework SSH timeout cuts off the hook around 10 minutes. The script keeps running
in the background after the SSH timeout returns "exec failed: timeout".

**Workaround**: The post_start hook recreates the systemd service file and starts it.
The most time-sensitive items (gnuhealth.service creation) are done early in install script.

## Sao Web Client Login Flow

Sao uses a 2-step login:
1. **Step 1**: Main page shows database/username form with LOGIN button
   - Database field: auto-filled with `health50`
   - Username field: type username (e.g., `admin`)
   - Click LOGIN button
2. **Step 2**: Password dialog appears (modal popup)
   - Type password in dialog
   - Click OK

### Login Coordinates (1920x1080)
Step 1:
- Database field: (730, 340) - usually auto-filled
- Username field: (730, 369) - click and type
- LOGIN button: (994, 429) - green button

Step 2 (password dialog):
- Password field: (861, 232)
- OK button: (1095, 314)

### VNC Connection
```python
from gym_anything.runtime.runners.vnc_utils import VNCConnection
vnc = VNCConnection('localhost', vnc_port, password='password')
img = vnc.screenshot()
```

## Task Database Verification

All tasks use direct DB queries to verify completion. Key tables:
- `party_party` - All parties (patients, organizations, people)
- `gnuhealth_patient` - Patient records (links to party_party)
- `gnuhealth_appointment` - Appointments
- `gnuhealth_prescription_order` - Prescriptions
- `gnuhealth_lab_test_request` - Lab orders
- `gnuhealth_lab_test_result` - Lab results

### Query Pattern
```bash
sudo -u gnuhealth psql -d health50 -At -c "SELECT COUNT(*) FROM party_party WHERE name = 'Marcus Delgado'"
```

## Systemd Service

```ini
[Unit]
Description=GNU Health Hospital Information System
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=gnuhealth
WorkingDirectory=/opt/gnuhealth
Environment=PATH=/opt/gnuhealth/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/gnuhealth/venv/bin/trytond -c /opt/gnuhealth/trytond.conf
Restart=on-failure
RestartSec=5
```

Start: `systemctl start gnuhealth`
Logs: `journalctl -u gnuhealth -f`
Startup time: ~60-90s (loading all 50+ modules from the demo DB)

## Startup Time Reference
- pre_start total: ~600s+ (times out but completes in background)
- post_start total: ~180-240s (DB restore + password rehash + server start + Firefox)
- per-task pre_task: ~30-60s (login verification)

## Environment Structure
```
benchmarks/cua_world/environments/gnu_health_env/
├── env.json
├── evidence_docs/
│   ├── README.md
│   ├── 00_login_page.png
│   ├── 01_logged_in_dashboard.png
│   ├── 02_dashboard.png
│   └── 03_patients_list.png
├── scripts/
│   ├── install_gnuhealth.sh  (pre_start)
│   ├── setup_gnuhealth.sh    (post_start)
│   └── task_utils.sh         (shared utilities)
└── tasks/
    ├── register_patient/
    ├── schedule_appointment/
    ├── create_prescription/
    ├── record_lab_result/
    └── update_patient_info/
```

## CRITICAL Schema Corrections (Found During Interactive Testing)

### party_party Table Structure
```
name     = first name (NOT full name)
lastname = last name (separate column)
```

**WRONG**: `WHERE name ILIKE '%Ana%Betz%'`
**CORRECT**: `WHERE name ILIKE '%Ana%' AND lastname ILIKE '%Betz%'`

### gnuhealth_patient FK Column
The foreign key from gnuhealth_patient to party_party is named **`party`** (NOT `name`).

**WRONG**: `JOIN party_party pp ON gp.name = pp.id`
**CORRECT**: `JOIN party_party pp ON gp.party = pp.id`

### Key Tables for Tasks
- `gnuhealth_prescription_order` — FK: `patient` (→ gnuhealth_patient.id)
- `gnuhealth_patient_lab_test` — FK: `patient_id` (→ gnuhealth_patient.id)
- `party_contact_mechanism` — FK: `party`, columns: `type` ('mobile','email'), `value`
- `gnuhealth_ses_assessment` — FK: `patient`, columns: `occupation`, `education`

### Demo Data Facts
- 10 registered patients (gnuhealth_patient)
- 12 prescriptions, 18 lab test requests, 34+ appointments in demo data
- John Zenon (party id=3): person in party_party but NOT registered patient; tasks using John Zenon should be changed to Ana Isabel Betz
- Ana Isabel Betz: party id=2, gnuhealth_patient id=1, PUID=GNU777ORG
