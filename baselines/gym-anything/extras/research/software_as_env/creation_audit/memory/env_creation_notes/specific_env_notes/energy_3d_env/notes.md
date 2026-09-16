> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Energy3D Environment Notes

## Application

Energy3D is a Java/Swing CAD/CAE tool from the Concord Consortium for designing
buildings and solar installations and running energy/solar-radiation analyses.
File extension: `.ng3` (Java-serialized binary - **not** a zip, so cannot be
inspected with python `zipfile`/`xml.etree`).

Source: <https://energy.concord.org/energy3d/>
Repository: <https://github.com/concord-consortium/energy3d>

## Critical: Java 8 Required

Energy3D's `setupLibraryPath()` uses reflection on `ClassLoader.sys_paths` (private static
field) to inject a native-library directory. On Java 11 the `--illegal-access=warn` runtime
silently zeroes out `sys_paths`, after which the very next AWT native-library load
(during `Toolkit.<clinit>` / `UIManager.getSystemLookAndFeelClassName`) NPEs:

```
Exception in thread "main" java.lang.ExceptionInInitializerError
    at java.desktop/javax.swing.UIManager.getSystemLookAndFeelClassName
    at org.concord.energy3d.MainApplication.main(MainApplication.java:98)
Caused by: java.lang.NullPointerException
    at java.base/java.lang.ClassLoader.loadLibrary(ClassLoader.java:2654)
```

`--add-opens java.base/java.lang=ALL-UNNAMED` does **not** fix this; the bug is the NPE
after the reflective write. Install `openjdk-8-jre` and pin the launcher to
`/usr/lib/jvm/java-8-openjdk-*/jre/bin/java`.

## Native JOGL libraries

Energy3D's main method hardcodes `./lib/jogl/native/linux-64` (relative to the working
directory) as `java.library.path`. After downloading and extracting
`jogl-all-natives-linux-amd64.jar` and `gluegen-rt-natives-linux-amd64.jar`, the launcher
must:

1. `cd /opt/energy3d` before invoking java, **and**
2. provide the relative directory `lib/jogl/native/linux-64` (symlinked to the real
   native dir) so the post-reflection path resolution still finds the `.so` files.

Pass `-Djava.library.path=/opt/energy3d/native` as well for safety on the initial load
before the reflection hack runs.

Use `unzip -j` so the `.so` files land directly in the target dir (not under
`natives/linux-amd64/...`).

## Window detection

Once a `.ng3` file is loaded the JFrame title is:
```
Energy3D V8.1.7 - /home/ga/Documents/Energy3D/<file>.ng3
```
Both `xdotool search --name Energy3D` and `xdotool search --class energy3d` work.
The startup splash phase is brief (<2s) so polling `xdotool search --name Energy3D`
every 2s is sufficient.

Process detection: use the full main class path:
```
pgrep -f org.concord.energy3d.MainApplication
```
Generic `pgrep java` will collide with desktop Java services.

## Verification

`.ng3` is Java serialization (`magic = 0xACED 0x0005`). There is no Python parser, so
programmatic inspection of project state is not feasible. The verifier is a stub; VLM
evaluation against the final screenshot is the production verification path
(consistent with sweet_home_3d_env and other 3D-design environments).

Useful signals available without parsing the binary:
- `stat -c %Y` of the starter file modified after task start timestamp
- `md5sum` of starter file changed vs baseline (recorded in `setup_task.sh`)
- screenshot diff vs baseline (visual analysis tools handle this)

## Real data sources

Tutorial / example projects live in the upstream repo at:
```
https://raw.githubusercontent.com/concord-consortium/energy3d/master/src/main/resources/org/concord/energy3d/tutorials/<name>.ng3
```
79 files available; full list via the GitHub contents API. Downloaded a curated set
of 12 covering both solar (rack arrays, tilt/azimuth optimization, heat maps) and
building (orientation, insulation, passive heating, roof shapes) workflows.

## Timing

- `pre_start` (install): ~110-130s on cold cache (apt install of openjdk-8 + Mesa libs,
  27 jar downloads from energy.concord.org, 12 sample downloads from GitHub)
- `post_start` (setup): ~15-25s (preferences, warm-up launch with window detection,
  kill warm-up)
- `pre_task` (per-task setup): ~12-15s (copy starter, launch Energy3D, wait for window
  via setup_energy3d_task)
- Total clean reset: ~150s; with `use_cache=True, cache_level="post_start"` ~30s

## Resource sizing

Energy3D itself is light (`-Xmx1024m` is enough for the tutorial models tested),
but JOGL/Ardor3D rendering plus the GNOME desktop benefit from 6 GB RAM and
4 vCPUs. `gpu: 0` is correct - Mesa software rendering works fine.
