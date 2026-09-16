> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# PyMOL Environment Notes

## Installation

### Method
PyMOL installs cleanly via `apt-get install -y pymol python3-pymol python3-pyqt5 python3-pyqt5.qtopengl` on the Ubuntu GNOME base image. No need for Schrodinger's binary distribution or conda. The open-source version (2.5.0) is sufficient for all tasks.

### Dependencies
- Qt5/PyQt5 for the GUI: `python3-pyqt5`, `python3-pyqt5.qtopengl`
- Mesa/OpenGL: `libgl1-mesa-glx`, `libgl1-mesa-dri`, `mesa-utils`
- BioPython for PDB manipulation: `pip3 install biopython`
- GUI automation: `xdotool`, `wmctrl`, `scrot`

### Data Sources
All PDB structures are real data from the RCSB Protein Data Bank (https://files.rcsb.org/download/). Only structures used by tasks are downloaded:
- **4HHB.pdb** - Human hemoglobin (474KB, 4 chains A/B/C/D) — used by color_protein_by_chain task
- **1UBQ.pdb** - Ubiquitin (79KB, single chain, 76 residues) — used by measure_atomic_distance task
- **1CRN.pdb** - Crambin (49KB, smallest common test protein, 46 residues) — used by ray_trace_protein_image task

## Application-Specific Quirks

### PyMOL Command Line Input
- PyMOL's command line at the bottom of the viewer captures keyboard input when the window is focused
- No need to click on the command line explicitly - just type when PyMOL window has focus
- Commands are entered by typing and pressing Enter
- The `PyMOL>` prompt is visible in the upper text output area (not the main viewer)
- For setup scripts that need to pre-run commands (e.g. `show cartoon`), use `.pml` script files passed to PyMOL at launch rather than fragile `xdotool type` — the `.pml` approach is deterministic and doesn't depend on window focus state

### PDB Atom Selection Syntax
- PyMOL uses backtick for residue numbering: `/1UBQ//A/MET\`1/CA`
- The backtick character must be properly escaped in shell scripts

### Ubiquitin (1UBQ) Terminal Distance
- The CA distance between MET1 and GLY76 in ubiquitin is ~3.71 Angstroms (NOT 26-30 as initially estimated)
- Ubiquitin has a compact beta-grasp fold where N and C termini are very close in 3D space
- This is correct PDB structure behavior, not an error

### Ray Tracing Performance
- `ray 1920, 1080` takes approximately 10-15 seconds for small proteins like crambin (1CRN)
- Larger proteins (4HHB hemoglobin) may take 30-60 seconds for ray tracing
- Software rendering only (no GPU needed for open-source PyMOL)

### First-Run Behavior
- PyMOL 2.5.0 open-source has minimal first-run dialogs
- The `.pymolrc` config file is loaded on startup and applies settings
- A warm-up launch in `post_start` ensures clean subsequent launches

### Window Detection
- PyMOL window is detected via `wmctrl -l | grep -i pymol`
- Window title includes "PyMOL" making detection straightforward
- The `-q` flag (quiet mode) suppresses the startup splash screen

## Verification Approach
All tasks use stub verifiers. Real verification is done externally via VLM evaluators that analyze the final screenshot. Key verification signals:
- **Task 1**: Cartoon representation visible + distinct colors on 4 chains
- **Task 2**: Distance measurement dashed line and label visible on structure
- **Task 3**: Output PNG file exists at expected path + ray-traced quality visible in screenshot
