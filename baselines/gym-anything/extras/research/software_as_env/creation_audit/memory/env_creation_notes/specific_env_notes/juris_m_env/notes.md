> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# juris_m_env — Environment Notes

## Application
**Juris-M (Jurism)** — legal-focused reference manager based on Zotero 6. Adds multi-jurisdiction citation support and legal citation styles (OSCOLA, Bluebook, etc.).

## Version
Jurism 6.0.30m3 (Linux x86_64)

## Download
```
https://github.com/Juris-M/assets/releases/download/client/release/6.0.30m3/Jurism-6.0.30m3_linux-x86_64.tar.bz2
```
Fallback: `https://jurism.net/jurism/dl?channel=release&platform=linux-x86_64`

## Installation Notes
- Extract to `/opt/jurism` (binary: `/opt/jurism/jurism`)
- Symlink: `/usr/local/bin/jurism -> /opt/jurism/jurism`
- Run `./set_launcher_icon` after extraction if present
- Dependencies: libgtk-3-0, libdbus-glib-1-2, libxt6, libx11-xcb1

## Profile and Data Directories
- Profile: `/home/ga/.jurism/jurism/*.default` (NOT `~/.zotero/zotero` like Zotero)
- Data directory: `/home/ga/Jurism/` (configured via prefs.js)
- Main database: `/home/ga/Jurism/jurism.sqlite` (NOT `zotero.sqlite`)
- Also present: `/home/ga/Jurism/abbrevs-filter.sqlite` (do NOT use this)

## Database Schema (Jurism 6)
The `items` table requires `libraryID` (INT NOT NULL) and `key` (TEXT NOT NULL) — different from Zotero 5!

### Item Type IDs (verified from live DB)
| Type | ID |
|------|----|
| case | 9 |
| journalArticle | 24 |
| book | 7 |

### Field IDs (verified from live DB)
| Field | ID |
|-------|----|
| title | 1 |
| abstractNote | 2 |
| publicationTitle | 7 |
| date | 8 |
| caseName | 58 |
| court | 60 |
| reporterVolume | 66 |
| firstPage | 67 |
| dateDecided | 69 |
| issue | 72 |
| reporter | 49 |
| pages | 47 |
| volume | 22 |
| ISSN | 108 |

### Inserting Items Programmatically
```python
import random, string
key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
cursor.execute(
    "INSERT INTO items (itemTypeID, dateAdded, dateModified, clientDateModified, libraryID, key) VALUES (?, ?, ?, ?, ?, ?)",
    (type_id, now_str, now_str, now_str, 1, key)
)
```
`libraryID=1` is always the user library (confirmed from `libraries` table).

## CRITICAL: Jurism 6.0.30m3 RIS Import Bug — KW Tags Cause Rendering Error

**Symptom**: After RIS import with `KW` (keyword) tags or `DA`/`PY` (date) tags, Jurism shows
"An error has occurred. Please restart Zotero." on the render cycle after clicking Finish.
This error persists across restarts. The items ARE imported to DB but cannot be displayed.

**Root Cause**: `KW` tags (stored as `itemTags`) and `DA`/`PY` date tags both trigger Jurism to
write `db|integrityCheck|1` to the `settings` table. On startup/render, Jurism runs its integrity
check, which fails or enters a broken state, showing the error.

**Fix**: Remove ALL `KW  - ...` and `DA`/`PY` date lines from the RIS file.
The import will work correctly with case names, courts, reporters, volumes, pages, abstracts,
journal names, ISSNs, and authors — but without dates and keywords.

**Evidence**: Confirmed via bisection testing:
- RIS with KW tags → integrityCheck=1 → error
- RIS with DA/PY dates → integrityCheck=1 → error
- RIS without KW or dates → integrityCheck NOT set → import works, items visible
- Plain Python injection (no tags/dates) → no integrityCheck → works

**Also CRITICAL**: When manually deleting items from the DB (via sqlite3 commands) after a
failed RIS import, do NOT leave a SQLite journal file. Kill Jurism, delete items, commit cleanly.
Messy DB operations (multiple scripts, partial deletes, etc.) compound the issue.

## RIS Import Field Mapping
Jurism's RIS.js translator maps fields differently for case vs. article types:

| RIS Tag | Case Field | Article/Other Field |
|---------|-----------|---------------------|
| TI | caseName | title |
| PB | court | publisher |
| A2 | reporter | secondary author |
| VL | reporterVolume | volume |
| SP | firstPage | startPage |
| PY | dateDecided | date |
| AU | (unused) | author |
| JO | (unused) | journal |

**CRITICAL**: The `CT` RIS tag maps to `title` (overwriting `caseName` for case items). NEVER use `CT` tag for court name in Jurism RIS imports. Use `PB` instead.

## First-Launch Dialogs
Jurism shows an **"Alert"** dialog: *"Configured 121 jurisdictions. Restart Jurism to install the updated configuration."* on first launch.

Dismiss with:
```bash
for attempt in 1 2 3; do
    ALERT_WID=$(DISPLAY=:1 xdotool search --name "Alert" 2>/dev/null | head -1)
    if [ -n "$ALERT_WID" ]; then
        DISPLAY=:1 xdotool key --window "$ALERT_WID" Return 2>/dev/null || true
        sleep 1
    fi
done
```

## Database Locking Pattern
The DB is locked while Jurism is running. **Always kill Jurism before querying or modifying the DB in setup scripts:**

```bash
pkill -f /opt/jurism/jurism 2>/dev/null || true
sleep 3
# ... do DB operations ...
# ... relaunch Jurism ...
setsid sudo -u ga bash -c 'DISPLAY=:1 /opt/jurism/jurism --no-remote >> /home/ga/jurism.log 2>&1 &'
sleep 18  # Wait for Jurism to fully start
```

## Task Setup Pattern
Each task's setup_task.sh should:
1. Kill Jurism (for DB access)
2. Inject/clear references as needed
3. Relaunch Jurism (sleep 18 for full startup)
4. Dismiss alert dialogs
5. Maximize and focus Jurism window

## Window Title
Jurism window title: `"My Library - Jurism"` — wmctrl search works with `-r "Jurism"`.

## Tasks Created
1. **import_legal_references** — Import supreme_court_cases.ris via File > Import (library starts empty)
2. **create_law_collection** — Create "US Constitutional Law" collection and add ≥3 items
3. **add_note_to_case** — Add note to Brown v. Board of Education
4. **change_citation_style** — Change to OSCOLA citation style via Edit > Preferences > **Export** tab > Item Format dropdown (NOT the Cite tab — Quick Copy is in Export)
5. **add_manual_case** — Manually add Roe v. Wade as a Case item with all fields

## Real Legal Data
All references are real historical US legal cases/articles:
- 7 US Supreme Court cases (Brown v. Board of Education, Miranda v. Arizona, etc.)
- 3 law review articles (Holmes, Monaghan, Poe)
- Data file: `assets/sample_data/supreme_court_cases.ris`
- Direct injection: `utils/inject_references.py <db_path>`

## Quick Copy Citation Style — CRITICAL UI Discovery
The **Quick Copy** setting (for changing citation style output format) is in the
**Export tab** of Preferences (Edit > Preferences > Export), NOT the Cite tab.

- Export tab → Quick Copy section → "Item Format:" dropdown
- OSCOLA CSL ID: `http://juris-m.github.io/jm-styles/jm-oscola`
- Pre-installed at: `/home/ga/Jurism/styles/jm-oscola.csl`
- Start state normalized via `user.js` in the profile dir (overrides prefs.js on every startup)
- The key pref written on style change: `extensions.zotero.export.quickCopy.setting`
  Format: `"bibliography=<csl-url>"`

## Verified Item Type IDs (Jurism 6)
| Type | ID | Notes |
|------|----|-------|
| case | 9 | Legal cases |
| journalArticle | 24 | |
| book | 7 | |
| annotation | 1 | Exclude from item count |
| note | 3 | Exclude from item count |
| attachment | 31 | Exclude from item count |

Use `WHERE itemTypeID NOT IN (1,3,31)` for user-visible item counts.

## Audit-Driven Fixes Applied (Feb 2026)
The environment was audited and the following fixes were applied:
1. **Real verifiers** added to all 5 tasks (replaced stubs)
2. **export_result.sh** added to all 5 tasks (post_task hook)
3. **add_manual_case** setup rewrote: proper cleanup (removes Roe v. Wade, clears collections/notes/tags), deterministic start state
4. **change_citation_style** setup: writes user.js to normalize Quick Copy to Chicago on startup
5. **RIS file** fixed: removed non-standard A2 fields, but note that DA/PY/KW tags cause Jurism integrity check errors (removed from RIS; dates injected via inject_references.py only)
6. **validated_pi.json** added to all 5 tasks
7. **env.json**: removed empty config/ mount
8. **task_utils.sh**: added DBUS_SESSION_BUS_ADDRESS to ensure_jurism_running

## Evidence
- `evidence_docs/README.md` — Full evidence documentation for all 5 tasks
- `evidence_docs/library_with_10_items.png` — Jurism with populated library
- `evidence_docs/empty_library_import_task.png` — Empty library for import task
- `evidence_docs/add_note_task_success.png` — Note attached to Brown v. Board
- `evidence_docs/collection_task_success.png` — US Constitutional Law collection with 4 items
- `evidence_docs/change_citation_style_success.png` — OSCOLA selected in Export tab Quick Copy
- `evidence_docs/add_manual_case_success.png` — Roe v. Wade added with Court + Date Decided
