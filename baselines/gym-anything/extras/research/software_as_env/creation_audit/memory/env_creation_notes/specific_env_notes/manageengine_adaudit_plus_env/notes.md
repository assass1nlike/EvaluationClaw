> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ManageEngine ADAudit Plus Environment (manageengine_adaudit_plus_env)

## Stack
- **App**: ManageEngine ADAudit Plus 8.0 (AD auditing tool)
- **Base**: `windows-11` QEMU image (1280x720)
- **Resources**: 4 CPU, 8GB RAM, net: true
- **Bundled DB**: PostgreSQL port 33307, database `adap`, user `postgres`
- **Web UI**: HTTP port 8081, HTTPS port 8444
- **Installer**: `ManageEngine_ADAudit_Plus_x64.exe` (~247MB), InstallShield GUI wizard
- **Install path**: `C:\Program Files\ManageEngine\ADAudit Plus`

## Credentials
- **Web admin**: `admin` / `Admin@2024` (changed from default `admin`/`admin` during install)
- **SSH**: `Docker` / `GymAnything123!` (Windows base image default)
- **DB**: `postgres` on port 33307, database `adap` (no password from localhost)

## Critical Installation Notes

### InstallShield GUI Automation Required
- Silent install (`-i silent`, `/s` flags) does NOT work for ADAudit Plus
- Must automate the InstallShield wizard via PyAutoGUI (TCP server on port 5555)
- Installer is a 247MB self-extracting EXE -- takes 30-45 seconds to show first wizard page
- **CRITICAL**: Session 0 (SSH) cannot detect Session 1 window titles via `Get-Process`. Use fallback: poll for ~120s then add 60s fixed wait before starting clicks. Total ~180s from schtasks /Run to first click.
- `schtasks /Create /ST 00:00` shows "Task may not run" warning (past midnight) but `/Run` still works

### Wizard Page Sequence (1280x720)
1. **Welcome** -- buttons: `< Back` (grayed), `Next >` (751, 525), `Cancel` (835, 525)
2. **License Agreement** -- buttons: `< Back` (675, 525), `Yes` (750, 525), `No` (834, 525)
   - Note: "Yes"/"No" not "Next"/"Cancel" on this page
   - "Yes" is enabled immediately (no need to scroll through license first)
3. **Choose Destination Location** -- default `C:\Program Files\ManageEngine\ADAudit Plus`
   - buttons: `< Back`, `Next >` (751, 525), `Cancel`, `Browse...`
4. **Web Server Port Selection** -- default 8081
   - buttons: `< Back`, `Next >` (751, 525), `Cancel`
5. **Registration for Technical Support (Optional)** -- buttons: `< Back`, `Next >`, `Skip` (834, 526)
   - **IMPORTANT**: Click `Skip` directly. Clicking `Next` triggers a "fill in email" popup.
   - `Skip` button is at the same position as `Cancel` on other pages
6. **Begin Installation** -- summary page, buttons: `< Back`, `Next >` (751, 525), `Cancel`
7. **Installing...** -- progress bar, then "Unpacking Jar Files" phase (2-4 minutes)
8. **InstallShield Wizard Complete** -- checkboxes + buttons:
   - Checkbox: "Yes, I want to view readme file" at (573, 328) -- UNCHECK this
   - Checkbox: "Start ADAudit Plus Server" at (573, 357) -- leave CHECKED
   - `Finish` button at (751, 525)

### Installer Timing Pitfall
- After `schtasks /Run`, the 247MB self-extracting installer takes 30-45 seconds to show its first wizard page
- If clicks start before the wizard window appears, they go to the desktop and shift all subsequent steps off by one page
- **Fix**: Poll for a process with `MainWindowTitle -like "*ADAudit*Setup*"` before starting clicks

### Password Change on First Login
- First login with `admin`/`admin` triggers mandatory password change
- Automated via Edge browser: navigate to `http://localhost:8081/`, login, fill password change form
- New password: `Admin@2024`
- Password marker file: `C:\Windows\Temp\adaudit_password.txt`

## Non-ASCII Character Corruption (CRITICAL)
- PowerShell files with em-dash `--` (U+2014) or arrow characters are corrupted during SCP to Windows
- Causes silent PowerShell parse errors (no error dialog, script just exits)
- **Fix**: Use ONLY ASCII characters in all .ps1 files (replace em-dashes with hyphens, arrows with `->`)

## Service Management
- Service name: look for `*ADAudit*` in `Get-Service`
- Alternative: start via `run.bat` in `bin\` directory
- Startup: service or `run.bat` starts Java/Zulu JRE + bundled PostgreSQL
- Typically 60-90 seconds from start to HTTP 200 on port 8081

## Database Details
- PostgreSQL bundled at `$installDir\pgsql\`
- Port: 33307 (not the standard 5432)
- Database: `adap`, User: `postgres`
- psql: `$installDir\pgsql\bin\psql.exe -h localhost -p 33307 -U postgres -d adap`
- Password reset utility: `bin\resetADAPPassword.bat`

## Data
- `generate_audit_events.ps1` creates realistic audit data:
  - 5 local Windows users (jsmith, mjohnson, rwilliams, abrown, dlee)
  - 3 security groups (IT_Support, Security_Team, Server_Admins)
  - Failed logon events (Event ID 4625) via .NET LogonUser
  - File access audit events on `C:\AuditTestFolder`
  - Password change events
- Audit policies set via `auditpol.exe`

## Task Setup Pattern
- All tasks use `task_utils.ps1` for shared functions
- Task setup launches Edge to ADAudit Plus login page via `Launch-BrowserToADAudit`
- Uses `schtasks /IT` to launch Edge in interactive Session 1
- Login URL: `http://localhost:8081/`
- Login endpoint: `/j_security_check` with `AUTHRULE_NAME=ADAPAuthenticator`

## 5 Tasks
1. **configure_email_settings** - Configure SMTP settings (smtp.company.local:587/TLS)
2. **create_technician** - Create operator account (secanalyst/Analyst@2024)
3. **configure_alert_profile** - Create "Brute Force Detection" alert (5 failures/10 min)
4. **view_logon_report** - Navigate to failed logon attempts report
5. **configure_file_audit** - Add C:\AuditTestFolder as monitored path
