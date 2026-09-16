# Writing Installation Scripts (pre_start hooks)

## Script Template

```bash
#!/bin/bash
set -euo pipefail

echo "=== Installing <Application Name> ==="

# Configure faster APT mirrors (optional but recommended)
sudo cat > /etc/apt/apt.conf.d/99custom << 'APT_CONF_EOF'
Acquire::Retries "3";
Acquire::http::Timeout "10";
Acquire::https::Timeout "10";
APT_CONF_EOF

# Install dependencies
echo "Installing dependencies..."
sudo apt-get update
sudo apt-get install -y \
    wget \
    <dependency1> \
    <dependency2>

# Download application
echo "Downloading <Application>..."
wget -q -O /tmp/app.deb "https://download-url/app.deb"

# Install application
echo "Installing <Application>..."
sudo dpkg -i /tmp/app.deb || sudo apt-get install -f -y

# Install verification/testing tools
echo "Installing verification tools..."
sudo apt-get install -y \
    python3-pil \
    python3-numpy \
    imagemagick \
    scrot \
    wmctrl \
    xdotool

# Cleanup
rm -f /tmp/app.deb

echo "=== <Application> installation completed ==="
```

## Key Principles

### 1. Use `set -euo pipefail`
- `-e`: Exit on error
- `-u`: Error on undefined variables
- `-o pipefail`: Catch errors in pipes

### 2. Handle dpkg failures gracefully
```bash
sudo dpkg -i package.deb || sudo apt-get install -f -y
```
The `|| apt-get install -f` fixes missing dependencies.

### 3. Always install verification tools
```bash
sudo apt-get install -y \
    scrot       # Screenshots
    wmctrl      # Window management
    xdotool     # UI automation
    python3-pil # Image processing
```

### 4. Use echo statements for logging
Logs go to `/home/<user>/env_setup_pre_start.log`

### 5. Clean up temporary files
```bash
rm -f /tmp/*.deb
```

## Application-Specific Examples

### Google Earth Pro
```bash
wget -q -O /tmp/google-earth-pro.deb \
    "https://dl.google.com/dl/earth/client/current/google-earth-pro-stable_current_amd64.deb"
sudo dpkg -i /tmp/google-earth-pro.deb || sudo apt-get install -f -y
```

### Chrome Browser
```bash
wget -q -O /tmp/chrome.deb \
    "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"
sudo dpkg -i /tmp/chrome.deb || sudo apt-get install -f -y
```

### VS Code
```bash
wget -q -O /tmp/vscode.deb \
    "https://code.visualstudio.com/sha/download?build=stable&os=linux-deb-x64"
sudo dpkg -i /tmp/vscode.deb || sudo apt-get install -f -y
```

### Snap Applications
```bash
# Note: Snap requires systemd and may have issues in containers
sudo snap install <app-name>
```

### Flatpak Applications
```bash
sudo apt-get install -y flatpak
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install -y flathub <app-id>
```

## Dealing with First-Run Dialogs

Many applications show dialogs on first launch. **Config files alone are rarely enough** — most apps ignore pre-created configs on true first launch. Use the two-layer approach (see `10_cross_cutting_patterns.md` patterns #2 and #13 for full details):

**Layer 1 — Pre-configure via config files:**
```bash
# Create config to skip first-run wizard
mkdir -p /home/$USER/.config/GIMP/2.10
echo '(first-run-wizard #f)' > /home/$USER/.config/GIMP/2.10/gimprc
```

**Layer 2 — Warm-up launch in `post_start` to clear first-run state:**
```bash
# Launch app, dismiss dialogs, kill it — subsequent launches will be clean
su - ga -c "DISPLAY=:1 gimp &"
sleep 10
# Dismiss any remaining dialogs with xdotool
DISPLAY=:1 xdotool key Escape
sleep 2
pkill -f gimp || true
```

**Also consider:**
- Accept EULA via command line (if supported)
- JVM options for JetBrains IDEs: `-Djb.privacy.policy.text=<!--999.999-->` (see pattern #12)

## Java Applications with Bundled JRE

Many scientific applications (AstroImageJ, 3D Slicer, etc.) bundle their own Java runtime.

### Installation Pattern

```bash
# Download from GitHub releases
AIJ_VERSION="6.0.3.00"
wget --timeout=120 \
    "https://github.com/AstroImageJ/astroimagej/releases/download/${AIJ_VERSION}/AstroImageJ-${AIJ_VERSION}-linux-x64.tgz" \
    -O astroimagej.tgz

# Extract (directory name may vary - check both cases!)
tar -xzf astroimagej.tgz -C /opt/astroimagej

# Find executable - check multiple possible paths
AIJ_EXEC=""
for subdir in "astroimagej" "AstroImageJ" ""; do
    for binpath in "bin/AstroImageJ" "AstroImageJ" "bin/aij"; do
        testpath="/opt/astroimagej/$subdir/$binpath"
        if [ -f "$testpath" ]; then
            AIJ_EXEC="$testpath"
            break 2
        fi
    done
done

# Create symlink for easy access
if [ -n "$AIJ_EXEC" ]; then
    chmod +x "$AIJ_EXEC"
    ln -sf "$AIJ_EXEC" /usr/local/bin/aij
fi
```

### Launching with Macros

For ImageJ-based applications, use `-macro` argument for reliable automation:

```bash
# Create launch script
cat > /home/ga/launch_astroimagej.sh << 'EOF'
#!/bin/bash
export DISPLAY=${DISPLAY:-:1}
export _JAVA_OPTIONS="-Xmx4g"  # Set memory limit
xhost +local: 2>/dev/null || true

# Launch with optional macro
if [ -n "$1" ]; then
    /usr/local/bin/aij -macro "$1" > /tmp/aij.log 2>&1 &
else
    /usr/local/bin/aij > /tmp/aij.log 2>&1 &
fi
EOF
chmod +x /home/ga/launch_astroimagej.sh
```

## Caching Large Downloads

For large datasets (>500MB), download once during install and cache:

```bash
# In install script (pre_start hook):
WASP12_DATA_URL="https://example.com/large_dataset.tar.gz"
WASP12_CACHE="/opt/fits_samples/dataset.tar.gz"

if [ ! -f "$WASP12_CACHE" ]; then
    echo "Downloading large dataset (4GB)..."
    wget -q --show-progress "$WASP12_DATA_URL" -O "$WASP12_CACHE" || {
        echo "WARNING: Download failed, will retry at task setup"
    }
fi

# Verify download size
if [ -f "$WASP12_CACHE" ]; then
    FILESIZE=$(stat -c%s "$WASP12_CACHE")
    if [ "$FILESIZE" -lt 1000000000 ]; then
        echo "WARNING: File too small, removing"
        rm -f "$WASP12_CACHE"
    fi
fi
```

```bash
# In task setup script (pre_task hook):
if [ -f "$CACHED_DATA" ]; then
    echo "Using cached data"
    tar -xzf "$CACHED_DATA" -C "$DATA_DIR"
else
    echo "Downloading data..."
    wget "$URL" -O /tmp/data.tar.gz
    tar -xzf /tmp/data.tar.gz -C "$DATA_DIR"
fi
```
