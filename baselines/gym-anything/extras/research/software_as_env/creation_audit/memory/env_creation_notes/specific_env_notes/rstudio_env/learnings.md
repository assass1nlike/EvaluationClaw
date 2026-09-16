> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# RStudio Environment Creation Notes

## Overview
This document captures lessons learned from creating the RStudio environment for Gym-Anything.

## Key Learnings

### 1. R/RStudio Version Compatibility
**Problem**: RStudio versions have specific R version requirements. Using RStudio 2024.04.2 with R 4.5.2 caused:
```
Error Starting R
R shared library (/usr/lib/R/lib/libR.so) undefined symbol: RF_ScalarLogicals
```

**Solution**: Use RStudio 2024.12.1-563 which supports R 4.5.x. The install script tries versions in order:
1. 2024.12.1-563 (works with R 4.5.x)
2. 2024.12.0-467 (fallback)
3. 2025.06.0-496 (future version)

### 2. Command Execution in QEMU Runner
**Problem**: The `runner.exec()` method wraps commands in `sudo`, which breaks shell builtins like `cd`:
```
sudo: cd: command not found
```

**Solution**:
- Use full paths instead of `cd`: `R -f /path/to/script.R` instead of `cd /path && R -f script.R`
- Use `runner.exec_capture()` to get actual command output (not just return codes)

### 3. JSON Export Safety
**Problem**: Shell variables with quotes break JSON generation:
```bash
OUTPUT_COLS=$(head -1 "$CSV" | tr ',' ' ')  # Contains "quoted" values
```

**Solution**: Strip quotes from shell variables before JSON embedding:
```bash
OUTPUT_COLS=$(head -1 "$CSV" | tr ',' ' ' | tr -d '"')
```

### 4. R Package Dependencies
**Problem**: tidyverse installation fails due to missing system dependencies (ragg, textshaping).

**Solution**: Install core packages individually:
- ggplot2 (for plotting)
- dplyr (for data manipulation)
- readr, tibble, tidyr (for data wrangling)
- Install tidyverse as optional at the end

### 5. Startup Dialog Handling
**Problem**: RStudio shows crash reporting and update dialogs on first launch.

**Solution**:
1. Configure rstudio-prefs.json with:
   ```json
   {
     "check_for_updates": false,
     "submit_crash_reports": false,
     "send_usage_stats": false
   }
   ```
2. Use xdotool to dismiss dialogs: `xdotool key Escape`

### 6. Dataset Downloads
**Problem**: External dataset URLs may be unreliable.

**Solution**: Use multiple fallback URLs with error handling:
```bash
wget -q -O file.csv "primary_url" 2>/dev/null || \
wget -q -O file.csv "fallback_url" 2>/dev/null || \
echo "Download failed"
```

### 7. Task Verification Pattern
For RStudio tasks, verify both:
1. **Output files** - Check existence, size, modification time
2. **Script content** - Check for required functions/patterns

Example patterns to check:
- `library(ggplot2)` - package loaded
- `geom_point()` - specific function used
- `ggsave()` - output saved

## Directory Structure
```
rstudio_env/
├── env.json                    # Environment configuration
├── config/
│   └── rstudio-prefs.json     # RStudio preferences
├── scripts/
│   ├── install_rstudio.sh     # pre_start hook
│   ├── setup_rstudio.sh       # post_start hook
│   └── task_utils.sh          # Shared utilities
├── tasks/
│   ├── create_scatter_plot/
│   │   ├── task.json
│   │   ├── setup_task.sh      # pre_task hook
│   │   ├── export_result.sh   # post_task hook
│   │   └── verifier.py
│   └── summarize_dataset/
│       ├── task.json
│       ├── setup_task.sh
│       ├── export_result.sh
│       └── verifier.py
├── utils/
│   └── rstudio_verification_utils.py
└── evidence_docs/
    └── verification_results.md
```

## Testing Commands

### Start environment interactively
```python
from gym_anything import from_config
env = from_config('benchmarks/cua_world/environments/rstudio_env', task_id='create_scatter_plot')
obs = env.reset()
# Environment running on SSH port: env._runner.ssh_port
```

### Get screenshot with ask_cua.py
```bash
python3 ask_cua.py --question "Where should I click?" --screenshot_path screenshot.png
```

### Run R commands
```python
runner.exec_capture("R --vanilla --slave -f /path/to/script.R 2>&1")
```

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Error Starting R" | RStudio/R version mismatch | Use compatible versions |
| exec() returns int only | Using exec() instead of exec_capture() | Use exec_capture() for output |
| JSON parse error | Quotes in shell variables | Strip quotes before JSON |
| Package install fails | Missing system deps | Install build dependencies |
| Dialog appears | First launch prompts | Configure prefs + xdotool Escape |
