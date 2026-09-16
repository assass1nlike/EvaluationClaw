> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# KStars + INDI CCD Simulator — Environment Creation Notes

## Installation

### Package Sources
- PPA: `ppa:mutlaqja/ppa` (maintained by INDI lead developer Jasem Mutlaq)
- Packages: `kstars-bleeding`, `indi-full`, `gsc`
- Total download: ~800MB (includes 238MB gsc-data, 161MB kstars-bleeding-dbg, 69MB kstars-bleeding-data)
- Install time: ~15 minutes in QEMU VM

### Critical: Guide Star Catalog (GSC)
- Package `gsc` installs to `/usr/share/GSC` (310MB)
- Contains real Hubble Space Telescope star position data
- The CCD Simulator uses GSC to render accurate star fields
- Without GSC, the CCD simulator produces only uniform noise (useless)
- Environment variable `GSCDAT=/usr/share/GSC` must be set for INDI processes

### Critical: Scope Info for CCD Simulator
- By default, `CCD Simulator.SCOPE_INFO.FOCAL_LENGTH=0` and `APERTURE=0`
- With focal length 0, the CCD simulator CANNOT render stars (produces only noise)
- Must set `FOCAL_LENGTH=750` and `APERTURE=200` (or similar realistic values) after connecting
- This must be done in `setup_kstars.sh` (post_start hook) after device connection

## VNC Configuration
- The base image `ubuntu-gnome-systemd_highres` creates a VNCSpec with `password=None`
- Must explicitly set `"vnc": {"password": "password"}` in env.json
- Without this, VNC authentication fails and the environment hangs

## KStars Configuration
- First-run wizard suppressed via `~/.config/kstarsrc` with `firstRun=false` and `RunStartupWizard=false`
- Location pre-set to Pittsburgh, PA (can be changed per task if needed)
- Despite config, KStars may still show startup tips — dismiss with Escape key presses

## INDI Server

### Simulator Drivers
| Driver | Binary | What It Does |
|--------|--------|-------------|
| Telescope Simulator | `indi_simulator_telescope` | Virtual mount, slews to RA/DEC coordinates |
| CCD Simulator | `indi_simulator_ccd` | Renders star field images from GSC catalog |
| Focuser Simulator | `indi_simulator_focus` | Adjustable focus with defocus effects |
| Filter Simulator | `indi_simulator_wheel` | RGB/narrowband filter switching |

### Key INDI Commands
```bash
# Connect device
indi_setprop "Telescope Simulator.CONNECTION.CONNECT=On"

# Slew (MUST send RA and DEC atomically in one command)
indi_setprop "Telescope Simulator.ON_COORD_SET.TRACK=On"
indi_setprop "Telescope Simulator.EQUATORIAL_EOD_COORD.RA;DEC=5.588;-5.39"

# Take exposure
indi_setprop "CCD Simulator.CCD_EXPOSURE.CCD_EXPOSURE_VALUE=10"

# Set scope info (critical!)
indi_setprop "CCD Simulator.SCOPE_INFO.FOCAL_LENGTH=750"
indi_setprop "CCD Simulator.SCOPE_INFO.APERTURE=200"

# Change filter
indi_setprop "Filter Simulator.FILTER_SLOT.FILTER_SLOT_VALUE=2"
```

### INDI Gotchas
1. RA and DEC MUST be sent in a single command with semicolons. Separate commands don't work.
2. RA is in decimal hours (0-24), DEC is in decimal degrees (-90 to +90)
3. The telescope simulator takes ~10 seconds to slew to a distant target
4. CCD exposure countdown is visible via `indi_getprop "CCD Simulator.CCD_EXPOSURE.CCD_EXPOSURE_VALUE"`
5. FITS files are saved to the UPLOAD_DIR with UPLOAD_PREFIX

## Task Design Notes

### Start State
- KStars should be open and maximized, showing the planetarium view
- INDI server running with all simulator drivers
- All devices connected
- Telescope unparked and ready to slew
- CCD configured to save locally

### Task Verification Approach
Since verifier.py is a stub (VLM evaluation is external), key verifiable signals are:
1. **FITS files created** — count before vs after, check coordinates in header
2. **Telescope position** — query via `indi_getprop`, compare to target RA/DEC
3. **Exposure metadata** — FITS header has EXPTIME, INSTRUME, OBJCTRA, OBJCTDEC
4. **Star content** — real star data in captured images (not just noise)

### Coordinate Reference
| Object | RA (hours) | DEC (degrees) | Notes |
|--------|-----------|---------------|-------|
| M31 (Andromeda) | 0.7123 | +41.2692 | Large angular size |
| M42 (Orion Nebula) | 5.5881 | -5.3911 | Rich star field |
| M45 (Pleiades) | 3.79 | +24.1167 | Bright cluster |
| M13 (Hercules) | 16.6949 | +36.4614 | Dense globular |
| M57 (Ring Nebula) | 18.8931 | +33.0292 | Small angular size |
| NGC 4526 | 12.5675 | +7.6992 | Transient alert target |

## Live Sky Survey Capture & Spectacular Visuals

### Problem: CCD Simulator Limitation
The INDI CCD Simulator only renders **point sources** (stars) from the GSC catalog. It does NOT render extended objects (galaxy structure, nebula emission, supernova remnants). CCD captures show white dots on black background — accurate but visually underwhelming.

### Solution: CDS hips2fits API + False Color Enhancement
The `capture_sky_view.sh` script produces stunning images by fetching real sky survey data on-demand:

1. **Read telescope position**: Reads current RA/Dec from INDI (`indi_getprop` on Telescope Simulator)
2. **Convert coordinates**: Converts RA from hours to degrees
3. **Fetch survey imagery**: Queries the CDS (Centre de Donnees astronomiques de Strasbourg) hips2fits API for DSS2 Color survey data at those coordinates
4. **Apply false color**: Runs `false_color.py` to apply artistic color enhancement
5. **Output**: Spectacular 1920x1080 PNG image

### capture_sky_view.sh Usage
```bash
# Basic usage (reads telescope position from INDI automatically)
bash ~/capture_sky_view.sh [output_path] [fov_degrees] [--palette NAME]

# Example with palette
bash ~/capture_sky_view.sh /home/ga/Images/m42.png 1.0 --palette hubble
```

### CDS hips2fits API
- Base URL: `https://alasky.cds.unistra.fr/hips-image-services/hips2fits`
- Survey: `DSS2 Color` (Digitized Sky Survey 2, full color)
- Coordinates derived live from INDI telescope position
- No pre-downloading needed — imagery is fetched on-demand for any sky position

### False Color Enhancement (`false_color.py`)
Available palettes:
| Palette | Style |
|---------|-------|
| `enhanced` | Enhanced natural colors (default) |
| `hubble` | Hubble Space Telescope palette |
| `narrowband` | Narrowband emission-style (SHO) |
| `heat` | Thermal/heat map |
| `cool` | Cool blue tones |
| `vibrant` | High saturation vibrant colors |

Output: 1920×1080 PNG files

### DS9 (SAOImageDS9)
- Installed via `apt install saods9`
- Command-line usage: `ds9 file.fits -scale log -cmap Heat`
- Available at `/usr/bin/ds9` in the VM
- Standard astronomical FITS viewer from Smithsonian Astrophysical Observatory

### Visual Results
The false-color sky survey captures are visually spectacular — each image shows real sky survey data from the DSS2 Color survey at the telescope's current pointing:
- **NGC 4526**: Lenticular galaxy with bright elongated core, diffraction spikes on stars
- **M42 (Orion)**: Blue/white nebulosity with embedded Trapezium stars
- **M57 (Ring)**: Classic ring structure clearly visible
- **M31 (Andromeda)**: Spiral galaxy with dust lanes and companion M32
- **M13 (Hercules)**: Dense sphere of hundreds of thousands of stars
- **M45 (Pleiades)**: Blue reflection nebulosity around the Seven Sisters

### Caching
- Pre-start checkpoint includes all package installs
- Second run restores from checkpoint, skipping the entire install phase (~15 min → ~0s)
- Post-start hook (INDI + KStars setup) still runs each time (~47s)
- Sky survey images are fetched live from CDS during task execution (not pre-cached)
- Use `use_cache=True` in `env.reset()` to enable
