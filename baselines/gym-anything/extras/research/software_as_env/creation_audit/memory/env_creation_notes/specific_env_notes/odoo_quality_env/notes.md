> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Odoo Quality Environment Notes

## Application
- **Name**: Odoo 17 Community Edition (Quality module — custom addon)
- **Type**: ERP web application (Quality Management)
- **Docker image**: `odoo:17` (CE)
- **DB**: PostgreSQL 16 (`odoo-db` container)
- **Odoo URL**: `http://localhost:8069`
- **Admin login**: `admin` / `admin`
- **Database**: `odoo_quality`

## CRITICAL: Odoo CE Has No Quality Module

`quality` and `quality_control` are **Odoo Enterprise-only modules**. They do **not** exist in the `odoo:17` CE Docker image. There are no 'q' modules at all in the CE image.

### Solution: Custom Addon
Created a fully custom Odoo addon named `quality` in `addons/quality/` that provides:
- `quality.alert` model with kanban/list/form views, stage-based workflow
- `quality.alert.stage` model (New, In Progress, Done stages)
- `quality.alert.team` model
- `quality.point` (Quality Control Points) with pass/fail check support
- `quality.check` with `do_pass()` / `do_fail()` methods and inline buttons
- All menus under a "Quality" top-level menu

A stub `quality_control` addon depends on `quality` so `odoo -i quality_control` installs everything.

### Custom Addon Location
```
benchmarks/cua_world/environments/odoo_quality_env/addons/quality/         # main addon
benchmarks/cua_world/environments/odoo_quality_env/addons/quality_control/ # stub dependency
```

### Mounting Custom Addons
Three places must all be configured consistently:
1. **`env.json`** — mount source to `/workspace/addons`
2. **`setup_odoo.sh`** — Step 0 copies `/workspace/addons/*` to `/opt/odoo/addons/`
3. **`config/docker-compose.yml`** — volume `- /opt/odoo/addons:/mnt/extra-addons:ro`
4. **`config/odoo.conf`** — `addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons`

### CRITICAL: chmod -R 755 After Copying Addons
```bash
cp -r /workspace/addons/quality "$ODOO_DIR/addons/"
cp -r /workspace/addons/quality_control "$ODOO_DIR/addons/"
chmod -R 755 "$ODOO_DIR/addons/"   # REQUIRED: cp creates dirs with 750 by default
```
Without `chmod -R 755`: Odoo container user (non-root) cannot read the addon directories.
Symptom: `docker compose run` runs but loads only base modules (NOT quality_control).
Even though `/mnt/extra-addons` appears in the addons path log, the dirs are silently
unreadable, so modules are not scanned or installed.

## Odoo 17 View Syntax (CE Docker Image)

The `odoo:17` CE Docker image uses the **older view syntax**, not the new Odoo 17 syntax:
- Use `<tree>` (NOT `<list>`) for list views
- Use `view_mode = "tree,form"` (NOT `"list,form"`)
- Use `invisible="quality_state == 'pass'"` (NOT `attrs="{'invisible': [...]}"`)
- `attrs` and `states` attributes raise errors in this version

## URL Navigation

`http://localhost:8069/web#action=quality.action_quality_alert` works correctly once logged in.
- The XML ID resolves to the numeric ID (e.g., 283) and redirects properly
- `http://localhost:8069/odoo/quality` returns **404** — the custom addon does not register this route
- Numeric IDs work too: `#action=283` (but are fragile — prefer XML IDs)

### Action XML IDs and Typical Numeric IDs (after clean install)
| XML ID | Numeric ID | View |
|--------|-----------|------|
| `quality.action_quality_alert_team` | 282 | Quality Teams |
| `quality.action_quality_alert` | 283 | Quality Alerts |
| `quality.action_quality_point` | 284 | Quality Control Points |
| `quality.action_quality_check_tree` | 285 | Quality Checks |
| `quality.action_quality_alert_stage` | 286 | Alert Stages |

### Menu IDs
| XML ID | Numeric ID |
|--------|-----------|
| `quality.quality_menu_root` | 156 |
| `quality.quality_menu_alerts` | 157 |

## task_utils.sh Patterns

### XAUTHORITY (CRITICAL)
Export `XAUTHORITY=/run/user/1000/gdm/Xauthority` at the top of task_utils.sh.
`~/.Xauthority` is 0 bytes and breaks all xdotool/wmctrl/scrot commands silently.

### Firefox Launch (from root in pre_task hooks)
```bash
su - ga -c "DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority setsid firefox --new-instance about:blank > /dev/null 2>&1 &"
```
Key flags:
- `XAUTHORITY` must be explicit in the su command
- `--new-instance` avoids "already running" stale lock issues from snapshot restore
- No `-profile` flag needed — snap Firefox auto-detects its profile

### Login Coordinates (1920×1080 maximized Firefox)
- Email field: `xdotool mousemove 994 348 click 1`
- Then type `admin`, Tab, type `admin`, Return
- Wait 10s for Odoo to load

### Broken URL Pattern (avoid in task setup scripts)
- `ensure_firefox "http://localhost:8069/odoo/quality"` → 404 (wrong)
- Use `ensure_firefox` (default = login URL) then `navigate_firefox "...#action=quality.action_quality_alert"`

## setup_data.py — Many2many Field Format

Odoo XML-RPC ORM commands for Many2many fields:
```python
# CORRECT: Use (6, 0, [ids]) to set a many2many
"product_ids": [(6, 0, [cabinet_product_id])]
"picking_type_ids": [(6, 0, [receipts_id])]

# WRONG: Passing a list directly
"product_ids": [cabinet_product_id]  # raises TypeError
```

## Database Initialization

Fresh init command (CRITICAL: use `--without-demo all`):
```bash
docker compose run --rm --no-deps odoo odoo \
    -d odoo_quality \
    -i quality_control \
    --db_host=db --db_user=odoo --db_password=odoo \
    --without-demo all \
    --stop-after-init
```

If init fails partway (duplicate key errors on stock warehouse, etc.), must drop and recreate the DB:
```bash
docker exec odoo-db psql -U odoo -c "DROP DATABASE IF EXISTS odoo_quality;"
```

## odoo.conf Permissions

`config/odoo.conf` must be chmod 644 (world-readable) — the Odoo process inside Docker runs as user `odoo` (non-root) and will fail with Permission denied if the file is 640.

## Common XML Errors During Module Development

1. **`External ID not found: quality.action_quality_alert_stage`** — In a single XML file, `<menuitem>` referencing an action must appear AFTER the `<record>` that defines it. Move `<record>` definitions before the `<menuitem>` that references them.

2. **`Field "color" does not exist in model "quality.alert"`** — Kanban view uses `kanban_getcolor(record.color.raw_value)`. Must add `color = fields.Integer(default=0)` to the model.

3. **`duplicate key value violates unique constraint "stock_warehouse_warehouse_code_uniq"`** — Stale DB from failed init. Must `DROP DATABASE` and reinitialize.

## Data Setup (10 tasks, 2 products, 1 team, 3 stages, 2 QCPs, 4 alerts, 2 checks)

Products used:
- Cabinet with Doors (stock product)
- Acoustic Bloc Screens (stock product)

Quality Alerts (all in "New" stage):
1. Material Hardness Below Specification (Acoustic Bloc Screens, priority=High)
2. Critical Weld Failure on Frame (Cabinet with Doors)
3. Incorrect Spacing Between Components (Cabinet with Doors)
4. Paint Discoloration on Metal Panels (Cabinet with Doors)

Quality Control Points:
1. Incoming Parts Verification (Instructions, Cabinet with Doors, Receipts op)
2. Final Assembly Audit (Pass/Fail)

Quality Checks (both in "To Do" state):
1. Dimension Verification - Screen Width (Acoustic Bloc Screens)
2. Visual Inspection - Cabinet Finish (Cabinet with Doors, linked to Incoming Parts Verification)

Quality Teams:
- Quality Control Team

## 10 Tasks Summary

| Task | Start State | Agent Goal |
|------|-------------|-----------|
| `create_quality_alert` | Alerts kanban, no "Surface Cracks on Batch 001" | Create new alert |
| `pass_quality_check` | Checks list, "Visual Inspection" in To Do | Click Pass on check |
| `fail_quality_check` | Checks list, "Dimension Verification" in To Do | Click Fail on check |
| `create_quality_team` | Teams list, 1 team, no "Electronics QA Team" | Create new team |
| `add_corrective_action` | Alerts kanban, "Incorrect Spacing" has no corrective action | Open alert, add corrective action |
| `add_preventive_action` | Alerts kanban, "Material Hardness" has no preventive action | Open alert, add preventive action |
| `close_quality_alert` | Alerts kanban, "Paint Discoloration" in New stage | Open alert, move to Done |
| `set_alert_priority` | Alerts kanban, "Critical Weld Failure" at Normal priority | Open alert, set to High |
| `create_quality_control_point` | QCPs list, no "Cabinet Assembly Alignment Check" | Create new QCP |
| `set_control_point_failure_message` | QCPs list, "Incoming Parts Verification" has empty failure_message | Open QCP, set failure message |

## Snap Firefox Launch Notes

Profile location: `/home/ga/snap/firefox/common/.mozilla/firefox/3globcey.default`
(Profile name is auto-generated; the `3globcey` prefix will differ on fresh installs)

The headless warm-up in `setup_odoo.sh` creates the profile:
```bash
su - ga -c "DISPLAY=:1 firefox --headless about:blank > /dev/null 2>&1 &"
sleep 12; pkill -9 -f firefox
```

Lock files from snapshot restore must be cleared before launching:
```bash
find "$SNAP_FF_MOZILLA" -name "lock" -delete 2>/dev/null || true
find "$SNAP_FF_MOZILLA" -name ".parentlock" -delete 2>/dev/null || true
```

## Verification Status
- All 10 tasks verified interactively (2026-02-22)
- All task setup scripts run successfully as root via sudo
- All views (Quality Alerts kanban/list, Quality Checks list, Quality Control Points list, Quality Teams list) confirmed working
- Screenshots saved in `evidence_docs/`
