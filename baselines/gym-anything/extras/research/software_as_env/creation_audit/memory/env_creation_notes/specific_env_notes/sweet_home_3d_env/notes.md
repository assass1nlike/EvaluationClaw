> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Sweet Home 3D Environment Notes

## Installation

### Method
- **Official Linux 64-bit tarball** from SourceForge: `SweetHome3D-7.5-linux-x64.tgz` (~72 MB)
- Bundles its own JRE — no external Java installation needed
- Extracted to `/opt/SweetHome3D/`
- Symlinked to `/usr/local/bin/SweetHome3D`

### Launcher Script Gotcha
The launcher script `/opt/SweetHome3D/SweetHome3D` already includes `-open "$1"` at the end:
```bash
exec "$PROGRAM_DIR"/runtime/bin/java ... com.eteks.sweethome3d.SweetHome3D -open "$1"
```
**Do NOT pass `-open` yourself** — just pass the file path as the first argument:
```bash
/opt/SweetHome3D/SweetHome3D /path/to/file.sh3d   # CORRECT
/opt/SweetHome3D/SweetHome3D -open /path/to/file.sh3d  # WRONG — results in -open -open
```

## Window Detection

### Java Window Names
Sweet Home 3D (Java Swing) has non-standard window naming:
- **Splash screen**: Window class = `com-eteks-sweethome3d-SweetHome3D`
- **Main window**: Title = `filename.sh3d - Sweet Home 3D`
- **Java class name**: `com-eteks-sweethome3d-SweetHome3D`

### Detection Strategy
Use class-based detection, NOT name-based:
```bash
# BEST: Search by class name
xdotool search --class "sweethome3d"

# FALLBACK: Search by Java class name pattern
xdotool search --name "com-eteks-sweethome3d"

# ALSO WORKS (after file is loaded): Search by partial name
xdotool search --name "Sweet Home"
```

**Do NOT use**: `xdotool search --name "Sweet Home 3D"` — this may not match during splash screen phase.

## VNC Configuration

**CRITICAL**: Must include VNC password in env.json:
```json
"vnc": {
    "password": "password"
}
```
Without this, the VNCSpec defaults to `password: None`, causing the VNC connection to fail with "VNC password required but not provided".

## Preferences / First-Run Behavior

Sweet Home 3D stores preferences via Java Preferences API:
- Location: `~/.java/.userPrefs/com/eteks/sweethome3d/prefs.xml`
- Key settings:
  - `updateCheckDate`: Set to far future to suppress update checks
  - `showTipsAtStartup`: Set to `false` to skip tip dialog

A warm-up launch during post_start ensures all first-run initialization is complete.

## Real Data Files (.sh3d format)

- `.sh3d` files are ZIP archives containing serialized Java objects + embedded 3D models/textures
- Official gallery at: https://www.sweethome3d.com/gallery/
- Download URL pattern: `https://www.sweethome3d.com/benchmarks/cua_world/environments/<filename>.sh3d`
- Files are self-contained and portable across systems

### Available samples used:
| File | Size | Description |
|------|------|-------------|
| userGuideExample.sh3d | 2.3 MB | Basic apartment from user guide |
| SweetHome3DExample.sh3d | 1.8 MB | Basic apartment |
| SweetHome3DExample7.sh3d | 7.0 MB | Contemporary villa |

## Timing

- Pre-start (install): ~69s (download SH3D tarball + sample files + apt-get)
- Post-start (setup): ~3s (copy files, configure preferences, warm-up launch + kill)
- Pre-task (task setup): ~23s (kill old instance, launch with file, wait for window, maximize)
- Total reset time: ~92s (without caching)

## Key Observations

1. Sweet Home 3D takes 2-3 seconds to show window, but 10+ seconds to fully render 3D view
2. The furniture catalog tree is always visible in the left panel
3. The search box for furniture may not be visible by default in some views
4. Furniture can be added by double-clicking in the catalog or dragging to the plan
5. The 3D view menu provides "Create photo..." for photorealistic rendering
6. Java X11 libraries (libxrender1, libxtst6, etc.) are needed for GUI
