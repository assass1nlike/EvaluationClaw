> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# GeoGebra Environment Notes

## Installation

### GeoGebra Versions

GeoGebra has multiple versions:
- **GeoGebra Classic 5**: Older version, available in some Ubuntu repositories
- **GeoGebra Classic 6**: Current stable version, requires adding the official repository
- **GeoGebra Discovery**: Experimental version with bleeding-edge features (via Snap)

For this environment, we use GeoGebra Classic 6 from the official repository.

### Repository Setup

```bash
# Add GeoGebra GPG key
wget -qO- https://www.geogebra.net/linux/apt/geogebra.gpg.key | gpg --dearmor -o /usr/share/keyrings/geogebra-archive-keyring.gpg

# Add repository
echo "deb [signed-by=/usr/share/keyrings/geogebra-archive-keyring.gpg] https://www.geogebra.net/linux/ stable main" | tee /etc/apt/sources.list.d/geogebra.list

# Install
apt-get update
apt-get install -y geogebra-classic
```

### Fallback Installation

If the official repository fails, fallback options:
1. Install older `geogebra` package from Ubuntu repos
2. Use Flatpak: `flatpak install -y flathub org.geogebra.GeoGebra`

## Configuration

### User Preferences

GeoGebra stores preferences in `~/.geogebra/prefs.xml`. Key settings to disable first-run dialogs:

```xml
<entry key="showToolBarHelp" value="false"/>
<entry key="showInputHelp" value="false"/>
<entry key="tooltipTimeout" value="0"/>
```

### Working Directories

Standard directories created:
- `~/Documents/GeoGebra/projects/` - For saved .ggb files
- `~/Documents/GeoGebra/exports/` - For exported images/PDFs

## File Formats

### GeoGebra Files (.ggb)

GeoGebra files are ZIP archives containing:
- `geogebra.xml` - The main construction data
- `geogebra_thumbnail.png` - Preview image
- Other optional resources

### Extracting for Verification

```bash
unzip -q file.ggb -d /tmp/ggb_extract
# Parse /tmp/ggb_extract/geogebra.xml for verification
```

### XML Structure

Key elements to look for in `geogebra.xml`:
- `<element type="point">` - Points with `<coords x="..." y="..."/>`
- `<element type="segment">` - Line segments
- `<element type="polygon">` - Polygons
- `<element type="function">` - Function definitions
- `<element type="circle">` - Circles

## Common Issues

### Java Memory Settings

GeoGebra runs with default JVM settings:
- Initial heap: 32MB
- Max heap: 512MB

If memory issues occur, GeoGebra can be launched with custom settings:
```bash
java -Xms64m -Xmx1024m -jar /usr/share/geogebra/geogebra.jar
```

### Display Issues

Always ensure DISPLAY=:1 is set when launching GeoGebra:
```bash
su - ga -c "DISPLAY=:1 geogebra-classic"
```

### Window Focus

GeoGebra windows can be identified by:
```bash
DISPLAY=:1 wmctrl -l | grep -i geogebra
```

## Verification Patterns

### Geometry Verification

For geometric constructions:
1. Parse `geogebra.xml` to extract point coordinates
2. Calculate distances between points
3. Calculate angles using vectors
4. Compare with expected values (with tolerance)

### Function Verification

For graphing tasks:
1. Search XML for `<element type="function">`
2. Extract expression from `<expression exp="..."/>`
3. Verify function matches expected form (e.g., `x^2-4*x+3`)

### Screenshot Analysis

GeoGebra screenshots can be analyzed using:
- Pillow for basic image properties
- VLM (Vision Language Model) for visual verification

## Task Ideas

### Geometry Tasks
- Construct equilateral triangle
- Construct regular pentagon
- Bisect an angle
- Construct perpendicular bisector
- Inscribe circle in triangle

### Algebra/Graphing Tasks
- Graph linear function
- Graph quadratic function
- Find intersection points
- Graph system of equations
- Create slider-controlled function

### Calculus Tasks
- Find derivative visually
- Explore tangent lines
- Calculate area under curve
- Visualize limits

### 3D Tasks
- Create 3D point
- Construct plane through points
- Visualize 3D functions
