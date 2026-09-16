> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Tcl/Tk Environment Notes

## Installation
- Packages: `tcl8.6 tk8.6 tcllib tklib` via apt-get
- Binaries: `/usr/bin/tclsh8.6` and `/usr/bin/wish8.6`
- Tcl version on Ubuntu 22.04: 8.6.12

## Key Findings

### Tk Demos Not in tk8.6 Package
On Ubuntu 22.04, the `tk8.6` package does NOT include the widget demos directory (`/usr/share/tk8.6/demos/` or `/usr/share/tcltk/tk8.6/demos/`). The demos would require a separate package or manual download. Workaround: embed the plot.tcl demo content directly in the setup script as a fallback.

### Terminal Selection
- `gnome-terminal` does NOT launch reliably in the QEMU VM via SSH hooks (no window appears, no error)
- `xterm` works reliably and is pre-installed in the `ubuntu-gnome-systemd_highres` base image
- Use `xterm -fa 'Monospace' -fs 12 -bg black -fg white` for readable text

### No First-Run Dialogs
Neither `tclsh` nor `wish` have any first-run wizard, EULA, or setup dialogs. They start cleanly every time. No dialog suppression needed.

### wish Window Behavior
- `wish` always creates a main window `.` on launch, even without a script
- Scripts that create `toplevel` windows appear as separate windows in wmctrl
- `wish -e 'after 2000 {destroy .}'` is a safe warm-up test

### Launching GUI from Hooks
Always use `setsid` and set both `DISPLAY=:1` and `XAUTHORITY=/home/ga/.Xauthority`:
```bash
setsid su - ga -c "DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority wish /path/to/script.tcl &"
```

## Data Sources
- Weather: NOAA 1991-2020 Climate Normals for Pittsburgh (KPIT)
- Periodic table: IUPAC 2021 Standard Atomic Weights (elements 1-36)
