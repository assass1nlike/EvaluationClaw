> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# ArkCase Environment Notes

## Task Script Fixes (2026-03-16)

### Bugs Fixed
1. **`batch_tag_urgent_cases`**: Double `json.load(sys.stdin)` — second read fails because stdin already consumed. Fixed to read once into variable.
2. **`search_case_by_phrase`**: Killed Firefox but called `auto_login_arkcase` without relaunching. Added `ensure_firefox_on_arkcase` + sleep before login.
3. **`upload_and_duplicate_evidence`**: Same Firefox lifecycle bug. Fixed same way.
4. **`transcribe_paper_complaint`**: Firefox killed and never relaunched. Added launch + focus + maximize.
5. **`audit_complaint_cases`**: Called undefined `wait_for_window` function. Replaced with `sleep 15` + `focus_firefox`.
6. **`triage_complaint_case`**: Used `caseId` (wrong) instead of `complaintId`. Fixed with fallback chain.
7. **`reassign_complaint_case`**: Used `--no-remote` flag (causes profile lock issues). Removed.

### Infrastructure Fix: ECR Rate Limiting
- Added authenticated ECR public pulls to `install_arkcase.sh`
- Pre-pulls all 15 ArkCase images with retry/backoff during pre_start (before Helm deploy)
- Falls back gracefully if aws-cli install or auth fails

### Known Remaining Issues
- 12 tasks use `arkcase_api GET` which returns 500 with basic auth — most have fallback logic
- `pip install` during setup in 2 tasks (`transcribe_paper_complaint`, `upload_and_duplicate_evidence`)

---

## Overview
ArkCase is an open-source case management platform designed for FOIA requests, complaints, and legal case workflow management. It is deployed via K3s (lightweight Kubernetes) and the official Helm chart.

## Architecture
- **Base image**: `ubuntu-gnome-systemd_highres` (Ubuntu 22.04 with GNOME desktop, 1920x1080)
- **Resources**: 16GB RAM, 8 CPUs (minimum — ArkCase is heavy)
- **Deployment**: K3s (single-node Kubernetes) + Helm chart `arkcase/app`
- **Chart source**: `https://arkcase.github.io/ark_helm_charts/`
- **Services**: core (Tomcat/8443), rdbms (MariaDB), search (Solr), messaging (Artemis), ldap (Samba AD), content (MinIO), zookeeper, acme, app-proxy, app-artifacts
- **Total pods**: 10 pods required

## Critical Configuration

### Port-Forward (CRITICAL)
- **Use `pod/arkcase-core-0` NOT `svc/core`** — the core service uses haproxy which returns 503 via kubectl port-forward; direct pod access returns 200/302
- **Port**: Use 9443 external → 8443 internal (avoid 8443 directly due to conflicts)
- **Persistence**: Use `tmux` with an auto-restart loop — plain `nohup`, `disown`, or systemd all fail:
  ```bash
  KUBECONFIG=/etc/rancher/k3s/k3s.yaml tmux new-session -d -s arkcase \
    "while true; do KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl port-forward \
     -n arkcase pod/arkcase-core-0 9443:8443 --address 0.0.0.0 2>&1; sleep 2; done"
  ```
- Port-forward dies after each request without the loop (broken pipe error)

### Admin Credentials (CRITICAL)
- ArkCase Helm chart generates **random LDAP passwords** for all users
- Must reset after deploy: `kubectl exec -n arkcase arkcase-ldap-0 -- bash -c "samba-tool user setpassword arkcase-admin --newpassword='ArkCase1234!' 2>&1"`
- **Username format**: Must be email format `username@ldap-domain` — HTML form enforces pattern
- **LDAP domain**: `dev.arkcase.com` (configured in Helm chart values)
- **Final credentials**: `arkcase-admin@dev.arkcase.com` / `ArkCase1234!`

### Pentaho Secrets (CRITICAL)
Even when `reports.enabled: false`, the init-dependencies containers still reference:
- `arkcase-reports-admin` (keys: username, password, group, url)
- `arkcase-reports-main` (keys: username, password, url)

Must pre-create before helm install:
```bash
kubectl create secret generic arkcase-reports-admin \
    --namespace arkcase \
    --from-literal=username=pentaho-admin \
    --from-literal=password=PentahoAdmin123 \
    --from-literal=group=PentahoAdmin \
    --from-literal=url=http://localhost:8080/pentaho
```
Note: `group=PentahoAdmin` (NOT `pentaho-users` — conflicts with Samba AD built-in groups)

### LDAP Crash Loop
Samba AD pod (`arkcase-ldap-0`) crash-loops if PVC has partial provisioning from a failed first run:
- Error: `Failed to create the group [Administrator] - samAccountName 'Administrator' already in use!`
- Fix: Delete the LDAP PVC and let helm recreate it
- Detection: `kubectl describe pod arkcase-ldap-0 | grep "Restart Count"` >= 3

### SSL Certificate
ArkCase uses a self-signed TLS cert. Firefox snap profile NSS database must be updated:
```bash
# Get cert
kubectl exec -n arkcase arkcase-acme-0 -- cat /etc/ssl/certs/ca-certificates.crt > /tmp/arkcase.crt
# Import to Firefox snap NSS db
certutil -A -n "ArkCase-localhost" -t "CT,C,C" -i /tmp/arkcase.crt \
    -d sql:/home/ga/snap/firefox/common/.mozilla/firefox/g2s4ex1q.default
```

## ArkCase REST API

### Authentication
- **Basic auth works for POST**: `curl -u "arkcase-admin@dev.arkcase.com:ArkCase1234!" -X POST ...`
- **Basic auth does NOT support GET** (returns 500 "Request method 'GET' not supported")
- **Session auth via cookie works for all methods**:
  ```bash
  # Login to get session cookie
  curl -sk -c /tmp/arkcase_sess.txt \
      -d "username=arkcase-admin@dev.arkcase.com&password=ArkCase1234!" \
      -X POST https://localhost:9443/arkcase/login_post
  # Use session cookie for API calls
  curl -sk -b /tmp/arkcase_sess.txt -H "Accept: application/json" ...
  ```

### Creating Cases
- Endpoint: `POST /api/v1/plugin/complaint`
- **CRITICAL**: Field name is `complaintTitle` (NOT `title`!) — if you use `title`, it gets ignored
- Case ID field in response: `complaintId` (NOT `id` or `caseId`)
- Example payload:
  ```json
  {
    "caseType": "GENERAL",
    "complaintTitle": "FOIA Request - Example Case",
    "details": "Case details here",
    "priority": "Medium",
    "status": "ACTIVE"
  }
  ```

## Firefox Configuration

### Snap Profile Path
Firefox on Ubuntu 22.04 is installed as a snap:
- Profile path: `/home/ga/snap/firefox/common/.mozilla/firefox/g2s4ex1q.default`
- Must use `-profile` flag when launching: `firefox -profile <path> <url>`
- Do NOT use `--new-instance` (causes issues with profile locking)

### Profile Lock File Issue
When Firefox is killed forcefully (`pkill -9`) and immediately relaunched:
- `.parentlock` file may not be released immediately
- Solution: `find /home/ga -name ".parentlock" -delete 2>/dev/null`
- Wait 4+ seconds after `pkill -9` before trying to remove lock
- Remove from BOTH snap and non-snap paths

### Firefox Launch Pattern (Correct)
```bash
pkill -9 -f firefox 2>/dev/null || true
sleep 4
find /home/ga -name ".parentlock" -delete 2>/dev/null || true
find /home/ga -name "parent.lock" -delete 2>/dev/null || true

SNAP_PROFILE=$(find /home/ga/snap/firefox -name "prefs.js" 2>/dev/null | head -1 | xargs dirname 2>/dev/null || echo "")
if [ -n "$SNAP_PROFILE" ]; then
    su - ga -c "DISPLAY=:1 firefox -profile '$SNAP_PROFILE' 'https://localhost:9443/arkcase/login' &>/dev/null &" &
else
    su - ga -c "DISPLAY=:1 firefox 'https://localhost:9443/arkcase/login' &>/dev/null &" &
fi
sleep 15
```

## Wait for ArkCase
ArkCase returns HTTP 302 (redirect to home) when accessible (not 200 directly):
```bash
wait_for_arkcase() {
    local timeout=120
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        local http_code
        http_code=$(curl -skL --max-time 10 -o /dev/null -w "%{http_code}" "${ARKCASE_URL}/" 2>/dev/null)
        if [ "$http_code" = "200" ] || [ "$http_code" = "302" ]; then
            echo "ArkCase accessible (HTTP $http_code)"
            return 0
        fi
        sleep 10
        elapsed=$((elapsed + 10))
    done
}
```

## K3s Kubernetes
- Binary: `/usr/local/bin/k3s`
- Kubeconfig: `/etc/rancher/k3s/k3s.yaml` (root-only access, must use `KUBECONFIG=/etc/rancher/k3s/k3s.yaml`)
- Helm chart: `arkcase/app` from `https://arkcase.github.io/ark_helm_charts/`
- Namespace: `arkcase`
- `install_arkcase.sh` (pre_start hook): installs K3s + Helm + downloads chart
- `setup_arkcase.sh` (post_start hook): deploys via Helm, resets passwords, configures Firefox

## Tasks
5 tasks implemented:
1. `create_foia_request` — Create a new FOIA case
2. `add_complaint` — File a new complaint
3. `add_person` — Add a person to the contact directory
4. `assign_case_task` — Assign a task within an existing case (setup creates pre-existing FOIA case)
5. `close_case` — Close an existing FOIA case (setup creates pre-existing FOIA case)

All tasks start with ArkCase login page at `https://localhost:9443/arkcase/login`

## Known Issues / Lessons Learned
1. **Port-forward instability**: kubectl port-forward dies after each connection without the auto-restart loop in tmux
2. **Random LDAP passwords**: Must always reset admin password after fresh Helm deploy
3. **complaintTitle vs title**: API silently ignores `title`; must use `complaintTitle`
4. **GET not supported**: REST API doesn't support GET for listing cases; only POST creates work with basic auth
5. **Pentaho secrets always required**: Even with `reports.enabled: false`, init containers need the secrets
6. **samba group naming**: Don't use `pentaho-users` for the group field — it conflicts with Samba AD built-in groups
7. **Firefox profile locking**: Need 4+ second wait after `pkill -9` before removing `.parentlock` files
8. **wait_for_arkcase timing**: The curl check must use `-L` to follow redirects and check for 200 OR 302

## ArkCase Version
- Version: 25.09.00 (from Product Version displayed on login page)
- Deployed via Helm chart `arkcase/app`
