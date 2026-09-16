> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# 2N Access Commander Environment Notes

## Summary
Environment for 2N Access Commander (physical access control web app by Axis/2N Telecommunications).
Uses nested QEMU/KVM to run the official OVA appliance inside the outer VM.

## OVA Acquisition (CRITICAL)
- 2N Access Commander is distributed **only as an OVA** (not as Docker image or Linux package)
- The OVA must be downloaded from: https://www.2n.com/en-GB/download-center/?product=2n-access-commander
- Download is from the "Software & Firmware" section of 2N Download Center
- Place the OVA at: `benchmarks/cua_world/environments/twon_access_commander_env/data/access_commander.ova`
- Free "Lite" tier (1 device, 5 users) is available without purchase
- Default credentials: `admin` / `2n`

## Why NOT acdemo.2n.com (Online Demo)
- acdemo.2n.com shows a registration form, NOT a login page
- Requires email registration + Google reCAPTCHA (server-side validated)
- The `/api/register/email` endpoint requires `g-recaptcha-response` header — cannot be bypassed
- `PUT /api/v3/auth` with any credentials returns HTTP 500 (demo assigns per-user instances)
- **Cannot be used for automated benchmark environments**

## Architecture
- **Outer VM**: Ubuntu 22.04 GNOME, 8GB RAM, 4 CPU (`mem_gb: 8` required)
- **Inner VM**: 2N Access Commander OVA running as nested QEMU/KVM (2GB RAM, 2 CPUs)
- **Port forwarding**: outer `localhost:9443` → inner `:443`; outer `localhost:9080` → inner `:80`
- **Nested KVM**: Confirmed working — AMD EPYC 9354 with SVM flag; `-cpu host` passes it through
- **AC URL**: `https://localhost:9443` (self-signed TLS cert)
- **Firefox**: Snap Firefox (Ubuntu 22.04's default `firefox` package is snap-wrapped)

## Snap Firefox on Ubuntu 22.04 (CRITICAL)
- `apt-get install firefox` installs a snap wrapper → `firefox` binary actually runs snap
- Snap Firefox profile is at: `/home/ga/snap/firefox/common/.mozilla/firefox/`
- NOT at `~/.mozilla/firefox/` (which is empty)
- Detection: `if [ -d "/home/ga/snap/firefox/common/.mozilla/firefox" ]` → use snap path
- Launch: `su - ga -c "DISPLAY=:1 XAUTHORITY=... DBUS_SESSION_BUS_ADDRESS=... setsid firefox --new-instance -profile '...' 'url' &"`
- GTK warnings (`canberra-gtk-module cannot be loaded`) are harmless — ignore

## Install Hook (pre_start)
All packages successfully installed on Ubuntu 22.04:
- `qemu-system-x86`, `qemu-utils`, `ovmf`, `bridge-utils`, `cpu-checker` → nested QEMU
- `firefox` (snap wrapper), `libnss3-tools`, `wmctrl`, `xdotool`, `scrot`, `jq`, `xclip`
- Python `requests` via pip (pre-installed as system package in Ubuntu 22.04)

## Setup Hook (post_start) Pattern
1. Define helper functions (`_setup_firefox_profile`, `_launch_firefox`) **BEFORE** OVA check
2. Check for OVA at `/workspace/data/access_commander.ova`; if missing → graceful fallback
3. Extract OVA: `tar xf access_commander.ova -C /home/ga/ac_vm/`
4. Convert VMDK: `qemu-img convert -f vmdk -O qcow2 *.vmdk /home/ga/ac_disk.qcow2`
5. Launch inner VM: `qemu-system-x86_64 -enable-kvm -m 2048 -smp 2 -drive file=... -netdev user,id=net0,hostfwd=tcp::9443-:443 -device e1000,netdev=net0 -display none -daemonize`
6. Poll `https://localhost:9443` up to 300 seconds (AC takes ~3-5 min to boot)
7. Set up snap Firefox profile; optionally add cert via certutil
8. Launch Firefox to `https://localhost:9443`

**IMPORTANT**: `-daemonize` flag not universally supported; fallback to `nohup ... &`

## TLS Certificate Handling
- 2N AC uses self-signed TLS cert at `localhost:9443`
- Approach: `certutil -A -d sql:$PROFILE_DIR -n "2NAccessCommander" -t "CT,," -i cert.pem`
- Cert extracted via: `openssl s_client -connect localhost:9443 -servername localhost </dev/null | openssl x509 -outform PEM`
- Firefox NSS database must be initialized first: `certutil -N -d sql:$PROFILE_DIR --empty-password`
- Also set in user.js: `security.tls.insecure_fallback_hosts = "localhost"`, `security.enterprise_roots.enabled = true`

## REST API Pattern (for verifiers)
```python
import requests, urllib3
urllib3.disable_warnings()
s = requests.Session()
s.verify = False
resp = s.put("https://localhost:9443/api/v3/auth",
             json={"login": "admin", "password": "2n"}, timeout=15)
# resp.status_code should be 200 or 201
users = s.get("https://localhost:9443/api/v3/users", timeout=15).json()
```

## QEMU Savevm and Nested VM (IMPORTANT)
- With `-daemonize`, inner QEMU runs as background process inside outer VM
- When outer VM's state is saved (`savevm`), inner QEMU process IS included
- When loadvm restores, inner QEMU resumes → 2N AC available immediately
- This means: once setup completes successfully (with OVA), subsequent task setups will be fast

## 10 Tasks
1. `create_user` — Create "Heather Morrison" with email/phone/company
2. `assign_rfid_card` — Assign card "0013988412" to "Derek Caldwell"
3. `create_user_group` — Create "Maintenance Staff" group
4. `add_user_to_group` — Add "Sandra Okafor" to "Reception Team" group
5. `set_user_pin` — Set PIN "47219" for "Marcus Webb"
6. `create_time_profile` — Create "Office Hours" Mon-Fri 08:00-18:00
7. `navigate_access_logs` — Filter access logs by "Access Denied"
8. `update_user_email` — Change "Priya Nair" email to `priya.nair@securefacilities.org`
9. `disable_user` — Deactivate "Victor Schulz"
10. `remove_card_from_user` — Remove card "0007654321" from "Leon Fischer"

## Pre-seeded Data (created in setup_task.sh for each task)
- Each task pre-creates required users/groups via REST API before navigating Firefox
- API calls use cookie-based sessions (`PUT /api/v3/auth` → cookie jar)
- 2N AC API v3: users at `/api/v3/users`, groups at `/api/v3/groups`, creds at `/api/v3/users/{id}/credentials`
- Cleanup at task start: delete any leftover test data from prior runs

## Verified Working (2026-02-22)
- **pre_start hook**: All packages install correctly (Firefox 146.0, QEMU 6.2.0)
- **post_start hook**: Handles missing OVA gracefully; launches Firefox to localhost:9443
- **Snap Firefox**: Launches correctly from `su - ga -c "... setsid firefox ..."`
- **Snap profile path**: `/home/ga/snap/firefox/common/.mozilla/firefox/accommander.profile`
- **Task pre_task hook**: Handles unavailable inner VM gracefully (wait timeout → proceed)
- **Full flow with OVA**: Not tested (OVA requires 2N download center access)

## Known Issues / Gotchas
1. **Script function ordering**: Helper functions must be defined BEFORE they are called (bash scoping)
2. **pre_task wait time**: `wait_for_ac_demo` waits up to 300s; with savevm this should be instant
3. **certutil path**: certutil is in `libnss3-tools`; NSS DB must be initialized before adding cert
4. **Inner VM boot time**: 2N AC takes 3-5 minutes to fully initialize after QEMU starts
5. **OVA size**: Typically 2-4GB; disk conversion creates another 2-4GB QCOW2 file; ensure adequate disk
6. **QEMU daemonize**: `-daemonize` requires QEMU to be in PATH; fall back to `nohup &` if needed
