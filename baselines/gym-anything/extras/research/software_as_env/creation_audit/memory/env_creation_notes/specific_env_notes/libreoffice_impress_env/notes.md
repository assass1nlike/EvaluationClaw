> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# LibreOffice Impress Environment Notes

## Installation Quirks

- Ubuntu 22.04 base image has pip3 that does NOT support `--break-system-packages`. Use fallback pattern: try without flag first, then with flag.
- LibreOffice 7.3.7 is the version available via apt on Ubuntu 22.04.
- `scrot` is NOT pre-installed in the base image - must be explicitly added to apt install list.

## Dialog Suppression (Critical)

LibreOffice 7.3 has FOUR startup dialogs that must be handled:

1. **Document Recovery** - Appears if LibreOffice was killed without graceful shutdown. Recovery entries are stored in `registrymodifications.xcu` under `/org.openoffice.Office.Recovery/RecoveryList`. Fix: remove these entries with Python after warm-up.

2. **Select a Template** - Appears when launching `libreoffice --impress` without a filename. Controlled by `StartWithTemplate` in config, but may still appear. Dismiss with Escape.

3. **Tip of the Day** - First-run dialog. Controlled by `ShowTipOfTheDay` in config. But the warm-up launch is needed to set the "seen" flag in the config.

4. **What's New Info Bar** - Yellow bar at top showing version info. Controlled by `mstone` setting. Warm-up launch sets this automatically. IMPORTANT: Do NOT re-copy the entire clean config after warm-up, or these flags are lost. Instead, only remove recovery entries.

## Warm-up Pattern

The correct two-layer suppression pattern for LibreOffice Impress:

```
1. Copy clean config (pre-warm-up)
2. Launch LibreOffice (warm-up)
3. Wait 15 seconds for it to fully load and process first-run
4. Dismiss dialogs with xdotool (Escape, Return)
5. Close gracefully (Ctrl+Q)
6. Wait and force-kill if needed
7. Remove ONLY recovery entries from config (keep the first-run flags)
8. Clean up temp/lock files
```

## Window Matching

- LibreOffice Impress window title in v7.3: `<filename> - LibreOffice Impress` or `Untitled 1 - LibreOffice Impress`
- The Start Center shows as `LibreOffice 7.3` (not "Impress")
- Use broad patterns for wmctrl: `Impress\|impress\|\.odp\|\.pptx\|LibreOffice`

## Process Detection

- Main process: `/usr/lib/libreoffice/program/soffice.bin --impress`
- Splash process: `/usr/lib/libreoffice/program/oosplash --impress`
- Use `pgrep -f soffice` for detection (matches both)

## Keyboard Shortcuts

- F11 in LibreOffice opens **Styles sidebar**, NOT fullscreen/maximize
- Use `wmctrl -r ... -b add,maximized_vert,maximized_horz` for maximize
- Ctrl+Q closes LibreOffice
- Ctrl+S saves the file
- Ctrl+H opens Find & Replace

## Data Format Notes

- ODP files (OpenDocument Presentation) are the native format
- odfpy library parses ODP structure (XML inside ZIP)
- python-pptx handles PPTX format
- Text content is in `draw:frame > draw:text-box > text:p` elements
- Shapes, connectors are `draw:custom-shape`, `draw:connector` elements

## Recovery File Locations

- Config: `~/.config/libreoffice/4/user/registrymodifications.xcu` (XML items with RecoveryList)
- Temp: `/tmp/lu*.tmp/` directories
- Lock files: `/tmp/.~lock.*`
- Backup: `~/.config/libreoffice/4/user/backup/`
