> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ManageEngine EventLog Analyzer Environment Notes

## Application
- **Name**: ManageEngine EventLog Analyzer 12.2.0
- **Type**: SIEM (Security Information and Event Management) web application
- **Vendor**: Zoho Corporation / ManageEngine
- **License**: Evaluation (30-day trial on fresh install)

## Installation

### Download
```
https://archive2.manageengine.com/eventlog-analyzer/12200/ManageEngine_EventLogAnalyzer_64bit.bin
```
Alternatively: search manageengine downloads for EventLog Analyzer 12.2.x Linux 64-bit.

### Installer Type
- InstallAnywhere binary (`.bin` file)
- Requires `expect` for silent/non-interactive installation
- Install duration: ~2 minutes for the Java installer itself

### Expect Script Key Patterns
The installer prompts that MUST be handled in expect:
1. `"Introduction"` — press Enter
2. `"I accept the terms of the License Agreement"` — `y` + Enter
3. `"ENTER A COMMA-SEPARATED LIST"` — Enter (accept default services menu, e.g., 2,3 for Linux)
4. `"Choose Installation Folder"` — Enter (default)
5. `"Choose Shortcut Folder"` — Enter
6. `"Pre-Installation Summary"` — Enter
7. `"Install"` — press Enter
8. Waits for `"Installation Complete"` with 600s timeout

### Install Path
```
/opt/ManageEngine/EventLog/
```
NOT `/opt/ManageEngine/EventLogAnalyzer/` - the path is just `EventLog`.

### Key Directories
```
/opt/ManageEngine/EventLog/bin/           # Executables
/opt/ManageEngine/EventLog/conf/          # Config files
/opt/ManageEngine/EventLog/pgsql/         # Bundled PostgreSQL
/opt/ManageEngine/EventLog/troubleshooting/ # Maintenance tools
/opt/ManageEngine/EventLog/logs/          # Application logs
```

## Service Management

### Starting ELA (CRITICAL)
Must `cd` to the `bin/` directory FIRST - `app_ctl.sh` uses relative paths like `./setCommonEnv.sh`:
```bash
(cd /opt/ManageEngine/EventLog/bin && nohup bash app_ctl.sh run > /tmp/ela_start.log 2>&1 &)
```

### Stopping ELA
```bash
pkill -f "WrapperJVMMain"
pkill -f "java.*EventLog"
```

### Startup Duration
- From cold start: ~3-5 minutes until HTTP 200
- Log shows: all modules LOADED → services CREATED → services STARTED
- Port 8095 begins listening while services are still starting

### Web Port
- **Default port: 8095** (NOT 8080 or 8400)
- Verify with: `ss -tlnp | grep 8095`
- `server.xml` has a comment mentioning 8080 but actual port is 8095

## Database

### PostgreSQL
- **Port**: 33335 (NOT 5432 or 33336)
- **User**: eventloganalyzer (NOT postgres or eventlog)
- **Database**: eventlog
- **Path**: `/opt/ManageEngine/EventLog/pgsql/`
- Query: `"$ELA_HOME/pgsql/bin/psql" -h localhost -p 33335 -U eventloganalyzer -d eventlog`

### pg_hba.conf Warning
ELA startup FAILS with `"Auth Mode cannot be trust"` if `pg_hba.conf` is changed to trust mode.
Backup is at `/opt/ManageEngine/EventLog/pgsql/data/pg_hba.conf.bak`.
Always restore from backup after any manual pg_hba.conf changes.

## Admin Password

### Default Password Issue
The fresh installation does NOT set admin password to "admin" - the initial hash may not match.

### Reset Admin Password (REQUIRED)
Run `resetPwd.sh` AFTER ELA has started at least once (it needs to initialize the DB):
```bash
# Must stop ELA first
pkill -f WrapperJVMMain; sleep 5
# Run reset
cd /opt/ManageEngine/EventLog/troubleshooting && bash resetPwd.sh
# Output: "Password Changed to 'admin'."
# Then restart ELA
```

### Login Verification
Test with curl (plain text passwords work for j_security_check):
```bash
curl -c /tmp/tc.txt --data "j_username=admin&j_password=admin" --max-redirs 5 -L \
    http://localhost:8095/event/j_security_check | grep -o "dashboard\|isLoginPage"
```
- `dashboard` in response → login successful
- `isLoginPage` header present → login failed

## Web UI Navigation

### URL Structure
ELA uses a Single Page Application (SPA) router. Key URLs:
- Dashboard: `http://localhost:8095/event/AppsHome.do#/home/dashboard/0`
- Alerts: `http://localhost:8095/event/AppsHome.do#/alerts/alert`
- Compliance: `http://localhost:8095/event/AppsHome.do#/compliance`
- Search: `http://localhost:8095/event/AppsHome.do#/search/index`
- Settings: `http://localhost:8095/event/AppsHome.do#settings` (via tab click from main page)
- Device Management: `http://localhost:8095/event/AppsHome.do#/settings/devicemanagement/windows`
- Technicians: accessible from Settings > Admin Settings > Management

### CRITICAL: Settings Deep-Link Issue
Navigating directly to `AppHome.do#/settings` (with `App` not `Apps`) causes ELA error page `???ErrorPage.header???`.
**Solution**: Navigate to `AppsHome.do` first, then click the Settings tab.
The Device Management and other sub-pages work via `AppsHome.do` base.

### Browser Login via xdotool
ELA uses RSA-encrypted passwords on login form submission. The xdotool click on username field + Tab + type + Enter pattern works, but may show an intermediate error page. The "Go Back To Home" button on error pages leads to the dashboard (stays logged in).

## Firefox Setup

### Snap Firefox Profile Path
Profile is in snap location: `/home/ga/snap/firefox/common/.mozilla/firefox/ela.profile`
NOT in `~/.mozilla/firefox/`.

### Launch Command
```bash
su - ga -c "
    export DISPLAY=:1
    export XAUTHORITY=/home/ga/.Xauthority
    setsid firefox --new-instance \
        -profile /home/ga/snap/firefox/common/.mozilla/firefox/ela.profile \
        'http://localhost:8095/event/index.do' \
        > /tmp/firefox_ela.log 2>&1 &
"
```

## Background Continuation Pattern (Cross-Cutting #23)

### Reason
Full ELA installation takes ~10-15 minutes total. The `pre_start` hook has a timeout.

### Solution
- `pre_start` (`install_eventlog_analyzer.sh`):
  1. Install apt packages synchronously
  2. Write background install script to `/tmp/ela_install_bg.sh`
  3. Start it with `nohup bash /tmp/ela_install_bg.sh &`
  4. Return immediately (write "BACKGROUND_STARTED" marker)
  
- `post_start` (`setup_eventlog_analyzer.sh`):
  1. Wait up to 900s for `/tmp/ela_install_complete.marker`
  2. Marker content "OK" = success; anything else = failure
  3. Start ELA service, run resetPwd.sh, restart, configure Firefox

## Real Log Data

### Syslog Collection
ELA collects the VM's own syslog via rsyslog forwarding:
```bash
# /etc/rsyslog.d/10-eventlog-analyzer.conf
*.* @127.0.0.1:513
```
Expected events collected: 1400-1600 events in first install (all of /var/log/syslog + auth.log).

### Sample Files
Copied to `/home/ga/log_samples/`:
- `system.log` (copy of /var/log/syslog)
- `auth.log` (copy of /var/log/auth.log)
- `kern.log` (copy of /var/log/kern.log if exists)

## Tasks

### 1. add_syslog_device
- **Page**: Settings > Device Management > Syslog Devices tab
- **Setup**: Navigate to dashboard → click Settings tab → click Devices card
- **Verification**: API call to `/event/api/v1/devices` returns device with IP 192.168.1.100

### 2. create_alert_rule
- **Page**: Alerts section with "Add Alert Profile" button
- **Setup**: Navigate to `AppsHome.do#/alerts/alert` (direct URL works)
- **Verification**: Alert profile named "SSH Brute Force Detection" exists in DB or API

### 3. generate_compliance_report
- **Page**: Compliance section showing all standards
- **Setup**: Navigate to `AppsHome.do#/compliance` (direct URL works)
- **Verification**: Screenshot shows compliance report page with PCI DSS selected

### 4. search_log_events
- **Page**: Log Search with query input
- **Setup**: Navigate to `AppsHome.do#/search/index` (direct URL works)
- **Verification**: Screenshot shows search results with event count

### 5. create_user_account
- **Page**: Settings > Technicians & Roles
- **Setup**: Navigate to dashboard → click Settings tab → agent clicks Technicians & Roles
- **Verification**: New technician "analyst01" appears in /event/api/v1/technicians or DB

## Fixes Applied (2026-03-15)

### 1. Missing config mount directory
The `env.json` referenced a `config/` mount directory that didn't exist. Removed the mount entry.

### 2. Snap Firefox permissions (Profile Missing dialog)
The `post_start` hook (runs as root) creates directories under `/home/ga/snap/firefox/common/` with root ownership. Snap Firefox then fails with "Profile Missing" because it can't read/write its own dirs. Fixed by adding `chown -R ga:ga /home/ga/snap` in both `setup_eventlog_analyzer.sh` and `task_utils.sh`.

### 3. No auto-login in task setup
The `ensure_firefox_on_ela` function opened Firefox at an ELA URL but didn't handle authentication. Added `ela_browser_login()` function that uses coordinate-based clicks to fill in the login form on a maximized 1920x1080 Firefox window:
- Username field: (997, 510)
- Password field: (997, 550)
- Login button: (850, 627)

### 4. "What's New" dialog not dismissed
After login, ELA shows a "What's New" overlay. Added dismissal by clicking the X button at (1530, 244).

### 5. Race condition in wait_for_eventlog_analyzer
The function polled HTTP status which could succeed during the *first* ELA start, before `resetPwd.sh` restarts ELA. Fixed with two-phase wait: first wait for `/tmp/ela_service_ready.marker`, then verify HTTP connectivity.

### 6. ELA crash after resetPwd.sh
`resetPwd.sh` was run while ELA was still running, causing "Problem while Starting Server / System halted" on restart. Fixed by stopping ELA fully before running `resetPwd.sh`, with retry logic for the subsequent start.

### 7. Post-login JSON error on index.do
After xdotool login on `index.do`, browser shows JSON error `{"SEVERITY":"SEVERE","STATUS_MESSAGE":"ads.restapi.error.api_not_found"}`. Fixed by starting Firefox at `AppsHome.do` (the SPA entry point) instead of `index.do`. Login form appears on this URL too, and after login it properly renders the dashboard.

## Troubleshooting

### ELA Won't Start (pg_hba.conf trust mode error)
```
jvm 1 | Auth Mode cannot be trust. Kindly change and restart
```
Fix: `sudo cp /opt/ManageEngine/EventLog/pgsql/data/pg_hba.conf.bak /opt/ManageEngine/EventLog/pgsql/data/pg_hba.conf`

### Login Fails After resetPwd.sh
resetPwd.sh changes the hash in the running DB but ELA caches passwords in memory.
Fix: Always restart ELA after running resetPwd.sh.

### Port Detection
Do NOT use server.xml for port detection - it shows 8080 in comments.
Use: `ss -tlnp | grep -E "8[0-9]{3}"` to find actual listening port.

### ELA Error Page (???ErrorPage.header???)
This appears when navigating to wrong URLs or using AppHome.do (without 's') directly.
Fix: Click "Go Back To Home" button to return to authenticated dashboard.
Avoid: Never type AppHome.do URLs in address bar directly; use AppsHome.do.
