> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Stellarium Environment Notes

## Critical: LandscapeMgr NULL Pointer Crash

Stellarium crashes with a segfault at `LandscapeMgr::setFlagLandscape(bool)` during initialization when running with a pre-written `config.ini` that sets `first_time_run = false`.

**Root cause**: The `config.ini` must include `[init_location] landscape_name = guereins`. Without this key, `LandscapeMgr::init()` reads an empty string for `defaultLandscapeID`, calls `setCurrentLandscapeID("")` which returns early (empty ID check), leaving the `landscape` pointer as NULL. The subsequent `setFlagLandscape()` call dereferences NULL at offset 0x48, causing a segfault.

This happens because normally Stellarium's first-run wizard sets `init_location/landscape_name`. When we skip the wizard via `first_time_run = false`, this key is never written.

**Fix**: Always include in config.ini:
```ini
[init_location]
landscape_name = guereins
location = Pittsburgh, Pennsylvania, United States
```

## Software Rendering with Mesa llvmpipe

Stellarium requires OpenGL. In QEMU VMs without GPU, Mesa's llvmpipe software renderer provides OpenGL 4.5 (Compatibility Profile), which exceeds Stellarium's minimum requirement of OpenGL 2.1.

**Required packages** (same pattern as PsychoPy environment):
```
libgl1-mesa-glx libgl1-mesa-dri mesa-utils libglu1-mesa libosmesa6 libegl1-mesa
```

**Required environment variables** for the launch script:
```bash
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export MESA_GL_VERSION_OVERRIDE=4.5COMPAT
export MESA_GLSL_VERSION_OVERRIDE=450
```

Setting `LIBGL_ALWAYS_SOFTWARE=1` globally in `/etc/environment` ensures the GNOME desktop also uses llvmpipe.

## Stellarium Version Choice

- **Ubuntu 22.04 universe repo** provides Stellarium 0.20.4 (Qt5-based). This works reliably.
- **PPA version** (25.x, Qt6-based) also crashes at the same LandscapeMgr bug and has stricter OpenGL requirements.
- **AppImage versions** (0.22.2 Qt5, 24.4 Qt6) work but introduce DSO catalog version mismatches if the apt `stellarium-data` package is also installed. The AppImage approach is more complex and not needed.

**Recommendation**: Use the apt universe version (0.20.4).

## Performance

With llvmpipe on 4 CPU cores:
- Stellarium renders at ~20-40 FPS (varies with scene complexity)
- CPU usage: ~200-300% (multi-threaded software rendering)
- Memory usage: ~400MB
- Initial load time: ~30s (loading star catalogs, DSO data)

## Process Management

- Use `pkill stellarium` (not `pkill -f "/usr/bin/stellarium"`) to kill Stellarium. The process name in `ps` is just `stellarium` without the full path.
- Use `pgrep -x "stellarium"` for exact process name matching.
- The `setsid` wrapper is required when launching from SSH (cross-cutting pattern #18).

## Keyboard Shortcuts (Verified Working)

| Key | Function |
|-----|----------|
| a | Toggle atmosphere |
| g | Toggle ground/landscape |
| c | Toggle constellation lines |
| v | Toggle constellation names |
| e | Toggle equatorial grid |
| Ctrl+F | Open search dialog |
| F5 | Date/Time dialog |
| F6 | Location dialog |
| F4 | Sky/Viewing options |
| Page Up/Down | Zoom in/out |

## Config.ini Key Settings

```ini
[main]
version = 0.20.4
first_time_run = false
flag_show_splash = false

[video]
fullscreen = false
screen_w = 1280
screen_h = 720

[init_location]
landscape_name = guereins  # CRITICAL: prevents NULL pointer crash
```

## Real Data

All data files use real astronomical databases:
- **Messier catalog**: 33 objects from NASA/IPAC NED and SIMBAD
- **Historical eclipses**: NASA Eclipse Database (5 total solar eclipses 2017-2026)
- **Observatory locations**: IAU Minor Planet Center observatory codes (12 major observatories)
