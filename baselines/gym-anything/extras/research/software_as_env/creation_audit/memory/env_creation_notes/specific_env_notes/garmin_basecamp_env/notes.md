> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Garmin BaseCamp Environment Notes

**Verified:** 2026-02-24
**Base Image:** windows-11
**App:** Garmin BaseCamp 4.7.5 GPS route planning desktop application
**Status:** FULLY VERIFIED

---

## App Overview

Garmin BaseCamp is a Windows desktop application for planning GPS routes, managing waypoints, and importing/exporting GPS data. It maintains a local SQLite database (AllData.gdb) and supports GPX file import/export.

---

## Installation

### Installer
- URL: `https://download.garmin.com/software/BaseCamp_475.exe`
- Valid download size: ~61.9 MB (61,931,328 bytes)
- **CRITICAL**: Partial downloads (~47 MB) have valid MZ PE header but corrupted WiX payload → exit code 1392 (ERROR_FILE_CORRUPT = 0x80070570)
- **Fix**: Use `Start-BitsTransfer` for download; reject if `$fileSize -lt 50000000`

### Silent Install
```powershell
Start-Process -FilePath $bcInstaller -ArgumentList "/install /quiet /norestart" -Wait -PassThru
# Exit 0 = success, 3010 = reboot recommended (also success)
```

### Install Path
- `C:\Program Files (x86)\Garmin\BaseCamp\BaseCamp.exe` (most common)
- `C:\Program Files\Garmin\BaseCamp\BaseCamp.exe` (alternative)

---

## Task Launcher (CRITICAL BEHAVIOR)

BaseCamp shows a "Task Launcher" dialog on every startup. This is **NOT** a modal dialog — it IS BaseCamp's main application window (MainWindowHandle).

### Task Launcher Items
- Plan a Trip → Opens Route Planner ("New Route" dialog)
- Download BirdsEye Imagery
- GeoTag Photos
- Customize Activity Profiles
- Manage Your Device
- View Tutorial Videos

### How to Dismiss Task Launcher
- **WRONG**: Press ESC → closes BaseCamp entirely
- **WRONG**: Click Close/X button → closes BaseCamp entirely
- **CORRECT**: Click "Plan a Trip" at approximately (443, 210) in 1280x720 coordinates

### After Clicking "Plan a Trip"
1. Route Planner opens ("New Route" dialog)
2. Tutorial Video tip dialog may appear → dismiss with ESC
3. "3D Terrain Disabled" or "Detailed Map Needed" dialog may appear → click OK at (806, 405)
4. Press ESC again → closes Route Planner → returns to main map view with library

### Code Pattern for Task Launcher Dismissal (in schtasks /IT session)
```powershell
# Click Plan a Trip (coordinates in 1280x720)
[Win32Launch]::SetCursorPos(443, 210) | Out-Null
Start-Sleep -Milliseconds 200
[Win32Launch]::mouse_event(0x02, 0, 0, 0, 0) | Out-Null  # LEFTDOWN
Start-Sleep -Milliseconds 100
[Win32Launch]::mouse_event(0x04, 0, 0, 0, 0) | Out-Null  # LEFTUP
Start-Sleep -Seconds 5

# Dismiss tutorial video tip
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{ESCAPE}")
Start-Sleep -Seconds 2

# Dismiss detail map / 3D terrain dialog
[Win32Launch]::SetCursorPos(806, 405) | Out-Null
[Win32Launch]::mouse_event(0x02, 0, 0, 0, 0) | Out-Null
Start-Sleep -Milliseconds 100
[Win32Launch]::mouse_event(0x04, 0, 0, 0, 0) | Out-Null
Start-Sleep -Seconds 2

# Close Route Planner (returns to main map view)
[System.Windows.Forms.SendKeys]::SendWait("{ESCAPE}")
Start-Sleep -Seconds 2
```

---

## Database

### Location
- Active: `C:\Users\Docker\AppData\Roaming\Garmin\BaseCamp\Database\4.7\`
- Files: `AllData.gdb` (SQLite) + `FolderData.gfi` + subdirs

### Backup Pattern
After importing GPX data (via post_start hook), backup the database:
```powershell
$dbSrc = "C:\Users\Docker\AppData\Roaming\Garmin\BaseCamp\Database"
$dbDst = "C:\GarminTools\BaseCampBackup\Database"
Copy-Item $dbSrc $dbDst -Recurse -Force
```

### Restore Pattern (in each task pre_task hook)
```powershell
Close-BaseCamp  # Kill process first!
Copy-Item $dbDst $dbSrc -Recurse -Force
```

---

## GPX Data

### fells_loop.gpx
- 66 waypoints in Middlesex Fells area (Massachusetts)
- Key waypoints: BEAR HILL, BELLEVUE, SHEEPFOLD, DARKHOLLPO, PANTHRCAVE, GATE5-24, 5058ROAD, 5067, 5096, 5142, 5148NANEPA, 5156, 5224, 5229, 5237, etc.
- Used for: change_waypoint_symbol, create_waypoint, rename_waypoint, create_route

### dole_langres_track.gpx
- Track from Dole to Langres, France
- Used for: import_gpx_file task (agent must import this)

### hike_track.gpx
- Additional track data

---

## Interactive Session Pattern (schtasks /IT)

SSH operates in Windows Session 0 (non-interactive, no desktop). To interact with the GUI, all automation must run in Session 1 (the interactive desktop session).

### Pattern
```powershell
# Write the interactive script to disk
$psScript | Set-Content "C:\GarminTools\launch_bc_task.ps1" -Encoding UTF8
"@echo off`r`npowershell -ExecutionPolicy Bypass -File `"C:\GarminTools\launch_bc_task.ps1`"`r`n" | Set-Content "C:\GarminTools\launch_bc_task.bat" -Encoding ASCII

# Schedule via schtasks /IT (runs in interactive session)
$runTime = (Get-Date).AddMinutes(1).ToString("HH:mm")
schtasks /Create /SC ONCE /IT /TR "C:\GarminTools\launch_bc_task.bat" /TN "MyTask" /ST $runTime /F

# Wait for it to complete
Start-Sleep -Seconds 80
schtasks /Delete /TN "MyTask" /F 2>&1 | Out-Null
```

### CRITICAL: Avoid Nested Here-String Escaping
When generating PowerShell scripts that contain `Add-Type -TypeDefinition @"..."@` blocks:
- DO NOT embed the C# Add-Type as a nested here-string — escaping breaks it
- INSTEAD: Write the C# source to a `.cs` file using single-quoted here-string (`@'...'@`) and use `Add-Type -Path "file.cs"` in the generated script

```powershell
# Good: Write .cs file separately
@'
using System.Runtime.InteropServices;
public class MyClass { ... }
'@ | Set-Content "C:\GarminTools\MyClass.cs" -Encoding UTF8

# Then reference in generated script:
"Add-Type -Path `"C:\GarminTools\MyClass.cs`" -ErrorAction SilentlyContinue"
```

---

## MainWindowHandle from SSH

When checking BaseCamp from an SSH session (Session 0), `Get-Process BaseCamp | Select MainWindowHandle` always returns 0 — even when the window is visible in Session 1/VNC. This is a Windows session isolation limitation. Use process existence check (`Get-Process "BaseCamp"`) instead of window handle check.

---

## OneDrive Popup

OneDrive "Turn On Windows Backup" notification appears frequently. Kill it at the start of every schtasks /IT script:
```powershell
Get-Process | Where-Object { $_.Name -match "OneDrive" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
```

---

## Tasks Summary

| Task | Start State | Key Verification |
|------|-------------|-----------------|
| change_waypoint_symbol | BaseCamp open, fells_loop waypoints in library | BEAR HILL waypoint exists with default symbol |
| create_waypoint | BaseCamp open, fells_loop waypoints in library | Library count increases by 1 |
| rename_waypoint | BaseCamp open, fells_loop waypoints in library | DARKHOLLPO renamed to new name |
| create_route | BaseCamp open, fells_loop waypoints in library | New route appears in library |
| import_gpx_file | BaseCamp open, EMPTY library; dole_langres_track.gpx on Desktop | Track appears in library after import |

---

## Verifier Pattern (SQLite-based)

BaseCamp's AllData.gdb is a SQLite database. Verifiers can query it directly:
```python
import sqlite3
conn = sqlite3.connect(r"C:\Users\Docker\AppData\Roaming\Garmin\BaseCamp\Database\4.7\AllData.gdb")
# Tables: Point, Route, Track, Folder, Collection, etc.
```

Key tables:
- `Point`: Waypoints (name, lat, lon, symbol)
- `Route`: Routes (name, start point, end point)
- `Track`: Tracks (from imported GPX files)
- `Folder`: Folders/collections in library
