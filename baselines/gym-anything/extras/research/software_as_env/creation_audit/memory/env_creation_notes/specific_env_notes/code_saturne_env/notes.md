> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Code_Saturne Environment Notes

## Installation

- Installed via `apt-get install code-saturne` (version 6.0.2-2build1 on Ubuntu 22.04)
- Also needs `python3-pyqt5` for the GUI
- GUI binary is at `/usr/bin/code_saturne` — run with `code_saturne gui setup.xml`

## Key Learnings

### Case Directory Name is CASE1 (uppercase)
The `code_saturne create -s StudyName` command creates the case directory as **CASE1** (uppercase), not `case1` (lowercase). The task setup scripts must auto-detect this.

### code_saturne create Permission Issues
The `code_saturne create` command must be run as the `ga` user (not root). It creates the study directory as a subdirectory of the current working directory. When running as `su - ga`, ensure the CWD is writable by `ga`. Best approach: use a temp directory, then `mv`.

### GUI Tree Navigation
The Code_Saturne GUI tree structure (version 6.0):
```
Calculation environment
├── Mesh
│   └── Preprocessing
├── Calculation features
│   ├── Turbulence models
│   ├── Thermal model
│   ├── Body forces
│   ├── Conjugate heat transfer
│   └── Species transport
├── Fluid properties
├── Volume zones
│   └── Initialization
├── Boundary zones
│   └── Boundary conditions
├── Time settings
├── Numerical parameters
├── Postprocessing
└── Performance settings
```

### Boundary Conditions UI
- Click "Boundary conditions" (child of "Boundary zones") in the tree
- A table shows all boundary zones (Inlet, Outlet, Wall)
- Click on a row (e.g., Inlet) to reveal detail settings **below the table**
- Detail sections: Velocity (norm + direction), Turbulence, Thermal

### Turbulence Model Dropdown
Available models in Code_Saturne 6.0:
- No model (laminar flow)
- Mixing length
- k-epsilon
- k-epsilon Linear Production (default in tutorial)
- k-epsilon LRR
- k-epsilon SSG
- k-epsilon EBRSM
- v2f BL-v2/k
- k-omega SST
- Spalart-Allmaras
- LES (Smagorinsky, classical dynamic, WALE)

### GUI Window Title Format
The GUI window title is: `CASE1 : setup.xml - Code_Saturne`

### No First-Run Dialogs
Code_Saturne GUI has no first-run wizard or dialog. No warmup launch needed.

### Real Data
Tutorial data from https://github.com/code-saturne/saturne-tutorials:
- `01_Simple_Junction/MESH/downcomer.med` — T-junction pipe mesh
- `01_Simple_Junction/case1/DATA/setup.xml` — Full simulation configuration
- `01_Simple_Junction/case1/DATA/run.cfg` — Run resource configuration

### setsid Required
Use `setsid` when launching the GUI to prevent it from being killed when the SSH session ends.

### pkill Pattern
Kill the GUI with: `pkill -9 -f "code_saturne gui"`
Do NOT use just `pkill -9 code_saturne` as it may kill other code_saturne processes.
