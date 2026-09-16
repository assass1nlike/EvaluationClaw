> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# SNAP Environment Creation Notes

## Application Details
- **ESA SNAP 13.0.0** (Sentinel Application Platform)
- Java/NetBeans-based desktop app for satellite remote sensing
- Installer: `esa-snap_sentinel_linux-13.0.0.sh` from download.esa.int
- Install dir: `/opt/snap`
- Process: `/opt/snap/jre/bin/java` (Java process with SNAP classpath)

## Installation Quirks

### Unattended Install
- Use `-q -varfile response.varfile` for silent installation
- Key varfile settings:
  - `sys.installationDir=/opt/snap`
  - `sys.symlinkDir=/usr/local/bin/snap-esa` (avoid conflict with Ubuntu snap)
  - `sys.component.S1TBX$Boolean=true` etc. for toolboxes

### Ubuntu snap Conflict
- ESA SNAP creates `/usr/local/bin/snap` which conflicts with Ubuntu's snap package manager
- Solution: Use `sys.symlinkDir=/usr/local/bin/snap-esa` and create custom symlinks:
  - `/usr/local/bin/esa-snap` -> `/opt/snap/bin/snap`
  - `/usr/local/bin/snap-gpt` -> `/opt/snap/bin/gpt`

### CLI File Opening NOT Supported
- SNAP does NOT accept file paths as command-line arguments
- Passing a file path results in: `"There are parameters but nobody wants to process them"`
- Files must be opened via File > Open Product menu (or gpt CLI for processing)

## First-Run Dialog
- "SNAP Update" dialog appears asking to check for plugin updates
- Coordinates (1280x720): Remember checkbox at (491,379), No button at (754,403)
- Coordinates (1920x1080): Remember at (737,569), No at (1131,605)
- Solution: Warm-up launch in post_start, dismiss dialog with xdotool, then close SNAP

## File Open Dialog
- File > Open Product (Alt+F then Enter) opens a Java file chooser
- File Name field coordinates (1280x720): center at (644,412)
- File Name field coordinates (1920x1080): center at (966,618)
- Open button (1280x720): (803,456)
- Open button (1920x1080): (1205,684)

### Two-Step File Open (Critical)
The Java file chooser does NOT open a file when you type a full path and press Enter. Instead, it navigates to the directory. The correct approach is:
1. Click File Name field → Ctrl+A → type full path (e.g., `/home/ga/snap_data/landsat_multispectral.tif`) → Enter
   - This navigates the dialog to `/home/ga/snap_data/`
2. Click File Name field again → Ctrl+A → type just the filename (`landsat_multispectral.tif`) → Enter
   - This selects and opens the file

Clicking the Open button at fixed coordinates is unreliable because the dialog position varies between launches. The two-step Enter approach is more robust.

### "Multiple Readers Available" Dialog
When opening GeoTIFF files, SNAP may show a "Multiple Readers Available" dialog asking which reader to use. Press Enter to accept the default GeoTIFF reader.

## Process Detection
- Use `/opt/snap/jre/bin/java` pattern to avoid matching Ubuntu snapd
- Alternative patterns: `org.esa.snap`, `nbexec.*snap`
- Window title: "SNAP 13" (matched with `grep -qi "SNAP"` in wmctrl)

## Data Sources
All real satellite data, no synthetic/mock data:
- Sentinel-2A GeoTIFF: github.com/mommermi/geotiff_sample (~5.7MB)
- Sentinel-2 RGB bands: github.com/leftfield-geospatial/homonim (~2.1MB)
- Landsat multispectral: github.com/opengeos/data (~9.7MB)
- Sentinel-2 COGs from AWS: sentinel-cogs.s3.us-west-2.amazonaws.com (no auth needed)
- Landsat 7 RGB: github.com/rasterio/rasterio (~1.7MB)
- SRTM DEM: github.com/opengeos/data (~5.8MB)

## Timing
- Pre-start (install): ~90s (download SNAP + satellite data)
- Post-start (setup + warmup): ~50s
- Pre-task (launch SNAP + open file): ~45s
- Total from fresh: ~185s
- Total from pre_start cache: ~120s

## Interactive Testing Findings

### GUI Automation Tips
- **Context menus**: Menu items like "Open RGB Image Window" and "Open HSV Image Window" are very close together (~14px in 1280x720). Keyboard navigation (Down arrow x N + Enter) is more reliable than mouse coordinates.
- **Band Maths dialog**: Raster > Band Maths opens a dialog. The "Target Band" name field, "Edit Expression..." button, and expression editor are all navigable. Expression validation shows "Ok, no errors." when valid.
- **NDVI expression**: For the landsat_multispectral.tif data, NDVI = `(B2 - B3) / (B2 + B3)` where B2=NIR and B3=Red.
- **RGB composite**: Right-click product → "Open RGB Image Window" (5th item in context menu) opens the RGB dialog with default channel assignments. Clicking OK creates a false-color composite.

### Task Verification Results
All 3 tasks verified as completable via interactive screenshot→action→screenshot loop:
1. **open_and_inspect_geotiff**: Agent opens file via File menu, handles Multiple Readers dialog, expands product tree, displays band
2. **create_rgb_composite**: Agent right-clicks product, navigates context menu to Open RGB Image Window, accepts defaults
3. **compute_ndvi**: Agent uses Raster > Band Maths, edits expression, computes NDVI band

## Memory
- SNAP configured with `-Xmx5G` max heap
- VM needs 8GB RAM minimum
- Disk: SNAP install ~2GB + data ~251MB
