> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# PyCharm Environment Notes

## Installation Quirks

### apt-get update Issues
The Ubuntu GNOME base image has a Python module issue with `cnf-update-db`:
```
E: Problem executing scripts APT::Update::Post-Invoke-Success
```

**Solution**: Disable the script or ignore the error:
```bash
if [ -f /usr/lib/cnf-update-db ]; then
    chmod -x /usr/lib/cnf-update-db 2>/dev/null || true
fi
apt-get update || {
    echo "Warning: apt-get update had some errors, continuing anyway..."
}
```

### pip install Conflicts
Some system packages (like `blinker`) can't be uninstalled by pip:
```
error: uninstall-distutils-installed-package
```

**Solution**: Use `--ignore-installed` flag:
```bash
pip3 install --ignore-installed flask pytest ...
```

### PyCharm Download URL
- Use CDN URL: `https://download-cdn.jetbrains.com/python/pycharm-community-2024.3.tar.gz`
- NOT: `https://download.jetbrains.com/...` (redirects, can fail)
- Version format: `2024.3` not `2024.3.1.1`

## Configuration Notes

### Config Directory Naming
PyCharm uses version-specific config directories:
- Build `PC-243.x.x` → Config dir `PyCharmCE2024.3`
- Formula: `year = (major/10 + 2000)`, `minor = (major % 10)`

### Pre-accepting EULA
Create these files to suppress first-run dialogs:
```
~/.config/JetBrains/PyCharmCE2024.3/accepted
~/.java/.userPrefs/jetbrains/_!(!)!'-sym!/prefs.xml
```

### Trusted Paths
Pre-configure trusted paths to avoid "Trust Project" dialog:
```xml
<!-- ~/.config/JetBrains/PyCharmCE2024.3/options/trusted-paths.xml -->
<application>
  <component name="TrustedPathsSettings">
    <option name="trustedPaths">
      <list>
        <option value="/home/ga/PycharmProjects" />
        <option value="/home/ga" />
        <option value="/workspace" />
      </list>
    </option>
  </component>
</application>
```

## UI Behavior

### Welcome Screen
- PyCharm 2024.3 has a sidebar-based Welcome screen
- "New Project" button is at approximately (747, 262) on 1920x1080
- Window title: "Welcome to PyCharm"

### What's New Dialog
- Appears on first project open in new version
- Window title includes "What's New in PyCharm"
- Can be dismissed with Escape key

### Virtual Environment Creation
- PyCharm automatically creates venv when opening a project
- Shows "Creating Virtual Environment" dialog
- May block the main window

## Verification Strategy

### Task Files to Check
1. `app.py` - Flask application with routes
2. `test_app.py` - pytest test file
3. `requirements.txt` - Dependencies

### Verification Points
- Flask import present
- Flask app instance created
- Routes defined (`/` and `/greet/<name>`)
- Test functions exist
- pytest passes

### Export Script Pattern
```bash
# Run pytest and capture output
PYTEST_OUTPUT=$(cd $PROJECT_DIR && python3 -m pytest -v 2>&1)
TESTS_PASS="false"
if echo "$PYTEST_OUTPUT" | grep -q "passed"; then
    TESTS_PASS="true"
fi
```

## Common Issues

| Issue | Solution |
|-------|----------|
| PyCharm not starting | Check `/tmp/pycharm_startup.log` |
| Window not detected | Use `wmctrl -l` to list windows |
| Trust dialog appears | Pre-configure trusted-paths.xml |
| venv creation hangs | Increase timeout or skip venv |

## Resource Requirements

- **CPU**: 4 cores recommended
- **RAM**: 8GB (PyCharm is memory-intensive)
- **Disk**: ~1GB for PyCharm + dependencies
- **Network**: Required for PyCharm download (~683MB)
