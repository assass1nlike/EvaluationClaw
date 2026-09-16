> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Manager.io Environment Notes

Env path: `benchmarks/cua_world/environments/manager_env/`
Date created: 2026-02-20
Application: Manager.io Server Edition (free, open-source accounting software)
Docker image: `ghcr.io/aliyusuf95/manager.io:latest`
Application version: 26.2.13.3181

---

## Architecture Summary

```
VM (Ubuntu 22.04, 6G RAM, 4 CPU)
└── Docker container: manager-server
    ├── Image: ghcr.io/aliyusuf95/manager.io:latest
    ├── Port: 0.0.0.0:8080→8080/tcp
    ├── Health check: GET /healthz every 10s
    └── Data volume: ./data:/data
        ├── 00000000000000000000000000000000.manager  (admin config)
        └── Northwind Traders.manager                 (business data)

Firefox (snap) running in DISPLAY=:1
└── navigate_manager.py (xdotool automation)
```

---

## Installation (pre_start hook): install_manager.sh

Key steps:
1. Install Docker CE via apt (docker.io package)
2. Download Docker Compose v2 binary from GitHub to `/usr/local/lib/docker/cli-plugins/docker-compose`
3. Add `ga` user to docker group
4. Install xdotool, wmctrl (for GUI automation)
5. Set up snap Firefox with a custom `manager.profile`
6. Configure Firefox profiles.ini to use manager.profile as default

**Important**: Docker Compose v2 must be installed as a CLI plugin, not the v1 `docker-compose` binary. Use `docker compose` (space, not hyphen).

**Important**: Firefox snap profile at `~/snap/firefox/common/.mozilla/firefox/manager.profile/` (NOT `~/.mozilla/firefox/manager.profile/`). The classical path is a symlink that doesn't include the lock files.

---

## Setup (post_start hook): setup_manager.sh + setup_data.sh

1. `setup_manager.sh`: Starts Manager.io via `docker compose up -d`, waits for health check
2. `setup_data.sh`: Populates the business via Manager.io's web API (curl POST requests):
   - Creates "Northwind Traders" business
   - Enables 12 modules: Bank accounts, Receipts, Payments, Customers, Sales Invoices, Credit Notes, Suppliers, Purchase Invoices, Debit Notes, Inventory, Journal Entries, Reports
   - Creates 2 customers: Alfreds Futterkiste, Ernst Handel
   - Creates 1 supplier: Exotic Liquids
   - Creates 1 bank account: Cash on Hand

**API format**: Manager.io uses base64-encoded protobuf keys in POST payloads (not standard REST JSON). Data extracted by creating real entries and using `curl -s http://localhost:8080/<business_key>/customers-form?key=<item_key>` to get saved keys.

---

## Task Setup (pre_task hook): navigate_manager.py

Navigate Manager.io to a specific module and optionally open a new entry form:
```bash
python3 navigate_manager.py <module> [new]
```

### Firefox startup sequence (in start_firefox()):
1. `pkill -9 -f firefox` — kill existing Firefox
2. `systemctl --user stop/reset-failed snap.firefox.firefox*.scope` — clear systemd user scope
3. Remove lock files: both `~/.mozilla/firefox/manager.profile/.parentlock` AND `~/snap/firefox/common/.mozilla/firefox/manager.profile/.parentlock`
4. Launch: `setsid firefox --no-remote --new-window http://localhost:8080/`
   - Do NOT pass `-profile` flag — `profiles.ini` already sets manager.profile as default
   - `--no-remote` bypasses existing-instance IPC detection
5. Wait 12s for Firefox to load
6. `wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz` — maximize Firefox
7. Detect "Restore Session" page (from SIGKILL crash) → navigate via Ctrl+L

### Login sequence (in login()):
- Manager.io single-step login: username → click Next (no password)
- Credentials: `administrator` / (empty)
- LOGIN_USERNAME_COORDS = (998, 417) in 1080p
- LOGIN_NEXT_COORDS = (836, 468) in 1080p

### Business selection (in select_northwind()):
- BUSINESS_LINK_COORDS = (861, 368) in 1080p
- The Northwind Traders link appears as first (and only) business in the list

### Sidebar navigation:
All sidebar items at **x=154 in 720p = x=231 in 1080p** (verified via visual_grounding 2026-02-20).
Firefox window geometry: position (70, 101), size (1850 × 1016).

| Module | y (720p) | y (1080p) |
|--------|----------|-----------|
| summary | 238 | 357 |
| bank_accounts | 263 | 395 |
| receipts | 288 | 432 |
| payments | 313 | 470 |
| customers | 337 | 506 |
| sales_invoices | 362 | 543 |
| credit_notes | 387 | 581 |
| suppliers | 411 | 617 |
| purchase_invoices | 436 | 654 |
| debit_notes | 461 | 692 |
| inventory | 485 | 728 |
| journal_entries | 510 | 765 |
| reports | 535 | 803 |
| settings | 560 | 840 |

### New button:
NEW_BUTTON_COORDS = (582, 468) in 1080p
(Measured from live screenshot: "New Customer" button at (388, 312) in 720p)

---

## Known Issues / Gotchas

### 1. Firefox "Close Firefox" dialog (stale lock file)
**Cause**: After `pkill -9 firefox`, snap Firefox leaves `.parentlock` at the snap path (not classical path). Also, the systemd user scope (`snap.firefox.firefox*.scope`) persists and makes new Firefox think an instance is running.
**Fix**: Remove locks from BOTH paths AND stop the systemd scope before relaunch.

### 2. Firefox "Restore Session" page
**Cause**: SIGKILL prevents Firefox from doing clean shutdown, triggering crash recovery on next launch.
**Fix**: Detect "Restore Session" in window title, navigate to Manager URL via Ctrl+L.

### 3. 9p virtio mount caching (testing only)
**Cause**: QEMU's virtio-9p (virtio filesystem) caches files aggressively. After editing files on the host, the VM may serve stale content from /workspace.
**Fix during testing**: `sudo mount --bind /home/ga/updated_file.py /workspace/scripts/updated_file.py`
This is NOT an issue at runtime (hooks copy files before VM starts).

### 4. Docker Compose v1 vs v2
**Cause**: `docker-compose` (v1, separate binary) is not installed. Only Docker Compose v2 (plugin) is available.
**Fix**: Use `docker compose` (space) everywhere — in scripts, task_utils.sh, etc.

### 5. Manager.io API format
**Cause**: Manager.io does not expose a simple REST API. Business data is encoded as base64 protobuf keys in POST bodies.
**Fix**: Use pre-computed base64 key blobs in `setup_data.sh`. To get new keys, create entries manually via the UI, then inspect the POST requests with browser dev tools.

### 6. VNC password: use `vnc.password` not `vnc_password` in env.json
**Cause**: The QEMU runner reads VNC password from `spec.vnc.password` (the VNCSpec object), NOT from the top-level `vnc_password` field. If only `vnc_password` is set, `spec.vnc.password` is None, and QEMU gets `change vnc password None`, causing VNC auth to block forever.
**Fix**: In env.json, use a `"vnc"` section:
```json
"vnc": {
  "password": "password"
}
```
NOT `"vnc_password": "password"` (top-level field is ignored by QEMU runner).

### 7. Running as ga (non-root) vs root
**Cause**: The `ga` SSH user cannot `su - ga` (circular). Hooks run as root (via cloud-init/hooks), so `su - ga` works from hooks, but not from SSH sessions as `ga`.
**Fix in navigate_manager.py**: `os.getuid() == 0` check — use `su - ga` if root, run directly if ga.

---

## Tasks (10 total)

| Task directory | Module | Action |
|----------------|--------|--------|
| create_customer | customers | new |
| create_sales_invoice | sales_invoices | new |
| record_receipt | receipts | new |
| create_supplier | suppliers | new |
| create_purchase_invoice | purchase_invoices | new |
| add_inventory_item | inventory | new |
| create_journal_entry | journal_entries | new |
| view_balance_sheet | reports | (navigate only) |
| create_credit_note | credit_notes | new |
| generate_aged_receivables | reports | (navigate only) |

---

## Verification

See `evidence_docs/` for screenshots and log snippets confirming:
- Manager.io running and healthy in Docker
- Northwind Traders business with seed data (2 customers, 1 supplier, 1 bank account)
- All 10 task setup scripts navigating correctly via Firefox xdotool automation

---

## Audit Fixes (2026-02-20)

### Form Fields Confirmed (from live screenshots)

**Customer form**: Name, Code (optional), Credit Limit (optional), Address (multiline), Email, Image upload
- NO "Contact Person" field
- NO "Phone" field

**Supplier form**: Name, Code (optional), Credit Limit (optional), Address (multiline), Email, Image upload
- Same as customer form — no Contact Person or Phone

**Sales Invoice form**: Date, Reference (optional), Customer dropdown, Order number (optional), Due date; Line items: Item (optional inventory picker), Description, Account (required income account), Qty, Unit Price, Discount
- When no inventory items seeded: leave Item blank; fill Description + Account + Qty + Unit Price
- "Sales" account exists in GL by default (enabled with Sales Invoices module)

**Receipt form**: Date, Reference (optional), "Paid By" > Contact (customer dropdown), "Received In" > Account (bank account dropdown); Line items: Account (GL account), Amount
- "Cash on Hand" appears in "Received In > Account" dropdown (bank accounts)
- "Cash on Hand" does NOT appear in Journal Entry Account dropdown (it's a bank module account, not a GL account)

**Journal Entry form**: Date, Reference (optional), Narration (text field), Line items: Account (GL dropdown), Debit, Credit
- Account dropdown default: "Suspense"
- Confirmed-existing accounts: "Accounting fees", "Advertising and promotion", "Bank charges", "Computer equipment", "Donations" (all Expenses); "Retained earnings" (Equity)
- Bank accounts (e.g., "Cash on Hand") do NOT appear in Journal Entry Account dropdown

**Credit Note form**: Issue date, Reference, Customer dropdown, Sales Invoice dropdown (optional), Billing address, Description; Line items: Account, Qty, Unit Price
- Similar to Sales Invoice form

### Task Description Corrections

| Task | Issue | Fix |
|------|-------|-----|
| create_customer | Referenced non-existent Contact Person/Phone fields | Replaced with Code (BRT-001) and Credit Limit (25000) |
| create_supplier | Same — Contact Person/Phone don't exist | Replaced with Code (PIS-001) |
| create_sales_invoice | Referenced non-existent "Chai/Chang" inventory items | Changed to Description+Account-based entries (Consulting Services, 10×150.00; Software Support, 1×500.00) |
| record_receipt | Hedged "link invoice if available" (no invoices exist) | Concrete instructions: Paid By=Alfreds Futterkiste, Received In=Cash on Hand, Amount=440.00, no invoice linking required |
| view_balance_sheet | Implied non-zero data | Added clarification: values may be 0.00 in fresh business |
| generate_aged_receivables | Implied non-empty data ("identify customer with largest balance") | Clarified report may be empty; 0.00 is valid result |
| create_journal_entry | Used "Prepaid Expenses (or equivalent)" — account may not exist | Changed to "Accounting fees" (debit) and "Retained earnings" (credit) — both confirmed to exist |

