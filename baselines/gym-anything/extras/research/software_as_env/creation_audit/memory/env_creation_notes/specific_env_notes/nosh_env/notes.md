> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# NOSH ChartingSystem Environment Notes

## Verified: 2026-02-22

## Stack
- **App**: NOSH ChartingSystem 2.0 (nosh2) — Laravel 5/PHP 7.4 EHR
- **Docker images**: `shihjay2/nosh2:latest` (PHP-FPM port 9000) + `mariadb:10.11` + `nginx:alpine`
- **URL**: `http://localhost/login`
- **Admin**: admin / Admin1234! | **Provider**: demo_provider / Provider1234!
- **Practice**: Hillside Family Medicine (practice_id=1)

## Critical: NOSH Requires .env File (not just Docker env vars)

The `CheckInstall` middleware (`app/Http/Middleware/CheckInstall.php`) does `file_exists(base_path().'/.env')`. Without the file, every request redirects to `/update_env` which shows "installation went horribly wrong".

**Fix**: In `setup_nosh.sh`, after containers start, create `/var/www/nosh/.env` inside the nosh-app container:
```bash
docker exec nosh-app sh -c 'cat > /var/www/nosh/.env << ENVEOF
APP_ENV=local
APP_KEY=base64:jmwtyRJvY4/JhUKDi79WJ9o3MOojEvj5tgh/8H6/XqU=
APP_URL=http://localhost
DB_HOST=nosh-db
DB_DATABASE=nosh
DB_USERNAME=asuser
DB_PASSWORD=noshpassword
MAIL_HOST=localhost
DOCKER=1
...
ENVEOF'
docker exec nosh-app php artisan config:clear
```

Key `.env` requirements:
- `MAIL_HOST` must NOT be `mailtrap.io` (PostAuth middleware redirects to `setup_mail` if it is)
- `MAIL_HOST` must NOT be `smtp.gmail.com` (PostAuth checks Google token)
- `DOCKER=1` skips version file check and non-Docker migration checks
- `DB_DATABASE` must NOT be `homestead` (CheckInstall triggers `update_env` if it is)

## Critical: practiceinfo.version Must Be '2.0.0'

`CheckInstall` middleware checks `$install->version < '2.0.0'`. PHP string comparison: `"2.0" < "2.0.0"` is TRUE, so using version "2.0" triggers redirect to `/update_install`. Use "2.0.0" exactly.

## Critical: practiceinfo_plus Must Have Data

`CheckInstall` checks `DB::table('practiceinfo_plus')->first()` — if empty, redirects to `/jwk_install`. Insert with NULL JWK fields (not empty string — MariaDB has `CHECK (json_valid(private_jwk))` constraint):
```sql
INSERT IGNORE INTO `practiceinfo_plus` (practice_id, private_jwk, public_jwk) VALUES (1, NULL, NULL);
```

## Critical: Use Pipe Pattern for docker exec SQL (Not Bare Heredoc)

`docker exec container mysql ... << 'ENDSQL'` (without `-i`) silently receives no stdin — SQL is never executed. Fix:
```bash
# WRONG - stdin not connected to container without -i:
docker exec nosh-db mysql -uroot -prootpassword nosh << 'ENDSQL'
INSERT ...
ENDSQL

# CORRECT - pipe pattern:
echo "INSERT ..." | docker exec -i nosh-db mysql -uroot -prootpassword nosh

# Also CORRECT - heredoc with -i:
docker exec -i nosh-db mysql -uroot -prootpassword nosh << 'ENDSQL'
INSERT ...
ENDSQL
```

## Login Flow (for curl testing)

NOSH login requires `practice_id` field (when `patient_centric='n'`):
```bash
TOKEN=$(curl -s -c /tmp/cookies.txt http://localhost/login | grep -o '_token" value="[^"]*"' | cut -d'"' -f2)
curl -c /tmp/cookies.txt -b /tmp/cookies.txt -X POST http://localhost/login \
  --data-urlencode "username=admin" \
  --data-urlencode "password=Admin1234!" \
  --data-urlencode "_token=$TOKEN" \
  --data-urlencode "practice_id=1"
# Returns 302 to http://localhost (success) or 302 to http://localhost/login (fail)
```

## demographics_relate Schema

Table has NO `relation` column. Actual columns: `demographics_relate_id`, `pid`, `practice_id`, `id`, `appointment_reminder`, `api_key`, `url`, etc.

Correct INSERT:
```sql
INSERT IGNORE INTO `demographics_relate` (pid, id, practice_id)
SELECT pid, 2, 1 FROM demographics WHERE pid BETWEEN 1 AND 20;
```

## NOSH Docker Architecture

- **nosh-app** (`shihjay2/nosh2:latest`): PHP-FPM on port 9000, supervisord manages php-fpm + laravel-schedule
- **nosh-nginx**: nginx:alpine, proxies PHP to nosh-app:9000
- **nosh-db**: mariadb:10.11
- Entrypoint auto-runs `php artisan migrate` — no need to run manually
- APP_KEY must be provided (entrypoint reads from env var `APP_KEY`)

## Key NOSH Routes

- `/login` — login form (GET: 200, POST: 302 to `/` on success)
- `/` — dashboard (route name: 'dashboard', uses CoreController@dashboard)
- `/add_patient` — new patient registration
- `/set_patient/{pid}` — set current patient in session (GET, 302 to `/patient`)
- `/patient` — patient chart overview with full sidebar
- `/demographics` — demographics section (requires scans dir to exist — see bug fix below)
- `/allergies_list/list` — allergies section
- `/medications_list/active` — medications section
- `/immunizations_list` — immunizations section
- `/conditions_list/active` — conditions/problems section
- `/encounters_list` — encounters list
- `/schedule/{provider_id?}` — appointment scheduling
- `/users/{type}/{active}/{practice_id?}` — users management (type=2 for providers, active=1 for active)
- `/update_env` — triggered when .env missing
- `/install/practice` — triggered when practiceinfo is empty

## Groups Table

- 1 = admin, 2 = provider, 3 = assistant, 4 = billing, 100 = patient
- group_id=100 patients can access patient portal
- group_id=1-4 can access provider interface

## Disk Space Note

When `use_savevm=True`, saving a 6GB VM snapshot requires ~6GB free disk space. Reduced mem_gb from 8 to 6 to minimize snapshot size. Check `df -h ~/.cache/gym-anything/` before testing — disk is often 99% full on shared nodes.

## Patients

20 Synthea Massachusetts patients, PIDs 1-20. Task assignments:
- PID 11 (Hobert Wuckert): add_medication
- PID 12 (Malka Hartmann): add_immunization
- PID 14 (Coreen Treutel): schedule_appointment
- PID 15 (Tracey Crona): document_vitals
- PID 16 (Myrtis Armstrong): add_allergy
- PID 17 (Arlie McClure): add_medical_problem
- PID 18 (Crystal Schroeder): create_encounter
- PID 19 (Luann Sanford): update_demographics
- PID 21 reserved for register_new_patient task (Garfield Lebsack)

## Critical Bug Fixes (Found During Interactive Testing)

### Bug 1: Sex Field — demographics 500 error
- **Symptom**: `GET /demographics` → HTTP 500 "Undefined index: Male"
- **Root cause**: `patients.sql` had `sex='Male'/'Female'`; NOSH `array_gender()` returns `['m'=>'Male','f'=>'Female','u'=>'Undiff']`, so `$gender['Male']` fails
- **Fix**: `data/patients.sql` uses `'m'` and `'f'` (single lowercase chars)

### Bug 2: Missing Scans Directory — demographics 500 error
- **Symptom**: `GET /demographics` → HTTP 500 "mkdir(): No such file or directory"
- **Root cause**: `Controller.php:get_scans()` calls `mkdir(Storage::path('scans/1'), 0777)` but parent dir `/var/www/nosh/storage/app/scans` doesn't exist at container start
- **Fix**: Added to `setup_nosh.sh` after .env creation:
  ```bash
  docker exec nosh-app mkdir -p /var/www/nosh/storage/app/scans/1
  docker exec nosh-app chown -R www-data:www-data /var/www/nosh/storage/app
  ```

### Bug 3: Provider Not Listed in Users Page
- **Symptom**: `/users/2/1` shows "None." even though demo_provider user exists with group_id=2
- **Root cause**: CoreController@users for type=2 does `->join('providers', 'providers.id', '=', 'users.id')` — demo_provider had no row in `providers` table
- **Fix**: Added to `setup_nosh.sh` after inserting provider user:
  ```bash
  echo "INSERT IGNORE INTO providers (id, npi, specialty, timeslotsperhour, schedule_increment, practice_id) VALUES (2, '1234567890', 'Family Medicine', 2, '20', 1);" | docker exec -i nosh-db mysql -uroot -prootpassword nosh
  ```

### Bug 4: Firefox Autocomplete Interference
- **Symptom**: Password field pre-filled with wrong cached value from earlier failed login attempts
- **Fix**: Added to `setup_nosh.sh` Firefox user.js: `browser.formfill.enable=false`, `signon.generation.enabled=false`

### Bug 5: Admin Cannot Add Clinical Data (CRITICAL)
- **Symptom**: No "+" add button visible on any patient chart section (allergies, immunizations, medications, conditions, encounters) when logged in as admin
- **Root cause**: NOSH restricts clinical data entry to group_id=2 (provider). Admin (group_id=1) can view chart sections but "+" buttons are hidden.
- **Fix**: All 8 clinical task descriptions updated to use `demo_provider / Provider1234!` instead of `admin / Admin1234!`. Practice management tasks (add_provider, register_new_patient) still use admin.

### Bug 6: FullCalendar "Closed" Blocks → schedule page non-functional (CRITICAL)
- **Symptom**: `/schedule/2` shows calendar but all time slots covered by "Closed" blocks; clicking produces no appointment dialog
- **Root cause**: `practiceinfo` table had NULL for `weekends`, `minTime`, `maxTime`, `timezone`, `mon_o`, `mon_c`, `tue_o/c`, `wed_o/c`, `thu_o/c`, `fri_o/c`; `calendar` table empty (no visit types available)
- **Fix**: Added to `setup_nosh.sh` after provider profile insert:
  ```sql
  UPDATE practiceinfo SET weekends='0', minTime='08:00', maxTime='18:00', timezone='America/New_York',
    mon_o='08:00', mon_c='17:00', tue_o='08:00', tue_c='17:00', wed_o='08:00', wed_c='17:00',
    thu_o='08:00', thu_c='17:00', fri_o='08:00', fri_c='17:00' WHERE practice_id=1;
  INSERT IGNORE INTO calendar (visit_type, duration, active, practice_id, provider_id) VALUES ('Office Visit', 30, 'y', 1, 0);
  ```

## All 10 Tasks Verified

Start state: Firefox maximized showing `http://localhost/login` with:
- Username, Password, Practice dropdown (Hillside Family Medicine), Login button
- **Clinical tasks** log in with `demo_provider/Provider1234!`; **admin tasks** use `admin/Admin1234!`
- All task descriptions include appropriate credentials

Verified patient chart sections load correctly (no 500 errors) after all fixes applied:
- demographics, allergies_list/list, medications_list/active, immunizations_list
- conditions_list/active, encounters_list, patient chart, users/2/1, schedule, add_patient
- Verified with provider login: "+" add button visible in all chart sections
- Verified encounter creation form, vitals form, appointment creation form, add allergy form (see evidence_docs/)

## Post-Audit Fixes (2026-02-22)

Round 1 (audit 1):
- `schedule_appointment`: Date changed from June 20, **2025** (past) to June 20, **2026** (future); setup_task.sh cleanup also updated from '2025-06-20%' to '2026-06-20%'
- `document_vitals`: Vital values corrected (98.4°F→98.2°F, 160lbs→185lbs, 61in→68in); description rewritten to have agent create October 19, 2023 encounter then add vitals; setup_task.sh now also deletes encounters for pid=15
- `add_medical_problem`: setup_task.sh now deletes ALL issues for pid=17 (not just back pain) to remove pre-existing inactive Synthea conditions
- `add_provider`: "administration panel" → "Users section (accessible from the top navigation bar)"
- All 10 tasks: Added login credentials to each task description

Round 2 (audit 2):
- All 8 clinical tasks: Changed credentials from `admin/Admin1234!` to `demo_provider/Provider1234!` (admin cannot see "+" add buttons in chart sections)
- `setup_nosh.sh`: Added practiceinfo calendar fields (Mon-Fri 08:00-17:00, America/New_York, no weekends) and 'Office Visit' entry in calendar table (required for FullCalendar to render clickable time slots)
- `patients.sql`: Fixed wrong comment (pid 1 incorrectly labeled "used for add_allergy task"; correct task patient is pid 16 Myrtis Armstrong)
- New evidence screenshots added: 18a (allergy + button), 18 (add allergy form), 19 (appointment form), 20 (encounter form), 21 (vitals form)
