> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# QBlade Environment Creation Notes

## Application Details
- **QBlade v0.96.2** (Community Edition, 64-bit Linux)
- Wind turbine blade design and BEM (Blade Element Momentum) simulation
- Qt5-based GUI application with OpenGL visualization
- Download: SourceForge `QBlade_linux_v0.96.2_64bit.zip`

## Installation Challenges

### 1. Bundled Library Conflicts
QBlade v0.96.2 bundles several shared libraries that conflict with the system:

- **libstdc++.so.6.0.20** (from GCC 4.x): This is too old for modern Qt5, missing CXXABI_1.3.9. **Must be deleted** so the system libstdc++ is used instead.
- **libQGLViewer.so.2.6.0**: Bundled but with wrong permissions (`-rwxr-x--x`). Needs `chmod 755` and should also be copied to `/usr/local/lib/` with proper symlinks for reliable resolution.
- **libgomp.so.1.0.0**: Bundled, works fine.

### 2. Qt5 Dependencies
Must explicitly install Qt5 runtime packages:
```bash
apt-get install -y libqt5opengl5 libqt5widgets5 libqt5xml5 libqt5gui5 libqt5core5a
```

### 3. Directory Name with Spaces
The zip extracts to "QBlade 64bit release linux/" - all scripts must properly quote paths.

### 4. File Format
QBlade v0.96 uses `.wpa` for project files (not `.qpr` which is used in newer versions). The bundled sample projects:
- NREL_5MW.wpa (746KB)
- NREL_PhaseVI.wpa (605KB)
- SANDIA_SERI-8.wpa (399KB)
- TUB_BeRTwpa.wpa (1.2MB)

Sample projects are in a directory called "sample projects" (lowercase, with space), not "SampleProjects".

### 5. Launch Command Pattern
When launching via `su - ga -c`, environment variables must use `export` with semicolons:
```bash
# CORRECT:
su - ga -c "export DISPLAY=:1; export LD_LIBRARY_PATH='$DIR'; cd '$DIR' && '$BIN' &"

# WRONG (vars treated as command prefix, not inherited by subcommands):
su - ga -c "DISPLAY=:1 LD_LIBRARY_PATH='$DIR' cd '$DIR' && '$BIN' &"
```

## Data Sources
- **Airfoil coordinates**: UIUC Airfoil Coordinates Database (https://m-selig.ae.illinois.edu/ads/coord_database.html)
- **Sample projects**: Bundled with QBlade installation (NREL reference turbines)

## Task Design Notes
- Tasks progress from simple (generate airfoil) to complex (BEM simulation)
- Each task has independent verification via export_result.sh -> verifier.py
- All verifiers use `copy_from_env` pattern to read `/tmp/task_result.json`
- QBlade is launched by setup_task.sh; export_result.sh checks both expected output files and QBlade running state
- Partial credit is given for QBlade running even if expected output file isn't found

## Interactive Testing Notes (ask_cua.py + xdotool)

### QBlade Window Geometry
- Window ID: 8388624 (consistent across runs)
- Client area position: (491, 279) on 1920x1080 display
- Client area size: 1027x505
- Window-relative coordinates work with `xdotool mousemove --window 8388624 X Y`

### Toolbar Icon Mapping (window-relative, y=48)
Discovered via systematic hover + status bar reading:
- x=215: "Change the MainToolBar to HAWT Mode"
- x=265: "Change the MainToolBar to VAWT Mode"
- **x=340: "Open Foil Design application"** (the Airfoil Design Module)
- x=390: "Open XFoil direct analysis application"
- x=440: "Extrapolate an XFOII Polar to 360 AoA"
- x=490: "Predict the noise generation"

### Menu Navigation
- Menu bar items at window y=9: File(20), View(57), Foil(98), Splines(144), Options(199)
- Foil menu has ~20 items; keyboard Down arrow navigation is most reliable
- "Naca Foils" is 20th item from top (after "Generate a Circular Foil")
- "Export..." is 4th item from top

### NACA Foils Dialog
- "4 or 5 digits" field and "Number of Panels" field
- CUA coordinates (1280x720 -> 1920x1080): digits(822,381), panels(822,431), OK(714,489)
- 100 panels produces 100-line .dat file (1 header + 99 data points)

### Key Learnings
1. **Toolbar icon scanning**: Hover over icons and read status bar (crop bottom 30px) - faster than visual inspection
2. **Keyboard menu navigation**: More reliable than clicking menu items at exact coordinates
3. **Qt file dialogs**: Can type full path in the filename field (e.g., `/home/ga/Documents/airfoils/file.dat`)
4. **Single-script approach**: Keep env object alive in same Python process for reliable verification - SSH connections drop if env object goes out of scope

## Testing Results
- Environment startup: ~62-67s total (52-58s install + 9s task hooks)
- QBlade launches reliably with fixed library setup
- All 5 tasks' verification pipelines tested successfully
- Verifiers correctly return score=0 when no agent work done
- **generate_naca_airfoil**: Score 100/100, reward=1.0 (interactive completion verified)
