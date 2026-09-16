> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Oracle SQL Developer Environment - Setup Notes

## Overview
Oracle SQL Developer 24.3.0 running in QEMU VM with Oracle Database XE 21c via Docker.

## Architecture
- **Base image**: `ubuntu-gnome-systemd_highres` (1920x1080)
- **Database**: Oracle XE 21c via `gvenzl/oracle-xe:21-slim` Docker image
- **IDE**: Oracle SQL Developer 24.3.0.284.2209 (no-jre version)
- **JDK**: OpenJDK 17 + OpenJFX
- **Schema**: Oracle HR sample (107 employees, 27 departments, 19 jobs)

## Download URLs (No Oracle Login Required)
- SQL Developer: `https://download.oracle.com/otn_software/java/sqldeveloper/sqldeveloper-24.3.0.284.2209-no-jre.zip`
- SQLcl: `https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip`
- **CRITICAL**: Must use `otn_software` path, NOT `otn` path (which requires login)

## Database Credentials
- System: `system` / `OraclePassword123`
- HR Schema: `hr` / `hr123`
- PDB: `XEPDB1`
- Port: 1521

## CRITICAL: JDK 17 Compatibility Issues

### Problem 1: "factory already defined" crash
SQL Developer 24.3 uses Eclipse OSGi framework which calls `URL.setURLStreamHandlerFactory()`.
Java 17's module system is stricter and throws `java.lang.Error` if the factory is already registered.

**Fix**: Add `--add-opens=java.base/java.net=ALL-UNNAMED` to JVM options.

### Problem 2: IllegalAccessException for sun.awt.AppContext
The NetBeans TopSecurityManager tries to access `sun.awt.AppContext` which is not exported in Java 17.

**Fix**: Add `--add-opens=java.desktop/sun.awt=ALL-UNNAMED` to JVM options.

### Problem 3: RenderBadPicture X11 error
Java2D's XRender pipeline causes X11 rendering errors in the QEMU VM's virtual GPU.

**Fix**: Add `-Dsun.java2d.xrender=false -Dsun.java2d.opengl=false` to JVM options.

### Complete JVM Options Required
```
--add-opens=java.base/java.net=ALL-UNNAMED
--add-opens=java.base/java.lang=ALL-UNNAMED
--add-opens=java.base/sun.net.www.protocol.jar=ALL-UNNAMED
--add-opens=java.base/sun.net.www=ALL-UNNAMED
--add-opens=java.desktop/sun.awt=ALL-UNNAMED
--add-opens=java.desktop/sun.awt.X11=ALL-UNNAMED
--add-opens=java.desktop/javax.swing=ALL-UNNAMED
--add-opens=java.desktop/java.awt=ALL-UNNAMED
-Dsun.java2d.xrender=false
-Dsun.java2d.opengl=false
```

These must be applied in THREE places for reliability:
1. `sqldeveloper.conf` (AddVMOption lines)
2. `product.conf` (user-level config)
3. `JAVA_TOOL_OPTIONS` env var (belt and suspenders)

## Oracle Query Output
- `sqlplus` output often includes leading/trailing whitespace and tabs
- Always use `tr -d '[:space:]'` (not just `tr -d ' '`) to strip all whitespace
- `oracle_query_raw` function strips whitespace via sed in the pipeline

## Tasks
1. **create_oracle_connection** (easy) - Create HR Database connection
2. **query_employee_salary** (medium) - Query Finance dept salaries > $7000, export to CSV
3. **create_database_table** (medium) - Create TRAINING_COURSES table with constraints and data

## SQL Developer 24.3 Connection Storage

SQL Developer 24.3 stores connections in **JSON** format, NOT XML (which older versions used).

- **Path**: `~/.sqldeveloper/system24.3.0.284.2209/o.jdeveloper.db.connection.24.2.0.284.2209/connections.json`
- Export/setup scripts must check for `connections.json` first, then fall back to `connections.xml`
- Connection names extracted via: `grep -oP '"name"\s*:\s*"[^"]*"' connections.json`

## Interactive Testing Notes

### CUA + xdotool Workflow
1. CUA coordinates returned in 1280x720 space; scale to 1920x1080 (`actual_x = cua_x * 1920 / 1280`)
2. SQL Developer's "New Connection" dialog opened via green "+" icon in Connections panel
3. Default connection type is "Basic" with SID; must switch radio button to "Service name" for XEPDB1
4. "Test" button shows "Status: Success" when connection parameters are correct
5. "Connect" button saves and opens the connection

### Window Title Behavior
- On launch: `"Oracle SQL Developer : Welcome Page"`
- After connecting: `"Oracle SQL Developer : HR Database"` (connection name in title)
- wmctrl pattern: `grep -iE "sql developer|oracle sql"`

## Verification Gotchas
- Oracle `sqlplus` outputs include tabs — always use `tr -d '[:space:]'` not `tr -d ' '`
- `grep -c` returns exit code 1 on zero matches — use `|| true` not `|| echo "0"`
- Use `printf '%s'` instead of `echo` when writing counts to files (avoids trailing newlines)
- export_result.sh must handle both JSON and XML connection formats for robustness

## Setup Timing
- Pre-start (install): ~170s (Docker + JDK + SQL Developer download + Oracle XE image pull)
- Post-start (setup): ~65s (Oracle XE startup ~90s wait + HR schema load + SQL Developer launch)
- Total: ~235s
