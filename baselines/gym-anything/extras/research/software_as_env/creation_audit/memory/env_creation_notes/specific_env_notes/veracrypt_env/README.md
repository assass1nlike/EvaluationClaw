> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# VeraCrypt Environment Notes

## Overview
VeraCrypt is a disk encryption tool that creates and manages encrypted volumes. The environment tests GUI-based volume management operations.

## Installation
- **Source**: PPA `ppa:unit193/encryption`
- **Version**: 1.26.24
- **Package**: `veracrypt`
- **Dependencies**: `libfuse2`, `dmsetup`, `exfatprogs` (fallback to `exfat-utils`)

## Key Technical Notes

### Password Handling
- **CRITICAL**: Do NOT use `!` in passwords in bash scripts. In some shell contexts, `!` triggers history expansion even in double quotes, corrupting the password hash during volume creation.
- Use single quotes for passwords in all shell scripts: `--password='MyPassword123'`
- Passwords used in this env: `OldPassword123`, `MountMe2024`, `DismountMe123`, `SecurePass2024`, `NewSecure2024`

### VeraCrypt CLI
- Create: `veracrypt --text --create <path> --size=<size> --password='<pwd>' --encryption=AES --hash=SHA-512 --filesystem=FAT --pim=0 --keyfiles='' --random-source=/dev/urandom --non-interactive`
- Mount: `veracrypt --text --mount <path> <mountpoint> --password='<pwd>' --pim=0 --keyfiles='' --protect-hidden=no --non-interactive`
- Dismount: `veracrypt --text --dismount [path|--all] --non-interactive`
- List: `veracrypt --text --list --non-interactive`
- Change password: `veracrypt --text -C <path> --password='<old>' --new-password='<new>' --new-keyfiles='' --pim=0 --new-pim=0 --non-interactive`

### Setup Script
- Removed `set -e` because VeraCrypt CLI sometimes returns non-zero on success
- Post-start creates 3 pre-existing volumes: test_volume.hc, data_volume.hc, mounted_volume.hc
- data_volume.hc contains sample files (confidential.txt, budget_report.txt, ssh_key_backup.txt)
- Verification step: each volume is test-mounted after creation to confirm it works

### Mount Points
- VeraCrypt uses `/media/veracrypt1` through `/media/veracrypt64` as default mount points
- The `--slot=N` flag controls which slot/mount point is used
- Mount requires sudo (runs via `echo password123 | sudo -S veracrypt ...`)

### GUI
- Launched via `su - ga -c "DISPLAY=:1 veracrypt &"` in post_start
- Window title: "VeraCrypt"
- Main features: slot list, Create Volume button, Mount/Dismount buttons
- Volume Creation Wizard: multi-step wizard for creating new containers
- Volumes menu: Change Volume Password, Set Header Key Derivation Algorithm

## Tasks

| Task | Difficulty | Description |
|------|-----------|-------------|
| create_encrypted_container | medium | Create 50MB AES/SHA-512 container |
| mount_volume | easy | Mount existing data_volume.hc |
| change_volume_password | medium | Change test_volume.hc password |
| create_keyfile | easy | Generate keyfile via Tools > Keyfile Generator |
| dismount_all_volumes | easy | Dismount all mounted volumes |

## Verification Pattern
All tasks use the two-part verification pattern:
1. `export_result.sh` runs in VM, writes JSON to `/tmp/veracrypt_<task>_result.json`
2. `verifier.py` runs on host, uses `copy_from_env()` to fetch JSON, scores criteria
