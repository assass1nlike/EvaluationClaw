> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Docker Desktop Environment Notes

## Overview
Docker Desktop for Linux provides a GUI for managing Docker containers, images, volumes, and more. This environment enables testing GUI-based container management tasks.

## Installation Notes

### Docker Desktop Requirements
- Docker Engine must be installed first
- Requires systemd-based Linux
- Needs user to be in `docker` group
- Requires specific packages: `gnome-terminal`, `kmod`, `qemu-system-x86`

### Installation Process (pre_start hook)
1. Install Docker Engine via official repository
2. Download Docker Desktop .deb package
3. Install Docker Desktop
4. Add user to docker group
5. Install GUI automation tools (wmctrl, xdotool, scrot)

### Post-Start Configuration
1. Create Docker Desktop settings to skip welcome wizard
2. Launch Docker Desktop with proper display
3. Wait for daemon to be ready
4. Dismiss initial dialogs (subscription, sign-in)
5. Pre-pull commonly used images

## GUI Interaction Patterns

### Key UI Elements
- **Left Sidebar**: Containers, Images, Volumes, Kubernetes, Builds, Extensions
- **Container Row**: Shows name, ID, image, ports, CPU%, last started, actions
- **Action Buttons**: Start (play icon), Stop (square icon), Delete (trash icon)
- **Status Indicator**: Green dot = running, Empty circle = stopped

### Dialog Handling
Docker Desktop shows several dialogs on first launch:
1. **Subscription Agreement**: Click "Accept" button
2. **Sign In Dialog**: Click "Skip" link (top right of dialog)
3. **Walkthroughs Popup**: Click "X" to close

### Coordinate Scaling
ask_cua.py returns coordinates normalized to 1280x720. For actual resolution (e.g., 1920x1080):
- Scale factor: actual_width / 1280 (e.g., 1920/1280 = 1.5)
- x_actual = x_normalized * scale_factor
- y_actual = y_normalized * scale_factor

## Task Design Patterns

### Container Tasks
Tasks typically follow this pattern:
1. **Setup**: Create specific container state (running/stopped/removed)
2. **Agent Action**: Interact with Docker Desktop GUI
3. **Export**: Collect container state information
4. **Verify**: Check if expected state was achieved

### Verification Data Structure
```json
{
    "task": "task_name",
    "target_container": "container_name",
    "container_exists": true/false,
    "container_stopped": true/false,
    "container_status": "Status string",
    "initial_running_count": N,
    "current_running_count": M,
    "docker_daemon_ready": true/false
}
```

### Scoring Criteria
- Docker daemon operational: 10 points
- Docker Desktop running: 10 points
- Main objective (e.g., container stopped): 60 points
- Secondary criteria (e.g., count decreased): 20 points

## Common Issues & Fixes (updated 2026-03-16)

### Issue: Docker context mismatch (CRITICAL)
Docker Desktop creates a `desktop-linux` context for the ga user with its own socket at
`/home/ga/.docker/desktop/docker.sock`. Root uses the `default` context pointing to Docker Engine.
This means task scripts running as root see different containers/images than what Docker Desktop shows.
**Fix**: `task_utils.sh` now auto-detects and exports `DOCKER_HOST=unix:///home/ga/.docker/desktop/docker.sock`
so all scripts (root or ga) talk to the same Docker Desktop daemon.

### Issue: Subscription/sign-in dialogs blocking setup (25-min delay)
Docker Desktop v4.65+ shows a Subscription Agreement, then a Sign In dialog on first launch.
The old dialog dismissal code used wrong coordinates and the setup script hung for 25 minutes.
**Fix**: Correct coordinates for 1920x1080:
- Accept subscription: (1757, 1043)
- Skip sign-in: (1223, 254)
- Close walkthroughs panel: (1883, 126)
- Click Containers sidebar: (173, 155)

### Issue: `settings.json` vs `settings-store.json`
Docker Desktop reads `settings-store.json` (PascalCase keys), not `settings.json` (camelCase).
**Fix**: Pre-create both files before launching Docker Desktop.

### Issue: Missing mount directories
`config/` and `utils/` directories were in env.json mounts but didn't exist.
**Fix**: Removed from env.json mounts.

### Issue: Auto-started welcome-to-docker container
Docker Desktop starts a `welcome-to-docker` container on first launch.
**Fix**: Setup script now stops and removes it after pre-pulling images.

### Issue: Docker Desktop process not detected
The process name may be `docker-desktop` or different variants depending on version.
**Solution**: Check multiple possible process names or use Docker daemon connectivity as proxy.

### Issue: Container operations timeout
Docker operations may take time, especially image pulls.
**Solution**: Use adequate timeouts and wait loops with proper checking.

## Useful Commands

### Check Docker Status
```bash
docker info  # Check daemon status
docker ps    # List running containers
docker ps -a # List all containers
```

### Find Docker Desktop Process
```bash
pgrep -a docker-desktop
pgrep -f "Docker Desktop"
```

### Focus Docker Desktop Window
```bash
wmctrl -a "Docker Desktop"
```

## Real-World Data Usage

The environment includes real-world applications for testing:

### Docker Example Voting App
- **Source**: https://github.com/dockersamples/example-voting-app
- **Location**: `/workspace/data/docker-compose.yml`
- **Services**: 5 containers (vote, result, worker, redis, postgres)
- **Purpose**: Tests multi-container deployment capabilities

This is a production-grade example used in Docker's official tutorials, providing realistic container management scenarios.

## Files Created

### Environment Files
- `env.json` - Main environment configuration
- `scripts/install_docker_desktop.sh` - Pre-start installation
- `scripts/setup_docker_desktop.sh` - Post-start configuration
- `scripts/task_utils.sh` - Shared utility functions
- `data/docker-compose.yml` - Docker Example Voting App

### Tasks
1. **deploy_voting_app**: Deploy real multi-container app (5 services)
2. **pull_docker_image**: Pull a Docker image
3. **run_container**: Run a container with port mapping
4. **stop_container**: Stop a running container

### Task Files (per task)
- `task.json` - Task metadata and verification config
- `setup_task.sh` - Pre-task setup
- `export_result.sh` - Post-task data collection
- `verifier.py` - Verification logic
