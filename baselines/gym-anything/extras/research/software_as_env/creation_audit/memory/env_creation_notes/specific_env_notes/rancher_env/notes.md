> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Rancher Environment - Creation Notes

## Installation

- Docker image: `rancher/rancher:v2.8.5` (single container with embedded K3s)
- Pattern: Docker-in-QEMU (same as Jenkins, Rocket.Chat)
- Admin creds: admin/Admin12345678! (Rancher requires >= 12 char passwords)
- Bootstrap password: "admin" (set via CATTLE_BOOTSTRAP_PASSWORD env var)
- No docker-compose needed — Rancher is a single `docker run` command

## Critical Gotchas

### 1. Password Minimum Length = 12 Characters
Rancher enforces a minimum password length of 12 characters. Shorter passwords silently fail during the password change API call, leaving the bootstrap password active.

**Fix:** Use a password >= 12 characters (e.g., `Admin12345678!`).

### 2. Container Name Conflicts
If the script runs twice (e.g., after a restart), `docker run --name rancher` fails because the name is already in use.

**Fix:** Always `docker rm -f rancher 2>/dev/null || true` before `docker run`.

### 3. No `set -e` in Setup Script
Rancher's setup involves many steps that may return non-zero but aren't fatal (e.g., deleting a non-existent container, applying already-existing manifests). Using `set -e` causes cascading failures.

**Fix:** Use explicit error checks (`if [ $? -ne 0 ]`) for critical operations only.

### 4. docker-compose-plugin Not Available
In the QEMU Ubuntu base image, `docker-compose-plugin` is not in apt repositories. Including it in `apt-get install` causes the ENTIRE install to fail, meaning Docker itself won't be installed.

**Fix:** Don't install `docker-compose-plugin`. Rancher doesn't need it — it's a single `docker run` command.

### 5. Rancher API Bootstrap Sequence
The API bootstrap must follow this exact order:
1. Login with bootstrap password → get token
2. Accept EULA (`/v3/settings/eula-agreed`)
3. Set server URL (`/v3/settings/server-url`)
4. Disable telemetry (`/v3/settings/telemetry-opt`)
5. Change admin password (`/v3/users?action=changepassword`)
6. Re-authenticate with new password

### 6. K3s Cluster Readiness
After Rancher starts, the embedded K3s cluster takes additional time (1-3 minutes) before the node reports "Ready". Deploying manifests before this will fail.

**Fix:** Poll `docker exec rancher kubectl get nodes` until the node shows "Ready".

### 7. Firefox Self-Signed Certificate Warning
Rancher uses a self-signed cert. Firefox blocks the page with SEC_ERROR_UNKNOWN_ISSUER. The `enterprise_roots.enabled` pref doesn't help because it's not a system root CA.

**Fix:** Use xdotool to click "Advanced..." → scroll down → "Accept the Risk and Continue":
```bash
# Click "Advanced..." button
DISPLAY=:1 xdotool mousemove 1320 768 click 1
sleep 3
# Scroll to reveal Accept button
DISPLAY=:1 xdotool key Page_Down
sleep 2
# Click "Accept the Risk and Continue"
DISPLAY=:1 xdotool mousemove 1251 1005 click 1
```

### 8. Firefox Extensions Popup Steals Focus
On first launch, Firefox may show an "Extensions" popup that intercepts keyboard/mouse input intended for the Rancher login form.

**Fix:** Send `Escape` keypress before interacting with the login form:
```bash
DISPLAY=:1 xdotool key Escape
sleep 1
```

### 9. Login Form Coordinates (1920x1080 Display)
The Rancher login page field coordinates at `localhost/dashboard/auth/login`:
- Username field: (532, 577) — from (355, 385) in 1280x720
- Password field: (532, 645) — from (355, 430) in 1280x720
- "Log in with Local User" button: (531, 712) — from (354, 475) in 1280x720

Use direct mouse clicks with `ctrl+a` before typing to ensure fields are cleared:
```bash
DISPLAY=:1 xdotool mousemove 532 577 click 1
DISPLAY=:1 xdotool key ctrl+a
DISPLAY=:1 xdotool type --clearmodifiers "admin"
```

### 10. Keep Firefox Running Between Hooks
The post_start hook should leave Firefox running and logged in. Killing Firefox between hooks loses the session cookie. The pre_task hook then navigates the existing browser to the task-specific page via Ctrl+L → type URL → Enter.

## API Patterns

### Login
```bash
curl -sk "https://localhost/v3-public/localProviders/local?action=login" \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"Admin12345678!","responseType":"token"}' | jq -r '.token'
```

### List Namespaces
```bash
docker exec rancher kubectl get namespaces
```

### Create Namespace via API
```bash
docker exec rancher kubectl create namespace production
docker exec rancher kubectl label namespace production environment=production
```

### Deploy Workload
```bash
docker exec rancher kubectl create deployment web-frontend --image=nginx:latest --replicas=2
```

### Check Deployment
```bash
docker exec rancher kubectl get deployments -A
```

## Kubernetes Manifests
Real workloads are deployed via `docker cp` + `kubectl apply`:
- `namespaces.yaml`: Creates staging, monitoring, development namespaces
- `nginx-deployment.yaml`: Nginx 1.25-alpine (2 replicas) with ConfigMap and Service
- `redis-deployment.yaml`: Redis 7-alpine with ConfigMap, Service, resource limits
- `app-configmap.yaml`: ConfigMaps for each namespace with realistic config data

## Timing
- Docker + Rancher image pull (pre_start): ~2-5 minutes
- Rancher container start to API ready: ~3-5 minutes
- K3s cluster node Ready: ~1-3 minutes after API
- Workload deployment + rollout: ~1-2 minutes
- Firefox launch + cert + login: ~30-40 seconds
- Total environment boot (post_start): ~8-12 minutes

## Task Patterns

### create_namespace (easy)
- Pre-task: Delete production namespace, navigate to Namespaces page
- Agent task: Create "production" namespace with label environment=production via Rancher UI
- Verification: `kubectl get namespace production` + check labels

### deploy_workload (medium)
- Pre-task: Delete web-frontend deployment, navigate to Deployments page
- Agent task: Deploy "web-frontend" with nginx:latest, 2 replicas in default namespace
- Verification: `kubectl get deployment web-frontend` + check replicas/image

### scale_deployment (medium)
- Pre-task: Reset nginx-web to 2 replicas, navigate to deployment detail page
- Agent task: Scale nginx-web from 2 to 4 replicas via Scale widget or Config form
- Start state: Deployment detail page showing 2 Running pods, Scale widget visible

### edit_configmap (medium)
- Pre-task: Reset monitoring-config to original values, navigate to ConfigMap detail page
- Agent task: Edit prometheus.yml scrape_interval from 15s to 30s
- Start state: ConfigMap detail showing Data tab with prometheus.yml content

### upgrade_deployment (hard)
- Pre-task: Reset nginx-web image to nginx:1.25-alpine, pre-pull target image, navigate to detail
- Agent task: Change image to nginx:1.26-alpine and verify rollout completes
- Multi-step: Edit config → change image → save → verify pods updated

## Coordinate Scaling
- Visual grounding returns coordinates in 1280x720 space
- Scale to 1920x1080: `actual_x = cua_x * 1920 / 1280`, `actual_y = cua_y * 1080 / 720`
- Simplified: multiply by 1.5

## Navigation Pattern
- Use Ctrl+L → type URL → Enter for page navigation (more reliable than clicking sidebar links)
- Rancher URL patterns:
  - Dashboard: `localhost/dashboard/home`
  - Cluster Explorer: `localhost/dashboard/c/local/explorer`
  - Namespaces: `localhost/dashboard/c/local/explorer/namespace`
  - Deployments: `localhost/dashboard/c/local/explorer/apps.deployment`
  - Deployment detail: `localhost/dashboard/c/local/explorer/apps.deployment/staging/nginx-web`
  - ConfigMaps: `localhost/dashboard/c/local/explorer/configmap`
  - ConfigMap detail: `localhost/dashboard/c/local/explorer/configmap/monitoring/monitoring-config`
  - ConfigMap edit: append `?as=config` to detail URL
  - Deployment edit: append `?as=config` to detail URL
  - Login: `localhost/dashboard/auth/login`
