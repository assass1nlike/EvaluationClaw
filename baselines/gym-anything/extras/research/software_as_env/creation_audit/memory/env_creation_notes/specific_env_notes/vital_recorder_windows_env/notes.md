> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Vital Recorder Windows Environment - Creation Notes

## Application Overview

- **App**: Vital Recorder 1.16.6
- **Developer**: VitalDB team, Seoul National University Hospital
- **Purpose**: Free medical vital signs recording, viewing, and analysis tool
- **Website**: https://vitaldb.net
- **License**: Free for academic/clinical use

## Installation

### MSI Installer Quirk (CRITICAL)

The MSI installer from `https://vitaldb.net/getvr.php?type=msi&ver=1.16.6` does an "advertised" install by default. This means:

1. First `msiexec /i ... /qn` returns exit code 0 but **only creates Start Menu shortcuts** - no actual files are extracted
2. You MUST run a second install with `REINSTALL=ALL REINSTALLMODE=omus` to force full file extraction

```powershell
# Step 1: Creates advertised shortcuts only
Start-Process msiexec.exe -ArgumentList '/i "path\to\VitalRecorder.msi" /qn /norestart' -Wait

# Step 2: Forces actual file extraction (CRITICAL)
Start-Process msiexec.exe -ArgumentList '/i "path\to\VitalRecorder.msi" /qn /norestart REINSTALL=ALL REINSTALLMODE=omus' -Wait
```

### Install Location

- **Executable**: `C:\Users\Docker\AppData\Roaming\VitalRecorder\Vital.exe`
- **Process name**: `Vital` (NOT `VitalRecorder`)
- The MSI installs to the user's AppData\Roaming, not Program Files

### MSI Size

- MSI: ~6.9 MB
- Download URL: `https://vitaldb.net/getvr.php?type=msi&ver=1.16.6`
- Fallback: `https://vitaldb.net/getvr.php?type=msi&ver=1.16.4`

## UI Layout (1280x720)

### Title Bar
- App name + version + hostname: top-left
- Clock display: top-right
- Window controls (minimize, maximize, close): far top-right

### Toolbar Icons (top-left, left to right)
1. **(31, 58)** - Monitor/Track mode toggle (switches between waveform view and numeric bedside monitor view)
2. **(94, 58)** - Open folder / Open file
3. **(154, 58)** - Settings/gear icon
4. **(252, 162)** - Save icon (when file loaded, toolbar shifts slightly)
5. **(362, 162)** - Export icon (opens Save As dialog for CSV export)

### Right Panel
- **"+ Add Event" button**: (~693, 219) or (1070, 115) depending on window state
- **"Preset" button**: next to Add Event
- **Events list**: Shows timestamped events (Case started, Surgery started, etc.)

### Bottom Controls
- **Play** (triangle): (31, 640) / (135, 663)
- **Stop** (square): (86, 640) / (190, 663)
- **Navigation**: Skip-to-start, Previous, Next, Skip-to-end
- **Zoom**: magnifying glass icon at far right of bottom bar
- **Timeline slider**: between play controls and navigation

### Monitor Mode (after toggling with 1st icon)
- Large numeric displays: BIS=0, BT=21.5, etc.
- Single waveform strip (EEG1_WAV)
- Click 1st icon again to return to Track mode

### CSV Export Dialog
- Triggered by 5th toolbar icon
- Opens Windows Save As dialog
- File type pre-selected: "Comma-Seperated Values (*.csv)" [sic - typo in app]
- Default filename: based on open file name
- Save button at approximately (869, 495) in Save As dialog

## Data

### VitalDB Open Dataset

- Source: https://vitaldb.net / https://api.vitaldb.net
- Download pattern: `https://api.vitaldb.net/XXXX.vital` (where XXXX is case number)
- 6,388 real intraoperative vital sign cases
- .vital is VitalRecorder's native binary format

### Files Used

| File | Size | Duration | Key Tracks |
|------|------|----------|------------|
| `0001.vital` | 21MB | 3h 12m 22s | ART, ECG_II, ECG_V5, PLETH, CO2, AWP, BIS |
| `0002.vital` | 21MB | 4h 22m 20s | ECG_II, ECG_V5, PLETH, HR, ST_V5, SPO2, VENT_RR/MV |
| `0003.vital` | 6.5MB | 1h 13m 14s | ECG_II, ECG_V5, PLETH, COMPLIANCE, SEVO, PAMB/MAWP/PPLAT |

### Data Placement
- Pre-start copies from `/workspace/data/` to `C:\Users\Docker\Desktop\VitalRecorderData\`
- Post-start re-copies to ensure they persist (belt-and-suspenders)

## Automation Patterns

### Launching GUI App from SSH (Session 0)

SSH runs in Session 0 (no desktop). Must use `schtasks /IT` + batch file:

```powershell
$batchContent = "@echo off`r`nstart `"`" `"$vrExe`" `"$fileToOpen`""
[System.IO.File]::WriteAllText($launchScript, $batchContent)

$schedTime = (Get-Date).AddMinutes(1).ToString("HH:mm")
schtasks /Create /TN $taskName /TR "cmd /c `"$launchScript`"" /SC ONCE /ST $schedTime /RL HIGHEST /IT /F
schtasks /Run /TN $taskName
Start-Sleep -Seconds $WaitSeconds
schtasks /Delete /TN $taskName /F
```

### File Arguments
- Vital Recorder accepts file path as command-line argument: `Vital.exe "path\to\file.vital"`
- Opens directly in Track mode with data loaded

### No First-Run Dialogs
- Vital Recorder has NO first-run dialogs, sign-in prompts, or EULA screens
- Warm-up launch in post_start is a safety net but not strictly necessary
- Clean launches every time after installation

### Win32 Click Automation
- Win32 API clicks (SetCursorPos + mouse_event) work for VitalRecorder
- Unlike NinjaTrader, no need for PyAutoGUI server
- Click-At function in task_utils.ps1 handles this

## Known Issues

1. **Background cmd.exe windows**: schtasks creates cmd.exe windows that may appear behind VitalRecorder. Setup script minimizes them with Win32 ShowWindow.

2. **schtasks "file not found" error on first delete**: When deleting a task that doesn't exist yet, schtasks prints "ERROR: The system cannot find the file specified." This is harmless - the ErrorActionPreference is set to "Continue" during schtasks operations to handle this.

3. **Right-click context menu**: VitalRecorder does NOT have a right-click context menu on waveform tracks. Cannot change track colors or properties via right-click.

4. **Event timestamps**: Events in .vital files use dates like "2100-01-01" (not real calendar dates). The timestamps represent elapsed time from case start.

## Timing

| Operation | Duration |
|-----------|----------|
| MSI download | ~5s |
| MSI install (2 steps) | ~15s |
| Data file copy | ~2s |
| Post-start (OneDrive + warm-up) | ~40s |
| Pre-task (launch + dismiss) | ~35-38s |
| Full fresh boot | ~172s |
| Cached boot (post_start checkpoint) | ~127-144s |
