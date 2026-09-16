> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Panoply Environment Notes

## Application Details
- **Name**: NASA Panoply 5.3.1
- **Type**: Java Swing desktop application
- **Purpose**: Visualize netCDF, HDF, and GRIB scientific data files
- **Developer**: NASA Goddard Institute for Space Studies (GISS)

## Installation Quirks

### Download URL
- Primary: `https://www.giss.nasa.gov/tools/panoply/download/PanoplyJ-<version>.tgz`
- NASA GISS site may be unreachable — use Wayback Machine as fallback:
  `https://web.archive.org/web/20240115173241if_/https://www.giss.nasa.gov/tools/panoply/download/PanoplyJ-5.3.1.tgz`
- Also available as ZIP format

### Java Dependency
- Requires Java 11 or later
- `default-jdk` package on Ubuntu provides OpenJDK 11+
- Panoply bundles its own JAR files — no additional Java libraries needed

### Archive Extraction
- TGZ archive created on macOS (BSD tar) — may show "unknown header" warnings on GNU tar
- Use `tar --warning=no-unknown-keyword -xzf` to suppress warnings
- Extracts to `PanoplyJ/` directory

## UI Architecture

### Window Structure
Panoply opens multiple windows:
1. **Panoply — Sources**: Main data browser window (shows datasets and variables)
2. **<variable> in <dataset>**: Plot window (e.g., "air in air.mon.ltm")
3. **Plot Controls**: Settings panel for the active plot

### Menu Structure
- The **Sources window** and **plot windows** both have identical menu bars: File, Edit, View, History, Bookmarks, Plot, Window, Help
- **File > Save Image As...** (Ctrl+Shift+S) exports the active plot as an image
- **File > Save Image** (Ctrl+S) saves to the last-used path

### Creating a Plot
1. Open a data file → Sources window shows variables
2. Double-click a variable → "Create Plot" dialog appears
3. Select plot type (Georeferenced is default for lat/lon data) → Click "Create"
4. Plot window and Plot Controls window appear

### Plot Controls Panel
- **Show dropdown**: Switches between control categories (Arrays, Contours, Grid, Labels, Layout, **Map Projection**, Overlays, Scale, Shading, Vectors)
- **Map Projection**: Contains the "Projection:" dropdown with 200+ projections
- Default projection: Equirectangular

### Key Keyboard Shortcuts
- **Ctrl+S**: Save Image
- **Ctrl+Shift+S**: Save Image As...
- **Ctrl+O**: Open file

## Data Sources

All data files are from NOAA Physical Sciences Laboratory (psl.noaa.gov):
- NCEP/NCAR Reanalysis derived surface variables
- NOAA OI SST v2 climatology
- No authentication required — direct HTTP download

## Service Timing
- Panoply starts within 2-5 seconds after launch
- Window appears quickly but data loading can take a few seconds
- Allow 8-10 seconds sleep after launch before interacting with the UI
- Warm-up launch in post_start is recommended to initialize preferences

## Coordinate Scaling
- Screenshots are 1920x1080 resolution
- Visual grounding returns coordinates in 1280x720 scale
- Scale factor: `actual_x = int(vg_x * 1920 / 1280)`, `actual_y = int(vg_y * 1080 / 720)`

## Known Issues
- GTK warning "Failed to load module canberra-gtk-module" — harmless, can be ignored
- Panoply creates `.gissjava/logs` directory on first launch
- The projection dropdown is very long (200+ entries) — typing the first letters jumps to the section
