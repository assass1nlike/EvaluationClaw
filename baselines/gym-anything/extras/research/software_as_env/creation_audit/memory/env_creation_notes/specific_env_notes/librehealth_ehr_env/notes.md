> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# LibreHealth EHR Environment Notes

## Architecture
- Docker-in-QEMU: `librehealth/ehr` (PHP 7.2 + Apache2) + `mariadb:10.11` + `adminer`
- App port: 8000, Adminer port: 8001
- Admin: `admin` / `password`
- DB user: `libreehr` / `s3cret`, DB name: `libreehr`
- DB root: `m4ster_s3cret`
- Container names: `librehealth-app`, `librehealth-db`, `librehealth-adminer`

## NHANES Patient Data
- 9,375 real National Health and Nutrition Examination Survey patients
- Source: `https://github.com/LibreHealthIO/lh-ehr/raw/master/sql/nhanes/libreehr_nhanes.sql.gz` (~39MB gzip)
- Alt source: `https://gitlab.com/librehealth/ehr/lh-ehr/-/raw/master/sql/nhanes/libreehr_nhanes.sql.gz`
- **CRITICAL**: SQL is a COMPLETE dump (DROP TABLE + CREATE TABLE + INSERT) — no schema pre-init needed
- **CRITICAL**: Must import NHANES BEFORE starting app container. If app starts first, it creates an empty schema, and the NHANES dump's DROP TABLE statements conflict.
- Import command: `zcat $NHANES_FILE | docker exec -i librehealth-db mysql -uroot -pm4ster_s3cret libreehr`

## Admin Password
- NHANES SQL dump has its own bcrypt hash for the admin user (from NHANES demo data)
- Must reset to 'password' after each fresh boot via PHP:
  ```bash
  docker exec librehealth-app php -r '
  $password = "password";
  $new_hash = password_hash($password, PASSWORD_BCRYPT, array("cost" => 10));
  $new_salt = substr($new_hash, 0, 29);
  $mysqli = new mysqli("librehealth-db", "libreehr", "s3cret", "libreehr");
  $stmt = $mysqli->prepare("UPDATE users_secure SET password=?, salt=? WHERE username=\"admin\"");
  $stmt->bind_param("ss", $new_hash, $new_salt);
  $stmt->execute();
  $stmt->close();
  $mysqli->close();
  '
  ```
- Verify: `password_verify("password", $hash)` should return `true`

## Setup Wizard Bypass
- Copy `sqlconf.php` into the container to bypass setup wizard: `$config = 1`
- Container path: `/var/www/html/sites/default/sqlconf.php`
- Use `docker cp` + `docker exec chown www-data`

## Firefox Navigation
- **Snap Firefox** (`/snap/bin/firefox`) — needs `XAUTHORITY=/run/user/1000/gdm/Xauthority`
- Profile dir: `/home/ga/snap/firefox/common/.mozilla/firefox/default-release/`
- **CRITICAL**: Direct URL typing in address bar causes redirect loops in LibreHealth
  - LibreHealth v2.0.0 uses RELATIVE redirects (`header('Location: login/login.php?...')`)
  - This appends `login/login.php` to the current path, causing infinite loops
- **Working navigation**: Use header nav tabs (Calendar, Patient/Client) from the logged-in dashboard
- **Login approach**: Click username field, `ctrl+a Delete`, type 'admin', Tab, type 'password', Return
  - Login button: VG (542, 406) in 1280x720 → (813, 609) in 1920x1080
  - Wait 10s after pressing Return for dashboard to load
- **Graceful Firefox kill**: Use `ctrl+q` (xdotool) then `pkill -TERM` then `pkill -9` to avoid crash dialog
  - Also delete `recovery*.jsonlz4` and `sessionstore*.jsonlz4` to prevent troubleshoot mode dialog
- **Session cookies**: Firefox session is in-memory only. Restarting Firefox requires re-login.

## Task Details

### register_new_patient
- Start state: Main dashboard (Patient Finder + Calendar)
- Agent navigates to Patient/Client → New/Search
- No specific NHANES patient needed (creating a new one)

### add_appointment
- Start state: Calendar view (Calendar tab)
- Target patient: **Clifford Taylor** (PID=8471, DOB=1984-08-15)
- Search by last name "Taylor"
- Add "Office Visit" appointment for tomorrow at 10:00 AM

### add_medical_problem
- Start state: Patient search page (Patient/Client tab)
- Target patient: **Allan Thomas** (PID=782, DOB=1984-07-15)
- Search by last name "Thomas"
- Add problem: "Type 2 Diabetes Mellitus", ICD code E11, status Active

### update_patient_demographics
- Start state: Patient search page
- Target patient: **Erin Warren** (PID=2, DOB=2013-09-13)
- Search by last name "Warren"
- Update: Home Phone → '617-555-0233', Email → 'updated.contact@healthmail.test', City → 'Boston'
- Pre-task resets: phone='503-555-0000', email='original@nhanes.test', city='Springfield'

### write_prescription
- Start state: Patient search page
- Agent finds a patient and navigates to Prescriptions
- Writes a prescription for a medication

## Pre-existing NHANES Calendar Appointment
- The NHANES data includes a calendar appointment for "University of Central Florida" at 12:30pm
- This is visible in the calendar view — it's pre-existing NHANES demo data
- Tasks do NOT need to remove this appointment

## Task Setup Errors to Handle
- `update_patient_demographics/setup_task.sh`: **Hard-fails** if Erin Warren (PID=2) not found
  - This should never fail with real NHANES data (PID=2 is always present)
- All setup scripts verify patient existence before resetting demographics

## Debugging Commands

```bash
# Check NHANES patient count
docker exec librehealth-db mysql -u libreehr -ps3cret libreehr -N -e "SELECT COUNT(*) FROM patient_data"

# Query specific patients
docker exec librehealth-db mysql -u libreehr -ps3cret libreehr -N -e \
  "SELECT pid, CONCAT(fname,' ',lname), dob FROM patient_data WHERE pid IN (2,782,8471)"

# Check admin password hash
docker exec librehealth-db mysql -u libreehr -ps3cret libreehr -N -e \
  "SELECT username, password FROM users_secure WHERE username='admin'"

# Verify admin password
docker exec librehealth-app php -r \
  'echo password_verify("password","HASH_HERE") ? "YES" : "NO"; echo "\n";'

# Check app health
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/interface/login/login.php?site=default

# SSH into VM as ga user
ssh -i ~/.ssh/ga_qemu_key -p SSH_PORT ga@localhost
```

## Docker Compose Notes
- The `docker-compose.yml` uses Docker Compose v2 syntax
- MariaDB must be healthy before starting app container (wait loop with `mysqladmin ping`)
- `depends_on` with healthcheck is NOT used (too slow); manual wait loop in `setup_librehealth.sh`
