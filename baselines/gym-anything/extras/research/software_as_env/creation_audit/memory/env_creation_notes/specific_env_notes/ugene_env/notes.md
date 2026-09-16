> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# UGENE Environment Notes

## Installation
- UGENE 53.0 is distributed as a self-contained tar.gz from GitHub releases
- Download URL: `https://github.com/ugeneunipro/ugene/releases/download/53.0/ugene-53.0-linux-x86-64.tar.gz`
- Binary name is `ugeneui` (GUI) and `ugenecl` (CLI)
- The `ugene` script in the distribution is a launcher wrapper
- Requires Qt5 libraries, OpenGL, and various xcb libraries

## Key Gotchas

### VNC Password Required
- The env.json MUST include `"vnc": {"enable": true, "password": "password"}`
- Without this, the VNC connection pool fails and kills the VM
- The base preset `ubuntu-gnome-systemd_highres` does NOT set a VNC password

### Multi-Sequence FASTA Loading Dialog
- When UGENE opens a multi-sequence FASTA file, it shows a "Sequence Reading Options" dialog
- Options: separate sequences, merge, join into alignment, map reads
- For alignment tasks: select "Join sequences into alignment and open in multiple alignment viewer"
- The dialog coordinates (in 1280x720 scale):
  - "Join sequences" radio: ~(485, 314)
  - OK button: ~(697, 493)

### UGENE Command Line
- `ugeneui /path/to/file.fasta` does NOT reliably open the file
- Better to launch UGENE first, then use Ctrl+O to open files
- CLI tool `ugenecl` supports tasks like `align` (MUSCLE), `align-clustalw`, etc.

### First-Run Configuration
- Settings directory: `~/.config/UGENE/UGENE.ini`
- Set `show_tips_on_startup=false` and `check_updates_on_startup=false`
- Warm-up launch is recommended to clear first-run state

### UniProt Accession Pitfalls
- Always verify downloaded sequences match expected protein
- P04148 was incorrectly assumed to be Drosophila cytochrome c; it is actually Fibrohexamerin (Bombyx mori)
- Correct Drosophila melanogaster cytochrome c: P04657 (CYC1_DROME)
- P62894 is CYC_BOVIN (bovine), not pig; correct pig cytochrome c is P62895
- UniProt batch download URL sometimes fails; individual downloads are more reliable

## Data Sources
- UniProt REST API: `https://rest.uniprot.org/uniprotkb/{accession}.fasta`
- Batch download URL: `https://rest.uniprot.org/uniprotkb/stream?query=accession:{CSV_ACCESSIONS}&format=fasta`
- Batch download sometimes fails; always include individual download fallback
- NCBI efetch: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi`
- RCSB PDB: `https://files.rcsb.org/download/{PDB_ID}.pdb`

## Coordinate Reference (1280x720)
- File menu: ~(41, 48)
- Ctrl+O opens file dialog
- Open dialog file name field: ~(520, 478)
- Sequence Reading Options dialog:
  - "Join sequences" radio: ~(485, 313)
  - OK button: ~(697, 493)
- Alignment viewer sequence area: starts ~(522, 173)
- Status bar: ~(640, 643)
- Conservation graph: ~(70-1255, 660-690)
