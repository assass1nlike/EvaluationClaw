> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ActivInspire Environment Notes

## Application Information
- **Name**: ActivInspire by Promethean
- **Type**: Desktop application (interactive whiteboard software)
- **License**: Proprietary (Personal Edition available free)
- **Download URL**: http://activsoftware.co.uk/linux/repos/ubuntu/pool/focal/

## Key Learnings

### Library Dependencies
ActivInspire is built for Ubuntu 20.04 (Focal) and requires:
- libpng12.so.0 (not available in Ubuntu 22.04+)
- libcrypt.so.1 (version mismatch in newer Ubuntu)
- Qt5 libraries compiled for specific versions
- libre2-5 (older regex library)

### Installation Method
```bash
wget http://activsoftware.co.uk/linux/repos/ubuntu/pool/focal/a/ac/activinspire_2004-3.5.18-1-amd64.deb
dpkg -i --force-depends activinspire_*.deb
apt-get install -f
```

### Binary Location
After installation, the main binary is at:
- `/usr/local/bin/activsoftware/Inspire`

### First Run Behavior
ActivInspire shows:
1. License Agreement dialog (click "Run Personal Edition")
2. Welcome/Profile selection dialog (select ActivStudio, click Continue)
3. Optional Dashboard on startup

### Configuration Files
- `/home/ga/.activsoftware/ActivInspire/ActivInspire.conf`
- `/home/ga/.activsoftware/ActivSoftware/ActivSoftware.conf`

### Document Storage
- Default flipchart location: `/home/ga/Documents/Flipcharts/`
- File extension: `.flipchart`

## Known Issues

### Ubuntu 22.04 Compatibility
**CRITICAL**: ActivInspire does NOT work on Ubuntu 22.04 due to library ABI incompatibilities.

**Solution**: Use Ubuntu 20.04 (Focal) base image.

### Symlink Workarounds Don't Work
Creating symlinks like `libpng16.so.16 -> libpng12.so.0` fails because the ABI is different, not just the filename.

### Qt Platform Issues
If you see Qt errors, try:
```bash
export QT_QPA_PLATFORM=xcb
export QT_X11_NO_MITSHM=1
```

## Recommended Base Image
For ActivInspire to work correctly, create a new base image:
- Base: Ubuntu 20.04 LTS (Focal Fossa)
- Desktop: GNOME or similar
- Resolution: 1920x1080

## Verification Strategy
For flipchart tasks:
1. Export script should check for `.flipchart` file existence
2. Can use `unzip` to inspect flipchart contents (they are ZIP archives)
3. Check for specific XML elements inside the flipchart

## Task Ideas
1. Create new flipchart with specific title
2. Add text annotation to existing flipchart
3. Draw shapes (rectangle, circle, line)
4. Import image into flipchart
5. Save flipchart with specific filename
