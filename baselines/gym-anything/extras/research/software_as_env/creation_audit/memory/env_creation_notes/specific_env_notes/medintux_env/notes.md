> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# MedinTux Environment Notes

## Overview
MedinTux is a French medical practice management (logiciel de gestion de cabinet médical) desktop
application. Last release: v2.16.012 (2014-07-11). Written in Qt3/Qt4 C++, distributed as a Windows
installer. Runs under Wine on Ubuntu.

- **Installer**: `medintux-2.16.012.exe` from SourceForge (~210.9 MB)
  - URL: `https://downloads.sourceforge.net/project/medintux/Windows/2.16.012/medintux-2.16.012.exe`
  - SHA1: `417e0e4fe2bafb0c321c55fd6d3494e8a40d6ce3`
- **Install path**: `~/.wine/drive_c/MedinTux-2.16/Programmes/Manager/bin/Manager.exe`
  (MedinTux always installs to `MedinTux-2.16/` regardless of `/D` flag — NSIS ignores it)
- **Process name**: `Manager.exe` (under wine)
- **SSH credentials**: `ga` / `password123`
- **VNC password**: `password`

## Database Schema (CRITICAL)

MedinTux uses **MySQL** with **two linked tables** for patient data:

### `IndexNomPrenom` — Patient search index
| Column | Type | Description |
|--------|------|-------------|
| `FchGnrl_IDDos` | VARCHAR(36) | GUID — primary key, links to fchpat |
| `FchGnrl_NomDos` | VARCHAR(?) | Lastname (UPPERCASE in UI) |
| `FchGnrl_Prenom` | VARCHAR(?) | Firstname |
| `FchGnrl_Type` | VARCHAR(?) | Must be `'Dossier'` for patients |

### `fchpat` — Patient details
| Column | Type | Description |
|--------|------|-------------|
| `FchPat_RefPk` | BIGINT UNSIGNED AUTO_INCREMENT | PK (must add AUTO_INCREMENT!) |
| `FchPat_GUID_Doss` | VARCHAR(36) | Links to `IndexNomPrenom.FchGnrl_IDDos` |
| `FchPat_NomFille` | VARCHAR(?) | Lastname |
| `FchPat_Nee` | DATE | Birthdate (YYYY-MM-DD) |
| `FchPat_Sexe` | CHAR(1) | `'M'` or `'F'` |
| `FchPat_Titre` | VARCHAR(?) | `'M.'` or `'Mme'` |
| `FchPat_Adresse` | VARCHAR(?) | Street address |
| `FchPat_CP` | INT | Postal code |
| `FchPat_Ville` | VARCHAR(?) | City |
| `FchPat_Tel1` | VARCHAR(?) | Phone number |
| `FchPat_NumSS` | VARCHAR(?) | French social security number |

**CRITICAL**: `Personnes` table EXISTS in the schema but is for staff/doctors, NOT patients.
Always insert patients into BOTH `IndexNomPrenom` AND `fchpat` with a shared GUID.

**CRITICAL**: `fchpat.FchPat_RefPk` has no AUTO_INCREMENT in the bundled SQL dump. Must add it:
```sql
ALTER TABLE fchpat MODIFY FchPat_RefPk bigint unsigned NOT NULL AUTO_INCREMENT;
```

## Wine Configuration

- **Wine prefix**: `/home/ga/.wine` (initialized with `wineboot --init`)
- **Architecture**: 32-bit (`wine32:i386` required — MedinTux installer is PE32)
- **Qt4 MySQL driver**: Built directly into `QtSql4.dll` — NO separate `qsqlmysql4.dll` needed!
  - Verify: `strings QtSql4.dll | grep QMYSQL` → shows `QMYSQL3`, `QMYSQL`
- **Installer type**: NSIS — NOT truly silent. Requires Enter key via xdotool after 20s

## Database Connection Configuration

MedinTux reads database connection info from `BasesTest.conf`:
- Path: `~/.wine/drive_c/MedinTux-2.16/Programmes/set_bases/bin/BasesTest.conf`
- Format: `Master = QMYSQL3 , DbName , user , password , host , port`
- Example:
  ```
  Master = QMYSQL3 , DrTuxTest , root ,  , localhost , 3306
  Medica = QMYSQL3 , MedicaTuxTest , root ,  , localhost , 3306
  CIM10 = QMYSQL3 , CIM10Test , root ,  , localhost , 3306
  CCAM = QMYSQL3 , CCAMTest , root ,  , localhost , 3306
  ```
- **Note**: The bundled installer already ships with a `BasesTest.conf` configured for localhost.
  Only need to create it if missing (e.g., if DrTuxTest was empty before first run).

## Official SQL Dumps

The official demo data dumps are **bundled inside the installer** at:
`~/.wine/drive_c/MedinTux-2.16/Programmes/set_bases/bin/SqlCreateTable/`

- `Dump_DrTuxTest.sql` — Main patient database schema + demo data (40,304 lines)
- `Dump_MedicaTuxTest.sql` — Medication database
- `Dump_CIM10Test.sql` — ICD-10 medical codes
- `Dump_CCAMTest.sql` — French medical procedure codes

**IMPORTANT**: The external URL `https://medintux.org/download/DrTuxTest_demo.sql` is dead (2014 site).
Use the bundled dumps instead.

## Reliable Wine Launch Pattern

Using `su - ga -c "cd ... && wine ... &"` is unreliable — the background job may get SIGHUP when
the `su` subshell exits. The correct pattern is:

```bash
# 1. Write a launcher script
cat > /home/ga/launch_medintux.sh << EOF
#!/bin/bash
export DISPLAY=:1
export WINEDEBUG=-all
export WINEPREFIX=/home/ga/.wine
cd "/home/ga/.wine/drive_c/MedinTux-2.16/Programmes/Manager/bin"
exec wine "/home/ga/.wine/drive_c/MedinTux-2.16/Programmes/Manager/bin/Manager.exe"
EOF
chmod +x /home/ga/launch_medintux.sh
chown ga:ga /home/ga/launch_medintux.sh

# 2. Launch using setsid so it survives subshell exit
su - ga -c "setsid /home/ga/launch_medintux.sh > /tmp/medintux.log 2>&1 &"
```

**Key points**:
- Wine must be launched FROM the Manager.exe directory (finds sibling DLLs like QtSql4.dll, QtCore4.dll)
- `setsid` creates a new session, so the process isn't killed when the `su` shell exits
- `exec wine ...` replaces the shell process cleanly

## NSIS Installer Behavior

- The installer shows a GUI dialog even though it's supposed to be silent
- Need to send Enter key via xdotool after ~20 seconds:
  ```bash
  su - ga -c "DISPLAY=:1 xdotool key --clearmodifiers Return"
  ```
- Send Enter twice (two dialog pages possible)
- Wait up to 8 minutes for `Manager.exe` to appear in the wine filesystem

## Manager.ini

After first successful run, MedinTux creates `Manager.ini` at:
`~/.wine/drive_c/MedinTux-2.16/Programmes/Manager/bin/Manager.ini`

Contains the DB connection used:
```ini
[Database]
Master = QMYSQL3 , DrTuxTest , root ,  , localhost , 3306
...
started = 18-02-2026
```
The `started` key confirms a successful first run.

## Tasks

| Task | Patient | Verification |
|------|---------|--------------|
| `add_patient` | ROUSSEAU Laurent (removed, must be re-added) | Count in `IndexNomPrenom` increases |
| `search_patient` | SIMON Valérie (DOB 1970-10-19, Nice) | Phone `04.93.22.33.44`, City `Nice` in fchpat |
| `schedule_appointment` | MARTIN Sophie | Appointment on 2026-03-16 in DB |
| `add_consultation` | DUBOIS Marie-Claire | Consultation record in DB |
| `add_prescription` | BERNARD Pierre | Prescription with Bisoprolol + Furosemide |

## Patient Data

20 French patients inserted during post_start. Sample:
- ROUSSEAU Laurent — Paris, M, DOB 1975-08-14
- SIMON Valérie — Nice, F, DOB 1970-10-19
- MARTIN Sophie — Lyon, F, DOB 1985-03-22
- DUBOIS Marie-Claire — Marseille, F, DOB 1962-07-08
- BERNARD Pierre — Bordeaux, M, DOB 1968-11-30
- ...and 15 more

Plus 1 demo patient from official dump: TARTEMPION MARCEL (demo placeholder)

## Process Detection

```bash
# Check if Manager is running:
pgrep -f "Manager.exe"

# Check wine processes:
pgrep -a -f wine
```

## CRITICAL: Qt4 DLL Missing Problem (solved 2026-02-19)

### Problem
After wine installer runs, `QtGui4.dll`, `QtNetwork4.dll`, `QtSql4.dll`, `QtXml4.dll`
were MISSING from `Manager/bin/`. `Qt3Support4.dll` and `QtCore4.dll` might exist
in `Programmes/QtW/` but NOT in `Manager/bin/`. Wine only looks in the exe's directory.
Result: Manager.exe crashes silently with "Library QtGui4.dll not found".

### Root Cause
The NSIS installer contains ALL Qt4 DLLs (76 total) inside its compressed archive
under `Programmes/QtW/`. The wine installer run may not fully extract them before
we check, OR extracts them to QtW/ instead of Manager/bin/ where wine needs them.

### Solution
Use `7z e` to extract directly from the installer:
```bash
7z e /opt/medintux/medintux-2.16.012.exe -o/tmp/qt4_fix/ "*.dll" -r -y
# Extracts 108 files (76 unique DLLs, ~744MB uncompressed) including:
# QtGui4.dll (9.1M), QtNetwork4.dll (1.1M), QtSql4.dll (304K), QtXml4.dll (392K)
# QtWebKit4.dll, Qt3Support4.dll (2.6M), QtCore4.dll (2.4M), libmysql.dll, etc.
cp /tmp/qt4_fix/*.dll /home/ga/.wine/drive_c/MedinTux-2.16/Programmes/Manager/bin/
```
The `ensure_qt_dlls()` function in `scripts/task_utils.sh` does this automatically.

### Why the Checkpoint Has DLLs (Partly)
setup_medintux.sh runs 7z extraction as part of post_start → checkpoint saves with DLLs in Manager/bin.
However, if you load an OLD checkpoint without this fix, setup_task.sh's `launch_medintux_manager()`
calls `ensure_qt_dlls()` which re-extracts them at pre_task time.

## task_utils.sh Key Functions (added 2026-02-19)

- `ensure_qt_dlls()` — extracts Qt4 DLLs from installer via 7z if `QtGui4.dll` missing
- `create_medintux_launcher()` — creates `/home/ga/launch_medintux.sh` with correct hardcoded paths
- `launch_medintux_manager()` — full launch sequence:
  1. ensure_qt_dlls
  2. create_medintux_launcher
  3. Launch via `su - ga -c "setsid /home/ga/launch_medintux.sh ..."`
  4. Wait for `Manager.exe` process (up to 30s)
  5. Poll for window via `wmctrl -l` (up to 90s)
  6. Maximize window

## Manager UI Start State
After launch, Manager shows a **practitioner authentication screen**:
- Center: Tux penguin logo
- Red text: "To start, please get identified by selecting a user from the list below"
- Left panel: practitioner list (Identifier, Name, First name columns)
- Status bar: "Displayed 21 among 21" (21 demo practitioners from DrTuxTest dump)
Agent must click a practitioner to authenticate before accessing patient functions.

## Startup Speed
- From QEMU savevm checkpoint: window often appears immediately (warm Manager in QEMU memory)
- Cold start with 7z DLL extraction: ~30-60s for extraction + ~75s for wine GUI load
- pre_task hook total time: ~20s (extraction is fast when DLLs already there)

## pgrep Self-Match Bug
**CRITICAL**: `pgrep -a -f "Manager.exe" || echo NOT_RUNNING` has a false positive bug:
the pgrep's OWN command appears in `/proc/*/cmdline` and may contain "Manager.exe" or
"NOT_RUNNING". Use count-based check instead:
```bash
pgrep -c -f wine 2>/dev/null || echo 0  # Returns count of wine processes
```

## Launcher Script Bug (Fixed)
The original `setup_medintux.sh` launcher heredoc referenced `$QTW_DIR` which was NEVER
set before the heredoc, resulting in `QTW_DIR=""`. The DLL copy in the launcher was a no-op.
Fixed by: removing QTW_DIR logic from launcher (DLLs are extracted separately) and using
simple `cd MANAGER_DIR && exec wine Manager.exe`.

## Troubleshooting

**Manager won't start**:
1. Check `/tmp/medintux_warmup.log` for wine errors
2. Verify `BasesTest.conf` exists and has correct DB config
3. Verify MySQL is running: `mysqladmin ping -h localhost`
4. Check `DrTuxTest` DB has tables: `mysql -u root DrTuxTest -e "SHOW TABLES"`

**Qt SQL plugin error** (e.g., "Driver not loaded"):
- NOT a missing DLL issue — QMYSQL3 is built into QtSql4.dll
- Likely a MySQL connection problem (wrong host/port/password)

**Installer failed silently**:
- Check `/tmp/medintux_install.log`
- Verify Manager.exe exists: `find ~/.wine -name Manager.exe`
- The `|| true` on most commands means failures are silent

**fchpat INSERT fails**:
- Likely missing AUTO_INCREMENT on `FchPat_RefPk`
- Fix: `ALTER TABLE fchpat MODIFY FchPat_RefPk bigint unsigned NOT NULL AUTO_INCREMENT`
