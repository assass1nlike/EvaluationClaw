> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# odoo_scheduling_env — Implementation Notes

## Overview

Odoo 17.0 Community with the `calendar` and `contacts` modules. Agents perform
calendar/scheduling tasks: creating meetings, setting reminders, filtering by
attendee, rescheduling, canceling events, etc.

## Architecture

- **Odoo 17.0 Community** in Docker (`/opt/odoo/docker-compose.yml`)
- **PostgreSQL 15** in a separate Docker container
- **Firefox (snap)** for web access
- **Database**: `odoo_scheduling`
- **Credentials**: `admin` / `admin`
- **Base image**: `ubuntu-gnome-systemd_highres`

## Key Lessons Learned

### 1. Snap Firefox + `-profile` flag = "Close Firefox" dialog

**Problem**: Passing `-profile /home/ga/.mozilla/firefox/odoo.profile` to snap Firefox
triggers a "Close Firefox" dialog even after removing lock files. Root cause is unknown
(likely a snap filesystem namespace conflict with the profile path).

**Fix**: Launch Firefox WITHOUT `-profile`. Snap Firefox reads its own `profiles.ini`
at `/home/ga/snap/firefox/common/.mozilla/firefox/profiles.ini`. Write this file before
launch so it points to `odoo.profile`.

```bash
mkdir -p "$SNAP_FF_MOZILLA/odoo.profile"
cat > "$SNAP_FF_MOZILLA/profiles.ini" << 'PROFILES_EOF'
[Profile0]
Name=odoo
IsRelative=1
Path=odoo.profile
Default=1

[General]
StartWithLastProfile=1
Version=2
PROFILES_EOF

DISPLAY=:1 setsid firefox 'about:blank' &
```

### 2. Hooks run as `ga` user — don't use `su - ga`

**Problem**: `su - ga -c "..."` blocks waiting for password even when already running as `ga`.

**Fix**: Hooks already run as `ga`. Just run commands directly:
```bash
DISPLAY=:1 setsid firefox 'about:blank' &
```

### 3. Firefox session restore after SIGKILL

**Problem**: `pkill -9 firefox` leaves `recovery.jsonlz4` AND `recovery.baklz4` in
`sessionstore-backups/`. Removing only `*.jsonlz4` misses `.baklz4` causing session
restore dialog on next launch.

**Fix**: Delete the entire directory and recreate empty:
```bash
rm -rf "$SNAP_FF_PROFILE/sessionstore-backups" 2>/dev/null || true
mkdir -p "$SNAP_FF_PROFILE/sessionstore-backups" 2>/dev/null || true
```

Also add to `user.js`:
```
user_pref("browser.startup.page", 0);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.sessionstore.max_resumed_crashes", 0);
```

### 4. Odoo 17 Calendar URL — `/odoo/calendar` returns 404

**Problem**: Odoo 17.0 Community's `calendar` module does NOT register the `/odoo/calendar`
route controller. Direct `GET /odoo/calendar` returns 404 (no redirect).
The `?action=` query parameter format is also ignored — loads default home (Discuss).

**Fix**: Use the legacy hash-based URL:
```
http://localhost:8069/web#action=calendar.action_calendar_event
```

This loads the Odoo web client (`/web`) and JS resolves the action XML ID.
The resulting window title is "Odoo - Meetings — Mozilla Firefox".

For event-specific deep links (cancel/reschedule tasks):
```
http://localhost:8069/web#id=$MEETING_ID&model=calendar.event&view_type=form
```

### 5. Odoo login click coordinates

After navigating to login page, autofocus on email field is unreliable. Click directly:
```bash
DISPLAY=:1 xdotool mousemove 996 350 click 1  # 1920x1080 maximized Firefox, Odoo 17
```

### 6. Do NOT launch Firefox in post_start

Snap Firefox launched in `post_start` leaves stale snap lock after savevm restore.
Each `pre_task` hook calls `ensure_firefox()` which is the FIRST launch from the
clean snapshot — no lock file issues.

## Data Setup

`scripts/setup_data.py` creates:
- **8 contacts**: Alice Johnson, Bob Williams, Carol Martinez, David Chen, Emma Thompson,
  Frank Rivera, Grace Patel, Henry Kim (all `@northbridge.org`)
- **15 calendar events** over 3 weeks anchored to next Monday
- **Alice Johnson appears in 5 events** (for `filter_calendar_by_attendee` task)

Named events used by specific tasks:
- `Q2 Financial Review` → `set_meeting_reminder` (alarm cleared at task start)
- `Product Roadmap Planning` → `set_meeting_location` (location cleared at task start)
- `Annual Performance Review - Frank Rivera` → `add_meeting_description` (description cleared)

Per-task events created fresh:
- `Financial Planning - Bob Williams` → `cancel_meeting`
- `Tax Advisory - Alice Johnson` → `reschedule_meeting`
- `Career Coaching Session - Emma Thompson` → `create_meeting` / `book_meeting`

## Tasks

| Task | Description |
|------|-------------|
| `create_meeting` | Create new calendar event with attendees |
| `book_meeting` | Create meeting with specific attendee |
| `filter_calendar_by_attendee` | Use People filter to show Alice's events only |
| `cancel_meeting` | Delete a meeting from the calendar |
| `reschedule_meeting` | Change meeting date by 1 week |
| `set_meeting_reminder` | Add 30-min email alarm to event |
| `set_meeting_location` | Set location field on existing event |
| `add_meeting_description` | Add description text to existing event |
| `create_all_day_event` | Create all-day event |
| `create_recurring_event` | Create weekly recurring event |

## Testing

```python
env = gym_anything.api.from_config('benchmarks/cua_world/environments/odoo_scheduling_env', task_id='create_meeting')
obs = env.reset(seed=42, use_cache=True, cache_level='post_start', use_savevm=True)
# pre_task takes ~48s (Firefox launch + Odoo login + navigation)
# Expected window title: "Odoo - Meetings — Mozilla Firefox"
```

## Timing

- `post_start` from cache: ~40-65s
- `pre_task` (ensure_firefox + login + navigate): ~48s
  - Firefox startup: 12s
  - Odoo login: 10s
  - Navigation to Calendar: 3s
