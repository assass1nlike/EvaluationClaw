> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# System Advisor Model (SAM) Environment - Setup Notes

## Architecture

This environment uses **PySAM** (NREL's Python SDK for SAM) as the primary interaction method, with the SAM desktop application available for screenshot evidence. PySAM provides programmatic access to all SAM models and avoids the registration dialog that blocks the GUI on first launch.

## Installation

### SAM Desktop
- Version: 2024-12-12
- URL: `https://samrepo.nrelcloud.org/beta-releases/sam-linux-2024-12-12.run`
- Install: Self-extracting `.run` installer to `/opt/SAM/2024.12.12/`
- Binary: `/opt/SAM/2024.12.12/linux_64/sam.bin` (wrapper: `/opt/SAM/2024.12.12/SAM`)
- SDKtool: `/opt/SAM/2024.12.12/linux_64/SDKtool`
- **CRITICAL**: SAM desktop needs `LD_LIBRARY_PATH` set to find `ssc.so`
- **CRITICAL**: SAM GUI shows a Registration Dialog on first launch. Both `install_sam.sh` and `setup_sam.sh` kill SAM processes to prevent this.

### PySAM
- Install: `pip3 install NREL-PySAM --break-system-packages`
- Version tested: 7.1.0
- Key module: `PySAM.Pvwattsv8` for PVWatts V8 simulations
- Default model: `pv.default("PVWattsNone")` - creates empty model
- **NOTE**: `default("PVWattsNone")` sets default system_capacity to 100000 kW (100 MW)

### Dependencies
- GTK3 libraries for SAM GUI
- `jq` for JSON parsing in export scripts
- `imagemagick` for screenshots (use `import -window root`, NOT `scrot`)
- `python3-pip` for PySAM installation

## Weather Data

### Bundled TMY Files (in SAM installation)
Located at `/opt/SAM/2024.12.12/solar_resource/`:
- `phoenix_az_33.450495_-111.983688_psmv3_60_tmy.csv`
- `tucson_az_32.116521_-110.933042_psmv3_60_tmy.csv`
- `daggett_ca_34.865371_-116.783023_psmv3_60_tmy.csv`
- `blythe_ca_33.617773_-114.588261_psmv3_60_tmy.csv`
- `imperial_ca_32.835205_-115.572398_psmv3_60_tmy.csv`
- `des_moines_ia_41.586835_-93.624959_psmv3_60_tmy.csv`
- `fargo_nd_46.9_-96.8_mts1_60_tmy.csv`

### Weather Data Handling
- **CRITICAL**: PySAM `model.Outputs.city` returns `"-"` (not the city name) for these TMY files
- Location must be derived from weather filename
- City map: phoenix→Phoenix, tucson→Tucson, daggett→Daggett, etc.
- State derived from `_az_`→AZ, `_ca_`→CA, etc. patterns in filename

### Key Finding: Tucson > Phoenix in TMY Data
The NSRDB TMY data for Tucson produces ~2.8% more energy than Phoenix for identical systems.
This means for location comparison tasks, the ranking is: Tucson > Phoenix > Des Moines.

## Tasks

### 1. create_residential_pv_system (easy)
- 5 kW Phoenix system, Fixed rack, 20° tilt, 180° azimuth
- Output: `/home/ga/Documents/SAM_Projects/Phoenix_Residential_5kW.json`
- Expected: ~8781 kWh annual, CF ~20%

### 2. analyze_pv_tilt_sensitivity (medium)
- Run 5 kW Tucson system at tilt 0-60° in steps
- Find optimal tilt angle for max annual energy
- Output: `/home/ga/Documents/SAM_Projects/Tucson_Tilt_Analysis.json`
- Expected: Optimal tilt ~30°, ~9162 kWh at optimum

### 3. configure_commercial_pv_system (medium)
- 100 kW Daggett commercial system, maximize energy production
- Task describes outcomes (tracking, high-performance, low losses) without naming PySAM parameter values
- Output: `/home/ga/Documents/SAM_Projects/Daggett_Commercial_100kW.json`
- Expected: ~236,741 kWh, CF ~27% (1-axis tracking + premium modules)

### 4. compare_pv_locations (hard)
- 10 kW system across **Phoenix, Tucson, Des Moines**
- Best: **Tucson** (~18,300 kWh), Worst: **Des Moines** (~13,466 kWh)
- Output: `/home/ga/Documents/SAM_Projects/PV_Location_Comparison.json`
- Expected ranking: Tucson > Phoenix > Des Moines

### 5. export_hourly_production (hard)
- 7.5 kW Tucson system, export 8760-hour CSV
- Output: CSV at `.../Tucson_Hourly_Production.csv` + JSON summary at `.../Tucson_Hourly_Summary.json`
- Expected: ~13,733 kWh, peak ~6,522 W

## Agent Discovery Path

The agent starts with:
1. A terminal window open on the GNOME desktop
2. A quickstart file at `/home/ga/SAM_QUICKSTART.txt` (created by `setup_sam.sh`)
3. PySAM installed (but the agent must discover it)
4. Weather files under `/opt/SAM/` (path saved to `/home/ga/.SAM/solar_resource_dir.txt`)
5. No helper scripts - the agent must discover the PySAM API independently

SAM_QUICKSTART.txt provides minimal hints (tool name "PySAM" and weather directory) but no API details, parameter names, or code examples. Task descriptions describe desired outcomes, not implementation specifics.

## Verification Design

### Three-Layer Verification
1. **export_result.sh** (in VM): Extracts values from agent's JSON using flexible jq key paths, checks python_ran flag
2. **verifier.py** (on host): Validates extracted values against expected ranges + physics sanity checks
3. **Independent cross-check** (new): Verifier copies the agent's actual output file and independently parses it to cross-check export_result.sh extraction

### Anti-Bypass Protection
- `setup_task.sh` deletes all output files before each task (no pre-computed results)
- `export_result.sh` checks bash_history for python3 commands
- `export_result.sh` checks .py file contents for PySAM import statements (not just file existence - `touch foo.py` won't bypass)
- If `python_ran` is false, verifier caps score at 20 and task cannot pass
- JSON construction uses safe `jq -n` (not string interpolation) to prevent injection

### Physics Sanity Checks
- Desert SW (Phoenix, Tucson, Daggett): CF 16-26% (fixed), 22-32% (tracking)
- Midwest (Des Moines, Fargo): CF 12-20%
- Peak power must be < DC rating * 1.2
- Energy ranking must match geography

## Common Issues

### SAM Desktop ssc.so Error
SAM binary needs `LD_LIBRARY_PATH` set:
```bash
LD_LIBRARY_PATH=/opt/SAM/2024.12.12/linux_64:$LD_LIBRARY_PATH /opt/SAM/2024.12.12/SAM
```

### Registration Dialog
SAM GUI shows a free registration dialog on first launch (email-based, not payment).
The dialog has a "Skip for now" button (allows 15 uses).
**Solution**: setup_sam.sh launches SAM and dismisses the dialog via xdotool Tab+Enter.
SAM GUI is left open for the agent to use alongside PySAM.

### PySAM City Returns "-"
TMY weather files bundled with SAM don't include city metadata that PySAM expects.
**Solution**: Derive location from weather filename patterns.

## Real-World Data
- SAM bundles actual NREL TMY (Typical Meteorological Year) weather data
- Based on real satellite-measured solar radiation data from NSRDB
- No synthetic data needed - all weather files are from real measurements
