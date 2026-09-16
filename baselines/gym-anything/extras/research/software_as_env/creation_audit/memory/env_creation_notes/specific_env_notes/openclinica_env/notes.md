> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenClinica Environment - Creation Notes

## Installation Quirks

1. **Docker image**: `piegsaj/openclinica:oc-3.13` is a community image. It expects PostgreSQL with a `clinica` role and `openclinica` database.

2. **init-db.sh permissions**: The PostgreSQL container runs as `postgres` user. Any init scripts in `/docker-entrypoint-initdb.d/` must be world-readable+executable (chmod 755). Files mounted from QEMU's read-only workspace may have restrictive permissions.

3. **Docker Compose version field**: Docker Compose v2 warns about the `version` field being obsolete. This is cosmetic and can be ignored.

## Service Timing

- PostgreSQL starts in ~5-10 seconds
- OpenClinica (Tomcat) takes 3-8 seconds for server startup, but can take much longer on first deployment when it initializes the database schema
- Total setup time: ~10-12 minutes (including Docker pull, image extraction, and service initialization)
- **Critical**: The database role/database must exist BEFORE OpenClinica starts. If init-db.sh fails, OpenClinica will fail to connect and the container will remain unhealthy.

## Database Schema Notes

- OpenClinica 3.13 creates 122 tables in the `openclinica` database
- Key tables for verification: `study`, `study_subject`, `subject`, `user_account`, `study_event_definition`, `crf`, `crf_version`
- The `study` table uses `date_planned_start` (not `start_date`) and `protocol_date_verification`
- The `oc_oid` column is used for OpenClinica's internal object identifiers
- Foreign key constraint: `study_subject.subject_id` references `subject.subject_id` - must insert subject record first

## Password Management

- Default root password: `12345678`
- OpenClinica uses plain SHA-1 for password hashing
- Password change is MANDATORY on first login (password expiry is set)
- Curl-based password change is unreliable due to CSRF tokens and redirect flow
- Best approach: Update password hash directly in `user_account` table via SQL

## Verification Gotchas

1. **Field delimiter**: When using `psql -t -A`, the default field separator is `|`. The export scripts use `cut -d'|'` to parse results.

2. **Multi-level search**: Export scripts try exact name match → partial match → newest record. This handles cases where the agent names things slightly differently.

3. **Study_subject requires subject**: The `study_subject` table has a foreign key to `subject`. Creating a study subject requires both a `subject` record and a `study_subject` record.

4. **CRF upload format**: OpenClinica expects CRF templates in XLS format with specific sheets (CRF, Sections, Groups, Items). The sample_crf.xls was generated with xlwt.
