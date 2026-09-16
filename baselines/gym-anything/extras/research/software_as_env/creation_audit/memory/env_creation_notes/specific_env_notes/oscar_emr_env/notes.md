> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OSCAR EMR Environment Notes

## Overview
- Docker-in-QEMU: `openosp/open-osp:release` (oscar-app) + `mariadb:latest` (oscar-db), port 8080
- OSCAR = Open Source Clinical Application Resource, Canadian open-source EMR
- Admin: `oscardoc` / `oscar` / PIN: `1117`
- Provider: Dr. Sarah Chen, provider_no='999998'
- URL: `http://localhost:8080/oscar/login.jsp`

## Critical: FaxSchedulerJob Boot Failure

**Problem**: OSCAR fails to start with `NoSuchBeanDefinitionException: faxSchedulerJob`
- Root cause: `openosp/open-osp:release` image is missing the FaxSchedulerJob bean in `spring_managers.xml`
- OSCAR's Tomcat loads the Spring context during WAR deployment → crashes before HTTP is available
- **ORDERING IS CRITICAL**: Must patch `spring_managers.xml` BEFORE waiting for OSCAR to be ready

**Fix in setup_oscar.sh**:
1. Wait for WAR extraction: poll until `/usr/local/tomcat/webapps/oscar/WEB-INF/classes/spring_managers.xml` exists
2. Patch immediately: `docker exec oscar-app sed -i "s|</beans>|$FAX_BEAN\n</beans>|" "$SPRING_FILE"`
3. Use `grep -q` (NOT `grep -c`) to detect if patch applied — grep -c returns "0\n" with newline which breaks `[ -eq 0 ]`
4. Restart oscar-app: `docker restart oscar-app`
5. THEN wait for HTTP to be available

## OSCAR Password Hashing

SHA-1 via Java's `EncryptionUtils.getSha1()`:
- Bytes concatenated as **signed** decimal integers with `-` separator
- Hash of 'oscar': `45-179-551441115-117798-30877213-3052-6889-30-60`
- This is set via: `UPDATE security SET password='...' WHERE user_name='oscardoc'`

## Database Schema (Critical Differences from Standard)

### demographic table (patients):
- `year_of_birth VARCHAR(4)` — NOT a date field
- `month_of_birth VARCHAR(2)` — NOT a date field
- `date_of_birth VARCHAR(2)` — day of month, NOT a date field
- `patient_status VARCHAR(2)` — use `'AC'` for active (NOT `'A'`)
- `hin VARCHAR(20)` — health insurance number (NOT `hc`)
- NO `active` column

### provider table:
- `work_phone` — NOT `clinic_phone` (that column doesn't exist)
- `status CHAR(1)` — use `'1'` for active (NOT `active=1`)
- NO `active` column

### drugs table:
- `` `repeat` `` — MySQL reserved keyword, MUST use backticks
- `GN` = generic name, `BN` = brand name
- `freqcode` = frequency code ('od'=once/day, 'tid'=3x/day, 'bid'=2x/day)
- `durunit` = duration unit ('d'=days, 'w'=weeks, 'm'=months)
- `end_date` is NOT NULL — use `'0001-01-01'` as placeholder

### allergies table:
- `DESCRIPTION VARCHAR(255)` — uppercase column name
- `severity_of_reaction CHAR(1)` — not varchar (use 'M', 'S', 'L' for moderate/severe/life-threatening)
- `lastUpdateDate` — camelCase (NOT `LASTUPDATE`)
- `TYPECODE INT` — not varchar
- `demographic_no` — lowercase

## Firefox Launch from Root Context

**Problem**: Setup scripts called as root (via pre_task hook) need to launch Firefox as `ga` user.
- `sudo -u ga nohup firefox &` fails with `use_pty` sudoers option → process killed when sudo exits
- `su - ga -c "..."` requires a login TTY

**Working solution**:
```bash
if [ "$(whoami)" = "ga" ]; then
    DISPLAY=:1 nohup firefox "$URL" > /tmp/firefox_task.log 2>&1 &
    disown
else
    # sudo su ga + disown properly detaches the process
    sudo su ga -s /bin/bash -c "DISPLAY=:1 nohup firefox '$URL' > /tmp/firefox_task.log 2>&1 & disown"
fi
```

**Note**: gym_anything pre_task hooks actually run as the `ga` SSH user, so the `else` branch is for safety.

## URL: login.do vs login.jsp

- `login.jsp` — shows the login form (correct for browser navigation)
- `login.do` via GET — returns "Application Error. See Log." (LoginAction.java:94)
- `login.do` via POST — processes login form submission
- Always use `login.jsp` for browser-facing URLs; `login.do` is OK for `curl` readiness checks (302 redirect is fine)

## Provider Setup

- `oscardoc` is the security (login) user, linked to provider record via `provider_no`
- Provider INSERT: `INSERT IGNORE INTO provider (provider_no, last_name, first_name, provider_type, sex, specialty, work_phone, status, ohip_no) VALUES ('999998', 'Chen', 'Sarah', 'doctor', 'F', 'General Practice', '(416) 555-0100', '1', '123456789')`
- Link login to provider: `UPDATE security SET provider_no='999998' WHERE user_name='oscardoc'`

## Seed Data

- 20 patients with realistic Canadian demographics (Ontario addresses, HC numbers, area codes)
- Key task patients: Paul Tremblay, Jonathan Carroll, Agnes Miller, Eliseo Nader
- All patients assigned `provider_no='999998'` (Dr. Sarah Chen)
- Pre-existing medications: Lisinopril (Carroll), Metformin (Tremblay)
- Pre-existing allergies: Penicillin (Nader), Sulfa (Miller), Latex (Kowalski)

## Docker Compose Setup

- OSCAR depends on MariaDB being healthy before starting
- oscar-app logs go to: `docker logs oscar-app`
- spring_managers.xml location (after WAR extraction): `/usr/local/tomcat/webapps/oscar/WEB-INF/classes/spring_managers.xml`

## Tasks (5 total)

1. **register_patient** — Register Emily Nakamura (DOB: 1991-08-14, ON HC: 9001234567)
2. **add_allergy** — Add Codeine allergy (Moderate) to Eliseo Nader's chart
3. **document_encounter** — Create encounter note for Jonathan Carroll (hypertension)
4. **prescribe_medication** — Prescribe Amoxicillin 500mg TID to Agnes Miller
5. **schedule_appointment** — Schedule Paul Tremblay for "next Monday" at 14:00 with Dr. Chen

## Evidence

All 5 task start screenshots are in `evidence_docs/`:
- `task_register_patient_start.png` — OSCAR login page ready
- `task_add_allergy_start.png` — OSCAR login page ready
- `task_document_encounter_start.png` — OSCAR login page ready
- `task_prescribe_medication_start.png` — OSCAR login page ready
- `task_schedule_appointment_start.png` — OSCAR login page ready
- `01_login_page.png` — OSCAR login page (from actual task start)
- `02_dashboard_logged_in.png` — Dashboard after login as oscardoc → shows "Chen, Sarah"
