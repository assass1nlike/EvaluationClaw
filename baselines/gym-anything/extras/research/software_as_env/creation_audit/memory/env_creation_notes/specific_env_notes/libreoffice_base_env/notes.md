> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# LibreOffice Base Environment Notes

## Overview
- Application: LibreOffice Base 7.3 (embedded HSQLDB 1.8)
- Data: Chinook digital music store database (real, from GitHub)
- Base image: `ubuntu-gnome-systemd_highres` (1920x1080)
- 5 tasks: create_table, run_query, create_form, add_record, create_report

## Critical: ODB File Format (HSQLDB Script)

### Correct HSQLDB Script Order
The `database/script` inside the ODB MUST start with these lines in this EXACT order:
```
CREATE SCHEMA PUBLIC AUTHORIZATION DBA
CREATE USER SA PASSWORD ""
GRANT DBA TO SA
```
Then CREATE TABLE statements, then INSERT statements, then `SET WRITE_DELAY 0`.

**CRITICAL**: Without `CREATE USER SA PASSWORD ""`, LibreOffice throws:
> "The connection to the data source 'chinook' could not be established. User not found: SA"

**CRITICAL**: Without `GRANT DBA TO SA`, SA can connect but gets "Access is denied" on all queries.

SA is NOT automatically created when a script is provided — it MUST be in the script.

### Backslash Escaping
HSQLDB 1.8 treats `\` as an escape character. The Chinook `Track` table has 4 records with `\` in track names (e.g., `Cavalleria Rusticana \ Act \ Intermezzo Sinfonico`).

**Fix**: In `create_chinook_odb.py::format_value()`:
```python
escaped = str(val).replace("\\", "\\\\").replace("'", "''")
```

### ODF ZIP Structure
The ODB file is a ZIP archive with:
1. `mimetype` — MUST be FIRST entry, STORED (ZIP_STORED, not DEFLATED), no extra fields
   - Value: `application/vnd.oasis.opendocument.base`
   - Without this, LibreOffice reports "corrupt file"
2. `META-INF/manifest.xml` — uses empty `manifest:media-type=""` for `database/` entries
3. `content.xml` — LibreOffice connection metadata
4. `database/properties` — HSQLDB properties (version 1.8.0)
5. `database/script` — Full DDL + DML

## Data Model (Chinook)
11 tables, insertion order:
MediaType (5) → Genre (25) → Artist (275) → Employee (8) → Customer (59) →
Album (347) → Track (3503) → Invoice (412) → InvoiceLine (2240) →
Playlist (18) → PlaylistTrack (8715)

## Installation (pre_start)
- Packages: `libreoffice-base libreoffice-base-drivers libreoffice-java-common default-jdk libreoffice-calc xdotool wmctrl scrot imagemagick`
- Java required for HSQLDB embedded driver
- Chinook SQLite downloaded from GitHub (1MB) and converted to ODB via Python script

## GUI Automation Notes
- LibreOffice launches in ~25-30s cold, ~1-2s warm (already running)
- `--nofirststartwizard --norestore` flags prevent first-run wizard and document recovery dialogs
- Window detection: `xdotool search --name "chinook"` finds the window by filename
- Resolution: 1920x1080; VG coords are 1280x720 scale
- Tables panel in left sidebar: VG(82, 133) → actual (123, 200)
- Forms panel: VG(82, 221) → actual (123, 332)
- LibreOffice Base always starts showing Forms section by default after launch

## Task Start State
All tasks start with:
- LibreOffice Base open maximized with chinook.odb
- Forms section selected (default after fresh launch)
- No error dialogs
- 11 tables in database accessible by clicking Tables in left panel

## Document Recovery Dialog
Appears after force-kill. Dismiss sequence:
1. Click "Discard" at VG(770, 453) → actual (1155, 680)
2. Confirmation: "Yes" at VG(759, 377) → actual (1139, 566)
Using `--norestore` flag prevents this in normal task flows.

## HSQLDB Migration Dialog
May appear when opening database. Dismiss with Escape or click "Keep Current Format".
