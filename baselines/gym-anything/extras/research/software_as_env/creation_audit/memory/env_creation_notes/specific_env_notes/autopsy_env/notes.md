> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Autopsy Environment — Learnings and Quirks

## Application Overview
- **Autopsy 4.21.0**: Java-based (NetBeans RCP) digital forensics platform
- **The Sleuth Kit (TSK)**: Native C library + JNI Java bindings for disk image parsing
- **Critical requirement**: Both TSK Java `.deb` AND apt `sleuthkit` package needed

## Critical Installation Issues

### 1. TSK Package Conflicts (libtsk.so.19)
**Problem**: The `sleuthkit-java` .deb (v4.12.1) and the apt `sleuthkit` package (v4.11.1) both provide `libtsk.so.19`. Installing both with `dpkg -i` causes a conflict error.

**Solution**: Install the `.deb` first, then install `sleuthkit` from apt with `--force-overwrite`:
```bash
dpkg -i sleuthkit-java_4.12.1-1_amd64.deb
apt-get install -f -y -q   # resolve dependencies
apt-get install -y -q -o Dpkg::Options::='--force-overwrite' sleuthkit
```

**Why both are needed**:
- `sleuthkit-java` deb: provides `libtsk_jni.so` (JNI library) + `sleuthkit-4.12.1.jar` (Java bindings)
- `sleuthkit` apt: provides CLI tools (`fls`, `icat`, `mmls`, `img_stat`)

### 2. JNI Library Path Issue
**Problem**: Autopsy reports "Library not found in jar (libtsk_jni)" even though `libtsk_jni.so` is installed at `/usr/lib/x86_64-linux-gnu/`.

**Root cause**: OpenJDK 17 on Ubuntu has `java.library.path = /usr/java/packages/lib` only (not the standard system library directories).

**Solution**: Create symlinks:
```bash
mkdir -p /usr/java/packages/lib
for f in /usr/lib/x86_64-linux-gnu/libtsk_jni*; do
    ln -sf "$f" /usr/java/packages/lib/$(basename "$f")
done
```

### 3. DFTT Disk Image Downloads Fail (SourceForge 404)
**Problem**: SourceForge DFTT test image URLs return HTML error pages instead of disk images.

**Solution**: Always create fallback disk images locally:
- NTFS image: `dd` + `mkntfs -F` + `mount -o loop` to add files
- FAT image: `dd` + `mkfs.vfat` + `mcopy` (mtools, no mount needed)

The `head -c 20 | grep -qi html` check removes downloaded HTML error pages.

### 4. JVM Heap OOM Kills
**Problem**: Autopsy defaults to 4GB+ JVM heap which causes OOM on 8-12GB VMs, killing the entire VM.

**Solution**:
- Set `-J-Xmx2g -J-Xms256m` in launch command
- Also set `-Xmx2g` in `autopsy.conf`
- VM needs at least 12GB RAM (OS + Autopsy JVM + Solr + overhead)

### 5. needrestart Disrupts SSH
**Problem**: Ubuntu's `needrestart` service auto-restarts SSH after package installation, breaking the VM connection.

**Solution**: Disable it before installing packages:
```bash
echo '$nrconf{restart} = "a";' > /etc/needrestart/needrestart.conf
export NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1
```

## Autopsy-Specific UI Quirks

### Splash Screen Gets Stuck
On first launch, the splash screen shows "Starting modules..." and may appear stuck for 3-5 minutes while modules initialize. After initialization completes, clicking anywhere on the screen nudges it to dismiss and show the Welcome dialog.

**Impact on setup_task.sh**: The `wait_for_autopsy_window` function detects the Java process window quickly, but the Welcome screen only appears after the splash screen dismisses. Need to:
1. Wait for any autopsy window (300s timeout)
2. Click to nudge the splash screen
3. Wait specifically for the "welcome" window title

### Welcome Screen Layout
- "New Case" button with green plus icon
- "Open Recent Case" (disabled on first run)
- "Open Case" button
- "Close" button

### New Case Wizard
Two steps:
1. **Case Information**: Case Name (required), Base Directory, Case Type (Single/Multi-user)
2. **Optional Information**: Case Number, Examiner Name/Phone/Email/Notes, Organization

### Add Data Source Wizard
Five steps:
1. Select Host (auto-generate or specify)
2. Select Data Source Type (Disk Image pre-selected)
3. Select Data Source (file path, timezone, sector size)
4. Configure Ingest (modules with Select All/Deselect All)
5. Confirmation ("Data source has been added...")

## Resource Requirements
| Resource | Value | Notes |
|----------|-------|-------|
| CPU | 4 cores | Adequate for single-case analysis |
| RAM | 12GB | JVM 2GB + Solr + OS overhead |
| Disk | ~7.5GB used | Java + Autopsy + TSK + evidence |
| Network | Required | For downloading Autopsy + TSK during install |

## Timing
| Phase | Duration | Notes |
|-------|----------|-------|
| pre_start | ~94s | Package install + Autopsy download + evidence creation |
| post_start | ~5s | Config + desktop shortcuts |
| pre_task | ~247s | Autopsy first launch + module loading + Welcome screen |
| Total reset | ~342s | From env.reset() to agent-ready |

## JavaFX Warnings
Autopsy logs warnings about unknown JavaFX modules. These are non-critical — OpenJDK doesn't include JavaFX, but Autopsy works fine without it (no timeline visualization).
