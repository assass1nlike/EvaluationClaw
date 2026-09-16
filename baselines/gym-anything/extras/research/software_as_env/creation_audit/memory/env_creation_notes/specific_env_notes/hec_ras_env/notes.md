> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# HEC-RAS Environment Notes

## Architecture
- HEC-RAS 6.6 Linux compute engines (CLI only, no GUI on Linux)
- GUI interaction via: gedit (text editor), gnome-terminal, matplotlib
- Tasks involve editing HEC-RAS input files, running simulations, analyzing results

## Installation
- **Download URL**: `https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v66.zip` (213 MB)
- **Extracted structure**: `Linux_RAS_v66/bin/` (executables), `Linux_RAS_v66/libs/` (Intel Fortran + MKL), `Linux_RAS_v66/Muncie/` (example)
- **CRITICAL**: Libraries at `Linux_RAS_v66/libs/` NOT `lib/` - must search for correct path
- **CRITICAL**: Must install `dbus-x11` for gnome-terminal to work from `su - ga -c` hooks
- **Dependencies**: libgomp1, libgfortran5, python3, h5py, matplotlib, numpy, pandas, rashdf

## HEC-RAS Linux Command Syntax (IMPORTANT)
The command syntax is NOT what most tutorials show:
- `RasUnsteady Muncie.p04.tmp.hdf x04` (HDF file + geometry extension, NOT `.c04 b04`)
- `RasSteady Muncie.r04` (steady flow input file)
- `RasGeomPreprocess Muncie.p04.tmp.hdf x04`
- After unsteady run: `mv Muncie.p04.tmp.hdf Muncie.p04.hdf` (rename output)

## Library Paths
```
export LD_LIBRARY_PATH=/opt/hec-ras/lib:/opt/hec-ras/lib/mkl:/opt/hec-ras/lib/rhel_8:$LD_LIBRARY_PATH
```
Required libraries: libiomp5.so, libifport.so.5, libmkl_intel_thread.so.1, libmkl_core.so.1, libmkl_intel_lp64.so.1

## Muncie Example Project
- **Real data**: Official USACE flood model for Muncie, Indiana (White River)
- **Files**: Muncie.x04 (geometry, 1758 lines), Muncie.b04 (boundary conditions, 103 lines), Muncie.r04 (steady flow, 10582 lines), Muncie.p04.tmp.hdf (template HDF)
- **wrk_source/**: Contains input files that need to be copied to working directory
- **Simulation**: 2D unsteady flow, 5765 cells, 289 timesteps, ~60 sec runtime

## File Formats
### Geometry (.x04)
- "Section - XS Manning's/Roughness Data" marks each cross section's roughness
- Format: `N_ZONES  F  F  0\n  0  .07  250.23  .04  401.13  .07`
- Three zones: left overbank (0.07), main channel (0.04), right overbank (0.07)

### Boundary Conditions (.b04)
- "Upstream Flow Hydrograph" section contains time-flow pairs
- Format: `TIME  FLOW  TIME  FLOW  ...` (5 pairs per line)
- Peak flow: 21000 cfs at hours 15-20

### HDF5 Results (.p04.hdf)
- Path: `Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/2D Interior Area/Water Surface`
- Shape: (289 timesteps, 5765 cells)
- Peak WSE: 953.840 ft, Mean Peak: 946.104 ft

## Known Issues
1. **gnome-terminal D-Bus**: Needs `dbus-x11` package; use `dbus-launch` in `su - ga -c` commands
2. **1D Cross Sections in HDF5**: The cross section path contains structured arrays, not simple groups - wrap in try/except for `TypeError`
3. **matplotlib backend**: Use conditional backend (`TkAgg` with display, `Agg` without)
4. **Cell selection for hydrograph**: Don't pick cell with highest peak WSE (may be boundary cell with constant value); pick cell with highest WSE range instead
5. **Simulation pre-run for analysis tasks**: Tasks 3 (analyze_peak_wse) and 5 (plot_flood_hydrograph) expect `Muncie.p04.hdf` (simulation results). The `setup_task.sh` must call `run_simulation_if_needed` (~30s) to produce results from template. Without this, only `Muncie.p04.tmp.hdf` exists.
6. **Task description prescriptiveness**: Do NOT give exact commands in task descriptions — the agent should discover executables, scripts, and arguments. Task descriptions should describe the goal, not the solution.
7. **Manning's n Find/Replace risk**: The value `.04` appears in many non-Manning's contexts (geometry coordinates). Task description must NOT suggest Ctrl+H find/replace of `.04` — agent must understand the section structure and edit the correct line.
8. **Distinct terminal start states**: Terminal-based tasks (2, 3, 5) use `type_in_terminal` to auto-display file listings that differ per task, making screenshots visually distinguishable.
