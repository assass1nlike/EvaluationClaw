> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Nuxeo Platform Environment Notes

**Status**: FULLY VERIFIED 2026-02-22 (all 10 task start states confirmed)

## Overview
- **Application**: Nuxeo Platform 10.10 (Enterprise Content Management)
- **Stack**: Docker Compose with official `nuxeo:10.10` image + nuxeo-web-ui package
- **Web UI**: Nuxeo Web UI 2.4.0 (Polymer 2.x / Web Components)
- **Port**: 8080 (HTTP)
- **Admin credentials**: `Administrator` / `Administrator`
- **REST API**: `http://localhost:8080/nuxeo/api/v1/`
- **Web UI**: `http://localhost:8080/nuxeo/ui/`

## Installation

### Docker Image
- Use `nuxeo:10.10` from Docker Hub (official image)
- The image includes nuxeo-web-ui pre-downloaded in `/opt/nuxeo/server/packages/`
- Install via: `NUXEO_PACKAGES: nuxeo-web-ui` in docker-compose.yml (installs from local cache)
- **Do NOT** use marketplace credentials — the local package installs without internet

### docker-compose.yml
```yaml
version: '3'
services:
  nuxeo:
    image: nuxeo:10.10
    environment:
      NUXEO_PACKAGES: nuxeo-web-ui
    ports:
      - "8080:8080"
    volumes:
      - nuxeo_data:/var/lib/nuxeo/data
volumes:
  nuxeo_data:
```

### docker-compose Version
- **Use `docker-compose` (v1 with hyphen)** — `docker compose` (v2 without hyphen) is NOT available
- All scripts must use `docker-compose` not `docker compose`

## Nuxeo Web UI Routing (CRITICAL)

The Web UI uses hash-based routing. Some route names are NOT obvious:

| Purpose | Correct URL |
|---------|-------------|
| Admin: Users & Groups | `#!/admin/user-group-management` |
| Admin: Vocabularies | `#!/admin/vocabulary-management` |
| Admin: Analytics | `#!/admin/analytics` |
| Admin: Audit | `#!/admin/audit` |
| Admin: Cloud Services | `#!/admin/cloud-services` |
| Admin: NXQL Search | `#!/admin/nxql-search` |
| Home/Dashboard | `#!/home` |
| Browse path | `#!/browse/<path>` |

**Wrong URL `#!/admin/users-groups` → blank page** (page name mismatch in iron-pages)

Routing is defined in `/opt/nuxeo/server/nxserver/nuxeo.war/ui/routing.html` inside the container.

## X11/xdotool User Permissions (CRITICAL)

- All wmctrl/xdotool/X11 commands MUST run as the `ga` user (not root)
- Root cannot manipulate windows owned by `ga`
- Use `ga_x()` helper: `sudo -u ga bash -c "DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority CMD"`

## Login Automation

The Nuxeo login form coordinates in maximized 1920x1080 Firefox:
- Username field: click at **(600, 564)** (form is left-centered, not at screen center)
- Tab from username → password (no need to click password field)
- After login (8s wait): dismiss password save dialog with `xdotool key Escape`
- **Important**: The form is at x≈600, NOT x≈960 (not screen center)

## Snap Firefox Launch

```bash
pkill -9 -f firefox 2>/dev/null || true
sleep 2
sudo -u ga bash -c "DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority \
    DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus' \
    firefox '$url' > /tmp/firefox_nuxeo.log 2>&1 &"
```
Note: `DBUS_SESSION_BUS_ADDRESS` is required for snap Firefox confinement.

## Nuxeo Data Setup

Initial data created via REST API in `setup_nuxeo.sh`:
- `Projects` workspace under `/default-domain/workspaces/`
- `Annual Report 2023` (File, 2.2MB) — contains real "Attention Is All You Need" PDF (arXiv:1706.03762)
- `Project Proposal` (File, 757KB) — contains real BERT paper PDF (arXiv:1810.04805)
- `Q3 Status Report` (Note) in Projects
- `jsmith` user (John Smith, jsmith@acme.com, in `members` group)

Real PDFs stored in `data/` directory (mounted to `/workspace/data/`):
- `annual_report_2023.pdf` (2.2MB, 15 pages) — arXiv:1706.03762
- `project_proposal.pdf` (757KB, 16 pages) — arXiv:1810.04805
- `quarterly_report.pdf` (435KB, 15 pages) — arXiv:1409.0473
- `q3_status_report.pdf` (6.5MB, 75 pages) — arXiv:2005.14165

### NXQL Version Filtering
Nuxeo NXQL includes document versions in results. Always add `AND ecm:isVersion=0` to NXQL queries to exclude archived versions:
```
SELECT * FROM Document WHERE ecm:path STARTSWITH '...' AND ecm:isTrashed=0 AND ecm:isVersion=0
```

### Document Name Normalization
Nuxeo auto-generates path name (slug) from title. Special characters → hyphens:
- "Annual Report 2023" → `Annual-Report-2023`
- "Q3 Status Report" → `Q3-Status-Report`
- "Project Proposal" → `Project-Proposal`

## REST API Patterns

```bash
NUXEO_AUTH="Administrator:Administrator"

# Create document
curl -s -u "$NUXEO_AUTH" -H "Content-Type: application/json" \
    -X POST "http://localhost:8080/nuxeo/api/v1/path/parent-path/" \
    -d '{"entity-type":"document","type":"Workspace","name":"name","properties":{"dc:title":"Title"}}'

# Check if exists
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "$NUXEO_AUTH" \
    "http://localhost:8080/nuxeo/api/v1/path/doc-path")

# Delete (soft - goes to trash)
curl -s -u "$NUXEO_AUTH" -X DELETE "http://localhost:8080/nuxeo/api/v1/id/$UID"

# Delete permanent
curl -s -u "$NUXEO_AUTH" -X DELETE "http://localhost:8080/nuxeo/api/v1/id/$UID?permanent=true"

# Remove tag
curl -s -u "$NUXEO_AUTH" -X DELETE \
    "http://localhost:8080/nuxeo/api/v1/path/doc-path/@tagging/tag-name"

# Remove ACL
curl -s -u "$NUXEO_AUTH" -H "Content-Type: application/json" \
    -X POST "http://localhost:8080/nuxeo/api/v1/path/doc-path/@op/Document.RemoveACL" \
    -d '{"params":{"acl":"local"}}'

# Remove from collection
curl -s -u "$NUXEO_AUTH" -H "Content-Type: application/json" \
    -X POST "http://localhost:8080/nuxeo/api/v1/id/$COLL_UID/@op/Collection.RemoveFromCollection" \
    -d '{"params":{"documents":["$DOC_UID"]}}'
```

## Task Design Notes

### 10 Tasks (all verified)
1. **create_user**: Creates user mwilson (Margaret Wilson). Verified via `GET /api/v1/user/mwilson`.
2. **create_workspace**: Creates Marketing Materials workspace. Verified via path check.
3. **upload_document**: Uploads Quarterly_Report.pdf to Projects. Verified via NXQL search.
4. **create_note**: Creates Meeting Minutes note in Projects. Verified via NXQL search.
5. **edit_document_metadata**: Edits Annual Report 2023 description. Verified by description content check.
6. **add_document_tag**: Adds 'finance' tag to Annual Report 2023. Verified via `@tags` adapter.
7. **add_comment**: Adds comment to Project Proposal. Verified via `@comment` adapter.
8. **grant_permissions**: Grants jsmith Read on Projects. Verified via `@acl` adapter.
9. **create_collection**: Creates '2024 Planning Documents' collection. Verified via NXQL.
10. **add_to_collection**: Adds Annual Report 2023 to 'Q4 2023 Documents'. Verified via `@collections` adapter.

### Verifier Pattern
All verifiers use `exec_in_env` to run curl commands against the Nuxeo REST API:
```python
def verify_task(traj, env_info, task_info):
    exec_in_env = env_info.get("exec_in_env")
    result = exec_in_env("curl -s -u Administrator:Administrator http://localhost:8080/nuxeo/api/v1/...")
```

## Startup Time
- Nuxeo 10.10 takes ~2-3 minutes to start after `docker-compose up -d`
- Use `wait_for_nuxeo()` with 180s timeout in pre_task hooks
- `setup_nuxeo.sh` uses 180s timeout with repeated curl checks

## Gotchas
1. **Docker compose**: `docker-compose` (v1) only — `docker compose` (v2) not available
2. **Web UI route names**: `user-group-management` NOT `users-groups`
3. **xdotool must run as ga**: Not root
4. **Login form position**: (600, 564) — left-side form, not screen center
5. **Nuxeo slug naming**: Auto-generates path names (hyphens for spaces)
6. **NXQL versions**: Add `AND ecm:isVersion=0` to exclude archived versions
7. **Snap Firefox**: Requires `DBUS_SESSION_BUS_ADDRESS` for proper launch
8. **Password save dialog**: Appears after login — dismiss with `xdotool key Escape`
