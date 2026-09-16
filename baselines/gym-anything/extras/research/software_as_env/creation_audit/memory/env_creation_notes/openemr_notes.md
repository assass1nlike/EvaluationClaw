# OpenEMR Environment Creation Notes

## Overview

OpenEMR is an Electronic Health Records (EHR) web application that presents unique challenges compared to standalone desktop applications. It requires a full LAMP stack (Linux, Apache, MySQL/MariaDB, PHP) and browser-based interaction.

**IMPORTANT**: After extensive testing, the **Docker-based approach** is strongly recommended over manual LAMP stack installation. See the "Docker-Based Approach (Recommended)" section below.

---

## Docker-Based Approach (Recommended)

### Why Docker?

After significant debugging of the manual LAMP stack approach, we discovered that:

1. **OpenEMR has complex initialization requirements** - The web installer sets up ~70+ globals, GACL tables, user permissions, and site configurations that are difficult to replicate via scripts
2. **Version differences matter** - Different OpenEMR versions have different database schemas, making manual SQL scripts fragile
3. **Official Docker images handle everything** - The `openemr/openemr:7.0.2` image includes all dependencies pre-configured

### Docker Inside QEMU

Docker can run inside the QEMU VM used by gym_anything:

```bash
# Install Docker in the VM (pre_start hook)
apt-get install -y docker.io docker-compose
systemctl enable docker
systemctl start docker
usermod -aG docker ga
```

### Docker Compose Configuration

```yaml
# docker-compose.yml
version: '3.8'
services:
  mysql:
    image: mariadb:10.11
    container_name: openemr-mysql
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: openemr
      MYSQL_USER: openemr
      MYSQL_PASSWORD: openemr
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-uroot", "-proot"]
      interval: 10s
      timeout: 5s
      retries: 5

  openemr:
    image: openemr/openemr:7.0.2
    container_name: openemr-app
    ports:
      - "80:80"
      - "443:443"
    environment:
      MYSQL_HOST: mysql
      MYSQL_ROOT_PASS: root
      MYSQL_USER: openemr
      MYSQL_PASS: openemr
      MYSQL_DATABASE: openemr
      OE_USER: admin
      OE_PASS: pass
    depends_on:
      mysql:
        condition: service_healthy

volumes:
  mysql_data:
```

### Default Credentials (Docker)

| Field | Value |
|-------|-------|
| Username | admin |
| Password | pass |
| Database User | openemr |
| Database Password | openemr |
| Database Name | openemr |

### Starting OpenEMR (post_start hook)

```bash
#!/bin/bash
# Copy docker-compose.yml to working directory
mkdir -p /home/ga/openemr
cp /workspace/config/docker-compose.yml /home/ga/openemr/
cd /home/ga/openemr

# Start containers
docker-compose pull
docker-compose up -d

# Wait for OpenEMR to be ready
wait_for_openemr() {
    local timeout=${1:-180}
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost/interface/login/login.php?site=default")
        if [ "$HTTP_CODE" = "200" ]; then
            echo "OpenEMR ready after ${elapsed}s"
            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
    return 1
}

wait_for_openemr 180
```

### Database Access (via Docker)

```bash
# Query the database
docker exec openemr-mysql mysql -u openemr -popenemr openemr -e "SELECT * FROM patient_data"

# Create a utility script
cat > /usr/local/bin/openemr-db-query << 'EOF'
#!/bin/bash
docker exec openemr-mysql mysql -u openemr -popenemr openemr -e "$1"
EOF
chmod +x /usr/local/bin/openemr-db-query

# Usage
openemr-db-query "SELECT COUNT(*) FROM patient_data"
```

---

## Synthea Data Integration (Docker Schema)

### Schema Differences

The Docker OpenEMR image uses a **different schema** than manual installations:

| Column | Manual Install | Docker Install |
|--------|----------------|----------------|
| Primary Key | `pid` | `pid` (but `id` is auto_increment) |
| Creation Date | `create_date` | `date` and `regdate` |
| Outcome (lists) | String ('active') | Integer (0=active, 1=resolved) |
| Prescriptions | Basic fields | Requires `txDate`, `usage_category_title`, `request_intent_title` |

### Updated Converter (synthea_to_openemr.py)

Key fixes for Docker compatibility:

```python
# 1. Patient data - include both id and pid, use correct date columns
sql = f"""INSERT INTO patient_data (
    id, pid, pubpid, fname, lname, mname, DOB, sex, ss,
    street, city, state, postal_code, country_code,
    phone_home, phone_cell, email,
    race, ethnicity, language, status,
    drivers_license, date, regdate
) VALUES (
    {pid}, {pid}, 'P{1000+pid}', '{fname}', '{lname}',
    ...
    NOW(), NOW()
) ON DUPLICATE KEY UPDATE fname = VALUES(fname);
"""

# 2. Conditions (lists table) - outcome is integer, not string
outcome = 1 if end_date else 0  # 0=active, 1=resolved
enddate_value = f"'{end_date}'" if end_date else "NULL"

sql = f"""INSERT INTO lists (id, pid, type, title, diagnosis, begdate, enddate, outcome)
VALUES ({issue_id}, {pid}, 'medical_problem', '{description}', 'SNOMED:{code}',
    '{start_date}', {enddate_value}, {outcome})
ON DUPLICATE KEY UPDATE title = VALUES(title);
"""

# 3. Prescriptions - include required Docker fields
sql = f"""INSERT INTO prescriptions (
    id, patient_id, drug, rxnorm_drugcode, date_added, start_date,
    active, txDate, usage_category_title, request_intent_title
) VALUES (
    {rx_id}, {pid}, '{drug}', '{code}', '{start_date}', '{start_date}',
    {active}, '{start_date}', '', ''
) ON DUPLICATE KEY UPDATE drug = VALUES(drug);
"""
```

### Data Loaded (Final)

| Data Type | Count | Notes |
|-----------|-------|-------|
| Patients | 47 | 46 from Synthea + 1 default |
| Medical Conditions | 360 | COVID-19, Hypertension, Diabetes, etc. |
| Allergies | 30 | Drug and food allergies |
| Prescriptions | 115 | With RxNorm codes |
| Encounters | 43,000+ | Including default data |

### Sample Loaded Data

```sql
-- Patients with diverse demographics
SELECT fname, lname, DOB, sex FROM patient_data LIMIT 5;
-- Jacinto Kris, 2017-08-24, Male
-- Alva Krajcik, 2016-08-01, Female
-- Jayson Fadel, 1992-06-30, Male
-- Jimmie Harris, 2004-01-09, Female

-- Conditions linked to patients
SELECT p.fname, l.title FROM lists l JOIN patient_data p ON l.pid = p.pid LIMIT 5;
-- Jacinto Kris: Otitis media
-- Jacinto Kris: COVID-19
-- Jayson Fadel: Hypertension

-- Prescriptions with RxNorm codes
SELECT p.fname, rx.drug, rx.rxnorm_drugcode FROM prescriptions rx
JOIN patient_data p ON rx.patient_id = p.pid LIMIT 5;
-- Jacinto Kris: Amoxicillin 250 MG Oral Capsule (308182)
-- Jayson Fadel: amLODIPine/Hydrochlorothiazide/Olmesartan (999967)
```

---

## Manual LAMP Stack Approach (Not Recommended)

The manual approach is documented below for reference, but **Docker is strongly preferred**.

### Why Manual Approach Failed

1. **Authentication Issues**: Missing globals like `gbl_auth_hash_algo`, `ip_max_failed_logins`
2. **GACL Configuration**: Complex ACL tables (`gacl_acl`, `gacl_aco`, etc.) not properly initialized
3. **Missing Database Entries**: `users_secure`, `groups`, facility records all need specific setup
4. **Version-Specific SQL**: Database schema changes between OpenEMR versions break import scripts

### Key Challenges (Manual)

#### 1. Multiple Daemon Services

**Challenge**: OpenEMR requires Apache, MariaDB, and PHP to be running simultaneously.

**Solution**:
- Use `ubuntu-gnome-systemd_highres` base image which supports systemd
- Configure `use_systemd: true` in security settings
- Start services in post_start hook with polling loops

#### 2. Database Initialization

**Challenge**: OpenEMR normally requires a web-based installer wizard.

**Solution**: Bypass by manually creating database, sqlconf.php, importing schema, and creating admin user.

#### 3. Globals Table (CRITICAL)

The globals table must contain ~70+ configuration values. Missing any causes 500 errors.

```php
$globals = [
    ['language_default', 'English (Standard)'],
    ['openemr_name', 'OpenEMR'],
    ['login_page_layout', 'login/layouts/vertical_box.html.twig'],
    ['css_header', 'style_light.css'],
    ['gbl_auth_hash_algo', 'DEFAULT'],
    ['ip_max_failed_logins', '20'],
    // ... 60+ more required settings
];
```

---

## File Structure (Docker-Based)

```
benchmarks/cua_world/environments/openemr_env/
├── env.json                           # Environment configuration
├── scripts/
│   ├── install_openemr.sh             # pre_start: Install Docker & Firefox
│   ├── setup_openemr.sh               # post_start: docker-compose up + data load
│   └── task_utils.sh                  # Shared utility functions
├── config/
│   ├── docker-compose.yml             # OpenEMR Docker stack
│   ├── sample_patients.sql            # Synthea data (Docker schema compatible)
│   └── synthea_to_openemr.py          # Converter script
├── synthea/
│   └── 10k_synthea_covid19_csv/       # Source Synthea data
├── tasks/
│   └── add_patient/
│       ├── task.json
│       ├── verifier.py
│       ├── setup_task.sh
│       └── export_result.sh
└── utils/
    └── openemr_verification_utils.py  # Database query utilities
```

---

## Verification Strategy

**IMPORTANT**: Use `copy_from_env`, NOT `exec_in_env`. See `09_verification_patterns.md` for details.

For OpenEMR tasks, verification uses a two-part pattern:

### Part 1: Export Script (export_result.sh)

Runs inside the container, queries database, saves to JSON:

```bash
#!/bin/bash
# Query database via Docker
PATIENT_DATA=$(docker exec openemr-mysql mysql -u openemr -popenemr openemr -N \
  -e "SELECT pid, fname, lname, DOB, sex FROM patient_data WHERE fname='John' AND lname='TestPatient'")

# Parse and save to JSON
cat > /tmp/add_patient_result.json << EOF
{
    "patient_found": $([ -n "$PATIENT_DATA" ] && echo "true" || echo "false"),
    "patient": {
        "fname": "$(echo "$PATIENT_DATA" | cut -f2)",
        "lname": "$(echo "$PATIENT_DATA" | cut -f3)"
    }
}
EOF
```

### Part 2: Verifier (verifier.py)

Runs on host, reads exported JSON:

```python
def verify_add_patient(traj, env_info, task_info):
    copy_from_env = env_info.get('copy_from_env')
    if not copy_from_env:
        return {"passed": False, "score": 0, "feedback": "Copy function not available"}

    # Get expected values from task metadata
    metadata = task_info.get('metadata', {})
    expected_fname = metadata.get('expected_fname', 'John')

    # Copy and parse result JSON
    temp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    copy_from_env("/tmp/add_patient_result.json", temp.name)
    with open(temp.name, 'r') as f:
        result = json.load(f)

    if result.get('patient_found'):
        return {"passed": True, "score": 100, "feedback": f"Patient '{expected_fname}' found"}
    return {"passed": False, "score": 0, "feedback": "Patient not found"}
```

---

## Browser Configuration

### Firefox Profile Setup

```bash
# Create profile directory
FIREFOX_PROFILE_DIR="/home/ga/.mozilla/firefox"
mkdir -p "$FIREFOX_PROFILE_DIR/default-release"

# profiles.ini - prevents profile selection dialog
cat > "$FIREFOX_PROFILE_DIR/profiles.ini" << 'EOF'
[Install4F96D1932A9F858E]
Default=default-release
Locked=1

[Profile0]
Name=default-release
IsRelative=1
Path=default-release
Default=1

[General]
StartWithLastProfile=1
Version=2
EOF

# user.js - disable dialogs, set homepage
cat > "$FIREFOX_PROFILE_DIR/default-release/user.js" << 'EOF'
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage", "http://localhost/interface/login/login.php?site=default");
user_pref("browser.startup.page", 1);
user_pref("signon.rememberSignons", false);
user_pref("sidebar.revamp", false);
user_pref("sidebar.verticalTabs", false);
EOF
```

---

## Troubleshooting

### Docker-Specific Issues

| Issue | Solution |
|-------|----------|
| Container won't start | Check `docker-compose logs openemr` |
| Database connection failed | Wait for MySQL healthcheck to pass |
| OpenEMR 500 error | Check `docker logs openemr-app` |
| Data import fails | Verify SQL schema matches Docker version |

### Debug Commands (Docker)

```bash
# Check container status
docker-compose ps

# View OpenEMR logs
docker logs openemr-app

# View MySQL logs
docker logs openemr-mysql

# Access MySQL shell
docker exec -it openemr-mysql mysql -u openemr -popenemr openemr

# Check patient count
docker exec openemr-mysql mysql -u openemr -popenemr openemr -N -e "SELECT COUNT(*) FROM patient_data"
```

---

## Key Lessons Learned

### 1. Use Official Docker Images for Complex Applications

Web applications with many dependencies (database, web server, runtime, extensions) are better deployed via Docker than manual installation.

### 2. Schema Compatibility is Critical

When loading data into databases:
- Always check the exact table schema first (`DESCRIBE table_name`)
- Column types matter (integer vs string for `outcome`)
- Required fields must be included (`txDate`, `usage_category_title`)
- Auto-increment columns need careful handling

### 3. Docker Can Run Inside QEMU

Nested containerization works:
- QEMU VM with KVM acceleration
- Docker daemon inside the VM
- Containers inside Docker

This provides isolation while allowing complex orchestration.

### 4. Web Apps Need Database-Driven Verification

Unlike desktop apps where you check file changes, web app verification requires:
- Database queries to check state changes
- SQL joins to verify data relationships
- Count comparisons for additions/deletions

### 5. Realistic Data is Essential for AI Testing

- Synthea provides medically accurate synthetic data
- Proper medical codes (SNOMED, RxNorm, ICD-10) make the data realistic
- Coherent patient histories (conditions → medications → encounters) are important

### 6. First-Run Dialogs Break Automation

Browser configuration must disable:
- Welcome pages
- Profile selection dialogs
- Sidebar popups
- Password save prompts
- Update notifications

---

## Resource Requirements

| Resource | Docker Approach | Manual Approach |
|----------|-----------------|-----------------|
| CPU | 4 cores | 4 cores |
| RAM | 8GB | 8GB |
| Disk | ~2GB (images) | ~500MB |
| Network | Required | Required |
| Setup Time | ~3 minutes | ~5+ minutes |
| Reliability | High | Low |

---

## Future Task Categories

| Category | Tables | Example Tasks |
|----------|--------|---------------|
| Patient Management | patient_data | Add patient, update demographics, search patients |
| Appointments | openemr_postcalendar_events | Schedule, reschedule, cancel appointments |
| Encounters | form_encounter | Document visits, record vitals |
| Prescriptions | prescriptions | Write Rx, renew medications, check interactions |
| Lab Results | procedure_result | Enter results, flag abnormals |
| Reports | Various | Generate summaries, export data |
