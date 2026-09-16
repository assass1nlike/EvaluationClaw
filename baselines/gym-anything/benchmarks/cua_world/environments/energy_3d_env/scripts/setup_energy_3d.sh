#!/bin/bash
set -e
echo "=== Setting up Energy3D ==="

# Wait for desktop to be ready
sleep 5
for i in $(seq 1 30); do
    if DISPLAY=:1 xdpyinfo >/dev/null 2>&1; then
        echo "Desktop is ready"
        break
    fi
    echo "Waiting for desktop... ($i/30)"
    sleep 2
done

# Copy sample files to user's documents
USER_DIR="/home/ga/Documents/Energy3D"
mkdir -p "$USER_DIR"
cp /opt/energy3d_samples/*.ng3 "$USER_DIR/" 2>/dev/null || true
chown -R ga:ga "$USER_DIR"

# Pre-create Energy3D preferences directory so the app does not prompt for one on first run.
# Energy3D uses the Java Preferences API; pre-seed a minimal prefs file.
PREFS_DIR="/home/ga/.java/.userPrefs/org/concord/energy3d"
mkdir -p "$PREFS_DIR"
cat > "$PREFS_DIR/prefs.xml" << 'EOF'
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE map SYSTEM "http://java.sun.com/dtd/preferences.dtd">
<map MAP_XML_VERSION="1.0">
  <entry key="hint" value="false"/>
  <entry key="welcome" value="false"/>
</map>
EOF
chown -R ga:ga /home/ga/.java

# Warm-up launch to clear first-run state and surface any startup dialogs
echo "Performing warm-up launch of Energy3D..."
su - ga -c "setsid /opt/energy3d/energy3d.sh > /tmp/energy3d_warmup.log 2>&1 &" || true

# Wait for the main window. Energy3D's main JFrame title contains "Energy3D".
echo "Waiting for Energy3D window..."
WID=""
for i in $(seq 1 60); do
    WID=$(DISPLAY=:1 xdotool search --name "Energy3D" 2>/dev/null | head -1)
    if [ -z "$WID" ]; then
        WID=$(DISPLAY=:1 xdotool search --class "energy3d" 2>/dev/null | head -1)
    fi
    if [ -z "$WID" ]; then
        WID=$(DISPLAY=:1 xdotool search --class "Energy3D" 2>/dev/null | head -1)
    fi
    if [ -n "$WID" ]; then
        echo "Energy3D window detected after ${i}*2s (WID: $WID)"
        break
    fi
    sleep 2
done

if [ -z "$WID" ]; then
    echo "WARNING: Energy3D window not detected during warm-up; continuing"
    echo "--- warm-up log tail ---"
    tail -40 /tmp/energy3d_warmup.log 2>/dev/null || true
fi

# Dismiss any startup dialogs
sleep 3
for attempt in 1 2 3 4; do
    DISPLAY=:1 xdotool key Escape 2>/dev/null || true
    sleep 0.5
    DISPLAY=:1 xdotool key Return 2>/dev/null || true
    sleep 0.5
done

# Verification screenshot
sleep 2
DISPLAY=:1 scrot /tmp/energy3d_warmup_screenshot.png 2>/dev/null || true

# Kill the warm-up instance
echo "Killing warm-up instance..."
pkill -f "org.concord.energy3d.MainApplication" 2>/dev/null || true
sleep 2
pkill -9 -f "org.concord.energy3d.MainApplication" 2>/dev/null || true
sleep 1

# Verify install components
if [ ! -f /opt/energy3d/energy3d.jar ]; then
    echo "ERROR: energy3d.jar missing"
    exit 1
fi
if [ ! -x /opt/energy3d/energy3d.sh ]; then
    echo "ERROR: energy3d launcher missing"
    exit 1
fi
SAMPLE_COUNT=$(ls "$USER_DIR"/*.ng3 2>/dev/null | wc -l)
echo "  Sample projects in user dir: $SAMPLE_COUNT"
if [ "$SAMPLE_COUNT" -lt 1 ]; then
    echo "ERROR: no sample projects copied to $USER_DIR"
    exit 1
fi

echo "=== Energy3D setup complete ==="
