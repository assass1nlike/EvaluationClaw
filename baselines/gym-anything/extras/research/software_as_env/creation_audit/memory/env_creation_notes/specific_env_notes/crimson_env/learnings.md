> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Crimson HMI Environment - Learnings

## Installation Quirks

### Executable Name
- The main Crimson 3.0 executable is **`c3.exe`**, NOT `Crimson3.exe` or `Crimson.exe`.
- Install path: `C:\Program Files (x86)\Red Lion Controls\Crimson 3.0\c3.exe`
- `c3.exe` is a launcher that spawns `shexe.exe` as the main running process.
- When checking if Crimson is running, look for process name `shexe` (not `c3`).
- Related processes: `c3.exe` (launcher), `shexe.exe` (main app), `g3sim.exe` (simulator), `shcal.exe` (calibration).

### Download Performance
- The Crimson installer is ~170MB. PowerShell's `Invoke-WebRequest` buffers the entire file in memory, causing stalls at ~45MB over QEMU SLIRP networking.
- **Fix**: Use native `curl.exe` with streaming download: `curl.exe -L -o $path --retry 3 --connect-timeout 30 --max-time 600 $url`
- Download completes in ~4 minutes with curl.exe vs hanging indefinitely with Invoke-WebRequest.

### Silent Install
- Crimson uses an NSIS-based installer. Silent flag is `/S` (capital S).
- Exit code 0 = success. Exit code 3010 = success, reboot recommended.
- Install takes approximately 2-3 minutes in silent mode.

## Service/Timing Issues

### Windows Session 0 Isolation
- SSH sessions run in Session 0 (no display). GUI applications launched from SSH won't appear on screen.
- **Solution**: Use `schtasks` with `/IT` flag to launch GUI apps in the interactive desktop (Session 1).
- Process: Create scheduled task → Run it → Wait → Cleanup task.

### Path Quoting with `(x86)`
- `C:\Program Files (x86)\...` contains parentheses that break batch file parsing.
- **Solution**: Convert to 8.3 short path names using `Scripting.FileSystemObject`:
  ```powershell
  $fso = New-Object -ComObject Scripting.FileSystemObject
  $shortPath = $fso.GetFile($exePath).ShortPath
  # Result: C:\PROGRA~2\REDLIO~1\CRIMSO~1.0\c3.exe
  ```
- Use short paths in batch files passed to schtasks.

### Process Launch Timing
- After `schtasks /Run`, allow 10-15 seconds for the app to fully load.
- `c3.exe` launches and spawns `shexe.exe`; the original `c3.exe` process exits quickly.
- Wait-For-Process should check for `shexe` not `c3`.

### schtasks stderr Output
- `schtasks` writes informational messages to stderr, which triggers terminating errors under `$ErrorActionPreference = "Stop"`.
- **Fix**: Temporarily set `$ErrorActionPreference = "Continue"` around schtasks calls, or redirect stderr: `2>$null`.

## Registration Dialog
- Crimson shows "Register Your Copy of Crimson 3" dialog on **every** launch (unregistered copy).
- Dialog has "Register" and "Skip" buttons.
- **Dismissal sequence**: Click "Skip" → Click "Yes" on the confirmation dialog.
- The dialog appears at a consistent position centered on the screen.
- For 1280x720 resolution:
  - Skip button at approximately **(554, 585)** (verified via visual grounding)
  - Yes button on confirmation dialog at approximately **(630, 349)**
- Alternative fallback: `Alt+Y` hotkey to confirm the skip dialog.
- The dialog pre-populates with "Windows for Docker" name and "Dockur" company from the VM template.

## OneDrive Interference
- Windows 11 OneDrive popup appears over the application, showing "Turn On Windows Backup".
- **Mitigation**:
  1. Kill OneDrive processes in setup script
  2. Disable via Group Policy registry keys
  3. Uninstall OneDrive silently
  4. Click "No thanks" via PyAutoGUI if popup still appears (approx x=1166, y=627)

## Data Requirements
- Used UCI Air Quality Dataset (real sensor data, not synthetic).
- 8,991 rows of real sensor readings from an Italian city (2004-2005).
- Tag specifications derived from actual observed data ranges.
- ISA-standard naming: TT (Temperature), PT (Pressure), FT (Flow), LT (Level), AT (Analytical), MT (Moisture).

## PyAutoGUI Integration
- PyAutoGUI TCP server runs on guest port 5555 (forwarded to random host port).
- Commands: `screenshot`, `click` (x, y), `press` (keys), `hotkey` (keys array).
- The `Invoke-PyAutoGUICommand` function in task_utils.ps1 handles TCP communication.
- All GUI automation (dialog dismissal, button clicks) goes through this server.
- **CRITICAL**: Do NOT name the host parameter `$Host` in PowerShell - it conflicts with the built-in `$Host` automatic variable. Use `$ServerAddr` instead. Error: "Cannot overwrite variable Host because it is read-only or constant."

## Key Architecture Decisions
1. **Three-script pattern**: install_crimson.ps1 (pre_start) → setup_crimson.ps1 (post_start) → task-specific setup_task.ps1 (pre_task)
2. **Warm-up cycle**: Launch and kill Crimson once during setup to complete first-run initialization, reducing dialog prompts during actual task.
3. **8.3 short paths**: Always convert paths containing `Program Files (x86)` before writing to batch files.
4. **Process detection**: Check for `shexe` process, not `c3`, when verifying Crimson is running.
5. **Dialog dismissal timing**: Allow 8+ seconds after Crimson launch for registration dialog to appear. Use 3 retries to ensure reliable dismissal.
6. **Total environment boot time**: ~10 minutes (Windows boot + 170MB download + installation + setup + task setup). Checkpoint caching should significantly reduce subsequent starts.

## Crimson UI Structure
- **Tabs for tag configuration**: Data, Format, Colors, Alarms, Triggers, Plot, Security
- **Data type field**: "Treat As" dropdown on Data tab (Signed Integer, Float, etc.)
- **Min/Max values**: On Format tab under "Data Limits"
- **Alarm thresholds**: On Alarms tab, Alarm 1/2 sections with Event Mode, Value fields
- **Tag naming**: Label field on Data tab (under "Data Labels" section)
- **New tag creation**: "New" button in Navigation Pane creates a tag named "Tag1", "Tag2", etc.
- **Window arrangement**: Crimson takes full focus; Notepad with reference data accessible via Alt+Tab
