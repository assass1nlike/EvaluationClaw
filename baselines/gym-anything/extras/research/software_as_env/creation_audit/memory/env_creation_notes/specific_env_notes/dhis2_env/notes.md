> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# DHIS2 Environment Creation Notes

## Overview

DHIS2 (District Health Information Software 2) environment using Docker-in-QEMU pattern. Runs DHIS2 2.40.11 with the official Sierra Leone demo database.

## Architecture

- **VM**: QEMU with ubuntu-gnome-systemd_highres base image
- **DHIS2**: Docker container (`dhis2/core:2.40.11`) on port 8080
- **Database**: PostgreSQL with PostGIS (`postgis/postgis:14-3.4-alpine`)
- **Browser**: Firefox with pre-configured profile pointing to localhost:8080
- **Resources**: 4 CPU, 8GB RAM (needed for Java application + PostgreSQL + Docker overhead)

## Key Learnings

### 1. Docker Image Version Must Match Database Version

The Sierra Leone demo database from `databases.dhis2.org/sierra-leone/2.40/` contains Flyway migrations up to 2.40.32. If the DHIS2 Docker image version is older (e.g., 2.40.4), Flyway validation fails with:

```
FlywayValidateException: Detected applied migration not resolved locally
```

**Solution**: Use `dhis2/core:2.40.11` (latest available 2.40.x tag) which includes all required migrations.

### 2. dhis.conf Bind Mount vs Named Volume Conflict

Docker named volumes take precedence over bind mounts at the same path. If you mount both `dhis2_home:/opt/dhis2` (named volume) and `./dhis.conf:/opt/dhis2/dhis.conf:ro` (bind mount), the named volume will create an empty `/opt/dhis2/` directory that hides the bind-mounted dhis.conf.

**Solution**: Don't use a named volume for `/opt/dhis2`. Only bind-mount the dhis.conf file directly.

### 3. File Permissions for Container Access

The DHIS2 container runs as a non-root user. If dhis.conf has permissions `640` (rw-r-----), the container process cannot read it.

**Solution**: Always `chmod 644` the dhis.conf file to ensure world-readable access.

### 4. Database Table Names in DHIS2 2.40.x

In DHIS2 2.40.x, tracked entities use:
- Table: `trackedentityinstance` (NOT `trackedentity`)
- Primary key column: `trackedentityinstanceid` (NOT `trackedentityid`)
- The `trackedentityattributevalue` table joins on `trackedentityinstanceid`

Note: In newer DHIS2 versions (2.41+), these were renamed to `trackedentity` and `trackedentityid`.

### 5. Setup Script Timeout

The `setup_dhis2.sh` (post_start hook) has a default SSH execution timeout of 600 seconds. The script performs:
- DB container startup: ~30s
- Demo DB download (82MB): ~30-60s
- Demo DB import: ~60-120s
- DHIS2 startup and readiness wait: ~120-300s

Total can exceed 600s. The internal DHIS2 readiness timeout was reduced from 600s to 420s to fit within the SSH timeout.

### 6. Sierra Leone Demo Database

- **URL**: `https://databases.dhis2.org/sierra-leone/2.40/dhis2-db-sierra-leone.sql.gz`
- **Size**: ~82MB compressed
- **Tables**: 439
- **Organisation Units**: 1,332
- **Tracked Entity Instances**: 73,124
- **Default Credentials**: admin / district

### 7. Key DHIS2 IDs (Sierra Leone Demo)

- **Ngelehun CHC** (organisation unit): `DiszpKrYNg8`
- **Child Programme**: `IpHINAT79UW`
- **Tracker Capture** app path: `/dhis-web-tracker-capture/`

## Files Created

| File | Purpose |
|------|---------|
| `env.json` | Environment configuration (4 CPU, 8GB RAM, Docker support) |
| `config/docker-compose.yml` | Docker Compose for DHIS2 + PostgreSQL |
| `config/dhis.conf` | DHIS2 database connection configuration |
| `scripts/install_dhis2.sh` | Pre-start hook: installs Docker, Firefox, utilities |
| `scripts/setup_dhis2.sh` | Post-start hook: starts DHIS2, imports demo DB, launches Firefox |
| `scripts/task_utils.sh` | Shared utilities (DB queries, API calls, screenshots) |
| `tasks/register_child/task.json` | Task definition for registering a child |
| `tasks/register_child/setup_task.sh` | Pre-task hook: verify DHIS2 health, record baseline counts |
| `tasks/register_child/export_result.sh` | Post-task: export verification data to JSON |
| `tasks/register_child/verifier.py` | Stub verifier (VLM evaluation is external) |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `File /opt/dhis2/dhis.conf cannot be read` | Check file permissions (needs 644) and ensure no named volume conflict |
| `FlywayValidateException` | Docker image version must be >= demo DB version |
| `relation "trackedentity" does not exist` | Use `trackedentityinstance` for DHIS2 2.40.x |
| Setup script timeout | Reduce internal wait timeouts to fit within 600s SSH timeout |
| Firefox sidebar popup | Add `sidebar.revamp=false` and `sidebar.verticalTabs=false` to user.js |
