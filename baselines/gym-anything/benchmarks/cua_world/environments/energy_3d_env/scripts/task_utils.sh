#!/bin/bash
# Shared utilities for Energy3D tasks.

take_screenshot() {
    local path="${1:-/tmp/screenshot.png}"
    DISPLAY=:1 scrot "$path" 2>/dev/null || \
    DISPLAY=:1 import -window root "$path" 2>/dev/null || true
}

kill_energy3d() {
    pkill -f "org.concord.energy3d.MainApplication" 2>/dev/null || true
    sleep 2
    pkill -9 -f "org.concord.energy3d.MainApplication" 2>/dev/null || true
    sleep 1
}

# Find the Energy3D main window. Its title contains the application name and,
# once a file is loaded, the file path. Search by name first, then fall back
# to the Java class name.
find_energy3d_window() {
    local WID=""
    WID=$(DISPLAY=:1 xdotool search --name "Energy3D" 2>/dev/null | tail -1)
    if [ -z "$WID" ]; then
        WID=$(DISPLAY=:1 xdotool search --class "energy3d" 2>/dev/null | head -1)
    fi
    if [ -z "$WID" ]; then
        WID=$(DISPLAY=:1 xdotool search --class "Energy3D" 2>/dev/null | head -1)
    fi
    echo "$WID"
}

# Launch Energy3D with an optional .ng3 file. The Java MainApplication accepts
# the file path as its first positional argument.
launch_energy3d() {
    local file_path="$1"
    local timeout="${2:-90}"
    local elapsed=0

    if [ -n "$file_path" ]; then
        su - ga -c "setsid /opt/energy3d/energy3d.sh \"$file_path\" > /tmp/energy3d_task.log 2>&1 &"
    else
        su - ga -c "setsid /opt/energy3d/energy3d.sh > /tmp/energy3d_task.log 2>&1 &"
    fi

    while [ $elapsed -lt $timeout ]; do
        WID=$(find_energy3d_window)
        if [ -n "$WID" ]; then
            echo "Energy3D window detected after ${elapsed}s (WID: $WID)"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    echo "WARNING: Energy3D window not detected after ${timeout}s"
    return 1
}

maximize_energy3d() {
    local WID
    WID=$(find_energy3d_window)
    if [ -n "$WID" ]; then
        DISPLAY=:1 wmctrl -i -r "$WID" -b add,maximized_vert,maximized_horz 2>/dev/null || true
        DISPLAY=:1 xdotool windowactivate "$WID" 2>/dev/null || true
        echo "Window maximized and focused (WID: $WID)"
    else
        echo "WARNING: Could not find Energy3D window to maximize"
    fi
}

dismiss_dialogs() {
    local rounds="${1:-4}"
    for attempt in $(seq 1 $rounds); do
        DISPLAY=:1 xdotool key Escape 2>/dev/null || true
        sleep 0.4
        DISPLAY=:1 xdotool key Return 2>/dev/null || true
        sleep 0.4
    done
}

# Full task setup: kill any existing instance, launch with file, maximize, take a
# verification screenshot.
setup_energy3d_task() {
    local file_path="$1"

    echo "Killing any existing Energy3D instances..."
    kill_energy3d

    echo "Launching Energy3D..."
    launch_energy3d "$file_path"

    echo "Waiting for application to fully render..."
    sleep 8

    echo "Dismissing startup dialogs..."
    dismiss_dialogs 4

    echo "Maximizing window..."
    maximize_energy3d
    sleep 2

    echo "Taking initial screenshot..."
    take_screenshot /tmp/task_start_screenshot.png

    echo "Energy3D task setup complete"
}
