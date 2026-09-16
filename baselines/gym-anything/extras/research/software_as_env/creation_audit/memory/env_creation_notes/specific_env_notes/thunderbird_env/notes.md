> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Thunderbird Environment Notes

## Overview

Mozilla Thunderbird email client environment for desktop email management tasks.

## Installation

- **Package**: `apt-get install thunderbird` (Ubuntu repositories)
- **Dependencies**: `xdotool`, `wmctrl`, `scrot`, `jq`, `sqlite3`
- **No external downloads needed** - Thunderbird ships with Ubuntu repos

## Profile Configuration

### Key Architecture Decision: Local Folders Only

We use **local-only configuration** (no mail server) because:
1. The VM has no reliable internet for IMAP/SMTP
2. We need deterministic test data (server state would vary)
3. Tasks focus on UI interactions, not network operations

### Profile Setup Method

The profile is created headlessly via `user.js` and `prefs.js`:

```
~/.thunderbird/
├── profiles.ini          # Points to default-release profile
├── installs.ini          # Marks as non-first-run
└── default-release/
    ├── user.js            # Pre-configured preferences
    └── Mail/
        └── Local Folders/
            ├── Inbox      # mbox file with 50 real ham emails
            ├── Junk        # mbox file with 20 real spam emails
            ├── Drafts      # Empty
            ├── Sent        # Empty
            ├── Trash       # Empty
            └── Templates   # Empty
```

### Critical user.js Preferences

```javascript
// Suppress first-run wizard
user_pref("mail.provider.enabled", false);
user_pref("mailnews.start_page.enabled", false);

// Set up local account (type "none" = no server)
user_pref("mail.server.server1.type", "none");
user_pref("mail.server.server1.storeContractID", "@mozilla.org/msgstore/berkeleystore;1");

// Identity for composing
user_pref("mail.identity.id1.fullName", "Test User");
user_pref("mail.identity.id1.useremail", "testuser@example.com");
```

## Email Data

### Source: SpamAssassin Public Corpus

- **Ham emails**: 50 emails from `20030228_easy_ham.tar.bz2`
- **Spam emails**: 20 emails from `20030228_spam.tar.bz2`
- **Format**: RFC 2822 (standard email format)
- **Source URL**: https://spamassassin.apache.org/old/publiccorpus/
- **License**: Public domain (research corpus)

### Why This Dataset

1. Real emails (not synthetic) from public research corpus
2. Contains full headers (From, To, Subject, Date, etc.)
3. Mix of mailing list, personal, and spam emails
4. Standard format importable into mbox
5. CMU-hosted Enron corpus was too large (~423MB)

### Import Method

Emails are imported into Thunderbird's mbox format during `setup_thunderbird.sh`:
- Each email is prefixed with `From sender@example.com date` separator line
- Files are concatenated into Inbox/Junk mbox files
- Thunderbird auto-generates `.msf` index files on first run

## Verification Patterns

### Compose Email Task
- Check Drafts mbox for new messages (count increased)
- Parse mbox to extract To/Subject/Body from last message
- Verify recipient, subject, and body keywords match

### Organize Emails Task
- Check for new folder file in `Mail/Local Folders/`
- Count emails in the new folder (via `From ` separators in mbox)
- Verify Inbox count decreased (emails moved, not copied)

### Mail Filter Task
- Parse `msgFilterRules.dat` for new filter entries
- Verify filter name, condition (subject contains), and action (move to folder)
- Check target folder exists

## Known Issues

1. **First-run tab**: Even with `user.js` suppression, Thunderbird 115+ may show a "Set Up Another Account" tab. This is expected and the agent can close it or work around it.
2. **mbox index timing**: `.msf` files are generated asynchronously. If checking immediately after import, counts may not match. Add `sleep 3` after Thunderbird start.
3. **Window title varies**: Thunderbird window title format changes between versions. Use partial matching (e.g., grep -i "thunderbird").
4. **Filter rules format**: `msgFilterRules.dat` uses a custom format, not JSON. Fields are `name=`, `condition=`, `action=`, `actionValue=`.
5. **Ctrl+W closes entire Thunderbird**: In Thunderbird 128 Supernova, `Ctrl+W` closes the whole application, not just a tab. Never use it for closing sub-windows — use `Escape` or window-specific close actions instead.
6. **Compose window Tab key does NOT navigate fields**: In Thunderbird 128 Supernova, pressing `Tab` in the compose window's To field does **not** move focus to the Subject field. Instead, Tab confirms the current recipient (creates a pill/chip) and stays in the To area. Agents must **click directly** on the Subject field and body area to move between fields. See "Thunderbird 128 Compose Window Navigation" below for coordinates.
7. **Mailbox URI username must match server userName**: Identity preference URIs (`draft_folder`, `fcc_folder`) must use the same username as `mail.server.serverN.userName`. If the server userName is `"ga"`, URIs must be `mailbox://ga@Local%20Folders/...`, NOT `mailbox://nobody@Local%20Folders/...`. A mismatch causes silent failures (e.g., Ctrl+S in compose does nothing — no error, no save). See bug #7 below.

## Thunderbird 128 Compose Window Navigation

Thunderbird 128 (Supernova UI) uses a web-based compose window where standard keyboard navigation (Tab between fields) does not work. The correct approach for agents or xdotool automation:

### Field Coordinates (1920x1080 resolution, CUA-verified)

| Field | Click Position (x, y) | Notes |
|-------|----------------------|-------|
| To | (615, 233) | Pill/chip input — type email, then click away (don't use Tab) |
| Subject | (615, 269) | Click directly to focus — Tab from To does NOT reach here |
| Body | (545, 600) | Click directly on the body area |

### Correct Interaction Sequence

```
1. Click To field at (615, 233)
2. Type the email address
3. Click Subject field at (615, 269)   ← must click, NOT Tab
4. Type the subject
5. Click Body area at (545, 600)       ← must click, NOT Tab
6. Type the body text
7. Ctrl+S to save as draft
```

### What Fails

```
1. Type email in To field
2. Press Tab          ← creates a chip/pill, stays in To area
3. Type subject       ← subject text becomes another To recipient!
4. Tab again          ← still in To area
5. Type body          ← body text also becomes a To recipient
```

### How This Was Discovered

Interactive debugging with `ask_cua.py` + SSH showed the compose window title remained "Write: (no subject)" after Tab-based field navigation, while click-based navigation immediately changed it to "Write: Q4 Budget Review Meeting". Visual inspection via CUA confirmed the subject and body text were appearing as red pills/chips inside the To field.

## Bugs Found and Fixed

### Integer Comparison Error in `count_emails_in_mbox`

- **Symptom**: `[: 0\n0: integer expression expected` in export_result.sh
- **Root Cause**: `grep -c "^From "` returned count with trailing newline; bash `[` comparison failed on non-integer string
- **Fix**: Added `tr -d '[:space:]'` to strip whitespace, plus `[[ "$count" =~ ^[0-9]+$ ]]` regex validation with fallback to 0
- **Lesson**: Always sanitize command output before using in bash arithmetic/comparisons

### copy_from_env Method Name

- **Symptom**: `'QemuApptainerRunner' object has no attribute 'copy_from_env'`
- **Fix**: The correct method on the QEMU runner is `copy_from()`, not `copy_from_env()`. The verifier receives it via `env_info.get('copy_from_env')` which the framework maps correctly.

## Timing

- Installation: ~15-20s (from Ubuntu repos)
- Profile setup + email import: ~5-10s
- Thunderbird startup: ~5-8s
- Total env reset: ~45-60s

### Empty String Subject Match Bug

- **Symptom**: Baseline verifier score for compose_send_email was 40% instead of expected 20%
- **Root Cause**: Python `"" in "q4 budget review meeting"` is always True, so empty subject matched
- **Fix**: Added guard `if actual_subject and (...)` before substring check in verifier.py
- **Lesson**: Always guard against empty-string substring matching

### Subject Substring Vulnerability

- **Symptom**: Any single-character substring of the expected subject (e.g., "q") would score full 15 points
- **Root Cause**: Condition `actual_subject in expected_subject_lower` matches any substring of expected in actual (reversed containment check)
- **Fix**: Removed the reverse containment check. Now requires full expected subject string in actual subject for full credit. Partial credit requires at least 2 matching words from the expected subject.
- **Lesson**: Bidirectional substring checks are inherently vulnerable. Use one-directional containment.

### Organize Task Pass Threshold Too Lenient

- **Symptom**: Task passed with only 2 emails moved instead of the required 3
- **Root Cause**: Pass condition checked `folder_count > 0` instead of `folder_count >= min_emails`
- **Fix**: Changed pass condition to `folder_count >= min_emails`

### Export Script Awk Extraction Bug

- **Symptom**: Export script extracted all mbox messages instead of just the last one
- **Root Cause**: Awk pattern `/^From /{p=NR} p{print}` sets p on the first "From " and never resets, printing everything
- **Fix**: Used `awk '/^From /{msg=""} {msg=msg $0 "\n"} END{printf "%s", msg}'` to reset on each separator

### Filter actionValue Encoding

- **Symptom**: Test data used `%20` encoding in mailbox URIs, but Thunderbird uses literal spaces
- **Root Cause**: Thunderbird writes `actionValue="mailbox://nobody@Local Folders/Urgent"` with literal spaces
- **Fix**: Updated all test data to use literal spaces in mailbox URIs

### Mailbox URI Username Mismatch (Draft Save Silent Failure)

- **Symptom**: Pressing Ctrl+S in compose window does nothing — no error dialog, no save, Drafts mbox stays 0 bytes. Compose window remains open unchanged. File > Save menu item also has no effect.
- **Root Cause**: The `mail.identity.id1.draft_folder` preference used `mailbox://nobody@Local%20Folders/Drafts` but the server's `userName` was `"ga"`. Thunderbird could not resolve the `nobody@` URI to the local folders server. Thunderbird's own auto-generated `archive_folder` preference confirmed the correct format: `mailbox://ga@Local%20Folders/Archives`.
- **Debugging Method**: Booted the QEMU VM, used `ask_cua.py` to get compose window field coordinates, filled fields by clicking directly (not Tab), confirmed fields were filled (window title changed), then compared the `draft_folder` URI with Thunderbird's auto-generated `archive_folder` URI. Changed `nobody@` to `ga@` live in the VM, restarted Thunderbird, and Ctrl+S immediately saved an 878-byte draft.
- **Fix**: Changed `setup_thunderbird.sh` user.js preferences:
  ```javascript
  // BEFORE (broken — silent failure):
  user_pref("mail.identity.id1.draft_folder", "mailbox://nobody@Local%20Folders/Drafts");
  user_pref("mail.identity.id1.fcc_folder", "mailbox://nobody@Local%20Folders/Sent");

  // AFTER (working):
  user_pref("mail.identity.id1.draft_folder", "mailbox://ga@Local%20Folders/Drafts");
  user_pref("mail.identity.id1.fcc_folder", "mailbox://ga@Local%20Folders/Sent");
  ```
- **Lesson**: Thunderbird mailbox URIs must use the **exact username from `mail.server.serverN.userName`**, not `nobody` or any other placeholder. When Thunderbird can't resolve a mailbox URI, it **silently fails** with no error — making this extremely hard to diagnose without live interactive debugging. Always check what URIs Thunderbird auto-generates (e.g., `archive_folder`) and match that format.
- **How to verify**: After Thunderbird starts, check `prefs.js` for auto-generated folder URIs and compare the username part with your manually-set URIs.

### Mbox Modification While Thunderbird Running

- **Symptom**: Correct completion tests modified mbox files while Thunderbird was running
- **Root Cause**: Thunderbird's mbox format requires exclusive file access; concurrent modification risks corruption
- **Fix**: Added `pkill -f thunderbird; sleep 3` before mbox modifications, then restart Thunderbird after

## Verification Architecture

### Hybrid Multi-Signal Pattern

All 3 verifiers use hybrid programmatic + VLM verification, following the framework's `vlm_checklist_patterns.md` guidelines:

1. **Programmatic criteria** (65-75 points): JSON-based checks on exported task data
2. **VLM trajectory analysis** (15 points): `sample_trajectory_frames(traj, num_samples=5)` analyzed for task-specific workflow patterns
3. **VLM final state** (10 points): `get_final_screenshot(traj)` checked for expected final state

VLM functions accessed via `env_info.get('query_vlm')`, `env_info.get('sample_trajectory_frames')`, `env_info.get('get_final_screenshot')`. Graceful degradation when VLM is unavailable.

### Scoring Summary

| Task | Programmatic Max | VLM Max | Total | Pass Threshold |
|------|-----------------|---------|-------|---------------|
| compose_send_email | 75 | 25 | 100 | score ≥ 60 AND draft_added |
| create_mail_filter | 70 | 25 | 95 | score ≥ 50 AND filter_created AND urgent_folder |
| organize_emails_into_folders | 65 | 25 | 90 | score ≥ 50 AND folder_created AND folder_count ≥ min_emails |

## Test Results (2026-01-26)

### Baseline Tests (No Agent Interaction)

All three tasks tested end-to-end in actual QEMU VMs:
- Environment boots successfully with ubuntu-gnome-systemd_highres base
- Thunderbird installs and launches with pre-configured profile
- 50 ham + 20 spam emails visible in Local Folders
- All export scripts produce valid JSON
- All verifiers process results correctly with structured scoring
- Baseline scores (no agent): 10 points each (only "TB running" criterion met) - expected

### Correct Completion Tests (Task Completed in VM)

All three tasks completed in actual VMs, then verified with real exported data (programmatic-only, no agent trajectory for VLM):
- **compose_send_email**: PASSED, score=75/75 programmatic, all criteria met
- **create_mail_filter**: PASSED, score=70/70 programmatic, all criteria met
- **organize_emails_into_folders**: PASSED, score=65/65 programmatic, all criteria met

### Mock Verifier Tests (4 scenarios each, VLM-enhanced)

12/12 mock tests passed across all 3 verifiers:
- Do-nothing: correctly fails with score 10-15 (only TB running)
- Partial work: correctly fails with score 15-35 (below pass threshold)
- Correct completion: correctly passes with score 65-75 (programmatic-only, above threshold)
- Wrong parameters: correctly fails (missing key criteria even with some points earned)
