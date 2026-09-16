> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Houdini (SideFX) Environment Notes

## Overview

The Houdini environment provides a SideFX Houdini 20.5.684 installation for procedural 3D modeling, VFX, materials, and rendering tasks. Houdini is extracted from the Docker image `aaronsmithtv/hbuild:20.5.684-base` and runs inside a QEMU VM with Ubuntu GNOME desktop.

## Key Features

- **Houdini 20.5.684** - Extracted from Docker Hub image
- **Real 3D Data** - Stanford Bunny OBJ, Utah Teapot OBJ, Poly Haven HDRI
- **Graceful Fallback** - Environment boots and downloads data even without license
- **License Infrastructure** - hserver, sesinetd, sesictrl all in place
- **Stub Verifiers** - Real verification handled externally via VLM evaluators

## Installation Method: Docker Extraction

Houdini is installed by extracting from `aaronsmithtv/hbuild:20.5.684-base`:

1. Pull Docker image inside the QEMU VM (~2.9GB)
2. Create container and `docker cp /opt/houdini` to host (NOT `/opt/hfs20.5` which is a symlink)
3. Create symlink: `ln -sf /opt/houdini/build /opt/hfs20.5`
4. Copy license tools from `/usr/lib/sesi/` (sesictrl, sesinetd)

### Critical Gotchas

1. **Symlink vs directory**: `/opt/hfs20.5` in the container is a symlink to `/opt/houdini/build`. `docker cp` copies the symlink verbatim (a 18-byte file), NOT the target directory. Must copy `/opt/houdini` instead.

2. **find -L for symlinks**: `find /opt -maxdepth 1 -type d -name "hfs*"` does NOT find symlinks. Use `find -L /opt -maxdepth 1 -type d -name "hfs*"` to follow symlinks.

3. **libtinfo5 dependency**: The Houdini binary requires `libtinfo.so.5` which Ubuntu 22.04 does not ship (it has libtinfo6). Without the `libtinfo5` package, hython segfaults at startup with a `SIGSEGV` in `signalCallback`. Install with `apt-get install -y libtinfo5`.

4. **hython is a wrapper**: `/opt/hfs20.5/bin/hython` (828 bytes) is a shell script that sources `app_init.sh` and execs `hython-bin` (135KB). The actual binary is `hython-bin`.

## Licensing

**IMPORTANT**: Houdini requires SideFX API credentials even for the free Apprentice license.

### License Architecture
- `sesinetd` - License daemon (at `/usr/lib/sesi/sesinetd`)
- `hserver` - Local proxy between Houdini and sesinetd (at `$HFS/bin/hserver`)
- `sesictrl` - CLI license administration (at `/usr/lib/sesi/sesictrl`)

### Getting a License
1. Create free SideFX account at https://www.sidefx.com
2. Go to https://www.sidefx.com/services/ → Applications → Create new app
3. Copy client_id and client_secret
4. Create `config/sidefx_credentials.env`:
   ```
   SIDEFX_CLIENT_ID=your_client_id
   SIDEFX_CLIENT_SECRET=your_client_secret
   ```
5. The install script will run: `sesictrl login --client-id ... --client-secret ...`

### Without Credentials
- hython exits with: "No licenses could be found to run this application" (exit code 3)
- Houdini GUI launches but shows "Unable to Acquire a License" dialog
- Scene files (baseline_scene.hipnc, bunny_scene.hipnc) cannot be pre-created
- All other setup (data download, directory creation, environment config) works fine

## Data Sources (Real Data)

| File | Source | Size |
|------|--------|------|
| bunny.obj | Stanford 3D Scanning Repository | 205,917 bytes |
| venice_sunset_1k.hdr | Poly Haven | 1,440,400 bytes |
| teapot.obj | University of Utah / Stanford CS148 | 210,614 bytes |

## Environment Configuration

- **Base**: `ubuntu-gnome-systemd_highres`
- **Resources**: 8 CPU, 16GB RAM, net: true
- **Resolution**: 1920x1080
- **User**: `ga` with sudo_nopasswd

## Tasks

### import_obj_model (Easy)
- Import Stanford Bunny OBJ into Houdini and save as `.hipnc`
- Stub verifier (VLM verification is external)

### apply_material_and_render (Medium)
- Create gold Principled Shader, assign to bunny, render to PNG
- Stub verifier (VLM verification is external)

## Dialog Suppression

```bash
HOUDINI_NO_START_PAGE_SPLASH=1
HOUDINI_ANONYMOUS_STATISTICS=0
HOUDINI_NOHKEY=1
HOUDINI_LMINFO_VERBOSE=0
HOUDINI_PROMPT_ON_CRASHES=0
```

## Lessons Learned

### Lesson 1: Docker Extraction Symlink Bug
The most critical bug was `docker cp` copying a symlink instead of the actual directory. This resulted in a broken `/opt/hfs20.5` symlink pointing at nothing. The fix: copy the actual `/opt/houdini` directory, then recreate the symlink.

### Lesson 2: Missing System Library (libtinfo5)
The hbuild Docker image is Debian-based and has `libtinfo.so.5`. Ubuntu 22.04 only has version 6. Without it, hython crashes with a segfault (not a clear error message), making debugging difficult. Identified via `strace -e openat`.

### Lesson 3: find -L for Symlink Detection
Standard `find -type d` doesn't match symlinks even if their target is a directory. This caused the install script's detection logic to fail. Always use `find -L` when looking for directories that might be symlinks.

### Lesson 4: Proprietary Software Licensing is a Major Blocker
Unlike open-source 3D software (Blender, FreeCAD), Houdini requires authentication even for the free tier. This means the environment cannot be fully self-contained — it requires external credentials. The install script handles this gracefully with multiple fallback methods and clear documentation.
