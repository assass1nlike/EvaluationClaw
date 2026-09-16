> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# eQUEST Environment Notes

## Overview
- **Application**: eQUEST 3.65 build 7175 (DOE-2.2 building energy simulation)
- **Platform**: Windows 11 (QEMU VM with `windows-11` base image)
- **Install**: MSI from `doe2.com` ZIP download
- **Data**: Real DOE-2 building models (.inp format) from official training workbook examples

## Installation

### Download and Install
- URL: `https://doe2.com/Download/equest/eQUEST_3-65_Build7175_2018-10-04.zip`
- **CRITICAL**: Use `curl.exe` for downloads, NOT `Invoke-WebRequest` — IWR stalls/hangs on large downloads in Windows 11 QEMU VMs
- ZIP contains MSI installer; use `msiexec /i ... /quiet /norestart ALLUSERS=1`
- Installs to `C:\Program Files (x86)\eQUEST 3-65-7175\`
- Training examples from `https://doe2.com/Download/equest/eQuestTrainingWorkbook_Examples.zip`

### Registration Code (CRITICAL)
- Registration code: `9349417631702397005-001`
- Status: `1000`, Special: `581413115`
- **eQUEST CORRUPTS the Registration section** (Status/Special fields) in its INI file on EVERY run
- Without correct registration: "Invalid PreviousRunDate" error dialog blocks all functionality
- Two INI files need registration:
  1. **Install dir**: `C:\Program Files (x86)\eQUEST 3-65-7175\eQUEST.ini` (paths + registration)
  2. **Data dir**: `C:\Users\Docker\Documents\eQUEST 3-65-7175 Data\eQUEST.INI` (comprehensive config + registration)
- **MUST call `Restore-EqRegistration` before EVERY launch** — implemented in `task_utils.ps1`

### Warm-up Cycle
- First eQUEST launch creates data directories and writes initial INI files
- `setup_equest.ps1` (post_start) runs a warm-up launch to trigger this
- After warm-up, `Restore-EqRegistration` fixes the corrupted registration values

## GUI Automation

### Session 0 Isolation
- SSH (Session 0) cannot directly launch GUI apps visible on VNC (Session 1)
- **Solution**: `schtasks /Create /TN name /TR cmd /SC ONCE /ST HH:mm /RL HIGHEST /IT /F` + `schtasks /Run /TN name`
- Implemented in `Launch-EqProjectInteractive` in `task_utils.ps1`
- Uses a `.cmd` batch file as intermediary to avoid quoting issues with `schtasks`

### PyAutoGUI TCP Server
- Port: 5555 (inside VM)
- Commands: `{"action": "click", "x": 640, "y": 360}`, `{"action": "write", "text": "..."}`, `{"action": "press", "keys": "enter"}`, `{"action": "hotkey", "keys": ["ctrl", "a"]}`
- **All coordinates are in 1280x720 screen space** (matching VNC resolution)

### Startup Dialog Navigation
eQUEST shows a "Startup Options" dialog on every launch. Dialog layout (1280x720 coordinates):
- Dialog title bar (for focus): **(640, 234)** — MUST click here first before radio buttons work
- "Select an Existing Project to Open" radio: **(442, 331)**
- "OK" button: **(629, 422)**
- "Exit" button: **(821, 422)**

### File Browser Navigation (BDL Import)
After clicking OK with "Select Existing" selected:
1. Click filename field: **(305, 434)**
2. Ctrl+A to select all text
3. Type full .inp path (e.g., `C:\Users\Docker\Desktop\eQUEST_Projects\4StoreyBuilding.inp`)
4. Press Enter
5. Handle "project already exists" dialog → press Enter again
6. "Create Project from BDL File" dialog OK button: **(735, 419)**
7. Wait for import (30-60s depending on model size)

### Focus Requirements
- **CRITICAL**: Must click dialog title bar at (640, 234) before clicking radio buttons
- Without this focus step, radio button clicks are silently ignored and the wrong option stays selected
- This is a common Windows GUI automation pitfall in VNC/PyAutoGUI environments

## Building Models

### Recommended Models
| Model | Lines | Size | Import Time | Status |
|-------|-------|------|-------------|--------|
| 4StoreyBuilding.inp | 3,258 | 94 KB | 90s + processing | Works — needs wait |
| L_Shape.inp | 4,476 | 129 KB | 120s + processing | Works — needs longer wait |
| ReaganBuilding_Calibrated.inp | 8,883 | 292 KB | Hangs permanently | Too large |

- **CRITICAL**: Large models (8000+ lines) cause eQUEST to become permanently "(Not Responding)" during BDL import
- Even smaller models cause temporary "(Not Responding)" during import and when switching views (Building Shell, Component Tree)
- Setup scripts use 90-120s base wait + polling for responsiveness
- All models are from the official eQUEST training workbook examples (real building data)

### Model Data Details
- **4StoreyBuilding.inp**: 4 floors, multiple zones; "EWall Construction" has `ABSORPTANCE = 0.6` (line 82); layers: Stucco, Insulation Board (R-8.6), Gypsum Board
- **L_Shape.inp**: 4 floors (Basement BB, Ground G, Middle M, Top T); 25 PSZ systems; first system `"Sys1 (PSZ) (BB.C1)"` (line 3277) with zone `"South Perim Zn (BB.S1)"` having `DESIGN-COOL-T = 75` (line 3307)

### .pd2 vs .inp Files
- `.inp` files: Plain-text BDL (Building Description Language) format — source files
- `.pd2` files: Binary project descriptor (341 bytes) with relative path references
- `.pd2` files CANNOT be opened from arbitrary paths (relative references break)
- **Always import from .inp** in each task's setup_task.ps1 to ensure clean state
- Import creates a new `.pd2` project in `C:\Users\Docker\Documents\eQUEST 3-65 Projects\<ModelName>\`

## Task Setup Pattern

Every task's `setup_task.ps1` follows this pattern:
1. Kill any running eQUEST processes
2. Clean up previous project directory (avoid name conflicts)
3. Find eQUEST executable via `Find-EqExe`
4. Launch eQUEST interactively via `Launch-EqProjectInteractive` (includes registration restore)
5. Navigate startup dialog: focus title bar → select "Existing" radio → OK
6. Navigate file browser: click filename field → Ctrl+A → type .inp path → Enter
7. Handle "project already exists" dialog (Enter to dismiss)
8. Click OK on "Create Project from BDL File" dialog
9. Wait for BDL import (90-120s base) + poll for responsiveness (up to 120-180s more)
10. Verify eQUEST process is running and responsive

## Tasks

### modify_wall_absorptance (medium)
- **Model**: 4StoreyBuilding.inp
- **Goal**: Change ABSORPTANCE of 'EWall Construction' from 0.6 to 0.5 (lighter surface finish to reduce solar heat gain)
- **Timeout**: 240s, max 35 steps

### run_simulation (medium)
- **Model**: 4StoreyBuilding.inp
- **Goal**: Run DOE-2.2 simulation and view annual energy results
- **Path**: Simulate Building Performance → wait → Review Simulation Results View
- **Timeout**: 300s, max 30 steps

### change_thermostat_setpoints (medium)
- **Model**: L_Shape.inp
- **Goal**: Change DESIGN-COOL-T from 75 to 76F on first system's zone
- **Target**: `"Sys1 (PSZ) (BB.C1)"` → zone `"South Perim Zn (BB.S1)"` → DESIGN-COOL-T = 75 → 76
- **Path**: Air-Side HVAC toolbar → Component Tree tab → Sys1 (PSZ) (BB.C1) → South Perim Zn → DESIGN-COOL-T
- **Timeout**: 240s, max 35 steps

## Known Issues and Workarounds

1. **Registration corruption**: eQUEST corrupts INI registration on every run → `Restore-EqRegistration` before each launch
2. **Large model import hangs**: Models >5000 lines cause permanent "(Not Responding)" → use smaller models
3. **Startup dialog focus**: Radio buttons need title bar click first → always click (640, 234) before radio buttons
4. **"project already exists" dialog**: Re-importing a previously imported model shows this → extra Enter press to dismiss
5. **File browser default filter**: Shows `.pd2` files by default; typing full `.inp` path bypasses this
6. **Windows notifications**: Can interfere with GUI automation → disabled in post_start via registry
7. **Terminal windows covering**: CMD windows from hooks can cover dialogs → minimized in post_start
