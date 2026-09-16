> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Blue Sky Plan Environment Notes

## Overview
- **Application**: Blue Sky Plan 5.0.29 (dental implant planning software)
- **Vendor**: Blue Sky Bio (blueskybio.com)
- **OS**: Windows 11 (QEMU)
- **Resolution**: 1280x720
- **Resources**: 4 CPUs, 16 GB RAM
- **Install size**: ~1.73 GB installer, ~2 GB installed

## Installation
- **Installer URL**: `https://manual.blueskyplan.com/catalogs/BSP/BlueSkyPlan_5.0.29-setup64.exe`
- **Fallback**: `BlueSkyPlan_5.0.28-setup64.exe`
- **Installer type**: Inno Setup
- **Silent flags**: `/VERYSILENT /NORESTART /SUPPRESSMSGBOXES /SP-`
- **Install path**: `C:\Program Files\BlueSkyPlan\`
- **Must use `schtasks /IT`**: Installer has GUI components that fail in Session 0
- **Install time**: ~100 seconds after download complete
- **Download time**: ~3-4 minutes for 1.73 GB

## Architecture (CRITICAL)
- **DO NOT launch `BlueSkyPlan.exe` directly**
  - Error: "Blue Sky Plan can not be run as a standalone application"
- **Launcher**: `C:\Program Files\BlueSkyPlan\Launcher\BlueSkyLauncher.exe`
- **Launcher starts**: `nats-server` (messaging) + `BlueSkyPlan.exe` (actual app)
- **Kill order**: Must kill all of `BlueSky*`, `BSP*`, and `nats-server*`

## OpenGL / Mesa Software Rendering (CRITICAL)
- QEMU virtio-vga only provides OpenGL ~3.x. BSP requires OpenGL 4.3+.
- **Error without fix**: "Your hardware doesn't meet the minimum requirements. OpenGL 4.3 or higher is required."
- **Fix**: BSP ships with `opengl32sw.dll` (Mesa LLVMPipe, supports OpenGL 4.5)
  - Copy `opengl32sw.dll` → `opengl32.dll` in both:
    - `C:\Program Files\BlueSkyPlan\Launcher\`
    - `C:\Program Files\BlueSkyPlan\BlueSkyPlan4\`
  - Set environment variables: `QT_OPENGL=software`, `MESA_GL_VERSION_OVERRIDE=4.5`
  - These vars must also be set in the batch file that launches BSP via schtasks
- After Mesa fix: soft warning "Hardware doesn't meet recommended config" with checkbox
  - NOT a hard block — just click "Don't show again" + OK

## PowerShell / AMSI Issues (CRITICAL)
- **Windows Defender AMSI** blocks entire scripts containing `Set-MpPreference`, `Stop-Service WinDefend`, etc.
  - Error: "This script contains malicious content and has been blocked by your antivirus software"
  - AMSI scans the ENTIRE script before execution — the blocked command doesn't need to run
  - **Fix**: Remove ALL Defender-related commands from scripts. They fail from Session 0 anyway.
- **curl.exe stderr**: PowerShell's `$ErrorActionPreference = "Stop"` treats curl's progress to stderr as terminating error
  - **Fix**: Use `--silent --show-error` flags AND wrap in `$ErrorActionPreference = "Continue"` block

## Dialog Dismissal (dismiss_dialogs.ps1) — 7-Phase Approach

BSP launches Edge browser to blueskybio.com for login, which opens a login popup over BSP.
The dismiss script uses PyAutoGUI for all clicks (Win32 API clicks don't work for BSP).

**Phase 0**: Hardware warning — "Don't show again" checkbox (398,355) + OK (835,355)
**Phase 1**: Kill Edge browser (track `$edgeFound` flag)
**Phase 2**: Crash report dialog — click X at (957,71) (harmless if no dialog)
**Phase 3**: Kill Edge again (track `$edgeWasRunning` flag)
**Phase 4**: **CONDITIONAL** — Close login popup X (814,255) **only if Edge was detected**
  - If clicked when no login popup → hits SPLINT hex tile, opens "CHOOSE YOUR PROJECT TYPE" view
  - Escape does NOT close the project type view — only Back button works
**Phase 5**: Back button cleanup (322,104) — recovers from accidental hex grid clicks
**Phase 6**: Escape x2 — catch remaining dialogs
**Phase 7**: Wait 5s for late Edge, then conditional kill + login popup close + Back button cleanup

### First-Run Dialog Sequence (1280x720 coordinates)
1. **OneDrive "Turn On Windows Backup"**: "No thanks" at (1166, 627), X at (1237, 393)
2. **Hardware warning**: "Don't show again" checkbox at (398, 355), OK at (835, 355)
3. **Crash report dialog**: Dismiss with Escape (only if previous BSP session was killed)
4. **Login popup**: X button at (814, 255) — gated on Edge detection
5. After dismissal: BSP shows "START NEW PROJECT" hexagonal tile screen

## Main UI Layout (1280x720)
- **Menu bar**: File/Edit/View/Tools/Help at top-left
- **Hexagonal tiles** (project types):
  - EASY CT DICOM VIEWER: (713, 228)
  - ORTHODONTICS: (572, 312)
  - SPLINT: (855, 312)
  - IMPLANT PLANNING: (431, 393)
  - DENTURE: (714, 393)
  - CEPHALOMETRIC ANALYSIS: (996, 393)
  - CROWN AND BRIDGE: (572, 475)
  - ENDODONTICS: (855, 475)
  - MODEL MASTER: (714, 543)
- **Credits**: (1008, 52), **Log in**: (1089, 52)

## PyAutoGUI Server
- The QEMU runner starts a PyAutoGUI TCP server (port 5555) via schtasks
- Server terminal window may appear in foreground, covering BSP
- **Fix**: After dialog dismissal, use Alt+Tab to bring BSP back to foreground

## DICOM Data
- 100 synthetic dental CBCT slices (256x256, 0.4mm spacing) in `data/dicom/`
- Generated with pydicom, simulates jaw/teeth structures
- Mounted to `C:\workspace\data\dicom` and copied to `C:\Users\Docker\Documents\DentalDICOM`
- Note: medimodel.com DICOM download is dead; rubomedical only provides 1-3 files

## Crash Log
- After force-killing BSP, it saves a crash log at:
  `C:\Users\Docker\AppData\Local\BlueSkyBio\Blue Sky Plan\crashinfo.log`
- Next launch shows crash report dialog if this file exists
- **Fix**: Delete this file before launching BSP in task setup scripts

## Timing
- Full pre_start (download + install): ~5 minutes (327s in test)
- Post_start (warm-up + dialogs): ~1 minute
- Pre_task (launch + dialogs): ~69 seconds
- Total from scratch: ~6-7 minutes
- With post_start checkpoint (COW overlay, no savevm): ~138s per task reset

## Checkpoint / Caching
- **savevm mode fails**: 24GB checkpoint copy exceeds 100GB NFS home quota
- **COW overlay mode works**: `use_savevm=False` creates lightweight copy-on-write overlay (MBs)
- **Recommended**: `env.reset(seed=42, use_cache=True, cache_level="post_start", use_savevm=False)`
- Post_start checkpoint includes: BSP installed, Mesa configured, DICOM copied, warm-up complete
- Pre_task hook: launches BSP fresh each time, dismisses dialogs, verifies BSP running

## Tasks (5 total)
1. **import_dicom_scan** (easy): Import DICOM files into new project
2. **measure_distance** (easy): Measure ridge-to-canal distance
3. **place_implant** (medium): Place dental implant at tooth #30
4. **adjust_panoramic_curve** (medium): Adjust panoramic curve view
5. **create_surgical_guide** (hard): Create tooth-supported surgical guide

## Licensing & Registration
- Registration page opens automatically after first install
- Can be dismissed without registration (login popup X button)
- 2 free exports included with new installation
- Network access available during VM setup
