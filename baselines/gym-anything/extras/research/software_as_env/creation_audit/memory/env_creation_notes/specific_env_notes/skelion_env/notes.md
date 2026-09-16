> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# skelion_env — Environment Notes

**Status**: Scripts complete, interactive testing done, env ready for final clean test.
**Verified**: 2026-02-24

---

## Stack

- **Guest OS**: Windows 11 (QEMU/Apptainer)
- **Application**: SketchUp Make 2017 (last free version) + Skelion v5.5.2 solar plugin
- **Python**: 3.11 + PyAutoGUI (GUI automation via TCP server on port 5555)
- **User**: Docker (C:\Users\Docker\)

---

## CRITICAL: ANGLE_DEFAULT_PLATFORM=gl

SketchUp's License/Welcome dialog uses CEF (Chromium Embedded Framework) with ANGLE for GPU rendering. On VirtIO GPU VMs, ANGLE defaults to the D3D11 backend which **hangs indefinitely** during hardware initialization.

**Fix**: Set `ANGLE_DEFAULT_PLATFORM=gl` as a Machine-scope environment variable in the install script. This forces ANGLE to use the OpenGL backend (Mesa3D software renderer via `libgallium_wgl.dll`), which works reliably.

```powershell
[System.Environment]::SetEnvironmentVariable("ANGLE_DEFAULT_PLATFORM", "gl", "Machine")
[System.Environment]::SetEnvironmentVariable("LIBGL_ALWAYS_SOFTWARE", "1", "Machine")
[System.Environment]::SetEnvironmentVariable("GALLIUM_DRIVER", "softpipe", "Machine")
```

**Diagnosis**: If `sketchup_webhelper.exe` uses only 4-5 MB RAM, CEF never initialized (hanging). With the fix, it grows to 37-42 MB (healthy). Without this fix, SketchUp is permanently stuck on the License dialog and never becomes usable.

---

## schtasks /IT Launch Pattern (CRITICAL)

All SketchUp launches from SSH (Session 0) must use `schtasks /IT` to run in the interactive VNC session (Session 1). Additionally, schtasks `/TR` cannot handle paths with spaces in quotes reliably.

**Solution**: Create a batch file wrapper:

```powershell
$batPath = "C:\temp\launch_su_task.bat"
Set-Content -Path $batPath -Value "@echo off`r`nstart `"`" `"$suExe`" `"$filePath`"" -Encoding ASCII
schtasks /Create /TN "SketchUp_Task" /TR $batPath /SC ONCE /ST "00:00" /RL HIGHEST /IT /F
schtasks /Run /TN "SketchUp_Task"
```

The batch file internally handles the quoting for paths with spaces.

---

## Windows Firewall (CEF hang fix #2)

Even with ANGLE=gl, the CEF page tries to reach Trimble license servers and may stall on network timeout. Block outbound HTTP/HTTPS using `-RemoteAddress Internet` (NOT `-RemoteAddress Any`) to preserve loopback IPC between CEF processes:

```powershell
New-NetFirewallRule -DisplayName "Block SketchUp WebHelper HTTPS" `
    -Direction Outbound -Program $webHelper `
    -Protocol TCP -RemotePort 80,443 -RemoteAddress Internet `
    -Action Block -Enabled True
```

Using `Any` breaks CEF IPC and causes SketchUp to not render at all.

---

## Dialog Sequence (first launch / post_start)

1. **Wait 25s** for Welcome screen to appear
2. **Click (949, 669)** — "Start using SketchUp" button
3. **Press Enter** — accept default template
4. **Wait 20s** for workspace to load
5. **Click (277, 123)** — dismiss 2D Bool plugin dialog (if present)
6. **Click (191, 396)** — accept Skelion EULA dialog
7. **Click (793, 326)** — dismiss Skelion notification dialog
8. **Wait up to 90s** for Ruby plugin to create `Solar_Project.skp`
9. **Ctrl+S** — save model
10. **Alt+F4** — close SketchUp

Note: `WelcomeScreenShown=1` in registry does NOT reliably suppress the Welcome screen — SketchUp still shows it on first launch. The dialog clicking sequence handles this.

---

## Task Reset Pattern

On each task reset (setup_task.ps1 → `Reset-SketchUpModel`), SketchUp is opened with `Solar_Project.skp` directly (no Welcome screen since a file is passed). Wait 40 seconds (plugins load + file open), then dismiss residual dialogs. The Skelion EULA and notification only appear on the very first Skelion load (handled in post_start) — not on subsequent file opens.

---

## Building Model (Ruby plugin)

Auto-created by `auto_create_solar_building.rb` in the Plugins directory:
- Uses `UI.start_timer(3.0, false)` — fires 3s after SketchUp loads
- Flag file `C:\Users\Docker\solar_project_created.flag` prevents double-runs
- **Geometry**: 20m × 15m main block (4.5m tall), parapet walls (0.4m × 0.2m on all sides), HVAC unit (3m × 2m × 1.2m at NE), stairwell (2m × 2m × 2.5m at SW)
- Sets model attributes: Latitude=37.77, Longitude=-122.42, BuildingType=Commercial
- Saves to `C:\Users\Docker\Desktop\Solar_Project.skp`

---

## Skelion Plugin Installation

Skelion is distributed as a `.rbz` file (ZIP archive with `.rb`/`.rbs` files). Installation:
1. Download from `https://skelion.com/en/Skelion_skelion_v5.5.2.rbz`
2. Copy as `.zip`, extract with `Expand-Archive`
3. Copy extracted files to `C:\Users\Docker\AppData\Roaming\SketchUp\SketchUp 2017\SketchUp\Plugins\`

Skelion appears in Extension Manager as "Skelion v5.5.2 (Enabled, Unsigned)". Toolbar shows 7 icons.

---

## PyAutoGUI Server

Pre-installed at `C:\Windows\Temp\pyautogui_server.py`, runs on TCP port 5555. JSON command format:
- Click: `{"action": "click", "x": N, "y": N}`
- Key press: `{"action": "press", "key": "return"}`
- Hotkey: `{"action": "hotkey", "keys": ["ctrl", "s"]}`

VNC resolution: 1280×720. Coordinates are 1:1 (no scaling). The visual_grounding MCP tool returns 1280×720 coordinates directly usable with PyAutoGUI.

---

## Tasks

| Task | Verifier | Notes |
|------|----------|-------|
| `insert_solar_panels` | `verify_insert_solar_panels` | Default Skelion settings |
| `insert_panels_portrait` | `verify_insert_panels_portrait` | Portrait orientation |
| `insert_panels_tilted` | `verify_insert_panels_tilted` | 30° tilt |
| `set_row_spacing` | `verify_set_row_spacing` | 2.0m inter-row spacing |
| `set_location` | `verify_set_location` | San Francisco lat/lon |

---

## Files

```
benchmarks/cua_world/environments/skelion_env/
  env.json
  scripts/
    install_sketchup_skelion.ps1   # pre_start: downloads + installs + ANGLE fix
    setup_sketchup_skelion.ps1     # post_start: first launch, dialog dismissal
    task_utils.ps1                 # shared helpers (Launch-SketchUpInteractive, etc.)
  tasks/
    insert_solar_panels/
      task.json
      setup_task.ps1
      verifier.py
    insert_panels_portrait/  (same structure)
    insert_panels_tilted/    (same structure)
    set_row_spacing/         (same structure)
    set_location/            (same structure)
  evidence_docs/
    Readme.md
    screenshots/
      01_workspace_with_skelion_toolbar.png
      02_clean_workspace_skelion_toolbar.png
      03_building_model_iso_view.png
      04_skelion_insert_dialog.png
```

---

## Key Lessons

1. CEF/ANGLE hangs on D3D11 in VirtIO VMs — always set `ANGLE_DEFAULT_PLATFORM=gl` for any app using CEF/Electron on Windows QEMU.
2. `schtasks /TR` quoting with spaces: use a `.bat` wrapper file to avoid the issue entirely.
3. Firewall `-RemoteAddress Internet` (not `Any`) preserves loopback IPC while blocking external license checks.
4. Registry keys for first-run suppression don't always work (Welcome screen still shows) — implement dialog clicking as backup.
5. Ruby `UI.start_timer` is reliable for post-load initialization, but requires adequate wait time (3s timer + SketchUp load time).
