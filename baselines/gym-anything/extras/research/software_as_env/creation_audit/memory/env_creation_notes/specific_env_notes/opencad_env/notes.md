> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenCAD Environment Notes

## Application
- **Name**: OpenCAD (Computer Aided Dispatch)
- **Version**: 0.3.2 (archived PHP project)
- **Source**: https://github.com/opencad-app/OpenCAD-php (release/stable branch)
- **Purpose**: CAD system for roleplay communities (GTA V game data)
- **Stack**: PHP 7.3 + MySQL 5.7

## Docker Architecture
- `opencad-db`: mysql:5.7 container with healthcheck
- `opencad-app`: php:7.3-apache container
- No named volume for /var/www/html (uses container filesystem)
- MySQL has named volume `opencad_mysql` for data persistence within session

## Critical Findings

### Password Hashing
- OpenCAD uses PHP `password_verify()` which expects **bcrypt** hashes
- MD5/SHA-1 hashes will NOT work for login
- Must create users via PHP `password_hash("password", PASSWORD_DEFAULT)`
- Users are created in setup_opencad.sh AFTER SQL schema import

### DB_PREFIX
- OpenCAD supports a DB_PREFIX for table names (default was 'oc_')
- Set to empty string `define('DB_PREFIX', '');` to avoid prefixed table names
- All SQL files use `<DB_PREFIX>` placeholder - must `sed 's/<DB_PREFIX>//g'` before import

### Official Schema
- Use `/opt/opencad-src/sql/oc_install.sql` for schema (NOT hand-written SQL)
- Use `/opt/opencad-src/sql/game_data/GTAV/oc_GTAV_data.sql` for reference data
- Schema has specific SET-type columns with fixed allowed values
- The install SQL creates a placeholder user at ID=1 (`<NAME>`, `<EMAIL>`)
- Our admin user gets ID=2

### Table Schema Quirks
- `civilian_names`: Junction table with only `user_id` + `names_id` (NOT a full table)
- `ncic_names`: Single `name` field (NOT separate first_name/last_name)
- `calls`/`call_history`: No `call_status` column; active calls are in `calls`, closed in `call_history`
- `call_id` is NOT auto_increment - app manages ID assignment
- `bolos_vehicles`: `reason_wanted` (NOT `reason`)
- `ncic_citations`: `issued_date` (NOT `citation_date`)

### set -e Danger
- NEVER use `set -e` in install or setup scripts
- Docker-in-QEMU has many commands that return non-zero (warnings, etc.)
- `set -e` caused silent script abortion leading to incomplete setup

### Department Access (Critical)
- Users MUST have entries in `user_departments` table to access CAD features
- Department ID 1 = Communications = Dispatch access
- `dashboard.php` sets `$_SESSION['dispatch']='YES'` when iterating `user_departments` rows with `department_id==1`
- Without this, `cad.php` shows "You do not have permission to be here"
- Must also populate `user_departments_temp` table (used for temporary assignments)
- After DB changes, user must visit `dashboard.php` to refresh PHP session variables

### Admin Privileges
- admin_privilege=3 = Full Admin
- admin_privilege=2 = Moderator
- admin_privilege=1 = Regular user
- approved=0 = Pending, approved=1 = Approved, approved=2 = Suspended

## Login Credentials
- Admin: admin@opencad.local / Admin123!
- Dispatcher: dispatch@opencad.local / Admin123!
- Pending users: sarah.mitchell@opencad.local, james.rodriguez@opencad.local (password123)

## Tasks
1. **create_dispatch_call**: Create 10-50 traffic collision call
2. **register_civilian**: Register Wade Hebert as civilian identity
3. **create_bolo_vehicle**: BOLO for black Declasse Vigero plate XKCD420
4. **approve_pending_user**: Approve Sarah Mitchell's pending account
5. **lookup_ncic_name**: NCIC lookup Trevor Philips, issue Reckless Driving citation

## Setup Time
- ~120s total (install + setup)
- Install: Docker, Firefox, wmctrl, xdotool, imagemagick, pymysql, Docker images, OpenCAD source
- Setup: Docker Compose, SQL import, PHP config, user creation, Firefox launch
