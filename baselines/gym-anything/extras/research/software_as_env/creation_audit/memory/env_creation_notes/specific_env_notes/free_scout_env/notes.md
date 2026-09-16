> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# FreeScout Environment Notes

## Overview
FreeScout is an open-source help desk / shared mailbox system (PHP/Laravel). The environment uses Docker-in-QEMU with `tiredofit/freescout` + `mariadb:10.11`.

## Architecture
- **Base image**: `ubuntu-gnome-systemd_highres` (1920x1080)
- **Docker containers**: `freescout-app` (port 8080:80) + `freescout-db` (MariaDB 10.11)
- **Admin credentials**: `admin@helpdesk.local` / `Admin123!`
- **DB credentials**: `freescout` / `freescout123`, database `freescout`

## Key Learnings

### FreeScout Docker Image (tiredofit/freescout)
- First boot takes 2-5 minutes for schema auto-setup (SETUP_TYPE=AUTO)
- Creates admin user via env vars: `ADMIN_EMAIL`, `ADMIN_PASS`, `ADMIN_FIRST_NAME`, `ADMIN_LAST_NAME`
- No FreeScout REST API available by default (requires paid module)
- No `freescout:create-mailbox` artisan command exists

### Database Schema Gotchas
- `emails` table has NO `created_at`/`updated_at` columns - only `id`, `customer_id`, `email`, `type`
- `conversations` table requires `folder_id` (NOT NULL) and `preview` (NOT NULL varchar)
- Raw SQL `INSERT INTO mailboxes` does NOT create folders (folders are created by Laravel ORM events)
- Raw SQL `INSERT INTO conversations` will fail unless `folder_id` and `preview` are provided

### ORM-based Data Creation (artisan tinker)
- **CRITICAL**: Use `artisan tinker` for creating mailboxes and conversations to trigger ORM events
- Mailbox creation via ORM auto-creates 8 folder types (inbox, drafts, trash, etc.)
- Conversation creation via ORM auto-assigns `number` but NOT `folder_id` - must set manually
- Tinker output contains Unicode ⏎ (U+23CE) character - strip with `tr -cd '0-9'`
- Helper functions: `ensure_mailbox_exists()`, `create_conversation_via_orm()` in task_utils.sh

### Conversation State & Visibility
- **CRITICAL**: Conversations need `state=2` (published) to show in folder listings. `state=1` = draft
- Threads need `state=3` (published), `first=1`, proper `customer_id` and `created_by_customer_id`
- `threads_count`, `preview`, `last_reply_at`, `last_reply_from` must be set for conversation to render in list
- Folder `total_count` and `active_count` must be >0 for badge to show
- Must call `artisan cache:clear` after ORM/SQL data changes for UI to reflect updates
- FreeScout folder types: 1=Unassigned, 20=Drafts, 25=Assigned, 30=Closed, 40=Spam, 60=Deleted, 70=Starred, 80=Mine

### UI Navigation Quirks
- **No standalone Customers page**: FreeScout has no "Manage > Customers" menu item. The Manage dropdown has: Settings, Mailboxes, Users, Modules, Translate, Logs, System.
- Customers are created implicitly through the conversation "To" field autocomplete (type email, select "(add)")
- Customer profiles are accessible only via direct URL: `/customers/{id}/edit`
- **No password field in user creation**: FreeScout's "New User" form has Role, First Name, Last Name, Email, mailbox assignments, and "Send invitation email" checkbox — but NO password field
- New Conversation is accessed via the envelope icon at the bottom of the mailbox sidebar
- The "To" field in New Conversation is a select2/autocomplete widget — must click to focus, then type

### Firefox (Snap)
- Firefox is installed as a snap on Ubuntu 22.04
- Snap profile location: `/home/ga/snap/firefox/common/.mozilla/firefox/`
- Traditional profile at `/home/ga/.mozilla/firefox/` is ignored by snap Firefox
- Must configure BOTH locations for compatibility
- **Sidebar**: Firefox 147+ has Nimbus experiment forcing sidebar on. Fix requires:
  - `sidebar.revamp=false`, `sidebar.main.tools=""`, `sidebar.nimbus=""`
  - Patch both `user.js` AND `prefs.js` after first launch
- **Pattern**: Launch Firefox once to create snap profile, kill, configure, relaunch

### Hook Execution
- All hooks run as **root** via `sudo -E` (framework wraps with sudo)
- `/tmp/` files created by setup hooks are owned by root
- Export and verify scripts must handle root-owned temp files (use `safe_write_result` pattern)

## Data Sources
All task data uses realistic names and emails sourced from the **Kaggle Customer Support Ticket Dataset** (`chiapudding/kaggle-customer-service`).

## Tasks (5 total)

| Task | Description | Data | Scoring |
|------|-------------|------|---------|
| `assign_conversation` | Assign "Payment issue" conversation to Admin User | Frank Sherman, floresbryan@example.net | 4 criteria (15+15+30+40), pass >= 75 |
| `update_customer_profile` | Fill in customer name on edit page | Christina Dillon, bradleyolson@example.org | 4 criteria (10+40+40+10), pass >= 80 |
| `create_user` | Create agent Rebecca Fleming with role 'user' | Rebecca Fleming, rebecca.fleming@helpdesk.local | 6 criteria (15+15+15+15+25+15), pass >= 70 |
| `create_conversation` | Create conversation about peripheral compatibility | clarkeashley@example.com, "Peripheral compatibility" | 6 criteria (15+15+25+20+15+10), pass >= 65 |
| `create_mailbox` | Create "Technical Support" mailbox | techsupport@helpdesk.local | 4 criteria, pass >= 70 |

## Audit Fixes Applied

1. **assign_conversation data mismatch**: Verifier default was "Billing discrepancy on invoice #4521" from previous version; fixed to "Payment issue"
2. **create_customer renamed to update_customer_profile**: Task ID was misleading
3. **Verifier hardcoded defaults**: Fixed stale defaults in create_conversation and create_user
4. **assign_conversation wrong-assignee partial credit**: Removed 15pt partial credit, raised threshold to 75
5. **update_customer_profile free email points**: Rebalanced from 30pt email to 10pt, names now 40pt each
6. **create_user role verification**: Added role='user' check (15pt)
7. **Nonce dead code**: Removed from all setup/export scripts
8. **Task description over-specificity**: Removed step-by-step GUI instructions

## Testing Results

All 5 tasks verified at **100/100** via interactive testing:
- `assign_conversation`: 100/100 - Conversation assigned to Admin User
- `update_customer_profile`: 100/100 - Name fields filled in on edit page
- `create_user`: 100/100 - Agent created with correct role
- `create_conversation`: 100/100 - Conversation sent with correct To/Subject/Body
- `create_mailbox`: 100/100 - Mailbox created with correct name/email

See `evidence_docs/` for screenshots and detailed verification logs.

## Files Structure
```
free_scout_env/
  env.json
  config/
    docker-compose.yml
  scripts/
    install_freescout.sh    # pre_start: installs docker, pulls images
    setup_freescout.sh      # post_start: docker-compose up, waits, configures Firefox
    task_utils.sh           # Shared: DB queries, ORM helpers, Firefox helpers
  tasks/
    assign_conversation/    # task.json, setup_task.sh, export_result.sh, verifier.py
    create_conversation/
    update_customer_profile/
    create_mailbox/
    create_user/
  evidence_docs/
    README.md               # Comprehensive evidence documentation
    *.png                   # Screenshots from interactive testing
```
