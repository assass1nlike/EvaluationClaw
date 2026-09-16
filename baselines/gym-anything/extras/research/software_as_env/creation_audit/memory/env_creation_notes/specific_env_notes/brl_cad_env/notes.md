> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# BRL-CAD Environment Notes

## Installation

### Pre-built Binary Approach (Recommended)
- BRL-CAD 7.32.2 pre-built Linux x86_64 binary is available from SourceForge
- Download URL: `https://sourceforge.net/projects/brlcad/files/BRL-CAD%20for%20Linux/7.32.2/BRL-CAD_7.32.2_Linux_x86_64.tar.bz2/download`
- Extracts to `/tmp/BRL-CAD_7.32.2_Linux_x86_64/` (directory name varies by version)
- Installs to `/usr/brlcad/` with binaries in `/usr/brlcad/bin/`
- No missing library issues on Ubuntu 22.04 (GNOME base image)
- Download is ~220MB, takes ~44 seconds

### Building from Source (Not Recommended for QEMU environments)
- Build time is 30-60+ minutes, exceeds pre_start hook timeout (1800s)
- Requires `cmake`, `build-essential`, X11 dev packages
- Must use `-DBRLCAD_BUNDLED_LIBS=ON -DBRLCAD_ENABLE_STRICT=NO`
- GCC 13/14 (Ubuntu 24.04) triggers strict warnings in bundled libs

### Archer GUI Does Not Work
- Archer (next-gen GUI) fails with `invalid command name "::hv3::formmanager"`
- This is a missing Tkhtml3 widget library issue in the pre-built binary
- Use MGED instead (fully functional)

## MGED Launch Requirements

### Critical: MGED Requires a TTY
- **MGED cannot be launched directly from SSH** - it needs a pseudo-terminal (TTY)
- Direct launch (`setsid mged file.g &`) starts and immediately exits with code 0
- **Solution**: Launch via `xterm -e "mged file.g"` - xterm provides the TTY
- The `xterm -iconic` flag starts it minimized so it doesn't clutter the screen

### MGED Opens Three Windows
1. **xterm** (MGED_Terminal) - The TTY host, can be minimized
2. **MGED Command Window** (Tk) - Shows output, has menu bar, has command entry at bottom
3. **MGED Graphics Window** (OpenGL) - 3D viewport for viewing geometry

### Typing Commands into MGED
- The xterm window IS the MGED terminal - typing here sends commands to MGED
- The Command Window also has a text entry at the very bottom (Tk widget)
- **However, xdotool typing is unreliable** for both windows
- **Best approach**: Use `.mgedrc` auto-init script (see below)

## The .mgedrc Auto-Init Pattern

MGED sources `~/.mgedrc` on startup. This is the most reliable way to pre-configure the viewport:

```bash
cat > /home/ga/.mgedrc << 'EOF'
after 2000 {
    catch {e all.g}
    catch {ae 35 25}
    catch {autoview}
}
EOF
```

- `after 2000` delays execution by 2 seconds (allows MGED to fully initialize)
- `catch {}` prevents errors from stopping execution
- Each task's `setup_task.sh` writes task-specific commands to `.mgedrc` before launching MGED

## Sample .g Database Files

BRL-CAD ships with official sample databases in `/usr/brlcad/share/db/`:

| File | Size | Description | Top-level objects |
|------|------|-------------|-------------------|
| moss.g | 2,120 bytes | Classic benchmark scene | `all.g/` |
| m35.g | 300,992 bytes | M35 military truck | (multiple) |
| havoc.g | 588,976 bytes | AH-64 Apache helicopter | `havoc/`, `BRL-GSI_EFFORT/`, `sun/R` |
| ktank.g | 30,448 bytes | Tank model | (multiple) |
| star.g | 28,528 bytes | Star scene benchmark | (multiple) |
| bldg391.g | 68,960 bytes | Building 391 | (multiple) |

These are real models from the US Army Research Laboratory, not synthetic/toy data.

## Window Positioning

MGED windows need explicit positioning since they default to arbitrary positions:

```bash
# Minimize xterm
xdotool search --name MGED_Terminal windowminimize

# Remove maximized state (required before resize)
wmctrl -r "Command Window" -b remove,maximized_vert,maximized_horz
wmctrl -r "Graphics Window" -b remove,maximized_vert,maximized_horz

# Position side-by-side
wmctrl -r "Command Window" -e 0,0,0,960,1080
wmctrl -r "Graphics Window" -e 0,960,0,960,1080
```

Note: Window titles include version: "MGED 7.32.2 Command Window (id_0)". The `wmctrl -r` matches partial window titles.

## Launcher Script

A launcher script at `/usr/local/bin/launch_mged.sh` is created during setup to handle:
- Setting correct PATH and LD_LIBRARY_PATH
- Setting DISPLAY and XAUTHORITY
- Launching via xterm with the correct geometry

This avoids PATH pollution from SSH environment inheritance (the SSH session inherits the host's massive PATH which causes issues with `su - ga`).

## Performance Notes

- Environment setup: ~130s (mostly download + extraction)
- Task setup: ~13s (MGED launch + geometry draw + window positioning)
- MGED startup: ~3-5s until windows appear
- Geometry draw: ~2-3s for moss.g, ~3-5s for havoc.g (complex model)
