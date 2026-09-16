> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# WPS Office Writer Environment Notes

## Overview

WPS Office Writer is a free office suite alternative to Microsoft Office. This environment provides a word processor for document creation and editing tasks.

## Installation

### Package Source
- **Download URL**: `https://wdl1.pcfg.cache.wpscdn.com/wpsdl/wpsoffice/download/linux/11723/wps-office_11.1.0.11723.XA_amd64.deb`
- **Version**: 11.1.0.11723
- **Package Size**: ~300MB
- **Installation Method**: gdebi (preferred) or dpkg

### Dependencies
- `gdebi-core` - for proper dependency resolution
- `libfreetype6`, `fontconfig` - font rendering
- `fonts-wqy-microhei`, `fonts-noto-cjk` - CJK font support
- `scrot`, `wmctrl`, `xdotool` - automation tools
- `python3-pip`, `python3-docx` - document verification

## EULA/First-Run Handling

### The Problem
WPS Office shows a license agreement dialog on first launch, even when config files set `EULA=true`. This dialog must be accepted before the application can be used.

### The Solution
The `dismiss_wps_eula()` function in `task_utils.sh` handles this:

```bash
dismiss_wps_eula() {
    # Check for license dialog
    if wmctrl -l | grep -qi "License Agreement\|Kingsoft Office Software"; then
        # Get window ID
        local window_id=$(wmctrl -l | grep -i "License Agreement" | awk '{print $1}')
        local window_dec=$((window_id))

        # Click checkbox at relative position (12, 290-295)
        for click_pos in "12 290" "12 293" "12 295" "15 293"; do
            xdotool mousemove --window $window_dec $click_pos click 1
            sleep 0.3
        done

        # Click "I agree" button at (660, 293)
        xdotool mousemove --window $window_dec 660 293 click 1
    fi
}
```

### Additional Dialogs
After EULA, WPS may show:
1. **System Check** - Warns about missing fonts, can be closed with `wmctrl -c "System Check"`
2. **Default Office** - Asks to set as default, can be dismissed with Enter or wmctrl

## Configuration Files

### Location 1: `/home/ga/.kingsoft/office6/data/wpsoffice.ini`
```ini
[Common]
TipOfTheDay=0
ShowStartCenter=0
ShowSplash=0
[Writer]
AutoSave=false
BackupCopy=false
[General]
EULA=accepted
FirstRun=false
```

### Location 2: `/home/ga/.config/Kingsoft/Office.conf`
```ini
[Common]
EULA=true
FirstRun=false
ShowTipOfTheDay=false
[Application]
AutoCheckUpdate=false
```

Note: Despite these settings, the EULA dialog still appears. The dialog dismissal function is required.

## Window Detection

WPS Writer windows can be detected using:
```bash
# Any of these patterns
wmctrl -l | grep -i 'WPS Writer\|\.docx\|\.doc\|\.wps\|wps$'

# Or with xdotool
xdotool search --name "WPS Writer"
xdotool search --name "draft_letter"
```

## Document Launching

```bash
# Launch WPS Writer with a document
DISPLAY=:1 QT_QPA_PLATFORMTHEME=gtk2 wps /path/to/document.docx &

# Required environment variables:
# - DISPLAY=:1 (for X11)
# - QT_QPA_PLATFORMTHEME=gtk2 (optional, for better GNOME integration)
```

## Verification

### Document Format
WPS Office uses DOCX format which is compatible with python-docx:

```python
from docx import Document

doc = Document('/path/to/document.docx')

# Get all text
text = '\n'.join(para.text for para in doc.paragraphs)

# Check formatting
for para in doc.paragraphs:
    for run in para.runs:
        print(f"Text: {run.text}, Bold: {run.bold}, Italic: {run.italic}")

# Count tables
num_tables = len(doc.tables)
```

### Common Verification Checks
1. **Text content** - Check for expected strings
2. **Bold formatting** - Check `run.bold`
3. **Italic formatting** - Check `run.italic`
4. **Paragraph alignment** - Check `para.alignment`
5. **Tables** - Check `doc.tables` for count and content

## Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Save | Ctrl+S |
| Bold | Ctrl+B |
| Italic | Ctrl+I |
| Underline | Ctrl+U |
| Close | Alt+F4 or Ctrl+Q |
| Go to beginning | Ctrl+Home |
| Go to end | Ctrl+End |
| Select line | Home, then Shift+End |

## Known Issues

1. **EULA Dialog Always Appears**: Config settings don't prevent this
2. **Line Wrapping with xdotool**: Long text input may wrap unexpectedly
3. **Process Detection**: Multiple WPS processes may be running (wps wrapper + actual binary)

## Tasks Created

### 1. format_business_letter
Format a job application letter with addresses, salutation, and closing.

**Real Data Used**:
- **Recipient**: Microsoft Corporation, One Microsoft Way, Redmond, WA 98052
- **Data Source**: Microsoft official office locations page (https://www.microsoft.com/en-us/about/office-locations)
- **Recipient Name**: a fictional placeholder addressee (e.g. `Hiring Manager`
  or any synthetic name); do not target the seed task at a real, identifiable
  individual.

### 2. create_data_table
Create a sales report with a formatted data table using real Amazon financial data.

**Real Data Used**:
- **Source**: Amazon Q4 2023 Earnings Report (https://ir.aboutamazon.com/news-release/news-release-details/2024/Amazon.com-Announces-Fourth-Quarter-Results/)
- **Data**:
  - North America: $105.5B (+13% YoY)
  - International: $40.2B (+17% YoY)
  - AWS: $24.2B (+13% YoY)
  - Total Q4 2023: $170.0B (+14% YoY)

## Resources

- [WPS Office Official](https://www.wps.com/)
- [python-docx Documentation](https://python-docx.readthedocs.io/)
- [WPS Office Linux Forum](https://www.wps.com/wps-office-linux/)
