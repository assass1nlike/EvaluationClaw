> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# TiddlyWiki Environment Notes

## Architecture
- **No Docker needed**: TiddlyWiki runs natively on Node.js, so no Docker-in-QEMU setup
- **Node.js 18.x LTS** from nodesource repository
- **TiddlyWiki 5.3.8** installed globally via `npm install -g tiddlywiki`
- **Server**: `tiddlywiki mywiki --listen host=0.0.0.0 port=8080`
- **Base image**: `ubuntu-gnome-systemd_highres` (1920x1080)

## Key Implementation Details

### Tiddler File Format (.tid)
```
created: 20240118100000000
modified: 20240205140000000
tags: Science Biology Genetics
title: CRISPR Gene Editing

Body text starts after the blank line...
```

### WikiText Formatting
- `!` / `!!` / `!!!` for headings
- `''bold''` and `//italic//`
- `*` for bullet lists, `#` for numbered lists
- `[[Title]]` for internal links
- `|header|header|h` for tables

### Verification Approach
- All verification is filesystem-based, reading `.tid` files directly from `/home/ga/mywiki/tiddlers/`
- No REST API calls needed in export scripts (server may not reflect filesystem changes immediately)
- `task_utils.sh` provides shared functions: `tiddler_exists`, `get_tiddler_field`, `get_tiddler_text`, `count_user_tiddlers`, etc.

### Bugs Found and Fixed During Testing

1. **Filenames with spaces in bash**: Tiddler filenames can contain spaces (e.g., "CRISPR Gene Editing.tid"). Using `for f in $(find ...)` or `for f in $VAR` causes word splitting. **Fix**: Use `while IFS= read -r f; do ... done < <(find ...)` or `find ... | while IFS= read -r f; do`.

2. **Date matching in journal verifier**: The export produces `today_date` in `YYYYMMDD` format (e.g., `20260211`) while the title is "11 February 2026". A naive substring check fails. **Fix**: Parse year/day from the date string and check both are present in the title.

3. **`/tmp` file ownership**: Pre-task hooks run as root (via `sudo`), so files created in `/tmp` are owned by root. Post-task hooks also run as root, so this is fine in normal operation. Only manual testing as `ga` user exposes this.

## Seed Data
- 19 real-content tiddlers covering physics, biology, project management, philosophy, home renovation, and CS
- Interconnected with `[[internal links]]` between related tiddlers
- Uses proper TiddlyWiki formatting (tables, headings, lists, bold, italic)
- Includes Database Normalization tiddler (added during audit fix to resolve broken link)

## Tasks (5 total)
| Task | Difficulty | Key Verification |
|------|-----------|------------------|
| create_tiddler | Medium | Title, tags, word count, keywords, formatting |
| add_tags_to_tiddler | Easy | Tag addition, existing tags preserved, content preserved |
| create_journal_entry | Medium | Journal tag, date in title, word count |
| rename_tiddler | Medium | Old removed, new exists, tags/content preserved |
| create_tiddler_with_links | Hard | `[[internal links]]` syntax, link targets, keywords, tags |

## Testing Results (Live Environment, Feb 11 2026)

All 5 tasks tested on live QEMU environment (post two rounds of audit fixes):

| Task | Score | Status |
|------|-------|--------|
| create_tiddler | 100/100 | PASSED |
| add_tags_to_tiddler | 100/100 | PASSED |
| rename_tiddler | 100/100 | PASSED |
| create_tiddler_with_links | 100/100 | PASSED |
| create_journal_entry | 100/100 | PASSED |

### Anti-Gaming Verification

| Scenario | Score | Pass | Why |
|----------|-------|------|-----|
| create_tiddler DO-NOTHING | 0 | FAIL | new_count = 0 |
| add_tags DO-NOTHING | 25 | FAIL | No gui_save, no new tags |
| rename DO-NOTHING | 0 | FAIL | New title not found |
| create_tiddler DIRECT-FILE-EDIT | 75 | FAIL | gui_save required but not triggered |
| rename COPY-NOT-DELETE | 80 | FAIL | original_exists must be false |
| journal NO-DATE-IN-TITLE | 75 | FAIL | has_date_in_title required |
| links ONE-LINK-ONLY | 85 | FAIL | BOTH links required (AND) |

### Key Anti-Gaming Measures
1. **gui_save_detected** (20-25 pts, required for pass): Server log must show `Dispatching 'save' task:` entry. Direct `.tid` file edits don't trigger this.
2. **Trajectory analysis**: `_check_trajectory_for_gui_interaction(traj)` checks for mouse/keyboard actions in agent trajectory (informational).
3. **new_count > 0**: For creation tasks, new tiddler file must exist.
4. **Original deletion**: Rename task requires old title to NOT exist.
5. **Formatting bar**: Requires 2+ distinct formatting types (not just a single `*`).

### GUI Interaction Notes
- xdotool `type` has issues with TiddlyWiki's web editor for special characters (!, *, [[)
- Ctrl+A selects entire page, not just form fields
- Double-click to select a word works reliably for text replacement
- Escape key discards TiddlyWiki drafts - avoid using it near the editor
- REST API (`PUT /recipes/default/tiddlers/[name]`) is the most reliable way to create/modify tiddlers
- Search box in sidebar works well for navigating to tiddlers via xdotool
- ask_cua.py coordinates (1280x720) must be scaled: `actual = cua * 1920 / 1280` (x) and `actual = cua * 1080 / 720` (y)
