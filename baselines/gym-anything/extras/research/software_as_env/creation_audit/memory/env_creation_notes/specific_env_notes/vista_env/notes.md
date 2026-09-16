> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# VistA Environment Creation Notes

## Overview

VistA (Veterans Health Information Systems and Technology Architecture) is the VA's Electronic Health Record system. This environment uses:
- **VistA VEHU** - A synthetic/demo VistA database with test patients
- **CPRS** - The Computerized Patient Record System GUI client

## Key Learnings

### 1. VistA Runs Best via Docker

The VistA VEHU image (`worldvista/vehu:latest`) is the easiest way to run VistA:
- Pre-configured with test patients
- Exposes port 9430 for CPRS (XWB protocol)
- Uses YottaDB (M/MUMPS database)
- Takes ~2-3 minutes to fully initialize

### 2. CPRS Requires Wine 32-bit Mode

The CPRS client has COM/OLE dependencies that don't work in Wine 64-bit:

```bash
# Error in 64-bit Wine:
class {8778acf7-5ca9-11d3-8727-0060b0b5e137} not registered

# Solution: Use 32-bit Wine prefix
WINEARCH=win32 WINEPREFIX=/home/ga/.wine32 wine CPRSChart.exe s=localhost p=9430
```

### 3. CPRS Download Sources

The OR_30_187 CPRS package is available from:
- Primary: https://opensourcevista.net/NancysVistAServer/WorldVistAFilesFromSourceforgeWorldVistASite20250922/CPRS%20GUI/OR_30_187/OR_30_187.ZIP
- Note: OSEHRA (code.osehra.org) URLs redirect and may not work directly

### 4. Patient Data in VEHU

VEHU contains synthetic patients. To query patient names:

```bash
# Inside the container
docker exec vista-vehu /bin/bash -c 'source /home/vehu/.profile && mumps -direct <<< "S X=0,N=0 F  S X=\$O(^DPT(X)) Q:X=\"\"!(N>=10)  S N=N+1 W \$P(\$G(^DPT(X,0)),U,1),!"'
```

### 5. Verification Strategy

The verification follows the two-part pattern used by gym_anything:

1. **Export Script (runs in container)**:
   - Takes final screenshot
   - Queries VistA database for patient access/vitals
   - Captures window state via wmctrl
   - Outputs JSON to /tmp/

2. **Verifier (runs on host)**:
   - Uses `copy_from_env` to retrieve JSON
   - Validates multiple criteria with point-based scoring
   - Requires key criteria to be met for pass

### 6. Resource Requirements

- RAM: 8GB minimum (VistA database + Wine + GNOME)
- Network: Required for Docker image pull
- Boot time: ~4-5 minutes (hooks + container startup)

## Fixed Issues (2026-02-01)

### 1. CPRS COM/OLE Error Mitigation
- Added Wine DLL overrides for ole32, oleaut32, rpcrt4
- Automated splash screen dismissal attempts
- Multiple CPRS versions tried as fallback

### 2. Database Verification Added
- Export script now queries VistA database for patient access
- Verifier checks both window state AND database state
- Anti-gaming through timestamp checking

### 3. Patient Name Consistency
- Tasks use `accept_any_patient: true`
- Expected patient set to "ANY"
- Sample patients documented from VEHU

## Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| CPRS COM error | 32-bit Wine prefix + DLL overrides |
| Splash screen hangs | Automated keypresses (Enter, Space) |
| Patient not found | VEHU has specific synthetic patients - accept any |
| Port 9430 not accessible | Wait longer for VistA to initialize |
| Container not starting | Ensure Docker service is running |

## VEHU Sample Patients

The VEHU database contains synthetic patients including:
- BCMA,EIGHT
- DIABETIC,PATIENT
- IMMUNIZATION,PATIENT
- (and many others)

To list all patients:
```bash
vista-list-patients 50
```

## Interactive Testing Results (2026-02-01)

### Testing Session Summary

Conducted interactive testing using `ask_cua.py` as specified in the prompt.md workflow:

1. **Environment Launch**: VistA environment launched successfully with VistA VEHU container running
2. **CPRS Launch**: CPRS application launched from desktop icon
3. **Splash Screen Issue**: CPRS splash screen appears but application freezes during initialization
4. **COM/OLE Error**: Application shows "cprschart.exe is not responding" repeatedly
5. **Window Rendering**: Main CPRS window has 1x1 pixel size (Wine rendering bug)

### Root Cause Analysis

The CPRS application (OR_30_187 version from 2004) has severe Wine compatibility issues:

1. **COM/OLE Components**: CPRS uses Windows COM components that don't translate well to Wine
2. **Splash Screen Freeze**: The application hangs during COM initialization on the splash screen
3. **DLL Override Attempts**: Tried `ole32=n,b;oleaut32=n,b;rpcrt4=n,b` without success
4. **32-bit Wine Prefix**: Used but still encounters same issues

### Recommendations

1. **patient_lookup task**: May work in some runs when CPRS initializes correctly (evidence shows it passed before)
2. **record_vital_signs task**: Blocked by CPRS initialization issues - requires successful login first
3. **Alternative Approaches**:
   - Consider using VistA web interface (Panorama/RAMaVista) instead of CPRS
   - Use newer CPRS version if available with better Wine compatibility
   - Consider running CPRS in a Windows VM instead of Wine

### Evidence Files

Screenshots from testing session saved in evidence_docs:
- vista_cua_screen*.png - CUA-guided interaction screenshots
- cprs_splash_*.png - Various splash screen states

## Future Improvements

1. Find a newer CPRS version with better Wine compatibility
2. Pre-populate Wine prefix with required DLLs
3. Add rollup tasks for common clinical workflows
4. Consider using VistA web interface as alternative to CPRS
5. **PRIORITY**: Investigate VistA web GUI options that don't require Wine

## References

- [WorldVistA](https://worldvista.org/)
- [OSEHRA](https://www.osehra.org/)
- [VistA Documentation Library](https://www.va.gov/vdl/)
- [CPRS User Guide](https://www.va.gov/vdl/documents/Clinical/Comp_Patient_Recrd_Sys_(CPRS)/cprsguium.pdf)
