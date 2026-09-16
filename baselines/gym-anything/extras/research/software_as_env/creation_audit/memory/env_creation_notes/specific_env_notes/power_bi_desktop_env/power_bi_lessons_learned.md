> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Power BI Desktop Environment - Lessons Learned

These notes cover Power BI Desktop-specific patterns and pitfalls discovered while setting up the `power_bi_desktop_env` on a Windows 11 QEMU VM.

---

## 1. Installation: Use the EXE Installer, NOT MSI

Microsoft retired the MSI installer for Power BI Desktop in 2019. The only supported installer is the EXE from the Microsoft download center.

**Silent install command:**
```
PBIDesktopSetup_x64.exe -quiet -norestart ACCEPT_EULA=1 INSTALLDESKTOPSHORTCUT=0 DISABLE_UPDATE_NOTIFICATION=1 ENABLECXP=0
```

**Install path:** `C:\Program Files\Microsoft Power BI Desktop\bin\PBIDesktop.exe`

Key flags:
- `-quiet`: No UI during install
- `-norestart`: Prevent automatic reboot
- `ACCEPT_EULA=1`: Accept the license agreement
- `DISABLE_UPDATE_NOTIFICATION=1`: Suppress update nag dialogs
- `ENABLECXP=0`: Disable customer experience program / telemetry

Do NOT attempt to use the Microsoft Store version -- it requires a Store login and cannot be silently installed in a headless VM.

## 2. Process Names

Power BI Desktop runs as two processes:

| Process | Description |
|---------|-------------|
| `PBIDesktop` | Main GUI application |
| `msmdsrv` | Analysis Services sub-process (local engine for data models) |

**Both must be killed** when cleaning up Power BI. Killing only `PBIDesktop` leaves `msmdsrv` running and subsequent launches may behave unpredictably.

```powershell
Get-Process PBIDesktop -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process msmdsrv -ErrorAction SilentlyContinue | Stop-Process -Force
```

## 3. Home Screen (Always Shows on Launch)

Power BI Desktop **always** shows a Home screen on launch -- there is no registry key or command-line flag to bypass it. The Home screen must be navigated programmatically.

### Home Screen Layout (1280x720)

The Home screen contains:
1. **"Join us at FabCon Atlanta" promotional banner** at the top -- close via X button at **(1247, 64)**
2. **"Blank report" card** -- click at **(328, 243)** to enter the report canvas
3. Other cards (Recent files, Excel, SQL Server, etc.) -- ignore

**You must click "Blank report" to reach the actual report canvas.** There is no keyboard shortcut to skip the Home screen.

## 4. First-Run Dialog Chain

On the **first launch from a checkpoint**, Power BI shows a chain of dialogs after entering the report canvas. These dialogs only appear once -- subsequent launches from the same checkpoint are clean.

### Dialog sequence and coordinates (1280x720):

| Order | Dialog | X Button Coordinates | Notes |
|-------|--------|---------------------|-------|
| 1 | FabCon Atlanta banner | (1247, 64) | On Home screen, before Blank report click |
| 2 | "Dark mode is here" customization | (884, 225) | Modal dialog on report canvas |
| 3 | "Two ways to use sample data" tutorial | (930, 147) | Modal dialog on report canvas |
| 4 | Green "Live Edit semantic models in Direct Lake mode" banner | (640, 32) | Thin banner at top of canvas |

**Important**: These dialogs stack. Sending Escape between clicks helps clear any dialog that appeared behind another.

## 5. Coordinate Pitfalls

### Canvas "safe click" area

After dismissing all dialogs, you need to click an empty canvas area to ensure focus. However:

- **(500, 400) is NOT safe** -- it hits the "Import data from SQL Server" shortcut button that appears on a clean canvas
- **(535, 550) is safe** -- empty canvas area below the import shortcuts

### All critical coordinates (1280x720 resolution)

```
Home screen:
  FabCon Atlanta banner X:     (1247, 64)
  Blank report card:           (328, 243)

Report canvas dialogs:
  Dark mode dialog X:          (884, 225)
  Sample data dialog X:        (930, 147)
  Green Live Edit banner X:    (640, 32)

Safe canvas click:             (535, 550)
AVOID:                         (500, 400)  -- hits "Import from SQL Server"
```

**All coordinates are at 1280x720 resolution** (QEMU default). If the VM resolution changes, all coordinates must be recalibrated.

## 6. Warm-Up Launch in post_start

Power BI Desktop needs a warm-up launch during `post_start` to complete its first-run initialization cycle. Without this, the first `pre_task` launch takes significantly longer and shows more dialogs.

**Pattern:**
1. Launch Power BI via `schtasks /IT`
2. Wait 20 seconds (Power BI needs time to start its Analysis Services engine)
3. Kill both `PBIDesktop` and `msmdsrv`
4. Wait 3 seconds for process cleanup

After warm-up, subsequent launches are faster and show fewer dialogs (the Home screen still appears, but the Dark mode / sample data / Live Edit dialogs are less likely to appear again from the same checkpoint).

## 7. Dismiss Script Timing

The `dismiss_dialogs.ps1` script takes approximately **25 seconds** to run through its full sequence:
- 3s initial wait for Home screen to render
- ~4s OneDrive popup dismiss + FabCon banner
- 5s wait after clicking "Blank report"
- ~12s for Phase 2 dialogs (Escape + Dark mode + Escape + Sample data + Live Edit banner)
- ~3s for Phase 3 cleanup (Escape keys + safe click)

The `setup_task.ps1` scripts wait **28 seconds** after launching the dismiss script (includes a safety margin).

### Total pre_task timing breakdown:
```
Kill existing PBI + msmdsrv:    2s
Launch Power BI via schtasks:  15s
Run dismiss_dialogs.ps1:       28s (includes margin)
Process verification:           1s
Overhead:                       2s
                              ----
Total:                        ~48s
```

## 8. Registry Tweaks

The following registry keys are set during `post_start` to reduce noise:

```powershell
# Disable update notifications
Set-ItemProperty "HKCU:\Software\Microsoft\Microsoft Power BI Desktop" -Name "DisableUpdateNotification" -Value 1 -Type DWord

# Disable telemetry / customer experience program
Set-ItemProperty "HKCU:\Software\Microsoft\Microsoft Power BI Desktop\CXP" -Name "Enabled" -Value 0 -Type DWord

# Disable Windows consumer features (backup notifications, etc.)
Set-ItemProperty "HKLM:\SOFTWARE\Policies\Microsoft\Windows\CloudContent" -Name "DisableWindowsConsumerFeatures" -Value 1 -Type DWord
```

**Note**: These registry keys reduce but do not eliminate dialogs. The Home screen and first-run dialog chain still require programmatic dismissal.

## 9. OneDrive Must Be Disabled

OneDrive shows a "Turn On Windows Backup" popup that can block the entire screen. The `post_start` script handles this with a multi-pronged approach:

1. Kill `OneDrive` and `OneDriveSetup` processes
2. Remove from startup registry (`HKCU:\...\Run\OneDrive`)
3. Disable via Group Policy (`HKLM:\SOFTWARE\Policies\Microsoft\Windows\OneDrive\DisableFileSyncNGSC` = 1)
4. Uninstall with 30-second timeout (using `-PassThru` + `WaitForExit(30000)`)

**Critical**: Do NOT use `Start-Process -Wait` for OneDrive uninstall -- it can hang indefinitely. Always use `-PassThru` with a timeout.

## 10. Dialogs Only Appear on First Launch from Checkpoint

When building a checkpoint:
- The first launch from the checkpoint shows the full dialog chain (Home screen + Dark mode + Sample data + Live Edit banner)
- Subsequent launches from the **same** checkpoint are cleaner (Home screen always appears, but the other dialogs typically do not)

This means `dismiss_dialogs.ps1` must handle both cases gracefully. Clicking X buttons on coordinates where no dialog exists is harmless -- the clicks land on the canvas or ribbon area.

## 11. Troubleshooting

### Power BI fails to launch
- Check that `msmdsrv` from a previous run is not still holding ports
- Kill both `PBIDesktop` and `msmdsrv`, wait 2-3 seconds, then retry

### Canvas shows unexpected dialogs after dismiss
- Increase wait times in `dismiss_dialogs.ps1` (dialogs can be slow to appear on first boot)
- Add additional Escape key sends between dialog dismiss steps

### "Import from SQL Server" dialog appears unexpectedly
- A mouse click likely landed on (500, 400) instead of the safe zone (535, 550)
- Send Escape to close it and re-click at the safe coordinates

### Power BI hangs on launch
- The Analysis Services engine (`msmdsrv`) needs port 52359 (or similar). If another instance is running, it will conflict
- Always kill `msmdsrv` before launching a new Power BI instance
