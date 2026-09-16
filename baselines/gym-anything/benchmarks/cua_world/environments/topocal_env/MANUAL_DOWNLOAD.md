# Manual data download

This environment expects two files that are not currently available from a stable public URL.

## Files

| Path | Size |
|---|---|
| `data/topocalsetup.exe` | ~86 MB |
| `data/Tpc4_Printer.dll` | ~870 KB |

## How to obtain them

The reference build is **TopoCal 2025 v9.0.961**. The vendor site (`topocal.com`) is not currently reachable — if you do not already have these files locally, contact the project maintainers.

Place the files at:
- `data/topocalsetup.exe`
- `data/Tpc4_Printer.dll`

## Verify

```sh
sha256sum data/topocalsetup.exe data/Tpc4_Printer.dll
```

Expected sha256:
```
d04f2b8c9f833ec931d926c126e7ce3d3bf145062a1b743a3120f42bb3b5ec93  data/topocalsetup.exe
b2b4020a97682e45495b4115828c32f16674008459356e61e096cb6499784618  data/Tpc4_Printer.dll
```
