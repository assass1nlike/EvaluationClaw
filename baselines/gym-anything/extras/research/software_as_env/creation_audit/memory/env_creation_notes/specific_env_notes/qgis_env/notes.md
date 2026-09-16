> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# QGIS Environment Notes

## Overview

QGIS (Quantum GIS) is a free, open-source desktop geographic information system (GIS) application. This environment provides QGIS for tasks involving map creation, spatial analysis, and geospatial data management.

## Installation

### Method Used
- Official QGIS LTR (Long Term Release) repository for Ubuntu
- Fallback to default Ubuntu package if repository fails

### Key Installation Steps
1. Add QGIS signing key from `download.qgis.org`
2. Create sources list for QGIS LTR repository
3. Install `qgis` and `qgis-plugin-grass`
4. Install automation tools: `xdotool`, `wmctrl`, `scrot`
5. Install Python GIS libraries: `geopandas`, `shapely`, `pyproj`, `fiona`

### Dependencies
- GDAL/OGR libraries (installed automatically with QGIS)
- Python 3 with pip
- Qt5 libraries (installed automatically with QGIS)

## Configuration

### QGIS Settings
- Configuration stored in `~/.config/QGIS/QGIS3.ini`
- Disabled tips/welcome dialogs via config settings
- Profile directory: `~/.local/share/QGIS/QGIS3/profiles/default`

### Sample Data
Created sample GeoJSON files in `~/GIS_Data/`:
- `sample_polygon.geojson` - Two polygon features (Area A, Area B)
- `sample_points.geojson` - Three point features with elevation
- `sample_lines.geojson` - Two line features (roads)

### Directory Structure
```
~/GIS_Data/
├── projects/     # QGIS project files (.qgs, .qgz)
├── shapefiles/   # Shapefile data
├── rasters/      # Raster data
└── exports/      # Exported outputs
```

## Startup Behavior

### Welcome Dialog
QGIS 3.x shows a "News/Welcome" dialog on startup with options like:
- "New Empty Project"
- Recent projects
- Templates

This dialog appears even with config settings to disable tips. Users/agents can click "New Empty Project" to start.

### Process Name
The QGIS process runs as `/usr/bin/qgis.bin` (not just `qgis`).

## Verification Strategy

### File-Based Verification
QGIS projects are stored as:
- `.qgs` files - XML format, human-readable
- `.qgz` files - Compressed (zip) format containing .qgs

### Validating QGS Files
```bash
# Check if file is valid XML with QGIS root element
head -1 project.qgs | grep '<?xml' && grep '<qgis' project.qgs
```

### Validating QGZ Files
```bash
# Check if file is a valid zip archive
file project.qgz | grep -i zip
```

## Known Issues

### First-Run Dialogs
Even with config settings, QGIS may show:
1. News/Welcome panel (can be dismissed)
2. "What's New" dialog on version updates

### Plugin Grass
The `qgis-plugin-grass` package may fail on some Ubuntu versions due to dependency conflicts. This is non-critical for most tasks.

## Resource Requirements

- **CPU**: 4 cores recommended
- **Memory**: 6GB RAM (GIS operations can be memory-intensive)
- **GPU**: Not required (software rendering works fine)
- **Network**: Required for installation, optional for operation

## Useful Commands

### Launch QGIS
```bash
DISPLAY=:1 qgis &                    # Basic launch
DISPLAY=:1 qgis project.qgs &        # Open existing project
```

### QGIS Version
```bash
qgis --version
```

### List Open QGIS Windows
```bash
DISPLAY=:1 wmctrl -l | grep -i qgis
```

## Tasks

### create_new_project
- **Goal**: Create and save a new QGIS project
- **Verification**: Check for `.qgs` file in projects directory
- **Expected Output**: `my_first_project.qgs` in `~/GIS_Data/projects/`

## Future Task Ideas

1. **add_vector_layer** - Add a GeoJSON/Shapefile layer to project
2. **change_layer_style** - Modify layer symbology
3. **create_map_layout** - Create a print layout with map, legend, scale
4. **perform_buffer_analysis** - Buffer analysis on vector layer
5. **export_map_image** - Export map view as PNG/PDF
6. **add_basemap** - Add OpenStreetMap or other basemap
7. **measure_distance** - Use measure tool to calculate distance
8. **create_shapefile** - Digitize new features and save as shapefile
