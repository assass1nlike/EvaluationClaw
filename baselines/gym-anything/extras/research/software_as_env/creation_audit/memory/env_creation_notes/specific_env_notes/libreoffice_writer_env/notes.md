> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# LibreOffice Writer Environment Notes

## Installation Quirks

### pip install with --break-system-packages
Ubuntu 22.04's pip may not support `--break-system-packages`. The install script uses a fallback pattern:
```bash
pip3 install --no-cache-dir --break-system-packages python-docx 2>/dev/null || \
pip3 install --no-cache-dir python-docx || true
```

### "What's New" Infobar
LibreOffice shows a "What's New" notification bar on first launch. Suppressed via two mechanisms:
1. Creating `versionrc` in the user profile during post_start:
```bash
cat > "$home_dir/.config/libreoffice/4/user/versionrc" << VRCEOF
[Version]
AllLanguages=$lo_version
buildid=
VRCEOF
```
2. Each task setup_task.sh sends `Escape` key after window focus as a safety net to dismiss any residual infobar.

The `ooSetupLastVersion` XCU setting alone is not sufficient.

### DISPLAY Environment for X11 Commands
Scripts running as root (pre_task hooks) need `export DISPLAY=:1` and `export XAUTHORITY=/home/ga/.Xauthority` at the top of task_utils.sh for wmctrl/xdotool to work. Without these, window detection and focusing fail with "Cannot open display".

## Service Timing

### LibreOffice Startup
- Process detection (pgrep soffice): ~1 second after launch
- Window detection (wmctrl): ~5-6 seconds after launch
- Use `wait_for_process "soffice" 15` then `wait_for_window "LibreOffice Writer" 90` pattern

### VM Boot
- Full boot + SSH available: ~20-30 seconds
- Pre-start hook (installation): ~60-70 seconds
- Post-start hook (configuration): ~1-2 seconds
- Pre-task hook (document creation + Writer launch): ~5-10 seconds
- Total cold start: ~95-100 seconds

## Verification Notes

### DOCX Format
All documents use DOCX format (not ODT) because:
- python-docx provides rich API for style/formatting checks
- python-docx exists on both host (verifier) and VM (document creation)
- Ctrl+S in Writer preserves DOCX format when file was opened as DOCX

### Verifier Architecture
- Verifiers run on HOST, not in VM
- Use `copy_from_env` to copy documents from VM to temp directory
- Parse with python-docx on host
- Clean up temp files after verification

### Import Path for Verifiers
Verifiers use:
```python
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../', 'utils'))
from writer_verification_utils import ...
```
This resolves to `benchmarks/cua_world/environments/libreoffice_writer_env/utils/writer_verification_utils.py`.

### TOC Detection
The `detect_toc_present()` function uses 4 detection methods since LibreOffice Writer's TOC XML differs from Microsoft Word:
1. `w:instrText` containing "TOC"
2. `w:sdt` (structured document tag) with "TOC" in docPartGallery
3. `w:fldChar` field markers
4. Heuristic: "Table of Contents" heading followed by at least 2 TOC-like entries (paragraphs ending with page numbers, containing tabs, or with TOC styles). Plain text alone is not sufficient to trigger this heuristic.

### Hanging Indent Detection
Checks `pPr/ind` XML element. For 0.5-inch hanging indent:
- `hanging` attribute should be > 0 (typically 720 twips = 0.5 inch = 457200 EMU)
- OR `left` > `firstLine` (indicating hanging layout)

### Mail Merge Verification
The verifier tries `merged_letters.docx` first, falls back to `letter_template.docx`. Criterion 1 only passes if the merged output file (`merged_letters.docx`) was loaded — falling back to the template does NOT award credit for criterion 1. This prevents free points from template fallback while still allowing partial evaluation of other criteria.

## Known Behaviors

### F11 Styles Sidebar
The setup_task.sh scripts press F11 to open the Styles sidebar, making it easier for agents to apply heading styles. This is intentional for TOC and research paper tasks.

### Document Lock Files
LibreOffice creates `.~lock.*.docx#` files when documents are open. These are harmless and don't affect verification.

### Ctrl+S Preserving Format
When Writer opens a .docx file and the user presses Ctrl+S, it saves in the original format (DOCX) without a format dialog. This is the expected behavior for our tasks.

### Export Scripts Do NOT Force-Save
The export_result.sh scripts deliberately do NOT send Ctrl+S. The agent is responsible for saving their work. When closing Writer (Ctrl+Q), the "Save changes?" dialog is dismissed with "Don't Save" (Alt+D) to avoid masking agent failure. This ensures agents that forget to save do not get unearned credit.

## Audit Fixes Applied

The following issues from the post-implementation audit have been addressed:

1. **HIGH: Bibliography verifier APA format check** — Criterion 2 now calls `check_apa_citation_format()` to validate actual APA formatting (author format, year in parentheses) instead of just checking author name presence.

2. **MEDIUM: TOC detection Method 4 tightened** — Heuristic no longer triggers on plain "Table of Contents" text alone; requires at least 2 subsequent paragraphs with page numbers, tabs, or TOC styles.

3. **MEDIUM: "What's New" infobar dismissal** — All task setup scripts now send Escape key after window focus as a safety net, in addition to the versionrc fix.

4. **MEDIUM: Research paper pass threshold raised** — Changed from 57% (4/7) to 71% (5/7 or 6/8 with VLM) to prevent over-generous passing.

5. **MEDIUM: Export scripts don't force-save** — Removed Ctrl+S from all export_result.sh scripts; close dialog uses "Don't Save" (Alt+D).

6. **LOW: Dead sample "cultivated plants" fixed** — Replaced with "temperature anomalies" which actually appears in the climate science paper body text.

7. **LOW: Mail merge criterion 1 fix** — Template fallback no longer awards criterion 1; only the merged output file (`merged_letters.docx`) gets credit.

8. **LOW: Task descriptions simplified** — Removed over-specified menu paths and keyboard shortcuts from task descriptions for tasks 1 (TOC) and 2 (mail merge).

9. **LOW: VLM cross-validation added** — All 4 verifiers now include a VLM criterion that visually validates the final screenshot. VLM unavailability gracefully degrades (criterion is skipped, total adjusted).

10. **LOW: TOC criteria redundancy fixed** — Replaced redundant criterion 5 (heading count overlap with criteria 1+2) with "TOC placed near beginning of document" check.

## Second Audit Fixes Applied

11. **CRITICAL: `re.search` missing text argument** — `check_apa_citation_format()` line 475 called `re.search(r'\(\d{4}\)')` without the `text` argument, causing a `TypeError` crash. Fixed by adding `text` as the second argument. This bug made the bibliography_formatting task completely unverifiable.

12. **HIGH: README baseline inconsistency** — Bibliography baseline score was reported as 20 but the (now-fixed) APA format check would produce score 0. Updated README to show correct baseline score of 0 with explanation of the change.

13. **MEDIUM: Hanging indent detection too lenient** — `check_hanging_indent()` accepted any paragraph with `left_indent >= 0.3"` even without a negative `first_line_indent`. Fixed to check the XML `w:hanging` attribute directly when `first_line_indent` is `None`. Plain block indents no longer pass as hanging indents.

14. **MEDIUM: Style-inherited bold/italic not detected** — `check_text_formatting()` compared `run.bold` directly, but python-docx returns `None` (not `True`) when bold is inherited from a style (e.g., Heading 1, Title). Added `_resolve_run_bold()` and `_resolve_run_italic()` helpers that check the paragraph style and style name as fallbacks.

15. **MEDIUM: Mail merge verifier bypass** — Without VLM, an agent could dump CSV data into a DOCX with page breaks and pass all criteria. Replaced criterion 3 (address keywords) with a letter structure check: verifies the presence of template phrases ("Dear", "Sincerely", "Greenfield Public Library", "renew") that wouldn't exist in a plain CSV dump.

## Third Audit Fixes Applied

16. **HIGH: Bibliography threshold raised to 80%** — At 60%, an agent could pass by doing only 3 easy things (heading, sort, italics) while skipping the core APA conversion and hanging indent. At 80%, 4/5 criteria needed without VLM, requiring genuine formatting work.

17. **MEDIUM: TOC threshold raised to 80%** — At 60%, an agent could pass with content preservation (free) + fake TOC text + placement = 3/5. At 80%, 4/5 criteria needed, requiring actual heading style application.

18. **LOW: Run fragmentation in check_text_formatting** — Text split across multiple runs (e.g., "Regional Climate " + "Variability") wasn't detected. Added paragraph-level fallback: if text_fragment is in concatenated paragraph text but not in any single run, checks formatting on runs within the paragraph.
