> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# gvSIG Desktop Environment — Creation Notes

## Overview

- **App**: gvSIG Desktop 2.4.0 (Java-based GIS application)
- **Install**: OSGeoLive deb package from `http://download.osgeo.org/livedvd/data/gvsig/gvsig-desktop_2.4.0-2850-2_amd64.deb`
- **Base**: `ubuntu-gnome-systemd_highres`
- **Data**: Natural Earth 110m resolution vector datasets (countries, rivers, cities)
- **Resolution**: 1920x1080
- **SSH user**: `ga` / `password123`

## Installation

### Pre-start (install_gvsig.sh)

```bash
apt-get install -y wget curl unzip ca-certificates \
    libxrender1 libxtst6 libxi6 libxrandr2 libfreetype6 fontconfig \
    xdotool wmctrl x11-utils imagemagick python3-pip scrot \
    default-jre openjdk-8-jdk   # <-- openjdk-8-jdk is CRITICAL (see below)

pip3 install --no-cache-dir pillow

wget -q --timeout=600 --tries=3 "http://download.osgeo.org/livedvd/data/gvsig/gvsig-desktop_2.4.0-2850-2_amd64.deb" -O /tmp/gvsig.deb
dpkg -i /tmp/gvsig.deb || apt-get install -f -y
```

**CRITICAL — Java 8 requirement**: gvSIG 2.4.0 uses `commons-lang3` which cannot parse Java 9+ version strings (e.g., `11.0.25+9`). Without `openjdk-8-jdk`, gvSIG fails silently with a Java version parse error. Always install `openjdk-8-jdk` alongside `default-jre`.

### Install paths

- Deb installs to: `/usr/local/lib/gvsig-desktop/2.4.0-2850-2-amd64/`
- Actual launcher: `/usr/local/lib/gvsig-desktop/2.4.0-2850-2-amd64/gvSIG.sh`
- System wrapper: `/usr/local/bin/gvsig-desktop` (created by deb)
- Launcher path saved to: `/etc/gvsig_launcher_path` (for scripts to use)

### Natural Earth Data

Downloaded during pre_start to `/home/ga/gvsig_data/`:
- `countries/ne_110m_admin_0_countries.shp` — 177 features, 147 attribute fields
- `rivers/ne_110m_rivers_lake_centerlines.shp`
- `cities/ne_110m_populated_places.shp`

URLs (with fallback):
- Primary: `https://naciscdn.org/naturalearth/110m/cultural/{name}.zip`
- Fallback: `https://naturalearth.s3.amazonaws.com/110m_cultural/{name}.zip`

### Post-start (setup_gvsig.sh)

1. Creates `/usr/local/bin/launch-gvsig` wrapper (sets `LC_NUMERIC=C`, `DISPLAY=:1`)
2. Runs warm-up launch as `ga` user — waits up to 150s for gvSIG window
3. Dismisses first-run dialogs with `Escape`
4. Kills gvSIG after warm-up
5. Copies pre-built `countries_base.gvsproj` from `/workspace/data/projects/` to `/home/ga/gvsig_data/projects/`

**Warm-up purpose**: Populates `~/.gvSIG/` user directory so gvSIG starts faster in subsequent launches (no first-run plugin initialization).

## gvSIG Launch Command

```bash
su - ga -c "LC_NUMERIC=C DISPLAY=:1 XAUTHORITY=/home/ga/.Xauthority '/usr/local/lib/gvsig-desktop/2.4.0-2850-2-amd64/gvSIG.sh' '$PROJECT_FILE' > /tmp/gvsig_task.log 2>&1 &"
```

- `LC_NUMERIC=C` is required — gvSIG uses decimal points in coordinates
- `XAUTHORITY` must be set explicitly when launching via `su`
- Process name: `java` (check with `pgrep -f "gvSIG\|andami"`)

## gvSIG Project File Format

- Extension: `.gvsproj`
- Format: ZIP archive containing:
  - `state.xml` — main project definition (Views, layers, symbology)
  - `state_base.xsd`, `gvsig.xsd` — XML schema files
  - `preview.jpg` — thumbnail screenshot
- Layer paths are **hardcoded absolute paths** in `state.xml`:
  ```xml
  <shpFile type="file">/home/ga/gvsig_data/countries/ne_110m_admin_0_countries.shp</shpFile>
  ```
- The `countries_base.gvsproj` file (49KB) contains the countries layer pre-loaded in a View

## Pre-built Project Strategy

**Problem**: gvSIG has no headless API for creating projects. Loading a layer requires GUI automation.

**Solution**:
1. During initial development, manually open gvSIG, load the layer via GUI, save the project
2. Download the saved `.gvsproj` file and store it in `benchmarks/cua_world/environments/gvsig_desktop_env/data/projects/`
3. Mount `data/` directory in `env.json`
4. Copy the project file in `setup_gvsig.sh` to `/home/ga/gvsig_data/projects/`
5. Tasks 2-5 launch gvSIG with this pre-built project file as start state

## UI Coordinates (1920x1080)

All coordinates are actual 1920x1080 pixels. `visual_grounding` returns 1280x720 — multiply by 1.5.

### gvSIG Main Window Layout (after opening project)
- **Menu bar**: y ≈ 76 (File, Edit, View, Layer, etc.)
- **Table of Contents (TOC)**: left panel, layer names at y ≈ 300-600 depending on zoom
- **Map canvas**: center/right area

### Adding a Layer
1. Right-click in TOC empty area → context menu appears
2. "Add layer" option: approximately (207, 500) — varies
3. In "Add Layer" staging dialog: "Add" button at (1208, 338)
4. File picker: File Name field at (960, 668), Open button at (1140, 729)
5. Type full path: `/home/ga/gvsig_data/countries/ne_110m_admin_0_countries.shp`
6. Staging dialog "OK": (1181, 821)

**Key**: The "Add Layer" via top menu (Layer → Add Layer) may not be clickable when no View is active. Right-click in the TOC panel is more reliable.

### Layer Properties (for symbology/labels)
1. Right-click on layer name in TOC → "Properties" (Propiedades): approximately (216, 497)
2. Layer Properties dialog opens with tabs: Symbology, Labels, General

### Changing Symbology (Fill Color)
1. Open Layer Properties → "Symbology" tab: (200, 180)
2. "Choose symbol..." button: (773, 312)
3. Symbol Editor: click "..." button next to fill color swatch: (848, 360)
4. Color chooser: click "RGB" tab: (848, 425)
5. Red field (R=255): (1220, 456) — clear field, type 255
6. Green field (G=0): (1220, 481) — clear, type 0
7. Blue field (B=0): (1220, 506) — clear, type 0
8. OK → OK → OK (three dialogs to close)

### Opening Attribute Table
1. Right-click on layer in TOC → "Attribute table" (or "Ver tabla"): approximately (233, 218)
2. Table opens in a separate window showing 177 rows, ~147 columns
3. Close button: approximately (755, 125)

### Enabling Labels
1. Open Layer Properties → "Labels" tab: (272, 180)
2. "Enable labeling" checkbox: (110, 203)
3. Label field dropdown: (389, 276)
4. Select "NAME" field (position 19 in the dropdown list from top)
   - The field order is: ..., NAME_LONG, NAME (at position ~19)
   - If you accidentally select NAME_SORT or NAME_ALT, press Up arrow to correct
5. OK button: standard dialog position

### Saving Project
1. File menu (top-left): (93, 76)
2. "Save as...": (131, 161)
3. File dialog: type full path in filename field, click Save
4. Path example: `/home/ga/gvsig_data/projects/world_countries.gvsproj`

**Note**: Ctrl+S in gvSIG triggers "Save before closing?" dialog — NOT a direct save. Always use File → Save As.

## Screenshot Capture

```bash
# From root via SSH:
DISPLAY=:1 import -window root /tmp/screenshot.png
# Fallback:
DISPLAY=:1 scrot /tmp/screenshot.png
```

Both methods work in this environment (unlike GNOME compositor environments where scrot returns black).

## gvSIG UI Quirks

1. **TOC right-click is essential**: The Layer menu in the menu bar may be greyed out or unresponsive when clicked. Right-clicking in the TOC (layer list panel) reliably provides context menu options.

2. **Java startup time**: gvSIG takes 30-90 seconds to start from scratch. From a warm user directory, ~20-40 seconds.

3. **LC_NUMERIC=C required**: gvSIG uses locale-dependent number formatting for coordinates. Without `LC_NUMERIC=C`, coordinate parsing may fail on locales that use commas as decimal separators.

4. **Project opens in View**: When a `.gvsproj` is passed as argument, gvSIG opens directly to the View showing the map. The "Project Manager" window is NOT shown.

5. **First-run state**: After warm-up, subsequent launches are much faster (user directory already populated with plugin manifests).

6. **Alt+F4 on attribute table**: Triggers the "Save current project before closing?" dialog for the whole application. Use the window's X button instead.

7. **Color chooser has multiple tabs**: The default tab is "Basic" (color palette). Must click "RGB" tab to enter numeric values.

## Tasks Summary

| Task | Start State | Key Action | Verifier |
|------|------------|-----------|---------|
| `open_vector_layer` | Fresh gvSIG (no project) | Right-click TOC → Add layer → navigate to .shp → OK | Stub (VLM) |
| `change_layer_symbology` | countries_base.gvsproj loaded | Layer Properties → Symbology → fill color = #FF0000 | Stub (VLM) |
| `open_attribute_table` | countries_base.gvsproj loaded | Right-click layer → Attribute table | Stub (VLM) |
| `label_layer_by_field` | countries_base.gvsproj loaded | Layer Properties → Labels → enable → select NAME | Stub (VLM) |
| `save_project_to_file` | countries_base.gvsproj loaded | File → Save As → /home/ga/gvsig_data/projects/world_countries.gvsproj | Stub (VLM) |

All verifiers are stubs returning `{"passed": True, "score": 100}` — actual verification is done by external VLM evaluators.

## Environment Config Key Points

```json
{
  "id": "gvsig_desktop_env@0.1",
  "base": "ubuntu-gnome-systemd_highres",
  "resources": {"cpu": 4, "mem_gb": 6, "gpu": 0, "net": true},
  "vnc": {"enable": true, "host_port": 5956, "password": "password"},
  "user_accounts": [{"name": "ga", "password": "password123"}],
  "mounts": [
    {"source": "benchmarks/cua_world/environments/gvsig_desktop_env/scripts", "target": "/workspace/scripts", "mode": "ro"},
    {"source": "benchmarks/cua_world/environments/gvsig_desktop_env/tasks", "target": "/workspace/tasks", "mode": "ro"},
    {"source": "benchmarks/cua_world/environments/gvsig_desktop_env/data", "target": "/workspace/data", "mode": "ro"}
  ],
  "hooks": {
    "pre_start": "/workspace/scripts/install_gvsig.sh",
    "post_start": "/workspace/scripts/setup_gvsig.sh"
  }
}
```

## Evidence / Test Results

Confirmed workflows (all tested interactively via VNC + xdotool):
- `evidence_docs/gvsig_startup.png` — fresh gvSIG launch with open View
- `evidence_docs/gvsig_layer_added.png` — countries layer loaded (dark blue polygons)
- `evidence_docs/gvsig_red_map.png` — symbology changed to red (#FF0000)
- `evidence_docs/gvsig_attr_table.png` — attribute table open (177 countries)
- `evidence_docs/gvsig_labels_applied.png` — NAME labels visible on map

## Known Issues / Lessons Learned

1. **Java version**: Must install `openjdk-8-jdk` explicitly. `default-jre` alone installs Java 11+ which breaks gvSIG's version parser in commons-lang3. Additionally, must set `JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64` explicitly in the launch command — gvSIG.sh scans `/usr/lib/jvm` in filesystem order and may pick Java 11 before Java 8.

2. **pgrep `\|` alternation**: In `pgrep -f "gvSIG\|andami"`, the `\|` inside bash double-quotes does NOT work as alternation for pgrep on Linux. Use simple `pgrep -f "gvSIG"` instead (matches both `gvSIG.sh` and the java command line).

3. **Layer menu greyed out**: The top "Layer" menu is sometimes inactive. Right-click in TOC is more reliable for all layer operations.

4. **No headless project creation**: gvSIG has no CLI or headless mode for project manipulation. Pre-built project files must be created interactively and stored in `data/`.

5. **Hardcoded paths in .gvsproj**: The project file embeds absolute paths to shapefiles. Tasks must always have shapefiles at the same path (`/home/ga/gvsig_data/countries/`).

6. **Multiple OK dialogs**: Changing symbology requires closing 3 nested dialogs: color chooser → symbol editor → layer properties. Missing one leaves gvSIG in a blocked state.

7. **NAME field position**: In the countries shapefile, "NAME" is the 19th field in the attribute table. When enabling labels, the dropdown lists all 147 fields — scrolling to NAME requires patience. The dropdown order is alphabetical by field position, not alphabetically by name.

8. **gvSIG startup time**: ~18s to window appearance from warm user dir (on a VM that has already run gvSIG once). The pgrep process check returns 0s (immediately), then wmctrl window poll finds it at ~18s.

9. **Window title**: `gvSIG 2.4.0.2850 final : countries_base.gvsproj` when project is loaded; `gvSIG 2.4.0.2850 final : Untitled` for fresh launch with no project.
