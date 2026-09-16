> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# OpenICE Environment Creation Notes

## Application Overview

OpenICE is a Java-based medical device interoperability platform that uses:
- **Gradle** for build management
- **JavaFX** for GUI
- **RTI Connext DDS** for real-time networking

## Installation Challenges

### 1. Gradle Build Time
The Gradle build process is very resource-intensive and time-consuming:
- First run downloads ~500MB of dependencies
- Compilation takes 5-10 minutes
- Can cause VM instability if resources are limited

**Solution**:
- Skip pre-build in install script
- Build on first run in setup script with timeout
- Set memory limits: `GRADLE_OPTS="-Xmx2g"`

### 2. Java Version
OpenICE 2.0 requires Java 17:
```bash
apt-get install -y openjdk-17-jdk openjdk-17-jre
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
```

### 3. JavaFX Dependencies
Required packages:
```bash
apt-get install -y libgtk-3-0 libgl1-mesa-glx libasound2 libxrender1 libxtst6 libxi6
```

## Verification Strategy

### Window Detection
OpenICE creates windows with titles containing:
- "OpenICE"
- "ICE"
- "Supervisor"
- "demo-apps"

Use: `wmctrl -l | grep -iE "openice|ice|supervisor|demo"`

### Process Detection
Check for Java process:
```bash
pgrep -f "java.*demo-apps"
```

### Log Files
- Build log: `/home/ga/openice/logs/build.log`
- Runtime log: `/home/ga/openice/logs/openice.log`

## Task Design Considerations

### Device Adapter Tasks
- Simulated devices are the easiest to work with
- Device types: Multiparameter Monitor, Pulse Oximeter, etc.
- Device icons appear in right panel when created

### Clinical App Tasks
- Apps appear as icons on left side of screen
- Click icon to launch, "Exit App" button to return
- Apps: Vital Signs, Patient ID, X-ray Viewer, Infusion Safety

## Caching Recommendations

Due to long build times, consider using checkpointing:
```python
env.reset(seed=42, use_cache=True, cache_level="post_start")
```

This caches the state after OpenICE is built and running, saving significant time on subsequent runs.

## Known Issues

1. **SSH connection drops**: The Gradle build can cause VM to become unresponsive temporarily
2. **Memory pressure**: Gradle build needs 2-4GB heap space
3. **Network dependency**: Initial build requires internet for Maven dependencies

## Future Improvements

1. Consider pre-building a checkpoint with OpenICE already compiled
2. Add VLM verification for visual confirmation of UI elements
3. Create more complex tasks involving device data analysis
