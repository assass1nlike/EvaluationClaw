> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# NextGen Connect Integration Engine Implementation Notes

## Overview

NextGen Connect Integration Engine (formerly Mirth Connect) is a healthcare integration platform that enables HL7 message routing, filtering, and transformation between disparate health information systems.

**Created**: 2026-02-11
**Framework Version**: gym_anything 0.1
**NextGen Connect Version**: 4.5.0 (last fully open-source version)
**Tasks**: 5

## Critical Technical Findings

### X-Requested-With Header (CRITICAL)

NextGen Connect 4.x API requires `X-Requested-With: OpenAPI` header on ALL REST API calls:

```bash
# Without header → HTTP 400: "All requests must have 'X-Requested-With' header"
# With header → works correctly
curl -sk -H "X-Requested-With: OpenAPI" -H "Accept: text/plain" https://localhost:8443/api/server/version
# Returns: 4.5.0
```

This applies to ALL API endpoints (channels, statuses, statistics, etc.).

### Web Dashboard vs Java WebStart

The web dashboard at `https://localhost:8443` provides full admin functionality. Earlier investigations incorrectly concluded that only Java WebStart worked - this was because the API calls were missing the `X-Requested-With` header. Java WebStart approach was abandoned.

### SSL Self-Signed Certificate

Web dashboard uses self-signed cert. Firefox shows security warning for https://localhost:8443. Solution: launch Firefox at `http://localhost:8080` (HTTP landing page) - agent can then navigate to HTTPS and accept the cert warning.

### Database Schema (Actual, Verified)

14 tables in mirthdb public schema:

| Table | Key Columns | Purpose |
|-------|-------------|---------|
| `channel` | id char(36), name varchar(40), revision int, channel text (XML) | Channel configs |
| `d_channels` | local_channel_id bigint, channel_id varchar(36) | Deployed channels |
| `person` | id serial, username varchar(40) | User accounts |
| `configuration` | category varchar, name varchar, value text | System config |

**Important**: `channel.name` is varchar(40) - channel names must be short.
**Important**: Deployed channels tracked in `d_channels`, NOT in `channel` table.
**Important**: Channel config stored as XML in `channel.channel` text field.

## Installation Approach

### Docker-in-QEMU (Docker images)

**Images**:
- `nextgenhealthcare/connect:4.5.0` - Integration engine
- `postgres:15` - Database backend

**Why 4.5.0**: Last fully open-source version before licensing changes in 4.6+.

### Install Script (`pre_start`)

- Docker + docker-compose
- Firefox (Snap or native)
- Automation tools: wmctrl, xdotool, imagemagick, netcat-openbsd
- Python deps: lxml, requests, beautifulsoup4
- **NO Java/icedtea** (WebStart abandoned)

### Setup Script (`post_start`)

- **No `set -e`**: Wait functions return non-zero on timeout
- PostgreSQL: `pg_isready` polling, 60s timeout
- NextGen Connect: API polling with X-Requested-With header, 180s timeout
- PostgreSQL DB creation: Check `pg_database` first (NOT `CREATE DATABASE IF NOT EXISTS` - MySQL syntax)
- Snap Firefox detection: Check `/home/ga/snap/firefox/common/.mozilla/firefox/`
- Firefox launches at `http://localhost:8080`

## Data Sources

### HL7 Sample Messages

**Source**: [Work-In-Progress-For-Health/hl7-v2-examples](https://github.com/Work-In-Progress-For-Health/hl7-v2-examples)

1. `hl7-v2.3-adt-a01-1.hl7` (717 bytes) - Patient admission, KLEINSAMPLE BARRY Q JR
2. `hl7-v2.3-oru-r01-1.hl7` - Observation results (immunization)
3. `hl7-v2.4-oru-r01-1.hl7` - v2.4 observation results, MASSIE JAMES A

## Tasks

### 1. create_hl7_channel (basic)
- Create "Patient Admission Channel", TCP Listener port 6661, File Writer
- Verification: channel count increase + name match + deployment status

### 2. process_hl7_message (intermediate)
- Send ADT^A01 through channel (web dashboard or netcat/MLLP)
- Verification: message tables created + message exists + status

### 3. transform_hl7_format (advanced)
- Create "HL7 Transformer Channel" with JavaScript transformer (HL7→XML)
- Verification: channel exists + transformer logic in XML config

### 4. configure_channel_filter (advanced)
- Create "ADT Filter Channel" with JavaScript filter on MSH-9
- TCP Listener port 6662, only ADT messages pass
- Verification: channel exists + filter logic in XML config

### 5. setup_database_writer (advanced)
- Create "Patient DB Writer" with Database Writer destination
- TCP Listener port 6663, JDBC to PostgreSQL, INSERT into patient_records
- Verification: channel + db writer in config + patient_records table

## Verification Strategy

### task_utils.sh Functions

- `query_postgres` - Execute psql via docker exec
- `get_channel_count` / `channel_exists` / `get_channel_id` - DB queries
- `get_channel_status_api` - REST API status check (with X-Requested-With)
- `api_call_json` / `api_call` - Generic API calls (JSON/XML)
- `write_result_json` - Permission-safe JSON output
- `take_screenshot` - Uses `import -window root` (NOT scrot)

### Export Script Pattern

```bash
source /workspace/scripts/task_utils.sh
INITIAL=$(cat /tmp/initial_count 2>/dev/null || echo "0")
CURRENT=$(get_channel_count)
# Multi-level search: exact match → partial → newest
CHANNEL_DATA=$(query_postgres "SELECT id, name FROM channel WHERE LOWER(name) LIKE '%keyword%';")
# Check XML config for specific elements
CHANNEL_XML=$(query_postgres "SELECT channel FROM channel WHERE id='$CHANNEL_ID';")
echo "$CHANNEL_XML" | grep -qi "filter\|DatabaseDispatcher\|transformer"
# Deployment status: d_channels table + API fallback
DEPLOYED=$(query_postgres "SELECT COUNT(*) FROM d_channels WHERE channel_id='$CHANNEL_ID';")
API_STATUS=$(get_channel_status_api "$CHANNEL_ID")
write_result_json "/tmp/task_result.json" "$JSON_CONTENT"
```

### Permission Handling

```bash
# In setup_task.sh - clear old files before writing
rm -f /tmp/initial_count 2>/dev/null || sudo rm -f /tmp/initial_count 2>/dev/null || true
printf '%s' "$COUNT" > /tmp/initial_count 2>/dev/null || true
```

## Lessons Learned

1. **X-Requested-With header**: NextGen Connect 4.x requires this on ALL API calls
2. **Don't use `set -e`**: Wait functions return non-zero, kills script
3. **PostgreSQL syntax**: No `CREATE DATABASE IF NOT EXISTS` (that's MySQL)
4. **Snap Firefox**: Different profile path, needs launch→kill→configure→relaunch
5. **SSL certs**: Launch at HTTP to avoid SSL warning; agent navigates to HTTPS
6. **Channel XML**: Stored in `channel.channel` text field, contains full config
7. **`printf '%s'` not `echo`**: Avoid trailing newlines in count files
8. **`rm -f || sudo rm -f || true`**: Handle permission issues from previous runs
