> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Microsoft Edge Environment - Development Notes

## Overview

This document captures learnings and gotchas from creating the `microsoft_edge_env` environment for the gym_anything framework.

## Installation

### Adding Microsoft Repository

Microsoft Edge requires adding their apt repository:

```bash
# Add GPG key
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-edge.gpg

# Add repository
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-edge.gpg] https://packages.microsoft.com/repos/edge stable main" | tee /etc/apt/sources.list.d/microsoft-edge.list > /dev/null

# Install
apt-get update && apt-get install -y microsoft-edge-stable
```

### Package Name

- Package name: `microsoft-edge-stable`
- Binary location: `/usr/bin/microsoft-edge`
- Version tested: 144.0.3719.104

## Configuration

### Profile Location

Edge on Linux stores profile data at:
```
~/.config/microsoft-edge/Default/
```

Key files:
- `Bookmarks` - JSON file containing bookmarks (NOT SQLite)
- `Preferences` - JSON settings file
- `History` - SQLite database for browsing history
- `Cookies` - SQLite database for cookies

### First-Run Suppression

To suppress first-run dialogs, create these files BEFORE launching Edge:

1. **First Run file** (empty file):
```bash
touch ~/.config/microsoft-edge/First\ Run
```

2. **Local State file**:
```json
{
  "browser": {
    "enabled_labs_experiments": [],
    "has_seen_welcome_page": true
  },
  "fre": {
    "has_user_seen_fre": true
  }
}
```

3. **Preferences file** with key settings:
```json
{
  "browser": {
    "check_default_browser": false,
    "has_seen_welcome_page": true
  },
  "distribution": {
    "suppress_first_run_default_browser_prompt": true,
    "skip_first_run_ui": true,
    "suppress_first_run_bubble": true
  }
}
```

### Launch Flags

Recommended flags for automated testing:
```bash
microsoft-edge \
    --no-first-run \
    --no-default-browser-check \
    --disable-sync \
    --disable-features=TranslateUI \
    --disable-extensions \
    --disable-component-update \
    --disable-background-networking \
    --disable-client-side-phishing-detection \
    --disable-default-apps \
    --disable-infobars \
    --password-store=basic
```

## Bookmarks

### Format

Edge uses JSON format for bookmarks (unlike Firefox which uses SQLite).

Bookmarks file structure:
```json
{
  "checksum": "...",
  "roots": {
    "bookmark_bar": {
      "children": [
        {
          "name": "Bookmark Name",
          "url": "https://example.com",
          "type": "url"
        }
      ],
      "name": "Favorites bar",
      "type": "folder"
    },
    "other": {
      "children": [],
      "name": "Other favorites",
      "type": "folder"
    },
    "synced": {
      "children": [],
      "name": "Mobile favorites",
      "type": "folder"
    }
  },
  "version": 1
}
```

### Parsing Bookmarks

Use Python to parse the JSON:
```python
import json

def extract_bookmarks(node, path=''):
    results = []
    if node.get('type') == 'url':
        results.append({
            'name': node.get('name', ''),
            'url': node.get('url', ''),
            'folder': path
        })
    elif node.get('type') == 'folder':
        new_path = path + '/' + node.get('name', '') if path else node.get('name', '')
        for child in node.get('children', []):
            results.extend(extract_bookmarks(child, new_path))
    return results

with open('~/.config/microsoft-edge/Default/Bookmarks') as f:
    data = json.load(f)

for root_name, root_node in data.get('roots', {}).items():
    if isinstance(root_node, dict):
        bookmarks = extract_bookmarks(root_node, root_name)
```

## Known Issues

### Personalization Dialog

Even with all first-run suppression flags, Edge shows a "Personalize your feed" dialog on the new tab page. This is part of the new tab page experience, not the first-run wizard.

**Workaround**: The agent needs to close this dialog by clicking the X button before proceeding with tasks.

### msedgedriver

The Edge WebDriver (`msedgedriver`) may not be available in the Microsoft apt repository for all Ubuntu versions. The install script attempts to install it but falls back gracefully if unavailable.

### pip --break-system-packages

Older pip versions don't support the `--break-system-packages` flag. The install script attempts to use it but ignores the error if not supported.

## Differences from Firefox

| Aspect | Firefox | Edge |
|--------|---------|------|
| Profile location | `~/.mozilla/firefox/` | `~/.config/microsoft-edge/` |
| Bookmarks format | SQLite database | JSON file |
| First-run file | `profiles.ini` + prefs | `First Run` + Local State |
| Package manager | Built-in to Ubuntu | Requires Microsoft repo |

## Verification Strategy

The verifier uses a 5-criteria scoring system:

1. **Bookmarks file exists** (10 points) - Basic sanity check
2. **Wikipedia bookmark found** (40 points) - Primary criterion
3. **URL matches pattern** (25 points) - Validates correct URL
4. **Bookmark in correct folder** (15 points) - bookmark_bar or other
5. **New bookmarks added** (10 points) - Confirms agent action

Pass threshold: 75 points with Wikipedia found AND URL matches.

## Testing Tips

1. **Use paramiko for SSH**: The framework's SSH key auth may fail; paramiko with password works reliably
2. **Scale CUA coordinates**: CUA returns 1280x720 coordinates; scale by 1.5x for 1920x1080
3. **Wait for Edge**: Add 5+ seconds after launching before taking screenshots
4. **Check wmctrl -l**: Verify Edge window appears with "Microsoft Edge" in title

## Tasks

### Task 1: add_bookmark
- **Description**: Add Wikipedia as a bookmark
- **Data**: None (uses live Wikipedia website)
- **Verification**: Checks bookmarks JSON file for Wikipedia entry

### Task 2: import_bookmarks
- **Description**: Import bookmarks from HTML file
- **Data**: `assets/sample_bookmarks.html` - 40 real bookmarks in Netscape format
- **Verification**: Checks for imported bookmarks and folders

## Real-World Data

The `import_bookmarks` task uses a real bookmark HTML file (`assets/sample_bookmarks.html`) containing:
- 40 actual website bookmarks (Google, YouTube, GitHub, BBC News, etc.)
- 9 organized folders (News & Media, Technology, Reference, etc.)
- Standard Netscape Bookmark HTML format (used by all major browsers)

This data is NOT synthetic - it contains URLs to real, publicly accessible websites that can be verified.
