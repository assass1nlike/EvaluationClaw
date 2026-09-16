> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ManageEngine OpManager Environment Notes

## Installation Quirks

### 1. Silent Installer Port Placeholders
The `.bin` installer in silent mode (`-i silent`) does NOT replace port placeholders in `conf/server.xml`. The file contains literal strings `HTTP_PORT` and `WEBSERVER_PORT` instead of actual port numbers. **Must fix after install**:
```python
content = content.replace('HTTP_PORT', '8060')
content = content.replace('WEBSERVER_PORT', '8443')
```

### 2. Systemd Service Registration
The bundled `bin/linkAsService.sh` creates a **masked** systemd service. It also uses the wrong `WorkingDirectory`. Create a clean service file manually:
```ini
[Service]
Type=forking
WorkingDirectory=/opt/ManageEngine/OpManager/bin  # MUST be bin/ dir!
ExecStart=/opt/ManageEngine/OpManager/bin/run.sh
```
The `run.sh` script uses `./setCommonEnv.sh` and `./app_ctl.sh` (relative paths), so `WorkingDirectory` must be the `bin/` subdirectory.

### 3. X11 Library Package Names
On Ubuntu, X11 library packages use lowercase names: `libxtst6`, `libxi6`, `libxrender1`, `libxext6`, `libx11-6` (NOT `libXtst6`, etc.).

### 4. Bundled Components
OpManager bundles everything:
- **JRE**: `/opt/ManageEngine/OpManager/jre/` (Java 11)
- **PostgreSQL**: Port 13306 (NOT the default 5432)
- **Tomcat**: Embedded web server
- **Wrapper**: Tanuki Java Service Wrapper for process management

### 5. Installer Size
The installer binary is ~470MB. Download takes 1-3 minutes depending on network speed. The installation itself takes 1-2 minutes.

## Service Timing Issues

### Startup Time
OpManager takes **60-90 seconds** to fully start after the Java wrapper launches:
1. Wrapper starts Java process
2. Database initialization (PostgreSQL on port 13306)
3. Module loading (~30 modules: SNMP, Discovery, Tomcat, etc.)
4. WebService starts last → port 8060 becomes available

### Service Readiness Polling
Poll `http://localhost:8060` for HTTP 200. During startup, the port doesn't exist (HTTP 000), then the server responds. Additional services (SNMP monitoring, discovery) continue initializing after web UI is available.

## Database Schema Notes

- **Database**: OpManagerDB (PostgreSQL on port 13306)
- **User**: postgres (no password for local connections)
- **Access**: `/opt/ManageEngine/OpManager/pgsql/bin/psql -p 13306 -U postgres OpManagerDB`
- Key tables include device inventory, monitors, alerts, notification profiles

## First-Login Behavior

After initial login with `admin/admin`:
1. A "Change Password" form is displayed (mandatory)
2. A mobile app QR code popup appears
3. The agent must handle these before reaching the main dashboard

Consider automating password change in `post_start` to avoid this blocking the agent.

## API Access

### REST API
OpManager has a REST API but requires an API key generated from **Settings > REST API**. There's no programmatic way to generate the first API key without logging in to the web UI.

### Session-Based Auth
You can login via:
```bash
curl -c cookies.txt -d "userName=admin&password=admin" http://localhost:8060/apiclient/ember/Login.jsp
```
But session cookies are needed for subsequent API calls.

## SNMP Monitoring (Real Data)

The VM runs `snmpd` with community string `public` providing real system metrics:
- System description (kernel version, hostname)
- CPU load (hrProcessorLoad)
- Memory usage (hrStorageUsed)
- Disk partitions (hrStorageDescr, hrStorageSize)
- Network interfaces (ifTable)
- Running processes (hrSWRunName)

OpManager can discover and monitor localhost via SNMP to get real monitoring data.

## Resource Requirements

| Setting | Value | Notes |
|---------|-------|-------|
| CPU | 4 cores | Sufficient for free edition |
| RAM | 12GB | 8GB caused VM crashes; OpManager + PostgreSQL + Firefox need ~10GB |
| Disk | ~2GB | Install + DB + logs |
| Network | Required | For downloading installer |
| GPU | Not needed | Web application only |

## Automated First-Login Flow (Verified Working)

The post_start hook automates the entire first-login sequence using xdotool. The order is critical:

1. **Click Login button** at (836, 695) in 1920x1080 — default admin/admin credentials are pre-filled
2. **Wait 15s** for page to load (Change Password form + QR popup appear simultaneously)
3. **Dismiss QR popup FIRST** at (1326, 372) — this popup overlays the password change form
4. **Wait 3s** for popup to close
5. **Fill New Password** field at (668, 360) — type "Admin@123"
6. **Fill Confirm Password** field at (668, 431) — type "Admin@123"
7. **Fill Email** field at (668, 506) — type "admin@opmanager-lab.local"
8. **Click Update Password** at (758, 615)
9. **Wait 15s** for dashboard to load
10. **Dismiss setup wizard** at (1467, 362) — "Get started in 5 simple steps" X button

### Critical: QR Popup Must Be Dismissed First
The "Get alerts on your mobile" QR popup appears ON TOP of the Change Password form. If you try to click on password fields without dismissing the popup first, the clicks are intercepted by the popup overlay and nothing happens. Always dismiss QR popup before interacting with the password change form.

## pg_hba.conf Timing (Critical)

**DO NOT** modify pg_hba.conf during install (pre_start). OpManager's bundled PostgreSQL must start with its default configuration first. Modifying pg_hba.conf before the first OpManager startup causes "Problem in starting or connecting to the database" errors and the PostgreSQL process never starts.

**Correct approach**: Modify pg_hba.conf in post_start AFTER:
1. OpManager is fully started (HTTP 200 on port 8060)
2. PostgreSQL is confirmed listening on port 13306
3. A 30s stabilization wait has elapsed

Then:
```bash
sed -i '/^local.*all.*all.*md5/s/md5/trust/' "$PG_HBA"
sed -i '/^host.*all.*all.*127\.0\.0\.1.*md5/s/md5/trust/' "$PG_HBA"
sudo -u postgres "$PGSQL_DIR/bin/pg_ctl" reload -D "$PGSQL_DIR/data"
```

## setsid + DISPLAY Bug

`setsid DISPLAY=:1 firefox` does NOT work — `setsid` interprets `DISPLAY=:1` as a program name and fails with "No such file or directory".

**Correct**: `su - ga -c "export DISPLAY=:1; nohup firefox '...' > /tmp/firefox.log 2>&1 &"`

This applies to all scripts (setup_opmanager.sh AND setup_task.sh files).

## Database Password Bypass (Partial)

Setting `change_pwd_on_login = false` and `PASSWORD_CURRENT_STATUS = 'CHANGED_ON_FIRST_LOGIN'` in the database does NOT fully suppress the Change Password form in OpManager. The application uses additional application-level logic beyond just the database flag. Therefore, xdotool automation of the UI password change is still required.

The database modifications are still useful to:
- Reduce the likelihood of the form reappearing on subsequent logins
- Set a known password state in the database

## PostgreSQL Access Pattern

All `psql` commands must run as the `postgres` user (not root), and must `cd /tmp` first to avoid "could not change directory to /root" warnings:

```bash
cd /tmp
sudo -u postgres "$PG_BIN" -p "$PG_PORT" -U postgres OpManagerDB -t -A -c "$query"
```

## Known Issues

1. The `Connect to:` message in wrapper.log always shows `http://ga-base:null` even when the port is correctly configured - this is a display bug only
2. Firefox snap version has GTK module warnings (harmless)
3. `scrot` is not available in the base VM image; use `import -window root` from ImageMagick instead
4. OpManager systemd service may show "activating" instead of "active" — this is normal as the Java wrapper manages its own lifecycle. The web UI on port 8060 is the reliable health check.
5. `hrProcessorLoad` OID returns "No Such Instance" on some VM configurations — other SNMP data (memory, storage, interfaces) works correctly

## Reliability Improvements (2026-03-10 Post-Audit)

### Root Causes of Initial 87.5% Failure Rate

An independent audit found that only 1 out of 8 early episodes reached the expected dashboard state:
- **50% bare desktop**: Firefox failed to launch or was not detected
- **25% password change form**: DB modifications didn't fully bypass the Change Password page
- **12.5% service not started**: OpManager didn't start within 300s timeout

### Fixes Applied

1. **Firefox warm-up launch** (cross-cutting pattern #2): Launch Firefox once with `--headless` to clear first-run state, kill it, then relaunch. Prevents first-run dialogs from interfering with the OpManager login flow.

2. **Firefox retry loop**: Up to 3 launch attempts with 60s window detection per attempt. Between attempts, kill Firefox, remove `.parentlock` and `lock` files from the profile directory.

3. **Increased timeouts**: OpManager startup 300s → 480s, PostgreSQL 120s → 180s. Java apps with bundled databases have highly variable startup times.

4. **Curl-based password change attempt**: Before browser automation, attempt to change the password via the web API. Login with default creds via `POST /apiclient/ember/Login.jsp`, then POST to password change endpoints. This provides a headless, coordinate-independent password change mechanism.

5. **Additional DB flags**: Beyond `change_pwd_on_login` and `PASSWORD_CURRENT_STATUS`:
   - `UPDATE aaapasswordrule SET login_change_pwd = false` — disable at policy level
   - `UPDATE aaapassword SET modified_time = ...` — prevent expiry-triggered change
   - Use `SELECT...WHERE NOT EXISTS` instead of `ON CONFLICT DO NOTHING` for broader compatibility

6. **setup_task.sh recovery**: New `ensure_firefox_on_opmanager()` function in task_utils.sh that:
   - Checks if Firefox is running (if not, starts it with lock cleanup)
   - Waits for Firefox window (with mid-wait restart if process died)
   - Focuses and maximizes Firefox
   - Navigates to `http://localhost:8060/` (ensures OpManager is shown, not about:blank)
   - Dismisses any popups with Escape

7. **Escape key for popup dismissal**: Added `xdotool key Escape` before coordinate-based X button clicks for both QR popup and wizard. Escape is more reliable as it doesn't depend on exact popup position.

### Test Results After First Fixes

3 consecutive clean starts (different seeds, different tasks) all reached the dashboard successfully:
- Test 1: seed=42, task=add_device → Dashboard ✓
- Test 2: seed=123, task=add_device → Dashboard ✓
- Test 3: seed=456, task=create_url_monitor → Dashboard ✓

## Second Audit & Fixes (2026-03-10)

### Findings

A second audit of 15 episodes (8 pre-fix, 7 post-fix) showed:
- Pre-fix episodes: 1/8 success (12.5%)
- Post-fix episodes: 7/7 success (100%)
- Combined: 8/15 (53%) — misleading because pre-fix episodes are included

The audit correctly identified that the system had no recovery mechanism for:
1. **Maintenance page** ("Service has not started" DB error) — no restart logic
2. **Change Password page** appearing despite DB flags — no browser-level recovery
3. **Login page** (session expiry) — no re-login logic in pre_task hook

### Additional Fixes Applied

1. **Three-layer recovery architecture**:
   - Layer 1: `setup_opmanager.sh` (post_start) — primary setup with verification loop
   - Layer 2: `task_utils.sh:ensure_firefox_on_opmanager()` (pre_task) — safety net
   - Layer 3: Task description credentials (agent can handle login page)

2. **Service state detection** (`detect_opmanager_service_state()`): Curl-based check that distinguishes between "running", "maintenance" (DB error page), and "down" (no response). Called before any browser automation.

3. **Service restart logic** (`ensure_opmanager_service()`): If OpManager is in maintenance or down, gracefully shutdown, kill Java process, restart via systemd, and wait up to 300s for recovery.

4. **Password state verification** (`ensure_correct_password()`): Curl-based login check that detects if the Change Password redirect still appears. If so, re-applies all DB flags.

5. **Browser state detection and handling**: Window title-based detection in `ensure_firefox_on_opmanager()` that handles:
   - "Change Password" → `handle_browser_change_password()` (xdotool form fill)
   - "Login" → `handle_browser_login()` (Tab-based login, more robust than coordinates)
   - "Maintenance" → restart service + refresh page

6. **Post-start verification loop**: After the initial xdotool automation in `setup_opmanager.sh`, a verification step checks the window title and retries the password change if the Change Password page is still showing.

### Remaining Risk

- The xdotool coordinate-based automation is still the primary method for password change. Coordinates are calibrated for 1920x1080.
- OpManager startup time can vary (20-300s). The 480s timeout provides generous headroom.
- Firefox may show an extra "New Tab" tab (cosmetic only, doesn't affect functionality).
- The `handle_browser_login()` uses Tab-based navigation which is more robust than coordinates but still depends on form focus order.
