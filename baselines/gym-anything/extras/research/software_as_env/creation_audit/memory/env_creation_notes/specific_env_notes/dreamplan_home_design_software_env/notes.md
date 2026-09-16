> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# DreamPlan Home Design Software Environment — Notes

## Overview
- **Application**: DreamPlan Home Design v9.28 by NCH Software (Windows-only)
- **Base image**: `windows-11` (UEFI/OVMF)
- **RAM**: 8GB (required for smooth 3D rendering)
- **Install method**: GUI installer via PyAutoGUI automation + schtasks
- **env_hash**: `0d206bcb35681ea9`

## Critical: VBScript Variable Name `wsh` Is Reserved
**ROOT CAUSE of hours of debugging**: On this Windows 11 QEMU image, using `wsh` as a VBScript variable name causes runtime error 800A01C2 ("Wrong number of arguments or invalid property assignment"). This affects ALL VBScript operations: `Run`, `AppActivate`, `SendKeys`.

**Fix**: Always use `ws` instead of `wsh`:
```vbs
' BROKEN: causes error 800A01C2
Set wsh = CreateObject("WScript.Shell")

' WORKS: use 'ws' instead
Set ws = CreateObject("WScript.Shell")
```

Systematically tested with 6 VBS variants — `wsh` always fails, `ws` always works. The `wsh` naming convention is common in Windows scripting examples but breaks on this specific image.

## Critical: Session 0 vs Session 1 Isolation
SSH connections run in Session 0 (non-interactive). GUI applications like DreamPlan must run in Session 1. The pattern:

1. Create a VBScript with the desired action
2. Use `schtasks /Create /IT /RL HIGHEST` to create a scheduled task
3. Use `schtasks /Run` to execute it in the interactive session
4. Wait, then clean up with `schtasks /Delete`

**Direct `schtasks /TR "dreamplan.exe"` does NOT work** for launching DreamPlan. Must use a VBS wrapper with `ws.Run`.

## Critical: Multiple Startup Dialogs
DreamPlan shows up to 3 dialogs on launch after a force-kill:

1. **"Abnormal Termination Detected"** — crash dialog with "It Crashed" (default) and "Something Else" buttons. Title is "Abnormal Termination Detected" (NOT "DreamPlan").
2. **"Open Auto-save Project"** — recovery dialog with "Yes, Open Last Project" and "No Thanks". Title contains "Auto-save".
3. **Tutorial tips** — context-sensitive tip panels that appear on every tool selection.

**Dialog handling via VBScript** (not PyAutoGUI — VBS can target windows by title):
```vbs
Set ws = CreateObject("WScript.Shell")
If ws.AppActivate("Abnormal Termination") Then
    WScript.Sleep 300
    ws.SendKeys "{TAB}"    ' Move to "Something Else"
    WScript.Sleep 300
    ws.SendKeys "{ENTER}"
    WScript.Sleep 2000
End If
If ws.AppActivate("Auto-save") Then
    WScript.Sleep 300
    ws.SendKeys "{TAB}"    ' Move to "No Thanks"
    WScript.Sleep 300
    ws.SendKeys "{ENTER}"
End If
```

## Critical: Tutorial Tips Registry Setting
DreamPlan shows context-sensitive "Tips" panels on every tool selection. Disable with:
```powershell
Set-ItemProperty -Path "HKCU:\Software\NCH Software\DreamPlan\Settings" -Name "IsInstructionsDisplayed" -Value "0" -Force
```
Must be set BEFORE launching DreamPlan (takes effect on next launch).

## Critical: Graceful Close Doesn't Work
`Close-DreamPlanGracefully` (Alt+F4 via VBScript) always falls back to force-kill. DreamPlan doesn't respond to Alt+F4 reliably. This means:
- Crash dialog WILL appear on every subsequent launch
- Auto-save dialog may appear if a project was open
- Both must be handled in every launch sequence

## Sample Project Download
First click on "View Sample Project" triggers download of ~7 templates (30-60 seconds). Subsequent launches use cached samples. The post_start warm-up should trigger this download, but if PyAutoGUI crashes during warm-up, the download happens on the first pre_task run instead.

## PyAutoGUI Server Stability
The PyAutoGUI TCP server (port 5555) is prone to crashing during the post_start warm-up. When it crashes:
- All PyAutoGUI clicks/hotkeys fail silently (error: "target machine actively refused")
- VBScript-based operations (schtasks + WScript.Shell) still work
- The server can be restarted via schtasks

**Workaround**: Use VBScript for critical operations (launch, dialog dismiss) that must work even without PyAutoGUI. Save PyAutoGUI for non-critical automation (clicking in 3D viewport).

## Start Screen Coordinates (1280x720)
DreamPlan always shows the start screen on launch (after force-kill):

| Button | Coordinates |
|--------|------------|
| Start Blank Project | (768, 185) |
| View Sample Project | (768, 260) |
| Open Saved Project | (768, 335) |
| Trace Floor Plan | (768, 410) |
| Watch Online Tutorials | (768, 485) |

## Sample Selection Dialog Coordinates (1280x720)
After clicking "View Sample Project":

| Element | Coordinates |
|---------|------------|
| Tiny House | (453, 197) |
| Small Apartment | (602, 197) |
| Craftsman | (755, 197) |
| Stilt House | (908, 197) |
| Contemporary House | (452, 324) |
| Modern Colonial | (602, 324) |
| Urban House | (755, 324) |
| Open Project button | (857, 570) |
| Cancel button | (965, 570) |

## DreamPlan Registry Keys
Location: `HKCU:\Software\NCH Software\DreamPlan\`

| Key | Purpose |
|-----|---------|
| `Settings\IsInstructionsDisplayed` | `0` disables tutorial tips |
| `Settings\UseMetric` | `0` = imperial, `1` = metric |
| `RecentFileList\File0` | Last opened project path |
| `SamplesLoaded\contemporary` | `1` if Contemporary House downloaded |

## Edge Auto-Restore Handling
Windows 11 restores Edge from checkpoint. The environment uses:
1. Registry policies to disable Edge startup boost/restore
2. Background Edge killer task (VBS hidden cmd loop, kills msedge every 2s for 120s)
3. Clearing Edge session restore files from User Data directory

## File Locations
- DreamPlan exe: `C:\Program Files (x86)\NCH Software\DreamPlan\dreamplan.exe`
- Config: `C:\Users\Docker\AppData\Roaming\NCH Software\DreamPlan\`
- Sample projects: `C:\ProgramData\NCH Software\DreamPlan\samples\`
- Exe path cache: `C:\Users\Docker\dreamplan_exe_path.txt`
- Post-start log: `C:\Users\Docker\env_setup_post_start.log`
- Pre-task log: `C:\Users\Docker\task_pre_task_change_flooring_material.log`

## Pre-Task Flow (change_flooring_material)
1. Start Edge killer background task
2. Kill any existing DreamPlan process
3. Minimize PyAutoGUI console (Win+Down x2)
4. Launch DreamPlan via VBS + schtasks
5. Dismiss startup dialogs via VBS (crash + auto-save)
6. Navigate start screen: View Sample Project (768, 260)
7. Wait for sample dialog (8s if cached, 45s if downloading)
8. Select Contemporary House (452, 324) -> Open Project (857, 570)
9. Wait for 3D rendering (10s)
10. Verify DreamPlan process is running
11. Stop Edge killer, minimize terminals
