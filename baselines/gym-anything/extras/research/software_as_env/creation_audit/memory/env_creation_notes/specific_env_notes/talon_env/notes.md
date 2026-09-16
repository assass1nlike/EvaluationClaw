> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Talon Voice Environment Notes

## Overview
- **Application**: Talon Voice (hands-free voice control & eye-tracking)
- **OS**: Windows 11
- **Base image**: windows-11
- **Resources**: 4 CPU, 8GB RAM, no GPU
- **Resolution**: 1280x720

## Installation
- **Talon**: EXE installer from `talonvoice.com/dl/latest/talon-windows.exe` (~35.6 MB)
  - Silent install: `/S` flag, installs to `C:\Program Files\Talon\talon.exe`
  - **CRITICAL**: Do NOT use the portable ZIP (`talon-windows.zip`) - it uses a content-addressable archive format that PowerShell's `Expand-Archive` cannot handle (extracts to hash-named dirs like `06/`, `22/`, `6d/`)
- **Community commands**: GitHub ZIP from `talonhub/community` main branch
  - Extracts to `C:\Users\Docker\AppData\Roaming\Talon\user\community\`
  - Contains ~218 .talon files, ~261 .py files, ~85 .talon-list files
- **Notepad++**: v8.7.1 for .talon file editing, silent install `/S`

## First-Run Dialogs

### Notepad++ "Update Available" Dialog
- Shows on first launch with "Update", "Next time", "Never" buttons
- **"Never" button coordinates**: (784, 396) at 1280x720
- **Fix**: Warm-up launch via schtasks, click "Never", close gracefully with Alt+F4 so N++ saves config.xml with `noUpdate="yes"`
- Post-warmup config.xml patching as safety net (replace `noUpdate="no"` with `noUpdate="yes"`)
- Note: On first warm-up, config.xml may not have the `noUpdate` attribute yet (warning is expected), but clicking "Never" creates it

### Talon First-Run Sequence
1. **EULA Dialog**: "I Accept" button position VARIES between boots
   - **CRITICAL**: Click at MULTIPLE positions: (627,433), (648,458), (700,511), (717,552)
   - The EULA window is positioned randomly by Windows
   - EULA acceptance state does NOT persist across savevm restore
2. **Community Welcome Message**: imgui overlay from `plugin/new_user_message/`
   - **CRITICAL**: Cannot be dismissed via PyAutoGUI clicks (imgui renders on top of all windows)
   - **Fix**: Create empty file `plugin/new_user_message/new_user_message_dismissed` before launching Talon
   - The `user.help_message_show` setting does NOT exist - it was a wrong assumption
3. **Audio Error Notification**: X button at (1242, 572) - VM has no audio device

### Key Lessons for Dialog Handling
- EULA and community welcome are SEPARATE dialogs with different dismissal mechanisms
- The `new_user_message_dismissed` file persists across savevm restore (written to VM disk)
- The EULA acceptance does NOT persist across savevm restore (stored in memory/registry that resets)
- For pre_task scripts that launch Talon, ALWAYS include EULA dismiss clicks at multiple positions
- Use `Win+D` hotkey after dialog dismissal to ensure clean desktop

## Key Paths
- Talon exe: `C:\Program Files\Talon\talon.exe`
- Talon user dir: `C:\Users\Docker\AppData\Roaming\Talon\user\`
- Community commands: `C:\Users\Docker\AppData\Roaming\Talon\user\community\`
- Notepad++: `C:\Program Files\Notepad++\notepad++.exe`
- Tasks dir: `C:\Users\Docker\Desktop\TalonTasks\`
- Notepad++ config: `C:\Users\Docker\AppData\Roaming\Notepad++\config.xml`
- Welcome dismissal file: `community\plugin\new_user_message\new_user_message_dismissed`

## Talon Concepts
- `.talon` files: voice command definitions (context header + command rules)
- `.py` files: Python actions/modules that commands can call
- `.talon-list` files: named lists of items (e.g., phonetic alphabet)
- Context headers: `os: windows` / `app.name: Notepad` etc.
- Commands format: `voice pattern: action(args)`
- Talon runs as system tray app (no main window)

## Tasks (5 total)
1. **create_voice_command** (easy): Create custom .talon file with 3 voice commands
2. **edit_alphabet_list** (easy): Change phonetic alphabet entries in .talon-list
3. **configure_settings** (medium): Modify settings.talon (imgui.scale, speech.timeout, command_history_display)
4. **add_app_commands** (medium): Add app-specific Notepad commands to notepad.talon
5. **browse_help_menu** (medium): Navigate Talon tray menu to open user config directory

## Boot Times
- Pre-start (install): ~60s (download Talon + community + Notepad++)
- Post-start (setup + warm-up): ~50s
- Pre-task: ~10-40s (browse_help_menu ~40s due to Talon launch + dialog dismissal)
- Total first boot: ~120-150s

## Testing Notes
- Use `use_savevm=True` for faster subsequent boots
- VNC screenshots: `vncdotool.api.connect("localhost::port", password="password")` then `captureScreen(path)`
- SSH: paramiko to port `env._runner.ssh_port`, user `Docker` / `GymAnything123!`
- PyAutoGUI server on port 5555 for GUI automation
- Direct TCP to PyAutoGUI from host works better than SSH-piped commands for typing
- `$Host` is a reserved PowerShell variable - use `$ServerHost` for TCP client host parameter
