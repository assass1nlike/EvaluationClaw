> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Activity Browser Environment - Creation Notes

## Application Details

- **Activity Browser**: Open-source GUI for Brightway2 LCA framework
- **Version**: v2 stable (conda-forge)
- **Technology**: Python + PySide2 (Qt) + Brightway2
- **Data store**: SQLite-based, per-user at `~/.local/share/Brightway3/`

## Installation Quirks

### Miniconda already in base image
The `ubuntu-gnome-systemd_highres` base image already has miniconda3 installed at `/opt/miniconda3`. The install script must check for this and skip the download.

### Conda ToS issue
Newer conda versions require accepting Terms of Service for default channels. Fix: use `--override-channels -c conda-forge` when creating the environment, and configure conda to remove default channels:
```bash
conda config --remove channels defaults
conda config --add channels conda-forge
```

### lxml/libxslt shared library conflict
The conda env's lxml links against the conda env's `libxml2`/`libxslt`, but the system's `libxslt.so.1` gets loaded instead, causing `undefined symbol: xmlCtxtParseDocument`. Fix: set `LD_LIBRARY_PATH="/opt/miniconda3/envs/ab/lib:$LD_LIBRARY_PATH"` in the launcher script. Also `conda install -n ab libxml2 libxslt lxml` helps ensure compatible versions.

### Brightway3 directory permissions
The base image has `/home/ga/.local/share/Brightway3/` and `/home/ga/.cache/Brightway3/` directories created by root. Fix: `chown -R ga:ga /home/ga/.local /home/ga/.cache` in the post_start hook before running any Brightway2 Python commands as the ga user.

## Data Setup

### Project naming
Activity Browser opens the last-used project on startup. The "default" project is created automatically on first run. Using the "default" project name ensures the AB opens with our data without needing to configure startup project settings. Do NOT create a separate project name.

### Database creation with Brightway2 API
Use `db.write(data)` to create a database with all activities at once. Do NOT use `db.new_activity().save()` as it fails with "database refers to unknown database" if the database is not yet registered. The `db.write()` method handles registration automatically.

### biosphere3 pre-existence
The base image already has biosphere3 and LCIA methods installed in the default project. The setup script checks for this and skips `bw2setup()` if already present.

## UI and Interaction Notes

### Window detection
Activity Browser window title is "Activity Browser - {project_name}". Detect with:
```bash
wmctrl -l | grep -i "activity.browser"
```

### Startup time
- Cold start (first launch): ~5s for window to appear
- The app is a Qt application, not Electron, so it's relatively fast

### Project dropdown
The project dropdown in the left panel is a Qt QComboBox. Direct xdotool clicks at its coordinates may not reliably open it. For programmatic project switching, use the Brightway2 Python API before launching the app.

### First-run behavior
No significant first-run wizard. The Welcome tab shows on every launch. The "Set up your project with default data" button appears when a project has no databases.

### Environment variables needed for launch
```bash
export DISPLAY=:1
export QT_QPA_PLATFORM=xcb
export LIBGL_ALWAYS_SOFTWARE=1
export LD_LIBRARY_PATH="/opt/miniconda3/envs/ab/lib:$LD_LIBRARY_PATH"
export XDG_RUNTIME_DIR="/tmp/runtime-$(whoami)"
```

## Timing

| Phase | Duration |
|-------|----------|
| pre_start (install) | ~120s (conda env creation is the bottleneck) |
| post_start (setup) | ~80s (data setup + warm-up launch) |
| pre_task | ~20s (launch app + wait for window) |
| **Total** | ~225s |

## Task Design Notes

### Available data for tasks
- 10 activities in Energy_and_Materials (energy + industrial processes)
- 4,709 biosphere flows in biosphere3
- 762 LCIA methods (IPCC, ReCiPe, CML, etc.)
- Activities have inter-linked supply chains (e.g., steel -> grid_mix -> coal/gas/wind/solar)

### Recommended tasks
1. LCA calculation (medium): Select activity + method, calculate
2. Supply chain exploration (medium): Use Graph Explorer on steel/aluminium
3. Activity creation (hard): Create new database + activity + exchanges
