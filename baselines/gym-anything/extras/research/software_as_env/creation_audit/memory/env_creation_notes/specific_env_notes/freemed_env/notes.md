> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# FreeMED Environment Notes

**Status**: FULLY VERIFIED 2026-02-22
**Stack**: Apache 2.4 + MySQL 8.0 + PHP 7.4 + FreeMED 0.9.0-rc1 (GitHub master)
**URL**: `http://localhost/freemed/` (port 80, no 8080)
**Admin credentials**: `admin` / `admin`

---

## Critical Architecture Decisions

### Use LAMP (NOT Docker)
- **DO NOT use `jbuchbinder/freemed` Docker image** — it uses Docker manifest v1 format which is removed in containerd v1.7+/Docker 28+. Error: `"media type 'application/vnd.docker.distribution.manifest.v1+prettyjws' is no longer supported"`
- **Install FreeMED from GitHub source** on a LAMP stack instead

### Use PHP 7.4 (NOT PHP 8.x)
- FreeMED's `lib/API.php` unconditionally declares `get_magic_quotes_runtime()` — a built-in in PHP 7.4 (deprecated) and PHP 8.0+
- In PHP 8.3, `${variable}` variable variable syntax is removed → `controller.php` fails with `Undefined constant "layout"`
- **Fix**: Install PHP 7.4 via `ppa:ondrej/php` and apply the `function_exists()` wrapper patch to `lib/API.php`

### Use Dojo UI (NOT GWT UI)
- FreeMED's default `UI = "gwt"` requires compiling Java/GWT source code (takes 30+ min, needs Maven/JDK)
- The Dojo UI is pre-built JavaScript in `ui/dojo/` and works without compilation
- **Set**: `define("UI", "dojo")` in `lib/settings.php`

---

## Installation Sequence

### install_freemed.sh (pre_start)
1. Add `ppa:ondrej/php` for PHP 7.4 support on Ubuntu 22.04
2. Install: `apache2 mysql-server php7.4 php7.4-mysql php7.4-xml php7.4-gd php7.4-mbstring php7.4-curl php7.4-zip php7.4-intl libapache2-mod-php7.4`
3. Enable `a2enmod rewrite` and `a2enmod php7.4`

### setup_freemed.sh (post_start)
1. Start MySQL and Apache: `systemctl start mysql apache2`
2. Set `SET GLOBAL log_bin_trust_function_creators = 1` — needed for stored procedures in schema files
3. Create FreeMED DB: `CREATE DATABASE freemed DEFAULT CHARACTER SET utf8 COLLATE utf8_general_ci`
4. Clone: `git clone --depth=1 https://github.com/freemed/freemed.git /usr/share/freemed`
5. **Patch API.php** (wrap `get_magic_quotes_runtime` + `define_syslog_variables` with `function_exists()`)
6. Create `lib/settings.php` (use `UI = "dojo"`, `BASE_URL = "/freemed"`)
7. Load schema: **use `grep -v '^SOURCE' file.sql | mysql freemed`** for each `.sql` file in `data/schema/mysql/`
8. Create admin user: `INSERT INTO user (username, userpassword, userdescrip, usertype, userfname, userlname) VALUES ('admin', MD5('admin'), 'System Administrator', 'super', 'Admin', 'User')`
9. Create installed marker: `touch /usr/share/freemed/data/cache/healthy`
10. Set permissions: `chown -R www-data:www-data /usr/share/freemed/`
11. Configure Apache alias for `/freemed → /usr/share/freemed`
12. Load patient data from `/workspace/data/patients.sql`
13. **Fix snap ownership**: `chown -R ga:ga /home/ga/snap/` (snap directories created as root)
14. Launch Firefox with XAUTHORITY + setsid pattern

---

## Schema Loading: Strip SOURCE Commands

FreeMED's SQL schema files have `SOURCE data/schema/mysql/_functions.sql` lines that cause:
- Recursive loading issues
- `ALTER VIEW is not allowed in stored procedures` errors
- Missing tables when loaded with regular `mysql < file.sql`

**Working approach**: Strip SOURCE lines before loading:
```bash
cd /usr/share/freemed
for f in data/schema/mysql/*.sql; do
    [ -f "$f" ] || continue
    grep -v '^SOURCE' "$f" | mysql freemed 2>/dev/null || true
done
```

---

## API.php Compatibility Fix (CRITICAL)

FreeMED's `lib/API.php` ends with:
```php
function get_magic_quotes_runtime() { return false; }
function define_syslog_variables() { return false; }
```

These conflict with PHP 7.4 built-ins. Fix:
```python
# Python patch
old = 'function get_magic_quotes_runtime() { return false; }\nfunction define_syslog_variables() { return false; }'
new = 'if (!function_exists("get_magic_quotes_runtime")) { function get_magic_quotes_runtime() { return false; } }\nif (!function_exists("define_syslog_variables")) { function define_syslog_variables() { return false; } }'
content = content.replace(old, new)
```

---

## Database Schema

Key tables used by tasks:
- `patient` — `ptfname, ptlname, ptdob, ptsex, ptaddr1, ptcity, ptstate, ptzip, pthphone, ptmphone, ptemail, ptmarital`; ID is `id` (auto_increment)
- `immunization` — `dateof, patient (FK), immunization, manufacturer, lot_number, notes`
- `allergies_atomic` — `patient, allergy, reaction, severity`
- `scheduler` — `caldateof, calhour, calminute, calduration, calpatient, calphysician, calstatus, calprenote`
- `pnotes` — `pnotespat, pnotesdoc, pnotes_S/O/A/P, pnotelocation`
- `vitals` — `patient, bp_systolic, bp_diastolic, pulse, temperature, weight, height`
- `rx` — `rxphy, rxpatient, rxdrug, rxdosage, rxquantity, rxinterval, rxrefills`
- `current_problems` — `ppatient, problem, pdate`
- `referrals` — `rpatient, rphy, rprovider, rnote, rdate`
- `user` — `username, userpassword (MD5), userdescrip, usertype ENUM('phy','misc','super'), userfname, userlname`

---

## Patient Data

20 **Synthea-generated** patients loaded from `/workspace/data/patients.sql`, IDs 1-20
(Massachusetts cohort, generated via `java -jar synthea.jar -p 30 Massachusetts`):

1. Conchita Hernandes (f, 2006-12-04, MA)
2. Corine Ziemann (f, 2000-11-29, MA)
3. Crysta Parisian (f, 2005-03-26, MA)
4. Charles Nolan (m, 2003-11-02, MA)
5. Kent Zemlak (m, 2001-02-16, MA)
6. Dwight Dach (m, 1998-03-21, MA)
7. Ezequiel Hermiston (m, 2002-05-19, MA)
8. Denny Lubowitz (f, 2000-07-04, MA)
9. Kelle Crist (f, 2002-10-18, MA)
10. Sherill Botsford (f, 1995-01-24, MA)
11. Hobert Wuckert (m, 2000-10-27, MA) → add_referral task
12. Malka Hartmann (f, 1994-11-26, MA) → add_immunization task (Td vaccine 2024-11-15)
13. Cordie King (f, 1995-03-11, MA)
14. Coreen Treutel (f, 1990-07-20, MA) → schedule_appointment task
15. Tracey Crona (m, 1981-07-02, MA) → record_vital_signs task (BP 119/73, HR 70)
16. Myrtis Armstrong (f, 1985-04-08, MA) → add_allergy task (Ibuprofen, Synthea confirmed)
17. Arlie McClure (m, 1971-03-06, MA) → add_problem_diagnosis task (CLBP onset 2014-02-03)
18. Crystal Schroeder (f, 1972-07-19, MA) → write_prescription task (Naproxen 220mg)
19. Luann Sanford (f, 1977-03-26, MA) → update_patient_demographics task
20. Horacio Santacruz (m, 1954-02-19, MA) → add_clinical_note task (ischemic heart disease + MI)

Additional Synthea patient NOT pre-loaded:
- Garfield Lebsack (m, 1962-05-16, MA) → register_new_patient task

---

## Database Queries

Direct MySQL (no Docker):
```bash
mysql -u freemed -pfreemed freemed -N -e "SELECT COUNT(*) FROM patient"
```

Or use the utility:
```bash
freemed-db-query "SELECT COUNT(*) FROM patient"
```

---

## Login

FreeMED API login verification:
```bash
curl -s -c /tmp/cookies.txt -b /tmp/cookies.txt \
  -X POST -d 'param0=admin&param1=admin' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  http://localhost/freemed/relay.php/json/org.freemedsoftware.public.Login.Validate
# Returns: true (success) or false (failure)
```

---

## 10 Tasks (ALL VERIFIED — Synthea patients)

| Task | Patient (ID) | Key Action | Synthea Data Source |
|------|-------------|------------|---------------------|
| `add_immunization` | Malka Hartmann (12) | Td vaccine 2024-11-15, Lot TD2024-892, Sanofi Pasteur | Synthea immunization records |
| `add_allergy` | Myrtis Armstrong (16) | Ibuprofen, Skin rash and hives, Moderate | Synthea: confirmed Ibuprofen allergy |
| `record_vital_signs` | Tracey Crona (15) | BP 119/73, HR 70, Temp 98.4°F, Wt 160lbs, Ht 61in | Synthea 2023-10-19 encounter |
| `register_new_patient` | Garfield Lebsack (new) | DOB 1962-05-16, M, Ludlow MA | Synthea patient 21 (not pre-loaded) |
| `schedule_appointment` | Coreen Treutel (14) | 2025-06-20 09:00 AM, Office Visit, 30 min | Synthea demographics |
| `add_problem_diagnosis` | Arlie McClure (17) | Chronic Low Back Pain, ICD-9 724.2, onset 2014-02-03 | Synthea SNOMED 278860009 |
| `write_prescription` | Crystal Schroeder (18) | Naproxen Sodium 220mg, 30 tabs, 0 refills | Synthea: Naproxen 220 MG 2024-02-10 |
| `update_patient_demographics` | Luann Sanford (19) | Phone→617-555-9283, email→luann.s.updated@healthmail.test, addr→127 Franklin St Springfield MA | Synthea demographics |
| `add_clinical_note` | Horacio Santacruz (20) | SOAP note: post-MI, BP 148/92, ischemic heart disease | Synthea: MI 2026-01-02 |
| `add_referral` | Hobert Wuckert (11) | Orthopedic Surgery (Dr. Kevin Ramirez), knee meniscal tear, 2025-05-10 | Synthea demographics |

## FreeMED UI Navigation (1280×720 coords for visual_grounding)

| Element | Coordinates | Notes |
|---------|-------------|-------|
| Login field | (180, 196) | FreeMED login form |
| Password field | (180, 213) | FreeMED login form |
| Login button | (159, 261) | |
| Patients section | (69, 670) | Bottom-left sidebar |
| Patient>Search | (114, 147) | After expanding Patients |
| Patient Entry | (114, 189) | After expanding Patients |
| Smart Search field | (390, 159) | On patient search page |
| Patient autocomplete | (390, 170) | Dropdown after typing |
| Error OK button | (777, 432) | "Error refreshing" dialog (normal; always appears on chart load) |
| Dashboard tab | (225, 110) | Top nav |

---

## Snap Firefox Notes

- Profile: `/home/ga/snap/firefox/common/.mozilla/firefox/freemed.profile`
- **Critical**: `chown -R ga:ga /home/ga/snap/` BEFORE launching Firefox (snap dirs created as root)
- Launch: `DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority setsid /snap/bin/firefox --new-instance -profile <profile_path> <url> &`
- `--new-instance` (not `--no-remote`)
- Remove lock files before launch: `.parentlock` and `lock`

---

## Known Issues / Quirks

1. **ALTER VIEW in stored procedures**: `patient.sql` stored procedure has `ALTER VIEW` which MySQL 8 doesn't allow in procs. Error is ignored; the `patient` table is created correctly.
2. **Schema file ordering**: SOURCE commands in SQL files create cross-dependencies. Stripping them and loading files in alphabetical order works fine since `CREATE TABLE IF NOT EXISTS` is idempotent.
3. **PHP 8.x incompatible**: FreeMED was written for PHP 5/6 era. PHP 8.x breaks multiple things (not just API.php). Do NOT try to use PHP 8.x.
4. **FreeMED version**: Uses 0.9.0-rc1 (GitHub master, ~2012-era code). This is the only publicly available source.
5. **Timing**: Fresh install takes ~140 seconds total (install_freemed.sh: ~90s, setup_freemed.sh: ~50s including git clone)
