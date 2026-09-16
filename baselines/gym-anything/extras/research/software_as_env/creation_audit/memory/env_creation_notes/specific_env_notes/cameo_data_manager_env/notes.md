> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# CAMEO Data Manager Environment (cameo_data_manager_env) — FULLY VERIFIED 2026-02-24

## Overview
- **Application**: CAMEO Data Manager 4.5.1 by EPA/NOAA — Windows-only desktop app for hazardous chemical emergency planning
- **Base**: `windows-11` preset (4 CPU, 8GB RAM, 1280x720)
- **Download URL**: `https://www.epa.gov/system/files/other-files/2025-12/cameodatamanager451installer.exe`
- **Install**: InnoSetup 5.5.7 silent install via `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-` (exit code 0)
- **Install path**: `C:\Program Files (x86)\CAMEO Data Manager 4.5.1\CAMEO Data Manager.exe`
- **Installer size**: 126MB; pre-downloaded to `data/` directory (mount copy avoids slow EPA download during pre_start)

## Architecture
- **Electron app**: Built on Chromium/Electron (chromium PAK files, v8 snapshot, ffmpeg.dll, libEGL/libGLESv2 in install dir)
- **Client-server**: Main exe `CAMEO Data Manager.exe` (206MB) + `CAMEODataManagerServer.exe` in `resources\server\`
- **5 processes on launch**: Multiple Electron renderer processes
- **Auto-launches after install**: InnoSetup runs the app automatically post-install; warm-up in post_start kills and relaunches cleanly
- **CAMEO suite**: Part of EPA/NOAA CAMEO suite (ALOHA, MARPLOT, CAMEO Chemicals); this is the standalone Data Manager component
- **Tier II data standard**: EPCRA XML format for hazardous chemical inventory reporting; sample data from NOAA

## Sample Data
- **File**: `data/epcra_tier2_data.xml` (20KB) from NOAA (`https://cameo.noaa.gov/epcra_tier2/data_standard/v1/epcra_tier2_data.xml`)
- **Contains**: 1 facility (Green Valley Water Facility, Colchester VT), 4 contacts (Debra Monaco - Owner, Vincent Martinez - Info Contact, Mike Ward - Emergency Coordinator, Interstate Transportation Company), 2 chemicals (Chlorine CAS 7782-50-5, Fluorosilic Acid CAS 16961-83-4), Data year 2019
- **Import warnings**: "2 file attachments were not present" (GRENVAL1.jpg, GRENVAL2.jpg) — expected, non-blocking

## Import Workflow (verified end-to-end)
1. Click Import button (toolbar, ~1001, 54)
2. Import dialog opens with file type options (T2S, ZIP, loose CSV/XML/MER)
3. Click "Browse To File" button
4. Windows file browser opens (defaults to System32)
5. Type path: `C:\Users\Docker\Documents\CAMEO\epcra_tier2_data.xml`
6. File selected: shows "Individual XML file", "Ready for import."
7. Click Continue → Import File Information: 1 facility, 4 contacts, 2 chemicals, 2019
8. Warning about 2 missing file attachments (click Continue)
9. Import Summary: "Imported" status
10. Click OK → Facilities list shows Green Valley Water Facility

## Key UI Elements (1280x720 coordinates)
- **Import button**: ~(1001, 54) on toolbar
- **Facilities module**: Default view on launch, shows imported facilities in a table
- **OneDrive popup "No thanks"**: ~(1135, 627) — Windows 11 "Turn On Windows Backup" popup that must be dismissed

## Critical Findings

### 1. Installer filename and path have spaces
- **Exe name**: `CAMEO Data Manager.exe` (with spaces, NOT `CAMEODataManager.exe`)
- **Install dir**: `CAMEO Data Manager 4.5.1` (version-suffixed, NOT just `CAMEO Data Manager`)
- **Impact**: All search paths in scripts must use quoted paths with spaces

### 2. Pre-downloaded installer required for reliability
- **Problem**: 126MB download from EPA during pre_start is slow and unreliable
- **Solution**: Pre-download to `data/cameodatamanager451installer.exe`; mount copies to `C:\workspace\data\` at reset time
- **Fallback**: Script still has EPA download as fallback if mounted file missing

### 3. OneDrive popup on Windows 11
- **Problem**: Windows 11 shows "Turn On Windows Backup" OneDrive popup that covers CAMEO
- **Solution**: Click "No thanks" at ~(1135, 627) via PyAutoGUI in both setup_cameo.ps1 and task_utils.ps1 Dismiss-CAMEODialogs

### 4. InnoSetup 5.5.7 (confirmed via strings)
- **Flags**: `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-`
- **Exit code 0**: Normal success (NOT 3010 like MSI installers)
- **Auto-launch**: App starts automatically after install; post_start kills and relaunches cleanly

### 5. PowerShell schtasks stdout pollutes function return values
- **Problem**: `Start-EdgeKillerTask` returns a hashtable, but `schtasks /Create` and `schtasks /Run` emit "SUCCESS: ..." to stdout, which PowerShell captures as part of the return value, turning it into `Object[]` instead of `Hashtable`
- **Effect**: `Stop-EdgeKillerTask -KillerInfo $edgeKiller` fails with "Cannot convert System.Object[] to System.Collections.Hashtable"
- **Fix**: Pipe all schtasks calls to `Out-Null` (e.g., `schtasks /Create ... | Out-Null`)

### 6. OneDrive uninstall must be in post_start only (NOT in pre_task)
- **Problem**: Running `OneDriveSetup.exe /uninstall` during pre_task killed the SSH session, crashing the VM
- **Fix**: OneDrive uninstall runs once in `setup_cameo.ps1` (post_start). The `Suppress-OneDrive` function in `task_utils.ps1` only kills the process and sets registry, no uninstall attempt

### 7. Auto-import via GUI automation for tasks 2-5
- **Problem**: Tasks 2-5 describe Tier II data as "already imported" but each task runs independently from post_start checkpoint (no imported data)
- **Fix**: `Import-TierIIData` function in `task_utils.ps1` automates the full import workflow via PyAutoGUI clicks: Import button (1001,54) -> Browse (237,369) -> type path (345,442) -> Select (510,472) -> Continue (577,582) -> Continue (577,614) -> OK (640,421)
- **Duration**: ~30s for the GUI automation sequence

## Tasks (5 total)
1. **import_tier2_data** (medium, 180s, 30 steps): Import Tier II XML file into CAMEO; agent does import manually
2. **add_facility** (medium, 180s, 30 steps): Add Riverside Chemical Processing Plant; data auto-imported in pre_task
3. **search_chemical** (easy, 120s, 20 steps): Search for Chlorine (CAS 7782-50-5); data auto-imported in pre_task
4. **generate_responder_summary** (medium, 180s, 30 steps): Generate PDF report for Green Valley Water Facility; data auto-imported
5. **add_contact** (medium, 180s, 30 steps): Add Sarah Chen as Environmental Compliance Officer; data auto-imported

Tasks 2-5 auto-import Tier II data during pre_task via `Import-TierIIData` function. Each task is independently runnable.

## File Structure
```
benchmarks/cua_world/environments/cameo_data_manager_env/
  env.json                          # Environment config (windows-11, 8GB RAM)
  scripts/
    install_cameo.ps1               # pre_start: install CAMEO + copy data
    setup_cameo.ps1                 # post_start: warm-up launch, dismiss dialogs, Edge killer
    task_utils.ps1                  # Shared: Find-CAMEOExe, PyAutoGUI, schtasks /IT, Edge killer
  tasks/
    import_tier2_data/              # Task 1: Import XML
      task.json
      setup_task.ps1
      verifier.py                   # Stub (VLM evaluation)
    add_facility/                   # Task 2: Add facility
    search_chemical/                # Task 3: Search chemical
    generate_responder_summary/     # Task 4: Generate PDF report
    add_contact/                    # Task 5: Add contact
  data/
    epcra_tier2_data.xml            # NOAA Tier II sample XML (20KB)
    cameodatamanager451installer.exe # Pre-downloaded installer (126MB)
  evidence_docs/
    01_cameo_installed_and_running.png
    02_import_file_selected.png
    03_import_file_information.png
    04_import_summary_success.png
    05_facility_imported_successfully.png
```

## Testing Commands
```python
# Run from the repo root.
from gym_anything.api import from_config
env = from_config('benchmarks/cua_world/environments/cameo_data_manager_env', task_id='import_tier2_data')
obs = env.reset(seed=42, use_cache=False, use_savevm=True)

# Connection info via the stable SessionInfo contract.
session = env.get_session_info()
ssh_port = session.ssh_port
vnc_port = session.vnc_port
```
