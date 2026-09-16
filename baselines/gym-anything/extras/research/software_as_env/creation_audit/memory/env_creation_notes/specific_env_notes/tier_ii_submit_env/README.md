> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Tier II Submit Environment Notes

## Application Overview

Tier2 Submit 2025 Rev 1 is a Windows desktop application developed by the EPA and NOAA for facilities to electronically report hazardous chemical inventories under EPCRA Section 312 (Emergency Planning and Community Right-to-Know Act). It's an Electron-based app with a local server component (Tier2SubmitServer.exe).

## Installation Quirks

### Installer Type: Inno Setup (NOT NSIS)
The installer (`tier2submit_installer.exe`, 119 MB) is **Inno Setup**, not NSIS. This was confirmed by the `is-HKC64.tmp` extraction path during installation. The critical difference:

| Flag | Works | Notes |
|------|-------|-------|
| `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-` | YES | Inno Setup -- fully silent, no UI |
| `/SILENT /SUPPRESSMSGBOXES /NORESTART` | YES | Inno Setup -- progress bar only |
| `/S /v/qn` | NO | NSIS flags -- causes GUI wizard in Session 0 (invisible, hangs) |

**Always try Inno Setup flags first.** The install script uses a priority-ordered attempt list with 180-second timeout per attempt.

### Install Path
```
C:\Program Files (x86)\Tier2 Submit 2025 Rev 1\Tier2 Submit.exe
```
Note the space in "Tier2 Submit" and "2025 Rev 1". The path may change with version updates. The `Find-Tier2SubmitExe` function in `task_utils.ps1` searches multiple candidate paths.

### Server Component
A separate `Tier2SubmitServer.exe` runs alongside the main GUI at:
```
C:\Program Files (x86)\Tier2 Submit 2025 Rev 1\resources\server\Tier2SubmitServer.exe
```
When searching for the main executable, exclude files matching "server" to avoid finding this instead.

### Installer Timeout Handling
The installer can sometimes hang (especially if it encounters UAC prompts in Session 0). The install script uses `Process.WaitForExit(180000)` instead of `Start-Process -Wait` to enforce a 180-second timeout. If the process doesn't exit in time, it's killed and the next attempt method is tried.

## EPA Download URLs

The EPA installer download URL:
```
https://www.epa.gov/epcra/tier2-submit-software
```
Returns **403 Forbidden** when accessed from inside the VM (likely geo/bot blocking). The installer is therefore pre-downloaded and included in the `data/` directory. The install script looks for the local copy first.

## Startup Sequence and Dialog Dismissal

### First Launch Dialogs
When Tier2 Submit launches for the first time, it shows:

1. **Welcome Splash Screen** -- Large centered dialog with app description and "Start Tier2 Submit" button at (640, 495) @1280x720
2. **Quick Guide Popup** -- Informational overlay; dismissed with Escape key

### Session 0 Isolation
Like all Windows GUI apps launched from SSH, Tier2 Submit must be launched via `schtasks /Create /IT` (interactive task) pattern to run in the desktop session rather than Session 0.

### PyAutoGUI Server Protocol
The framework's PyAutoGUI server runs on guest port 5555 (forwarded to host). It uses **raw TCP** (not HTTP) with newline-delimited JSON:

```python
import socket, json
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('localhost', pyautogui_port))
sock.send((json.dumps({"action": "click", "x": 640, "y": 495}) + "\n").encode())
response = json.loads(sock.recv(4096).decode().strip())
```

Screen resolution is **1280x720**, matching the `visual_grounding` tool's coordinate system -- no scaling needed.

## Data Format

### .t2s Files
A `.t2s` file is a **ZIP archive** containing a single XML file (`epcra_tier2_data.xml`) that conforms to the NOAA EPCRA Tier 2 data standard v1.0.0:

```xml
<?xml version="1.0" encoding="utf-8"?>
<epcraTier2Dataset xmlns="https://cameo.noaa.gov/epcra_tier2/data_standard/v1" version="1.0.0">
  <dataset reportyear="2025">
    <facilities>...</facilities>
    <contacts>...</contacts>
  </dataset>
</epcraTier2Dataset>
```

### Report Year Validation
**Critical**: Tier2 Submit validates that the report year is within the past 2 years of the current date. If the baseline data has an old year (e.g., 2019), import will fail with "The report year is not within the past two years." The baseline XML uses `reportyear="2025"`.

### Rebuilding .t2s Files
When modifying the XML, rebuild the .t2s ZIP:
```python
import zipfile
with zipfile.ZipFile('green_valley_baseline.t2s', 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.write('epcra_tier2_data.xml')
```

## Baseline Data

The Green Valley Water Facility baseline includes:
- **1 facility**: Green Valley Water Facility, Colchester VT (NAICS 221310 Water Supply)
- **4 contacts**: Owner (Monaco), Information Contact (Martinez), Emergency Coordinator (Ward), Chemical Carrier (Interstate Transportation Company)
- **2 chemicals**: Chlorine (CAS 7782-50-5, EHS, 15000-20000 lbs) and Fluorosilic Acid (CAS 16961-83-4, mixture, 20000-45000 lbs)

## Task Design

### Task Start State
**Important**: The setup scripts do NOT import the baseline data into the application. The app starts **empty** (0 Facilities, "No records found"). Each task description instructs the agent to import the baseline `.t2s` file first using `Import > Browse to file`. This design was chosen because:

1. GUI automation for import in setup scripts is fragile and hard to verify
2. Making the agent perform the import is a more realistic workflow
3. It avoids race conditions between setup script import and agent interaction

### 5 Hard Tasks

1. **add_chemical_inventory**: Import baseline, add Sulfuric Acid (CAS 7664-93-9) with hazards, storage, and amounts; export to .t2s
2. **edit_facility_contacts**: Import baseline, replace Emergency Coordinator and add Parent Company contact; export to .t2s
3. **create_mixture_chemical**: Import baseline, add Sodium Hypochlorite 12.5% solution with 3 mixture components; export to .t2s
4. **update_storage_locations**: Import baseline, add second storage location for Chlorine, update Fluorosilic Acid storage; export to .t2s
5. **generate_annual_submission**: Import baseline, update year, certification, chemical amounts, and emergency planning status; generate submission .t2s

### Verification Strategy
All verifiers are **stubs** -- real verification is done externally via VLM evaluators that analyze the agent's screenshot trajectory. The verifier.py files return `{"passed": True, "score": 100}` unconditionally.

### Task Setup Pattern
Each task's `setup_task.ps1`:
1. Sources `task_utils.ps1` for shared utilities
2. Kills any running Tier2 Submit instances (`Stop-Tier2Submit`)
3. Cleans up any pre-existing output files
4. Ensures baseline `.t2s` file is in `C:\Users\Docker\Desktop\Tier2Tasks\`
5. Records task start timestamp (`Record-TaskStart`)
6. Finds and launches Tier2 Submit via `Find-Tier2SubmitExe` and `Launch-Tier2SubmitInteractive`
7. Dismisses startup dialogs (Welcome splash + Quick Guide)
8. **Does NOT import baseline data** -- the agent handles this

### Task Export Pattern
Each task's `export_result.ps1`:
1. Sources `task_utils.ps1`
2. Checks if the expected output file exists
3. Writes result JSON with pass/fail status

## Navigation Coordinates (1280x720)

| UI Element | X | Y | Type |
|-----------|---|---|------|
| Facilities tab | 170 | 55 | Dropdown |
| "List all facilities" | 255 | 88 | Dropdown item |
| Contacts tab | 278 | 55 | Dropdown |
| "List all contacts" | 361 | 88 | Dropdown item |
| Chemical Inventory tab | 414 | 55 | Dropdown |
| "List all chemicals" | 467 | 88 | Dropdown item |
| Import button | 991 | 55 | Menu bar |
| Export/Submit button | 1079 | 55 | Menu bar |
| Help button | 1189 | 55 | Menu bar |
| Back arrow | 62 | 56 | Navigation |
| "Start Tier2 Submit" | 640 | 495 | Welcome splash only |
| Browse To File | 247 | 369 | Import page |
| Continue (import) | 577 | 575 | Import page, after file selected |
| Add button (toolbar) | 173 | 112 | Chemical/Contact list |
| Edit button (toolbar) | 211 | 112 | Chemical/Contact list |
| Delete button (toolbar) | 249 | 112 | Chemical/Contact list |

## Known Limitations

1. **No live workspace mount**: QEMU copies workspace files at boot time. Updating files after boot requires SFTP push.
2. **Electron app multi-process**: Tier2 Submit spawns 4+ processes (renderer, GPU, utility). Only one has `MainWindowTitle != ""`.
3. **First-run initialization**: The server component (Tier2SubmitServer.exe) starts automatically with the app and creates the local database on first run.
4. **Internet connectivity**: The app tries to check for updates and validate state submission URLs on launch. Network access should be enabled in `env.json`.

## Files Created

```
benchmarks/cua_world/environments/tier_ii_submit_env/
+-- env.json
+-- scripts/
|   +-- install_tier2submit.ps1    (pre_start hook - installs app)
|   +-- setup_tier2submit.ps1      (post_start hook - copies data, launches app)
|   +-- dismiss_dialogs.ps1        (dismisses welcome + quick guide)
|   +-- task_utils.ps1             (shared: Find-Tier2SubmitExe, Launch-Tier2Submit, etc.)
+-- data/
|   +-- tier2submit_installer.exe  (119 MB, pre-downloaded)
|   +-- epcra_tier2_data.xml       (NOAA sample, report year 2025)
|   +-- green_valley_baseline.t2s  (ZIP of above XML)
|   +-- chemical_reference.csv     (15 common chemicals)
+-- tasks/
|   +-- add_chemical_inventory/    (task.json, setup_task.ps1, export_result.ps1, verifier.py)
|   +-- edit_facility_contacts/
|   +-- create_mixture_chemical/
|   +-- update_storage_locations/
|   +-- generate_annual_submission/
+-- evidence_docs/
    +-- README.md
    +-- 01-07: Initial verification screenshots
    +-- 08_task_start_state_empty.png       (actual start state - empty app)
    +-- 09_import_page.png                  (Import workflow step 1)
    +-- 10_import_file_selected.png         (Import workflow step 2)
    +-- 11_contacts_post_import.png         (4 contacts loaded)
    +-- 12_facilities_post_import.png       (1 facility loaded)
    +-- 13_chemical_inventory_list.png      (2 chemicals loaded)
    +-- 14_chemical_detail_form.png         (chemical edit form with all tabs)
    +-- 15_storage_locations_tab.png        (storage location fields)
    +-- 16_export_submit_dialog.png         (T2S export dialog)
    +-- 17_contact_detail_form.png          (contact edit form)
    +-- 18_add_chemical_form.png            (blank add chemical form)
```
