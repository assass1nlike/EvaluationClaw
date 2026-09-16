> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# draw_desktop_env - draw.io Desktop Environment Notes

## Application Details
- **App**: draw.io Desktop v26.0.9 (Electron-based diagramming tool)
- **Install**: `.deb` package from GitHub releases (jgraph/drawio-desktop)
- **Binary**: `/opt/drawio/drawio` (installed via dpkg)
- **Config**: `~/.config/draw.io/` (Electron config + LocalStorage in LevelDB)
- **File format**: `.drawio` XML with `<mxfile>` root, `<diagram>` pages, `<mxGraphModel>` canvas, `<mxCell>` elements

## Critical Findings

### Startup Dialog (MOST IMPORTANT)
draw.io Desktop **ALWAYS** shows a "Create New Diagram / Open Existing Diagram" startup dialog on launch, regardless of:
- File argument passed on command line
- `showStartScreen` setting in LocalStorage
- `DRAWIO_DISABLE_UPDATE=true` environment variable
- `.drawio-config` file in home directory

**The command-line file argument is silently ignored when the startup dialog appears.**

### Reliable File Open Pattern
To open an existing `.drawio` file, use this sequence:
1. Launch draw.io: `DRAWIO_DISABLE_UPDATE=true drawio --no-sandbox --disable-update`
2. Wait 5-8 seconds for the window to appear
3. Press `Escape` to dismiss the startup dialog (creates blank diagram)
4. Press `Ctrl+O` to open the native GTK file dialog
5. Press `Ctrl+L` to activate the location bar
6. Type the full file path
7. Press `Enter` to open

For creating new diagrams, just dismiss the startup dialog with Escape.

### LocalStorage Structure
- Stored in LevelDB at `~/.config/draw.io/Local Storage/leveldb/`
- Config key: `_file://\x00\x01.drawio-config`
- Value encoding: `0x01` prefix byte + UTF-16 LE encoded JSON
- Key fields: `showStartScreen`, `autosave`, `openCounter`, `libraries`
- **Setting `showStartScreen: false` via plyvel does NOT suppress the dialog** - tested and confirmed

### XML Format Details
- Shapes: `<mxCell>` with `vertex="1"` attribute
- Connections: `<mxCell>` with `edge="1"` attribute
- UML classes use swimlane style with `childLayout=stackLayout`
- Text content in `value=""` attribute, uses HTML entities (`&#xa;` for newlines, `&lt;` for `<`)
- Associations labeled with multiplicity like `1..*`

## Environment Design

### Differentiation from diagrams_net_env
| Feature | draw_desktop_env | diagrams_net_env |
|---------|-----------------|------------------|
| Install | .deb package | AppImage |
| Tasks | UML editing, PNG export, ER creation | Flowchart, network diagram, shapes |
| Verification | Python XML parsing | grep/awk |
| Diagram assets | Real UML/ER diagrams | Simple templates |

### Tasks
1. **edit_uml_class_diagram**: Add a Payment class with attributes/methods to existing e-commerce UML
2. **export_diagram_as_png**: Export hospital ER diagram as PNG to Desktop
3. **create_er_diagram**: Create library management ER diagram from scratch

### Key Launch Flags
- `--no-sandbox`: Required for container/QEMU environments
- `--disable-update`: Suppress update checks (along with `DRAWIO_DISABLE_UPDATE=true`)
- Do NOT pass file as command-line argument (startup dialog intercepts it)

## Gotchas
1. **set -e**: Do NOT use in setup scripts - draw.io commands may return non-zero harmlessly
2. **scrot vs import**: Use `import -window root` (ImageMagick) for screenshots, not `scrot`
3. **False positives**: "amount" in `totalAmount` can match - use regex word boundaries
4. **Singleton locks**: Must remove `SingletonCookie`, `SingletonLock`, `SingletonSocket` after killing draw.io
5. **GPU errors**: Bus/GPU errors in logs are harmless (expected in QEMU VM)
6. **plyvel**: Install in post_start for potential LocalStorage manipulation
